"""Stage the current prebuilt DeepSteam UI and local render runtimes.

This copies code, locked dependencies and assets only. User data, provider
configuration, local browser state, process logs and render jobs are excluded.
Windows pnpm junctions are recorded as in-payload relative links and recreated
by the installer; no junction may refer back to the development checkout.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "installer" / "app-payload"
MANIFEST = ROOT / "installer" / "frontend-payload-manifest.json"
LINKS: list[dict[str, str]] = []
LINK_TARGETS: list[tuple[Path, Path]] = []
EXCLUDED = {".git", "__pycache__", ".local", ".env", ".env.local", ".env.production"}


def clean_managed_stage(path: Path):
    """Remove only a checked disposable frontend staging tree, never a checkout."""
    checked = path.resolve()
    checked.relative_to(STAGE.resolve())
    if checked == STAGE.resolve() or path.is_junction() or path.is_symlink():
        raise RuntimeError('Refusing unsafe staging cleanup: ' + str(path))
    print('Checked disposable staging directory: ' + str(checked), flush=True)
    if path.exists():
        shutil.rmtree('\\\\?\\' + str(checked))


def copy_file(source: Path, target: Path):
    # CopyFile2 otherwise fails on pnpm's long Windows package paths even when
    # Python's regular stat/open operations can handle the same filenames.
    prefix = "\\\\?\\" if os.name == "nt" else ""
    shutil.copy2(prefix + str(source.absolute()), prefix + str(target.absolute()))


def relative(path: Path) -> str:
    return path.absolute().relative_to(STAGE.absolute()).as_posix()


def copy_regular_tree(source: Path, target: Path, mapping: tuple[Path, Path], *, root_excludes=()):
    """Do not follow junctions; map each one to its equivalent installed path."""
    target.mkdir(parents=True, exist_ok=True)
    source_root, destination_root = mapping
    for entry in os.scandir(source):
        src = Path(entry.path)
        dest = target / entry.name
        if entry.name in EXCLUDED or entry.name in root_excludes or entry.name.startswith(".env."):
            continue
        metadata = entry.stat(follow_symlinks=False)
        reparse = bool(getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        if reparse:
            resolved = src.resolve(strict=True)
            mapped = destination_root / resolved.relative_to(source_root.resolve())
            if not resolved.is_dir():
                dest.parent.mkdir(parents=True, exist_ok=True)
                copy_file(resolved, dest)
            else:
                LINKS.append({"path": relative(dest), "target": relative(mapped)})
                LINK_TARGETS.append((resolved, mapped))
            continue
        if entry.is_dir(follow_symlinks=False):
            copy_regular_tree(src, dest, mapping)
        elif entry.is_file(follow_symlinks=False):
            copy_file(src, dest)


def inventory(folder: Path) -> dict:
    digest = hashlib.sha256()
    count = total = 0
    for root, dirs, files in os.walk(folder):
        for name in dirs + files:
            path = Path(root) / name
            if path.is_junction() or path.is_symlink():
                raise RuntimeError(f"Reparse point leaked into staged payload: {path}")
        for name in sorted(files):
            path = Path(root) / name
            rel = path.relative_to(folder).as_posix()
            digest.update(rel.encode("utf-8"))
            native_path = ("\\\\?\\" + str(path.absolute())) if os.name == "nt" else str(path)
            with open(native_path, "rb") as stream:
                digest.update(hashlib.file_digest(stream, "sha256").digest())
            count += 1
            total += os.stat(native_path).st_size
    return {"path": relative(folder), "files": count, "bytes": total, "mib": round(total / 1024**2, 2),
            "inventory_sha256": digest.hexdigest()}


def supplement_sharp_native_libs():
    """Next's trace omits companion DLLs required by the pinned Windows addon."""
    package = Path('node_modules/.pnpm/@img+sharp-win32-x64@0.35.4/node_modules/@img/sharp-win32-x64/lib')
    source = ROOT / 'upstream/OpenMAIC' / package
    target = STAGE / 'runtime/openmaic-standalone' / package
    expected = {'sharp-win32-x64-0.35.4.node', 'libvips-42.dll', 'libvips-cpp-8.18.6.dll'}
    if not source.is_dir() or not expected.issubset({path.name for path in source.iterdir()}):
        raise RuntimeError('Pinned Windows sharp native addon and companion DLLs are incomplete')
    target.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in sorted(expected):
        original = source / name
        if original.is_symlink() or original.is_junction() or not original.is_file():
            raise RuntimeError('Unexpected sharp native dependency path: ' + name)
        copy_file(original, target / name)
        actual = hashlib.sha256((target / name).read_bytes()).hexdigest()
        if actual != hashlib.sha256(original.read_bytes()).hexdigest():
            raise RuntimeError('Sharp native dependency copy failed integrity: ' + name)
        rows.append({'path': relative(target / name), 'bytes': original.stat().st_size, 'sha256': actual})
    return rows


