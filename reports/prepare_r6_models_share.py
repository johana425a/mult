"""Prepare the public r6 source, licenses and guides beside the verified installer.

Reuses the established bounded public-source walk and secret-pattern checks.
Does not inspect installed user state, copy runtimes, contact a model or write E.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def import_script(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = import_script('r6_release_package', 'reports/build_r6_models_release.py')
clean = import_script('r6_clean_source_rules', 'reports/prepare_unified_clean_source.py')
boundary = import_script('r6_source_boundaries', 'reports/capture_unified_public_freeze_20261012.py')
retired = import_script('r6_retired_components', 'installer/retired_components.py')
packager = clean.packager
packager.SKIP_DIRS.update(boundary.SKIP_SOURCE_DIRECTORIES)
packager.SKIP_SUFFIXES.update(boundary.SKIP_SOURCE_SUFFIXES)
PUBLIC_REPORT_SOURCES = (
    'build_r6_models_release.py', 'prepare_r6_models_share.py',
    'prepare_unified_clean_source.py', 'capture_unified_public_freeze_20261012.py',
    'refresh_unified_release_20261012.py', 'build_unified_20261012_candidate.py',
    'prepare_unified_public_stage.py', 'prepare_unified_frontend_components.py',
    'build_unified_r5_candidate.py', 'assemble_unified_r5_spec.py',
    'refresh_unified_native_stage.py', 'test_unified_packaging_contract.py',
)
MINERU_LICENSE_MANIFEST = 'reports/mineru-licensed-runtime-files-20261012.json'
MINERU_LICENSE_ROWS = {}


def allowed(path):
    return (packager.allowed(path) and path.name.casefold() not in boundary.SKIP_SOURCE_FILES
            and not path.name.casefold().startswith('.env')
            and not retired.retired_program_path(path.as_posix()))


def checked_public_source(name, path):
    release.h.safe_name(name)
    if (not allowed(Path(name)) or path.is_symlink() or path.is_junction()
            or not path.resolve().is_relative_to(ROOT.resolve())):
        raise RuntimeError('Not a distributable public source: ' + name)
    blob = path.read_bytes()
    if name.startswith('licenses/mineru/'):
        row = MINERU_LICENSE_ROWS.get(name)
        if (row is None or len(blob) != row['bytes']
                or hashlib.sha256(blob).hexdigest() != row['sha256']):
            raise RuntimeError('MinerU license is not covered by the frozen verified component: ' + name)
    if path.suffix.casefold() in packager.TEXT_SUFFIXES:
        for kind, pattern in packager.SECRET_PATTERNS.items():
            if re.search(pattern, blob):
                raise RuntimeError('Source credential-pattern review required: ' + name + ' (' + kind + ')')
    return blob


def mineru_license_sources():
    """Select only final component license rows; never walk historical evidence."""
    manifest = ROOT / MINERU_LICENSE_MANIFEST
    value = json.loads(manifest.read_text('utf8'))
    if (value.get('schema') != 'deepsteam-mineru-runtime-v1'
            or value.get('engine_version') != '4.0.12' or value.get('tool_only') is not True
            or value.get('redistribution_status') != 'verified'):
        raise RuntimeError('Final verified MinerU component is required for source licenses')
    selected, descriptors, folded = {}, {}, set()
    for row in value['files']:
        name = row['target']
        if not name.startswith('licenses/mineru/'):
            continue
        release.h.safe_name(name)
        if not allowed(Path(name)) or name.casefold() in folded:
            raise RuntimeError('Invalid or duplicate MinerU license target: ' + name)
        source = Path(row['source'])
        source = source if source.is_absolute() else ROOT / source
        try:
            release.h.safe_name(source.relative_to(ROOT).as_posix())
        except (ValueError, RuntimeError) as error:
            raise RuntimeError('MinerU license source is outside the public workspace') from error
        if not source.resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError('MinerU license source escaped workspace: ' + name)
        cursor = source
        while cursor != ROOT.parent:
            if cursor.is_symlink() or cursor.is_junction() or getattr(cursor.lstat(), 'st_file_attributes', 0) & 0x400:
                raise RuntimeError('MinerU license source contains a reparse point: ' + name)
            cursor = cursor.parent
        blob = source.read_bytes()
        if len(blob) != row['bytes'] or hashlib.sha256(blob).hexdigest() != row['sha256']:
            raise RuntimeError('Verified MinerU license changed: ' + name)
        selected[name], descriptors[name] = source, dict(row)
        folded.add(name.casefold())
    if not selected:
        raise RuntimeError('Final MinerU component has no distributable licenses')
    MINERU_LICENSE_ROWS.clear()
    MINERU_LICENSE_ROWS.update(descriptors)
    return selected


def source_files():
    selected = {}
    for name in packager.ROOT_FILES:
        selected[name] = ROOT / name
    for directory in ('portal', 'integration', 'scripts', 'tests', 'demo', 'desktop'):
        for path in boundary.walk_public_sources(ROOT / directory):
            name = path.relative_to(ROOT).as_posix()
            if allowed(Path(name)):
                selected[name] = path
    license_root = ROOT / 'licenses'
    if license_root.is_symlink() or license_root.is_junction():
        raise RuntimeError('Public licenses cannot be a reparse root')
    for child in sorted(license_root.iterdir()):
        if child.name.casefold() == 'mineru' or child.is_symlink() or child.is_junction():
            continue
        paths = boundary.walk_public_sources(child) if child.is_dir() else [child]
        for path in paths:
            name = path.relative_to(ROOT).as_posix()
            if path.is_file() and allowed(Path(name)):
                selected[name] = path
    selected.update(mineru_license_sources())
    for name in packager.INSTALLER_SOURCES + packager.HARNESS_INSTALLER_SOURCES:
        selected['installer/' + name] = ROOT / 'installer' / name
    for name in ('build_document_release.py', 'document_runtime.py', 'document-runtime-requirements.txt',
                 'retired_components.py', 'mineru_runtime.py', 'mineru-runtime-lock.txt',
                 'DOCUMENT-RELEASE.md', 'document-fixtures/scanned-cn.png', 'Invoke-DocumentColdAcceptance.ps1'):
        selected['installer/' + name] = ROOT / 'installer' / name
    for name in PUBLIC_REPORT_SOURCES:
        selected['reports/' + name] = ROOT / 'reports' / name
    versions = {}
    for project in ('DeepTutor', 'OpenMAIC', 'DeepSeekHarness'):
        repo = ROOT / 'upstream' / project
        for raw in packager.git(repo, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0'):
            if not raw:
                continue
            relative = Path(raw.decode('utf8'))
            path = repo / relative
            name = 'upstream/' + project + '/' + relative.as_posix()
            if path.is_file() and allowed(Path(name)):
                selected[name] = path
        versions[project] = {
            'commit': packager.git(repo, 'rev-parse', 'HEAD').decode().strip(),
            'version': packager.git(repo, 'describe', '--tags', '--always', 'HEAD').decode().strip(),
            'working_tree_changes_included': True,
        }
    selected['installer/DeepSteamSetup-r6.cs'] = release.ARTIFACT / 'DeepSteamSetup-r6.cs'
    # Retired product-owned onboarding files are excluded even if a future root
    # source allowlist adds them explicitly. Upstream sources and general model
    # licenses retain their own paths and are not classified by brand words.
    selected = {name: path for name, path in selected.items()
                if not retired.retired_program_path(name)}
    return selected, versions


def release_notes(build):
    return f'''# DeepSteam release notes and modifications

Version: {release.VERSION}
Native interface build: {build['native_build_id']}
Classroom interface build: {build['openmaic_next_build_id']}
Timezone database: tzdata 2026.5

Changes include unified product branding, model selection and routing,
workspace and book model controls, usage records, timezone support,
and content-management actions with explicit resource boundaries.

DeepSteam integrates HKUDS/DeepTutor, THU-MAIC/OpenMAIC, DeepSeek Harness,
and other open-source components. Ownership, technical identifiers,
and licenses are retained in licenses/ and corresponding source trees.
Product naming does not transfer upstream copyright.

Public source includes application modifications and build scripts.
It excludes user databases, sign-in state, credentials, private documents,
runtime caches, model weights, and development acceptance reports.
Source fixtures are not installation-directory requirements.

Container CRC, per-file SHA-256, and installer self-tests are distinct from
a fresh installation on a second physical machine, a new API account,
or real classroom generation. Do not infer those acceptance results.
'''


def build_zip(path, selected, generated):
    manifest = []
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in sorted(set(selected) | set(generated)):
            blob = generated[name] if name in generated else checked_public_source(name, selected[name])
            archive.writestr('DeepSteam/' + name, blob)
            manifest.append({'path': name, 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()})
        summary = {'version': release.VERSION, 'files': manifest, 'file_count': len(manifest),
                   'user_data_copied': False, 'credentials_copied': False}
        archive.writestr('DeepSteam/PACKAGE-MANIFEST.json', release.h.json_bytes(summary))
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != len(manifest) + 1 or archive.testzip() is not None:
            raise RuntimeError('Public ZIP membership/CRC failed')
        for row in manifest:
            blob = archive.read('DeepSteam/' + row['path'])
            if len(blob) != row['bytes'] or hashlib.sha256(blob).hexdigest() != row['sha256']:
                raise RuntimeError('Public ZIP SHA differs: ' + row['path'])
    return {'name': path.name, 'bytes': path.stat().st_size, 'sha256': release.h.digest(path),
            'files': len(manifest) + 1, 'uncompressed_bytes': sum(row['bytes'] for row in manifest),
            'crc_passed': True, 'all_file_sha_passed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-spec-sha256', required=True)
    args = parser.parse_args()
    if release.h.digest(release.SPEC) != args.expected_spec_sha256:
        raise RuntimeError('Final package specification changed')
    build = json.loads((release.ARTIFACT / 'build-report.json').read_text('utf8'))
    if (build['spec']['sha256'] != args.expected_spec_sha256 or build['version'] != release.VERSION
            or not all(build.get(k) is True for k in ('all_file_sha_passed', 'crc_passed', 'actual_exe_self_test_passed'))):
        raise RuntimeError('A verified r6 installer is required first')
    for row in build['distribution_files']:
        release.h.checked_file(row)
    destination = release.ARTIFACT / 'release'
    selected, upstream = source_files()
    notes = release_notes(build).encode('utf8')
    public_identity = {'version': release.VERSION, 'native_build_id': build['native_build_id'],
                       'openmaic_next_build_id': build['openmaic_next_build_id'], 'tzdata_version': '2026.5',
                       'upstream': upstream, 'deferred_validation': build['deferred_validation'],
                       'source_reports_include_runtime_receipts': False}
    generated = {'RELEASE-r6.md': notes, 'RELEASE-IDENTITY.json': release.h.json_bytes(public_identity)}
    source = destination / 'DeepSteam-r6-Source-And-Demo-20261012.zip'
    source_report = build_zip(source, selected, generated)
    for project in upstream:
        if not any(name.startswith('upstream/' + project + '/LICENSE') for name in selected):
            raise RuntimeError('Required upstream source license missing: ' + project)
    docs_selected = {name: path for name, path in selected.items() if name.startswith('licenses/')}
    # Preserve all runtime component licenses too, without unpacking the runtime.
    docs_generated = dict(generated)
    payload = destination / f'DeepSteam-Setup-{release.VERSION}-x64.payload.dat'
    with zipfile.ZipFile(payload) as archive:
        for name in archive.namelist():
            if name.startswith('licenses/') and name not in docs_selected:
                release.h.safe_name(name)
                docs_generated[name] = archive.read(name)
    docs = destination / 'DeepSteam-r6-Guides-And-Licenses-20261012.zip'
    docs_report = build_zip(docs, docs_selected, docs_generated)
    readme = f'''DeepSteam distribution ({release.VERSION})

Keep DeepSteam-Setup-{release.VERSION}-x64.exe and its matching .payload.dat
in the same folder, then run the installer. Both files are required.
Do not rename or move the payload independently. Select a folder with
sufficient free space. Use the desktop launcher after installation.

Each user signs in to a model service or supplies their own API settings.
Embeddings, speech recognition, and speech synthesis are configured
separately. A chat connection does not configure these services.
Provider permissions and fees apply.

Close the previous application before upgrading. Existing user data stays
in its selected storage location. The distribution does not include,
migrate, or back up another user's data or credentials.

The source archive is for inspection and development. Guides and licenses
retain attribution and modification records. CHECKSUMS.json lists SHA-256
hashes for checking copied files. Container verification and self-tests
do not replace a fresh installation on a second physical machine or
a separate real model-generation acceptance test.
'''
    readme_path = destination / 'READ-ME-FIRST.txt'
    release.write_new(readme_path, readme.encode('utf8'))
    files = []
    for path in sorted(destination.iterdir()):
        if not path.is_file():
            raise RuntimeError('Distribution directory must contain only release files')
        files.append({'name': path.name, 'bytes': path.stat().st_size, 'sha256': release.h.digest(path)})
    release.write_new(destination / 'CHECKSUMS.json', {'version': release.VERSION, 'algorithm': 'SHA-256', 'files': files})
    report = {'version': release.VERSION, 'source_zip': source_report, 'licenses_zip': docs_report,
              'distribution_file_count': len(files) + 1, 'source_reports_include_runtime_receipts': False,
              'user_data_copied': False, 'credentials_copied': False, 'written_to_e': False,
              'source_secret_pattern_findings': 0, 'upstream_licenses_present': True,
              'files': [release.descriptor(path) for path in sorted(destination.iterdir())]}
    release.write_new(release.ARTIFACT / 'public-share-report.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
