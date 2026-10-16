"""Build the DeepSteam Windows installer (EXE) from this standalone installation.

Run with the bundled Python:  runtime\\python\\python.exe -I -B installer\\build_standalone_release.py ...

  --dry-run   inventory only: what would be packaged, what is excluded, junctions,
              anything that looks private. Nothing is written except the report.
  (default)   write <out>\\DeepSteam-Setup-<version>-x64.exe (+ .payload.dat when the
              payload is larger than a Windows EXE may be), then run the installer's
              own --self-test against it.

Only program files are packaged. Personal state (DeepTutor home with model keys,
workspaces, chats, classrooms, Harness sessions and tokens, the desktop browser
profile with site logins, logs, caches, reports) never enters the payload; the
installed copy creates empty data on first launch (installer/prepare_install.py).
The installation itself is never modified.
"""
from __future__ import annotations
import argparse, hashlib, json, os, stat, struct, subprocess, sys, time, zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
TRAILER_MAGIC = b'DeepSteamZip64v1'
MAX_PE_BYTES = 4 * 1024**3 - 65536 - 64

# Personal or machine state: excluded wherever the program writes it.
EXCLUDED_DIRS = {
    'data', 'logs', 'cache', 'reports', 'patches', '_repair-kit',
    'installer/app-payload', 'installer/releases',
    'runtime/deeptutor-home', 'runtime/harness-state', 'runtime/desktop-profile',
    'runtime/desktop-claims', 'runtime/document-jobs', 'runtime/temp', 'runtime/local-qwen',
    'runtime/openmaic-standalone/data', 'runtime/openmaic-standalone/%SystemDrive%',
    'runtime/render-service/.local',
}
EXCLUDED_DIR_NAMES = {'__pycache__', '.pytest_cache'}
EXCLUDED_FILES = {
    '.deepsteam-installed', '.deepsteam-installing', '.deepsteam-uninstall-id', 'PORTABLE-MANIFEST.sha256',
    'CLAUDE-CODEX-协作.md', '安装记录.txt', 'DeepSteam.exe', 'Uninstall-DeepSteam.exe',
    'installer/payload-manifest.json', 'installer/junctions.json', 'installer/uninstall-manifest.json',
    'runtime/deeptutor-processes.json', 'runtime/openmaic-process.json', 'runtime/portal-process.json',
    'runtime/video-follow-cache-version',
}
INCLUDED_EXCEPTIONS = {'reports/demo-lesson-video.mp4'}
EXCLUDED_SUFFIXES = ('.pyc', '.pyo', '.partial', '.tmp', '.log', '.sqlite3', '.sqlite3-wal', '.sqlite3-shm', '.db-journal')
STORED_SUFFIXES = ('.zip', '.gz', '.7z', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.mp3', '.woff', '.woff2',
                   '.gguf', '.onnx', '.safetensors', '.bin', '.pt', '.pak', '.asar')
SUSPICIOUS_NAMES = ('credential', 'cookie', 'secret', 'token', 'auth.json', 'login data', 'web data', 'history', '.env')