def configure_next_image_cache(server: Path):
    """Apply one official runtime-only cache setting; retain image URLs/optimizer."""
    marker = '// DeepSteam modification 2026-10-11: separate-storage image disk cache policy.'
    anchor = 'process.env.__NEXT_PRIVATE_STANDALONE_CONFIG = JSON.stringify(nextConfig)'
    original = server.read_bytes().decode('utf-8')
    if original.count(anchor) != 1 or original.count('const nextConfig = ') != 1:
        raise RuntimeError('Unexpected generated Next entry structure; no runtime injection applied')
    source_sha = hashlib.sha256(original.encode('utf-8')).hexdigest()
    injected = (marker + '\n' + "if (process.env.DEEPSTEAM_SEPARATE_STORAGE === '1') {\n"
                '  nextConfig.images = { ...nextConfig.images, maximumDiskCacheSize: 0 };\n}\n\n')
    if marker in original:
        if original.count(marker) != 1 or injected not in original:
            raise RuntimeError('Existing generated cache modification differs from this reviewed policy')
        unmodified = original.replace(injected, '', 1)
        return {'path': relative(server), 'already_applied': True,
                'unmodified_generated_sha256': hashlib.sha256(unmodified.encode('utf-8')).hexdigest(),
                'generated_sha256': source_sha, 'policy': 'flag1: images.maximumDiskCacheSize=0; flag0: unchanged',
                'official_source': 'https://nextjs.org/docs/app/api-reference/components/image#maximumdiskcachesize'}
    optimizer = server.parent / 'node_modules/next/dist/server/image-optimizer.js'
    if not optimizer.is_file():
        link_path = relative(server.parent / 'node_modules/next')
        links = json.loads((STAGE / 'installer/junctions.json').read_text('utf-8'))
        link = next((item for item in links if item['path'] == link_path), None)
        if link:
            optimizer = STAGE / link['target'] / 'dist/server/image-optimizer.js'
    optimizer_source = optimizer.read_text('utf-8')
    if 'nextConfig.images.maximumDiskCacheSize !== 0' not in optimizer_source or 'if (!this.isDiskCacheEnabled)' not in optimizer_source:
        raise RuntimeError('Installed Next lacks the official zero-disk-image-cache option')
    modified = original.replace(anchor, injected + anchor, 1)
    server.write_text(modified, 'utf-8', newline='')
    return {'path': relative(server), 'unmodified_generated_sha256': source_sha,
            'generated_sha256': hashlib.sha256(modified.encode('utf-8')).hexdigest(),
            'policy': 'flag1: images.maximumDiskCacheSize=0; flag0: unchanged',
            'official_source': 'https://nextjs.org/docs/app/api-reference/components/image#maximumdiskcachesize'}


