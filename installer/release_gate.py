"""Fail-closed acceptance and promotion for one immutable release candidate.

This is a local engineering gate, not a signature against a malicious operator.
Evidence producers must be trusted. A passing process exit alone is insufficient.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import competition_acceptance as competition

SCHEMA = 1
MAX_AGE = 24 * 3600
LIVE_MODELS = ('gpt-6.1-sol', 'deepseek-flash', 'deepseek-v4-pro')
CASES = {
    'models': ('test_model_repairs.py',),
    'answers': ('test_harness_answer.py', 'r11/test_harness_result_contract.py', 'test_document_long_paths.py', 'test_document_tool_schema.mjs', 'test_shared_reader_contract.py'),
    'personalized': ('test_mastery_harness_boundary.py', 'test_mastery_storage.py', 'test_mastery_source_alias.py', 'r11/test_learning_record_archive.py'),
    'reading_quiz': ('r11/test_video_source_revision.py', 'r11/test_quiz_planning.py', 'test_reading_directory_commit.py', 'test_pdf_import_index.py', 'test_document_size_policy.py', 'test_streaming_reading_upload.cjs', 'test_pdf_viewer_contract.cjs', 'test_quiz_answer_persistence.cjs', 'test_reading_async_io.py', 'test_reading_source_switch.cjs'),
    'classroom': ('r11/test_prefetch_refill.mjs', 'r11/test_compact_flow.mjs', 'r11/test_semantic_slide_layout.mjs', 'r11/test_table_layout.mjs', 'test_classroom_contract.mjs', 'test_classroom_startup.py', 'test_classroom_delivery_links.cjs', 'test_classroom_embedding.cjs'),
    'workspace': ('r11/test_sidebar_view_state.cjs', 'test_locale_loading.cjs', 'test_standalone_locale.cjs', 'test_standalone_locale_backend.py', 'test_settings_usability.py', 'test_settings_navigation.cjs', 'test_session_send_readiness.cjs', 'test_cowriter_scope.cjs', 'test_imported_session_workspace.py', 'test_server_event_loop.py', 'test_plugin_discovery_io.py', 'test_internal_http_initialization.py', 'test_model_client_async.py'),
    'fullscreen': ('test_transcript_scroll.cjs', 'test_fullscreen_policy.cjs', 'test_video_components.cjs', 'test_media_position_restore.cjs'),
    'gate': ('test_release_gate.py', 'test_source_integrity.py', 'test_runtime_binding.py', 'test_competition_acceptance.py', 'test_competition_profile.py', 'test_installer_payload_privacy.py', 'test_candidate_packaging.py', 'test_installer_shortcuts.py', 'test_installer_finalization.py', 'test_installer_presentation.py', 'test_desktop_uninstall_entry.cjs'),
}
REQUIRED_CASES = tuple(item for group in CASES.values() for item in group)
NATIVE_STEPS = ('enter_fullscreen', 'scroll_down', 'scroll_up', 'last_cue_visible',
                'no_vertical_oscillation', 'resize', 'exit_fullscreen', 'reopen_persisted')
REQUIRED_EVIDENCE = ('regressions', 'live-models', 'installed-package', 'native-fullscreen', *competition.KINDS)


def runtime_binding(source, runtime):
    """Catch accidentally packaging an older runtime after repairing the source."""
    from release_runtime_binding import verify_runtime
    return verify_runtime(Path(source), Path(runtime))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def descriptor(path):
    p = Path(path).resolve(strict=True)
    if not p.is_file():
        raise ValueError('Not a file: ' + str(p))
    return {'path': str(p), 'bytes': p.stat().st_size, 'sha256': digest(p)}


def checked(row):
    actual = descriptor(row['path'])
    if any(actual[k] != row.get(k) for k in ('bytes', 'sha256')):
        raise ValueError('Evidence or candidate bytes changed: ' + str(row['path']))
    return Path(actual['path'])


def source_identity(root):
    root = Path(root).resolve(strict=True)
    command = ['git', '-C', str(root)]
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    raw = subprocess.check_output(command + ['ls-files', '--cached', '--others', '--exclude-standard', '-z'], creationflags=flags)
    names = sorted(set(x.decode('utf-8') for x in raw.split(b'\0') if x))
    if not names:
        raise ValueError('Source tree is empty')
    h = hashlib.sha256()
    def hash_member(name):
        p = root / name
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise ValueError('Source identity cannot traverse a link: ' + name)
        # A removed tracked file must invalidate earlier acceptance too.
        value = digest(p) if p.is_file() else 'deleted'
        return (name + '\0' + value + '\n').encode('utf-8')
    # Bounded parallel reads of small Windows files; preserve hash order.
    with ThreadPoolExecutor(max_workers=8) as pool:
        for row in pool.map(hash_member,names):h.update(row)
    return {'root': str(root), 'tree_sha256': h.hexdigest(), 'files': len(names)}


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def begin(source, artifacts, directory, version):
    directory = Path(directory).resolve()
    source = Path(source).resolve(strict=True)
    if directory == source or source in directory.parents:
        raise ValueError('Keep run evidence outside the source tree')
    if directory.exists():
        raise ValueError('Use a fresh acceptance directory; old evidence cannot be reused')
    paths = [Path(p).resolve(strict=True) for p in artifacts]
    if not paths or len({p.name.casefold() for p in paths}) != len(paths):
        raise ValueError('Candidate files must be nonempty and have unique names')
    context = {'schema': SCHEMA, 'run_id': uuid.uuid4().hex, 'created_at': time.time(),
               'version': version, 'source': source_identity(source),
               'artifacts': [descriptor(p) for p in paths], 'required_cases': list(REQUIRED_CASES),
               'required_models': list(LIVE_MODELS), 'required_evidence': list(REQUIRED_EVIDENCE)}
    save_new(directory / 'context.json', context)
    return context


def binding(context):
    return hashlib.sha256(json.dumps(context, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_context(context, now=None):
    now = time.time() if now is None else now
    if context.get('schema') != SCHEMA or not context.get('run_id') or not context.get('version'):
        raise ValueError('Invalid candidate context')
    if not 0 <= now - context['created_at'] <= MAX_AGE:
        raise ValueError('Acceptance is stale or future-dated; start a new run')
    if context.get('required_cases') != list(REQUIRED_CASES) or context.get('required_models') != list(LIVE_MODELS):
        raise ValueError('Release policy changed; start a new run')
    if context.get('required_evidence') != list(REQUIRED_EVIDENCE):
        raise ValueError('Competition acceptance policy changed; start a new run')
    if source_identity(context['source']['root']) != context['source']:
        raise ValueError('Source or regression code changed after candidate was frozen')
    if not context.get('artifacts'):
        raise ValueError('No release candidate')
    for row in context['artifacts']:
        checked(row)


def receipt(context, kind, **fields):
    return {'schema': SCHEMA, 'kind': kind, 'binding': binding(context),
            'created_at': time.time(), **fields}


def load_receipt(directory, context, kind):
    path = Path(directory) / (kind + '.json')
    result = json.loads(path.read_text('utf-8'))
    if result.get('schema') != SCHEMA or result.get('kind') != kind or result.get('binding') != binding(context):
        raise ValueError(kind + ': evidence belongs to another source/candidate/run')
    if not context['created_at'] <= result.get('created_at', 0) <= time.time() + 2:
        raise ValueError(kind + ': evidence predates this candidate or is future-dated')
    if result.get('passed') is not True:
        raise ValueError(kind + ': failed, skipped or incomplete')
    return result


def check(directory):
    directory = Path(directory)
    errors = []
    try:
        context = json.loads((directory / 'context.json').read_text('utf-8'))
        validate_context(context)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        return {'passed': False, 'errors': [str(exc)]}
    for kind in REQUIRED_EVIDENCE:
        try:
            row = load_receipt(directory, context, kind)
            if kind == 'regressions':
                generation=json.loads(checked(row['generation_build']).read_text('utf-8'))
                if generation.get('passed') is not True or not generation.get('files'):
                    raise ValueError('Current generation source was not built')
                for built in generation['files']:checked(built)
                cases = row['cases']
                if len(cases) != len(REQUIRED_CASES) or {x['case'] for x in cases} != set(REQUIRED_CASES):
                    raise ValueError('Regression groups missing or duplicated')
                for case in cases:
                    if case.get('status') != 'passed' or case.get('exit_code') != 0 or case.get('assertions', 0) < 1:
                        raise ValueError('Regression failed, skipped, or ran zero assertions: ' + case['case'])
                    checked(case['log'])
                if row.get('source_after') != context['source']:
                    raise ValueError('Source changed during regression')
            elif kind == 'live-models':
                models = row['models']
                if len(models) != len(LIVE_MODELS) or {x['model'] for x in models} != set(LIVE_MODELS):
                    raise ValueError('Required real provider/model coverage missing or duplicated')
                if row.get('evidence_class') != 'live-provider':
                    raise ValueError('Mocks cannot satisfy real provider checks')
                for model in models:
                    if not all(model.get(k) is True for k in ('text_passed', 'tool_passed', 'tool_result_verified', 'frozen_selection')):
                        raise ValueError('Text/tool loop failed: ' + model['model'])
                    if not model.get('tool_names') or model.get('reasoning_effort') != 'high':
                        raise ValueError('Missing actual tool or changed model effort')
                checked(row['transcript'])
                recovery=row.get('synthetic_recovery',{})
                if recovery.get('passed') is not True or recovery.get('attempts')!=3 or recovery.get('answer') or recovery.get('error_count')!=1:
                    raise ValueError('Full Harness failure path did not stop after three attempts')
            elif kind == 'installed-package':
                if not all(row.get(k) is True for k in ('self_test_passed', 'all_payload_hashes_passed', 'source_binding_passed', 'isolated_install')):
                    raise ValueError('Installer, payload, source binding or isolation not verified')
                if row.get('files_verified', 0) < 1:
                    raise ValueError('Empty payload check')
                checked(row['report'])
            elif kind == 'native-fullscreen':
                if row.get('evidence_class') != 'native-ui' or row.get('product') != 'DeepSteam':
                    raise ValueError('DOM replay/browser is not native fullscreen acceptance')
                if not row.get('reviewer') or any(row.get('steps', {}).get(s) is not True for s in NATIVE_STEPS):
                    raise ValueError('Native fullscreen checklist incomplete')
                if not 0 <= row.get('max_scroll_drift_px', 999) <= 1 or row.get('samples', 0) < 30:
                    raise ValueError('Scrolling not stable or insufficiently observed')
                checked(row['recording'])
            else:
                profile_path=Path(context['source']['root'])/'upstream/DeepTutor/deeptutor/config/competition-features.json'
                profile=json.loads(profile_path.read_text('utf-8'))
                competition.verify(kind,row,context,checked,profile)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append(kind + ': ' + str(exc))
    return {'passed': not errors, 'run_id': context['run_id'], 'version': context['version'], 'errors': errors}


def promote(directory, destination):
    directory = Path(directory).resolve(strict=True)
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Release destination already exists; never overwrite a release')
    result = check(directory)
    if not result['passed']:
        raise ValueError('RELEASE BLOCKED: ' + '; '.join(result['errors']))
    context = json.loads((directory / 'context.json').read_text('utf-8'))
    if destination == directory or directory in destination.parents or Path(context['source']['root']) in destination.parents:
        raise ValueError('Release output must be separate from evidence and source')
    # Copy under an unpublishable temporary name. Failed copies stay quarantined.
    staging = destination.with_name(destination.name + '.unreleased-' + uuid.uuid4().hex)
    staging.mkdir(parents=True, exist_ok=False)
    for item in context['artifacts']:
        original = checked(item)
        target = staging / original.name
        shutil.copy2(original, target)
        checked({**item, 'path': str(target)})
    second = check(directory)
    if not second['passed']:
        raise ValueError('RELEASE BLOCKED after copy: ' + '; '.join(second['errors']))
    save_new(staging / 'RELEASE-ACCEPTANCE.json', {'context': context, 'gate': second,
        'evidence': {name: json.loads((directory / (name + '.json')).read_text('utf-8'))
                     for name in REQUIRED_EVIDENCE}})
    # Windows rename is non-overwriting. Recheck for other supported hosts too.
    if destination.exists():
        raise ValueError('Destination was created during promotion')
    staging.rename(destination)
    return {'released': str(destination), **second}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    start = sub.add_parser('begin')
    start.add_argument('--source', required=True); start.add_argument('--artifact', action='append', required=True)
    start.add_argument('--run', required=True); start.add_argument('--version', required=True)
    status = sub.add_parser('check'); status.add_argument('--run', required=True)
    release = sub.add_parser('promote'); release.add_argument('--run', required=True); release.add_argument('--out', required=True)
    args = p.parse_args()
    try:
        if args.action == 'begin': result = begin(args.source, args.artifact, args.run, args.version)
        elif args.action == 'promote': result = promote(args.run, args.out)
        else: result = check(args.run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('passed', True) else 1
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print('RELEASE BLOCKED: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