def native(path: Path) -> str:
    value = str(path)
    return value if value.startswith('\\\\?\\') else '\\\\?\\' + value


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_reparse(entry) -> bool:
    try:
        return bool(entry.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def active_frontend() -> str:
    manifest = json.loads((ROOT / 'runtime' / 'native-frontend.json').read_text('utf-8'))
    return PurePosixPath(manifest['root'].replace('\\', '/')).as_posix()


def scan():
    frontend = active_frontend()
    files, links, excluded, suspicious = [], [], {}, []
    def skip(path, reason):
        excluded[reason] = excluded.get(reason, 0) + 1
    stack = [ROOT]
    while stack:
        folder = stack.pop()
        with os.scandir(native(folder)) as entries:
            for entry in entries:
                path = folder / entry.name
                r = rel(path)
                if is_reparse(entry):
                    if any(r == d or r.startswith(d + '/') for d in EXCLUDED_DIRS):
                        skip(r, 'link inside excluded state'); continue
                    target = os.readlink(native(path))
                    target = target[4:] if target.startswith('\\\\?\\') else target
                    tpath = Path(target)
                    try:
                        trel = tpath.resolve().relative_to(ROOT.resolve()).as_posix()
                    except ValueError:
                        raise RuntimeError('Link points outside the installation: ' + r + ' -> ' + target)
                    links.append({'path': r, 'target': trel}); continue
                if entry.is_dir(follow_symlinks=False):
                    if (entry.name in EXCLUDED_DIR_NAMES or r in EXCLUDED_DIRS
                            or (r.startswith('runtime/native-frontends/') and r.count('/') == 2 and r != frontend)
                            or r.endswith('/.next/cache')):
                        if not (r == 'reports'):
                            skip(r, 'state, cache or inactive build'); continue
                    stack.append(path); continue
                if r.startswith('reports/') and r not in INCLUDED_EXCEPTIONS:
                    skip(r, 'reports'); continue
                name = entry.name
                if (r in EXCLUDED_FILES or name.endswith(EXCLUDED_SUFFIXES) or name == '.env' or name.startswith('.env.')
                        or (r.startswith('runtime/') and r.count('/') == 1 and name.startswith('native-frontend-before'))
                        or (r.startswith('runtime/render-service/') and name == 'process.json')):
                    skip(r, 'state or generated file'); continue
                size = entry.stat(follow_symlinks=False).st_size
                low = r.lower()
                if any(s in name.lower() for s in SUSPICIOUS_NAMES) and '/node_modules/' not in low and '/site-packages/' not in low \
                        and '/lib/' not in low and '/.next' not in low and '/static/' not in low:
                    suspicious.append(r)
                files.append((r, path, size))
    files.sort(key=lambda row: row[0])
    links.sort(key=lambda row: row['path'])
    return files, links, excluded, suspicious, frontend


def summarize(files):
    by_top = {}
    for r, _, size in files:
        top = '/'.join(r.split('/')[:2]) if r.startswith('runtime/') else r.split('/')[0]
        count, total = by_top.get(top, (0, 0)); by_top[top] = (count + 1, total + size)
    return {k: {'files': v[0], 'mb': round(v[1] / 1048576, 1)} for k, v in sorted(by_top.items(), key=lambda kv: -kv[1][1])}


def program_version() -> str:
    source = (ROOT / 'installer' / 'DeepSteamSetup.cs').read_text('utf-8')
    marker = 'internal const string Version = "'
    i = source.index(marker) + len(marker)
    return source[i:source.index('"', i)]


def compile_exe(dest: Path):
    subprocess.run([str(CSC), '/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/codepage:65001',
                    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                    '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
                    '/win32manifest:' + str(ROOT / 'installer' / 'DeepSteam.manifest'),
                    '/resource:' + str(ROOT / 'installer' / 'DeepSteamSetup.cs') + ',DeepSteamSetup.cs',
                    '/out:' + str(dest), str(ROOT / 'installer' / 'DeepSteamSetup.cs')],
                   check=True, creationflags=0x08000000)


def build_zip(files, links, version, archive: Path, log):
    rows = []
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as package:
        for index, (r, path, size) in enumerate(files):
            digest = hashlib.sha256()
            info = zipfile.ZipInfo(r, date_time=time.localtime(os.stat(native(path)).st_mtime)[:6])
            info.compress_type = zipfile.ZIP_STORED if r.lower().endswith(STORED_SUFFIXES) else zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(native(path), 'rb') as source, package.open(info, 'w', force_zip64=size > 2**31) as target:
                while block := source.read(4 * 1024 * 1024):
                    digest.update(block); target.write(block)
            rows.append({'path': r, 'bytes': size, 'sha256': digest.hexdigest()})
            if index % 2000 == 0:
                log(f'  packed {index}/{len(files)}')
        manifest = {'product': 'DeepSteam', 'version': version, 'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'source': 'standalone installation', 'user_data_copied': False, 'credentials_copied': False,
                    'files': rows}
        package.writestr('installer/payload-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=1))
        package.writestr('installer/junctions.json', json.dumps(links, ensure_ascii=False, indent=2))
    return rows


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(ROOT.parent / 'DeepSteam-Release'))
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    report_path = out / ('dry-run-report.json' if args.dry_run else 'build-report.json')
    log_path = out / ('dry-run.log' if args.dry_run else 'build.log')
    logf = open(log_path, 'a', encoding='utf-8')
    def log(message):
        line = time.strftime('%H:%M:%S ') + message
        print(line, flush=True); logf.write(line + '\n'); logf.flush()
    version = program_version()
    log(f'DeepSteam {version}: scanning {ROOT}')
    files, links, excluded, suspicious, frontend = scan()
    total = sum(size for _, _, size in files)
    report = {'version': version, 'root': str(ROOT), 'active_frontend': frontend, 'files': len(files),
              'bytes': total, 'gb': round(total / 1024**3, 2), 'junctions': len(links), 'excluded': excluded,
              'suspicious_names_for_review': suspicious[:200], 'by_folder': summarize(files)}
    log(f'{len(files)} files, {report["gb"]} GB, {len(links)} junctions, suspicious {len(suspicious)}')
    if args.dry_run:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8'); log('dry run written'); return 0
    stem = f'DeepSteam-Setup-{version}-x64'
    exe, payload, archive = out / (stem + '.exe'), out / (stem + '.payload.dat'), out / (stem + '.zip.building')
    for existing in (exe, payload, archive):
        if existing.exists():
            raise RuntimeError('Output already exists; choose a new --out folder: ' + str(existing))
    log('compiling installer EXE'); compile_exe(exe)
    log('packing payload'); rows = build_zip(files, links, version, archive, log)
    zip_bytes = archive.stat().st_size; zip_sha = sha256_of(archive)
    exe_bytes = exe.stat().st_size
    if exe_bytes + zip_bytes + 64 <= MAX_PE_BYTES:
        with open(exe, 'ab') as output, open(archive, 'rb') as source:
            offset = output.tell()
            while block := source.read(8 * 1024 * 1024): output.write(block)
            output.write(struct.pack('<16sQQ32s', TRAILER_MAGIC, offset, zip_bytes, bytes.fromhex(zip_sha)))
        archive.unlink(); container = 'embedded in EXE'
    else:
        with open(archive, 'ab') as output:
            output.write(struct.pack('<16sQQ32s', TRAILER_MAGIC, 0, zip_bytes, bytes.fromhex(zip_sha)))
        archive.rename(payload); container = 'EXE + payload.dat (keep both files in one folder)'
    log('payload ' + container + f', {round(zip_bytes / 1024**3, 2)} GB compressed')
    self_test = out / 'self-test.txt'
    result = subprocess.run([str(exe), '--self-test', str(self_test)], timeout=3600)
    test_text = self_test.read_text('utf-8', errors='replace').strip() if self_test.exists() else '(no report)'
    log('self-test: ' + test_text)
    report.update(container=container, compressed_bytes=zip_bytes, payload_sha256=zip_sha, exe=str(exe),
                  exe_sha256=sha256_of(exe), self_test=test_text, self_test_exit=result.returncode)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    log('BUILD ' + ('OK' if result.returncode == 0 and test_text.startswith('PASS') else 'FAILED'))
    return 0 if result.returncode == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