def main():
    start = time.monotonic()
    STAGE.mkdir(parents=True, exist_ok=True)
    source_manifest = ROOT / "runtime" / "native-frontend.json"
    if '--native-manifest' in sys.argv:
        source_manifest = Path(sys.argv[sys.argv.index('--native-manifest') + 1])
    active = json.loads(source_manifest.read_text(encoding="utf-8"))
    reuse_render = '--reuse-render' in sys.argv
    reuse_native = '--reuse-native' in sys.argv
    reuse_openmaic = '--reuse-openmaic' in sys.argv
    if reuse_render or reuse_openmaic:
        previous_links = json.loads((STAGE / 'installer/junctions.json').read_text('utf-8'))
        LINKS.extend(row for row in previous_links
                     if (reuse_render and row['path'].startswith('runtime/render-service/'))
                     or (reuse_openmaic and row['path'].startswith('runtime/openmaic-standalone/')))
    native_source = Path(active["root"])
    native_target = STAGE / "runtime" / "native-frontends" / active["build_id"]
    if reuse_native:
        staged_native = json.loads((STAGE / 'runtime/native-frontend.json').read_text('utf-8'))
        if staged_native['build_id'] != active['build_id'] or not native_target.is_dir():
            raise RuntimeError('Requested native reuse does not match active build')
    else:
        clean_managed_stage(STAGE / 'runtime/native-frontends')
        copy_regular_tree(native_source, native_target, (native_source, native_target))
    native_manifest = dict(active)
    native_manifest["root"] = relative(native_target)
    native_manifest["server"] = relative(native_target / "server.js")
    (STAGE / "runtime" / "native-frontend.json").write_text(json.dumps(native_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DeepSteam native UI staged", flush=True)

    openmaic = ROOT / "upstream" / "OpenMAIC"
    openmaic_target = STAGE / "runtime" / "openmaic-standalone"
    if reuse_openmaic:
        if not (openmaic_target / 'server.js').is_file():
            raise RuntimeError('Requested OpenMAIC reuse is missing its standalone server')
    else:
        clean_managed_stage(openmaic_target)
        copy_regular_tree(openmaic / ".next" / "standalone", openmaic_target, (openmaic, openmaic_target), root_excludes={"data"})
        copy_regular_tree(openmaic / ".next" / "static", openmaic_target / ".next" / "static", (openmaic, openmaic_target))
        copy_regular_tree(openmaic / "public", openmaic_target / "public", (openmaic, openmaic_target))
    supplement_sharp_native_libs()
    print("OpenMAIC standalone and browser assets staged", flush=True)

    render_source = openmaic / "render-service"
    render_target = STAGE / "runtime" / "render-service"
    if not reuse_render:
        clean_managed_stage(render_target)
        for directory in ("src", "scripts", "node_modules"):
            copy_regular_tree(render_source / directory, render_target / directory, (render_source, render_target))
        for name in ("package.json", "package-lock.json", "pnpm-lock.yaml", "tsconfig.json", "README.md", "WINDOWS-EDUAGENT.md", "resource-config.example.json"):
            if (render_source / name).is_file():
                copy_file(render_source / name, render_target / name)
        copy_file(openmaic / "LICENSE", render_target / "LICENSE")
    print("Renderer source and locked dependency tree staged", flush=True)

    # A traced package may omit an otherwise referenced directory. Fill only
    # those explicitly linked dependency targets, never the checkout as a whole.
    cursor = 0
    while cursor < len(LINK_TARGETS):
        src, dest = LINK_TARGETS[cursor]
        cursor += 1
        if not dest.exists():
            src_base, dest_base = ((render_source, render_target) if src.is_relative_to(render_source)
                                  else (openmaic, openmaic_target))
            copy_regular_tree(src, dest, (src_base, dest_base))
    unique = {item["path"]: item for item in LINKS}
    for item in unique.values():
        destination = STAGE / item["target"]
        if not destination.is_dir():
            raise RuntimeError(f"Missing in-payload junction target: {item}")
        destination.resolve().relative_to(STAGE.resolve())
    installer_dir = STAGE / "installer"
    installer_dir.mkdir(exist_ok=True)
    (installer_dir / "junctions.json").write_text(json.dumps(list(unique.values()), indent=2), encoding="utf-8")

    # Preserve publisher GPL license/readme plus both runtime command-line tools.
    ffmpeg_roots = list((render_source / ".local" / "ffmpeg").glob("*/bin/ffmpeg.exe"))
    if len(ffmpeg_roots) != 1:
        raise RuntimeError("Expected one previously checksum-verified FFmpeg distribution")
    ffmpeg_source = ffmpeg_roots[0].parent.parent
    ffmpeg_target = STAGE / "runtime" / "ffmpeg"
    (ffmpeg_target / "bin").mkdir(parents=True, exist_ok=True)
    if not reuse_render:
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            copy_file(ffmpeg_source / "bin" / name, ffmpeg_target / "bin" / name)
        for path in ffmpeg_source.iterdir():
            if path.is_file():
                copy_file(path, ffmpeg_target / path.name)
    ffmpeg_provenance = json.loads((ROOT / "reports" / "render-dependencies.json").read_text(encoding="utf-8"))
    ffmpeg_provenance["path"] = relative(ffmpeg_target / "bin" / "ffmpeg.exe")
    (ffmpeg_target / "PROVENANCE.json").write_text(json.dumps(ffmpeg_provenance, indent=2), encoding="utf-8")

    licenses = STAGE / "licenses"
    licenses.mkdir(exist_ok=True)
    copy_file(ROOT / "upstream" / "DeepTutor" / "LICENSE", licenses / "DeepTutor-LICENSE")
    copy_file(ROOT / "upstream" / "DeepTutor" / "THIRD_PARTY_NOTICES.md", licenses / "DeepTutor-THIRD_PARTY_NOTICES.md")
    copy_file(openmaic / "LICENSE", licenses / "OpenMAIC-LICENSE")

    finalize(start, active, [native_target, openmaic_target, render_target, ffmpeg_target], len(unique))


def finalize(start, active, components, junction_count):
    supplement_sharp_native_libs()
    entry_modifications = [configure_next_image_cache(components[0] / 'server.js'),
                           configure_next_image_cache(STAGE / 'runtime/openmaic-standalone/server.js')]
    licenses = STAGE / "licenses"
    licenses.mkdir(exist_ok=True)
    copy_file(ROOT / "upstream" / "DeepTutor" / "LICENSE", licenses / "DeepTutor-LICENSE")
    copy_file(ROOT / "upstream" / "DeepTutor" / "THIRD_PARTY_NOTICES.md", licenses / "DeepTutor-THIRD_PARTY_NOTICES.md")
    copy_file(ROOT / "upstream" / "OpenMAIC" / "LICENSE", licenses / "OpenMAIC-LICENSE")
    report = {"created_local": time.strftime("%Y-%m-%d %H:%M:%S"), "source_root": str(ROOT),
              "native_build_id": active["build_id"], "runtime_node_minimum": ">=22.19.0; tested Node 24.19.0 win-x64",
              "components": [inventory(path) for path in components],
              "junctions": junction_count, "junction_manifest": "installer/junctions.json", "staged_reparse_points": 0,
              "credentials_and_user_data_copied": False, "elapsed_seconds": round(time.monotonic() - start, 2)}
    report['generated_entry_modifications'] = entry_modifications
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if "--finalize-only" in sys.argv:
        native = json.loads((STAGE / "runtime" / "native-frontend.json").read_text(encoding="utf-8"))
        links = json.loads((STAGE / "installer" / "junctions.json").read_text(encoding="utf-8"))
        finalize(time.monotonic(), native, [STAGE / native["root"], STAGE / "runtime" / "openmaic-standalone",
                                          STAGE / "runtime" / "render-service", STAGE / "runtime" / "ffmpeg"], len(links))
    else:
        main()
