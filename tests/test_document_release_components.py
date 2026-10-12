"""Synthetic component/frozen-plan tests. No model downloads, build or deployment.

All supplied bytes and receipts are disposable fixture data. Product modules are
read-only; expensive baseline/OCR execution is substituted at their input boundary.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('document_component_test_subject', ROOT / 'installer/build_document_release.py')
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DocumentComponentFixtures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='component-fixture-', dir=ROOT / 'reports')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'workspace'
        self.home.mkdir()
        self.patches = []
        for target in (subject, subject.release, subject.release.h):
            self.change(target, 'ROOT', self.home)
        self.change(subject, 'COMPONENT_TARGETS', set())
        self.version = '2026.10.12-r9-synthetic'
        self.artifact = 'r9-synthetic'
        self.change(subject.release, 'VERSION', self.version)
        self.change(subject.release, 'ARTIFACT', self.home / 'installer' / self.artifact)
        self.change(subject.release, 'SPEC', self.home / 'reports' / (self.artifact + '-spec.json'))
        self.change(subject.release, 'BASELINE', self.put('public-baseline.dat', b'synthetic baseline; not an executable'))
        self.change(subject.release, 'BASELINE_SHA', digest(subject.release.BASELINE))
        self.change(subject.release, 'BASELINE_MANIFEST_SHA', '1' * 64)
        self.change(subject.release, 'WHEEL', self.put('downloads/timezone.whl', b'synthetic descriptor only'))
        self.change(subject.runtime, 'OCR_MANIFEST', self.put_json('reports/ocr.json', {'files': []}))
        self.change(subject.runtime, 'diagnostic_files', lambda: {})
        self.change(subject.runtime, 'check_rows', lambda *args: {})
        self.baseline = {}
        self.metadata = {'runtime/native-frontend.json': {'build_id': '20260101-000000'}, 'installer/junctions.json': []}
        self.change(subject.release, 'read_baseline', lambda *args, **kwargs: (deepcopy(self.baseline), deepcopy(self.metadata)))
        for name, blob in {
            'models/local-qwen/old.gguf': b'retired',
            'runtime/local-qwen/llama.exe': b'retired',
            'integration/local_qwen/config.py': b'retired',
            'scripts/qwen_runtime.py': b'retired script',
            'scripts/local_qwen_compat.py': b'retired compatibility shim',
            'integration/check_local_qwen_defaults.py': b'retired bundled-model diagnostic',
            'models/my-custom-llama/model.gguf': b'custom llama',
            'runtime/local-api/client.js': b'custom api',
            'models/qwen-user-model/model.gguf': b'custom same-brand model',
            'integration/local_qwen_defaults.py': b'public migration and manual provider logic',
        }.items():
            self.baseline[name] = {'path': name, 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}
        for name in ('services/config/provider_runtime.py', 'services/model_selection/llm.py'):
            source = self.put('upstream/DeepTutor/deeptutor/' + name, b'synthetic shared model-selection code')
            for prefix in (subject.release.PYTHON, subject.release.OVERLAY):
                target = prefix + 'deeptutor/' + name
                self.baseline[target] = {'path': target, 'bytes': source.stat().st_size, 'sha256': digest(source)}
        for name in ('sidecar.mjs', 'workspaces.mjs', 'workspace_http.mjs'):
            source = self.put('integration/harness/' + name, b'// synthetic Host source')
            for prefix in ('runtime/harness/', 'integration/harness/'):
                target = prefix + name
                self.baseline[target] = {'path': target, 'bytes': source.stat().st_size, 'sha256': digest(source)}
        self.put('installer/DeepSteamSetup.cs', b'synthetic installer source; never compiled')
        self.put('installer/DeepSteam.manifest', b'synthetic Windows manifest')
        self.native = self.put_json('reports/native.json', {'build_id': '20261012-123456'})
        self.acceptance = self.put_json('reports/accepted.json', {'passed': True, 'synthetic_fixture': True})
        self.uninstall = self.put_json('reports/uninstall.json', {'source_sha256': digest(self.home / 'installer/DeepSteamSetup.cs'),
            'tests': [{'passed': True, 'checks': 1}], 'total_checks': 1, 'synthetic_fixture': True})
        self.program = self.put_json('reports/program.json', {'files': [
            self.row('runtime/native-frontends/20261012-123456/server.js'),
            self.row(subject.release.OM + '.next/BUILD_ID', b'synthetic-next-id'),
            self.row(subject.release.OM + 'server.js')], 'user_data_copied': False, 'credentials_copied': False})
        for relative in ('reports/workspace-document-ocr-dependencies.json', 'installer/document-runtime-requirements.txt',
                         'scripts/check_document_runtime.py', 'installer/document_runtime.py', 'installer/document-fixtures/scanned-en.png'):
            self.put(relative, b'synthetic frozen document contract descriptor')

    def change(self, target, name, value):
        mutation = patch.object(target, name, value)
        mutation.start()
        self.addCleanup(mutation.stop)

    def put(self, relative, blob=b'synthetic public program'):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        return path

    def put_json(self, relative, value):
        return self.put(relative, json.dumps(value, ensure_ascii=False).encode('utf8'))

    def row(self, target, blob=b'synthetic public program'):
        # Source filename deliberately has no target-derived path, allowing unsafe
        # target tests without creating corresponding mutable/private directories.
        source = self.put('reviewed/' + hashlib.sha256(target.encode()).hexdigest() + '.asset', blob)
        return {'source': source.relative_to(self.home).as_posix(), 'target': target,
                'bytes': source.stat().st_size, 'sha256': digest(source)}

    def component(self, schema='deepsteam-harness-runtime-v1', extra=()):
        if schema == 'deepsteam-mineru-runtime-v1':
            rows = [self.row(name) for name in ('runtime/mineru/python.exe', 'runtime/mineru/Lib/site-packages/mineru/__init__.py',
                'models/mineru/runtime-models.json', 'licenses/mineru/LICENSE', 'scripts/mineru_document_worker.py', 'installer/mineru-runtime-lock.txt')]
            accepted = self.put_json('reports/mineru-acceptance.json', {'passed': True, 'worker_sha256': rows[-2]['sha256'], 'synthetic_fixture': True})
            value = {'schema': schema, 'tool_only': True, 'engine_version': '4.0.12', 'files': rows,
                     'redistribution_status': 'verified',
                     'acceptance': {'source': str(accepted), 'bytes': accepted.stat().st_size, 'sha256': digest(accepted)}}
        else:
            rows = [self.row(name) for name in ('runtime/harness/package.json', 'runtime/harness/package-lock.json',
                'runtime/harness/node_modules/@fixture/reader/index.js')]
            value = {'schema': schema, 'files': rows}
        value['files'] += list(extra)
        value['bytes'] = sum(row['bytes'] for row in value['files'])
        return value

    def load_component(self, value):
        path = self.put_json('reports/component.json', value)
        return subject.load_component_manifest(path)

    def args(self, components=()):
        return SimpleNamespace(program_manifest=[str(self.program)], component_manifest=list(map(str, components)),
            native_receipt=str(self.native), acceptance=str(self.acceptance), uninstaller_report=str(self.uninstall),
            junctions=None, extra_share_file=[], action='prepare', version=self.version, artifact=self.artifact)

    def freeze(self, component=None):
        paths = [] if component is None else [self.put_json('reports/component.json', component)]
        with contextlib.redirect_stdout(io.StringIO()):
            subject.prepare(self.args(paths))
        return json.loads(subject.release.SPEC.read_text('utf8'))

    def reload(self):
        subject.COMPONENT_TARGETS.clear()  # A new command starts with no dynamic permissions.
        args = SimpleNamespace(action='validate', version=self.version, artifact=self.artifact,
                               spec_sha256=digest(subject.release.SPEC))
        subject.configure(args)
        return subject.release.load_plan(args.spec_sha256)

    def test_harness_dependency_closure_is_selected_and_reloaded(self):
        component = self.component()
        plan = self.freeze(component)
        expected = {row['target'] for row in component['files']}
        self.assertTrue(expected <= {row['path'] for row in plan['files']})
        _, _, _, rows, sources = self.reload()
        self.assertTrue(expected <= rows.keys())
        self.assertTrue(expected <= sources.keys())
        for entry in component['files']:
            self.assertEqual(rows[entry['target']]['sha256'], entry['sha256'])

    def test_actual_mineru_manifest_acceptance_shape_can_freeze(self):
        component = self.component('deepsteam-mineru-runtime-v1')
        plan = self.freeze(component)
        expected = {row['target'] for row in component['files']}
        self.assertTrue(expected <= {row['path'] for row in plan['files']})
        self.assertTrue(expected <= self.reload()[3].keys())

    def test_complete_harness_component_replaces_only_its_dependency_tree(self):
        stale = 'runtime/harness/node_modules/removed-package/obsolete.js'
        blob = b'previous public dependency'
        self.baseline[stale] = {'path': stale, 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}
        plan = self.freeze(self.component())
        self.assertIn('runtime/harness/node_modules/', plan['replace_prefixes'])
        self.assertNotIn('runtime/harness/', plan['replace_prefixes'])
        rows = self.reload()[3]
        self.assertNotIn(stale, rows)
        self.assertIn('runtime/harness/sidecar.mjs', rows)
        self.assertIn('models/my-custom-llama/model.gguf', rows)

    def test_complete_mineru_component_drops_stale_tool_assets_not_custom_models(self):
        stale = ('runtime/mineru/old-library.dll', 'models/mineru/obsolete.onnx', 'licenses/mineru/old-license.txt')
        for name in stale:
            self.baseline[name] = {'path': name, 'bytes': 3, 'sha256': hashlib.sha256(b'old').hexdigest()}
        plan = self.freeze(self.component('deepsteam-mineru-runtime-v1'))
        self.assertTrue({'runtime/mineru/', 'models/mineru/', 'licenses/mineru/'} <= set(plan['replace_prefixes']))
        rows = self.reload()[3]
        for name in stale:
            self.assertNotIn(name, rows)
        self.assertIn('models/my-custom-llama/model.gguf', rows)
        self.assertIn('runtime/local-api/client.js', rows)

    def test_path_escape_targets_rejected_before_selection(self):
        for name in ('runtime/mineru/../secret', 'runtime/mineru//asset', '/runtime/mineru/asset',
                     'runtime\\mineru\\asset', 'runtime/mineru/file:stream', 'C:/outside'):
            with self.subTest(target=name), self.assertRaises((ValueError, RuntimeError)):
                self.load_component(self.component('deepsteam-mineru-runtime-v1', [self.row(name)]))

    def test_mutable_and_credential_targets_cannot_be_dynamic_exceptions(self):
        for name in ('runtime/harness/node_modules/.cache/state', 'runtime/harness/node_modules/pkg/.env',
                     'runtime/harness/node_modules/pkg/.ENV.PRODUCTION',
                     'runtime/harness/node_modules/pkg/credentials.json', 'runtime/harness/node_modules/pkg/AUTH.JSON',
                     'runtime/mineru/auth.json', 'models/mineru/token.json', 'runtime/mineru/profile/state'):
            schema = 'deepsteam-harness-runtime-v1' if name.startswith('runtime/harness/') else 'deepsteam-mineru-runtime-v1'
            with self.subTest(target=name), self.assertRaises(RuntimeError):
                self.load_component(self.component(schema, [self.row(name)]))
                subject.program_target(name)

    def test_component_sources_cannot_escape_workspace(self):
        outside = self.base / 'outside.asset'
        outside.write_bytes(b'only a synthetic external fixture')
        value = self.component()
        value['files'][0].update(source=str(outside), bytes=outside.stat().st_size, sha256=digest(outside))
        with self.assertRaises((ValueError, RuntimeError)):
            self.load_component(value)

    def test_component_source_reparse_ancestor_fails_closed(self):
        value = self.component()
        blocked = (self.home / value['files'][0]['source']).parent
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda path: path == blocked or original(path)):
            with self.assertRaisesRegex(RuntimeError, 'reparse'):
                self.load_component(value)

    def test_component_size_and_hash_mismatch_rejected(self):
        for field, replacement in (('bytes', 999), ('sha256', '0' * 64)):
            value = self.component()
            value['files'][0][field] = replacement
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.load_component(value)

    def test_wrong_mineru_version_or_non_tool_runtime_rejected(self):
        for field, replacement in (('engine_version', '4.0.11'), ('tool_only', False)):
            value = self.component('deepsteam-mineru-runtime-v1')
            value[field] = replacement
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.load_component(value)

    def test_mineru_requires_explicit_verified_redistribution(self):
        for status in (None, 'pending', 'unknown', 'Verified', True):
            value = self.component('deepsteam-mineru-runtime-v1')
            if status is None:
                value.pop('redistribution_status')
            else:
                value['redistribution_status'] = status
            before = set(subject.COMPONENT_TARGETS)
            with self.subTest(status=status), self.assertRaisesRegex(RuntimeError, 'redistribution'):
                self.load_component(value)
            self.assertEqual(subject.COMPONENT_TARGETS, before)

    def mineru_public_metadata(self):
        return {'schema_version': 1, 'engine': 'mineru', 'version': '4.0.12',
                'commit': 'b7f3dd0c5f6e6d66a298239ffd02b328b873918e',
                'python_version': '3.13.15', 'tool_only': True, 'provider': False,
                'small_backend': 'onnx', 'vlm_engine': 'official-local-llama-server',
                'model_root': '../../models/mineru', 'excluded_dependency': 'mineru-llama-cpp',
                'device': 'cpu', 'dependency_resolution_sha256': 'a' * 64}

    def test_exact_public_mineru_runtime_metadata_freezes_and_reloads(self):
        name = 'runtime/mineru/runtime.json'
        row = self.row(name, json.dumps(self.mineru_public_metadata()).encode('utf8'))
        self.freeze(self.component('deepsteam-mineru-runtime-v1', [row]))
        self.assertEqual(self.reload()[3][name]['sha256'], row['sha256'])

    def test_public_mineru_metadata_rejects_extra_credentials_and_wrong_values(self):
        changes = ({'api_key': 'synthetic-do-not-use'}, {'credentials': {}}, {'provider': True},
                   {'model_root': 'D:/outside'}, {'vlm_engine': 'unreviewed-wrapper'},
                   {'dependency_resolution_sha256': 'not-a-digest'})
        for change in changes:
            config = self.mineru_public_metadata()
            config.update(change)
            row = self.row('runtime/mineru/runtime.json', json.dumps(config).encode('utf8'))
            before = set(subject.COMPONENT_TARGETS)
            with self.subTest(change=change), self.assertRaisesRegex(RuntimeError, 'public metadata'):
                self.load_component(self.component('deepsteam-mineru-runtime-v1', [row]))
            self.assertEqual(subject.COMPONENT_TARGETS, before)

    def test_public_mineru_metadata_requires_complete_fixed_keys(self):
        config = self.mineru_public_metadata()
        config.pop('dependency_resolution_sha256')
        row = self.row('runtime/mineru/runtime.json', json.dumps(config).encode('utf8'))
        with self.assertRaisesRegex(RuntimeError, 'public metadata'):
            self.load_component(self.component('deepsteam-mineru-runtime-v1', [row]))

    def test_other_runtime_json_targets_remain_private(self):
        for name in ('runtime/mineru/subdirectory/runtime.json', 'runtime/mineru/RUNTIME.JSON',
                     'runtime/harness/node_modules/library/runtime.json',
                     'runtime/native-frontends/20261012-123456/.next-contest-native/server/runtime.json',
                     'runtime/openmaic-standalone/.next/static/runtime.json'):
            with self.subTest(target=name), self.assertRaisesRegex(RuntimeError, 'Private'):
                subject.program_target(name)

    def test_compiled_profile_sessions_routes_are_public_code_on_frozen_reload(self):
        prefixes = ('runtime/native-frontends/20261012-123456/.next-contest-native/server/',
                    'runtime/native-frontends/20261012-123456/.next-contest-native/static/',
                    'runtime/openmaic-standalone/.next/server/',
                    'runtime/openmaic-standalone/.next/static/')
        targets = [prefix + relative for prefix in prefixes
                   for relative in ('app/profile/page.js', 'app/api/sessions/route.js',
                                    'app/api/sessions/route.js.nft.json')]
        program = json.loads(self.program.read_text('utf8'))
        program['files'].extend(self.row(name, b'// synthetic public compiled route') for name in targets)
        self.put_json('reports/program.json', program)
        self.freeze()
        rows = self.reload()[3]
        for name in targets:
            self.assertIn(name, rows)

    def test_compiled_route_exception_is_exactly_scoped(self):
        for name in (
            'runtime/native-frontends/20261012-123456/public/profile/page.js',
            'runtime/native-frontends/20261012-123456/.next-contest-native/cache/state.json',
            'runtime/native-frontends/not-a-build/.next-contest-native/server/profile/page.js',
            'runtime/native-frontends/20261012-123456/.next-contest-native/server-extra/sessions/route.js',
            'runtime/openmaic-standalone/public/profile/page.js',
            'runtime/openmaic-standalone/.next/cache/sessions/state.json',
            'runtime/openmaic-standalone/.next/server-extra/profile/page.js',
        ):
            with self.subTest(target=name), self.assertRaisesRegex(RuntimeError, 'Private'):
                subject.program_target(name)

    def test_private_leaves_remain_rejected_inside_compiled_routes(self):
        prefixes = ('runtime/native-frontends/20261012-123456/.next-contest-native/server/',
                    'runtime/native-frontends/20261012-123456/.next-contest-native/static/',
                    'runtime/openmaic-standalone/.next/server/',
                    'runtime/openmaic-standalone/.next/static/')
        for prefix in prefixes:
            for relative in ('app/profile/auth.json', 'app/sessions/credentials.json',
                             'app/profile/TOKEN.JSON', 'app/profile/.ENV.PRODUCTION',
                             'app/sessions/store.sqlite3', 'app/profile/control-token',
                             '.cache/sessions/page.js', 'app/__pycache__/profile.pyc',
                             'app/harness-state/sessions/route.js'):
                with self.subTest(target=prefix + relative), self.assertRaisesRegex(RuntimeError, 'Private'):
                    subject.program_target(prefix + relative)

    def test_empty_and_unknown_components_rejected(self):
        for value in ({'schema': 'unknown', 'files': [self.row('runtime/mineru/x')]},
                      {'schema': 'deepsteam-harness-runtime-v1', 'files': []}):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.load_component(value)

    def test_duplicate_component_target_rejected(self):
        value = self.component()
        value['files'].append(deepcopy(value['files'][0]))
        with self.assertRaises(RuntimeError):
            self.load_component(value)

    def test_case_alias_component_target_rejected_on_windows(self):
        value = self.component()
        alias = deepcopy(value['files'][-1])
        alias['target'] = alias['target'].replace('index.js', 'INDEX.JS')
        value['files'].append(alias)
        with self.assertRaises(RuntimeError):
            self.load_component(value)

    def test_failed_manifest_does_not_grant_partial_target_permissions(self):
        value = self.component()
        value['files'].append(self.row('outside/forbidden.asset'))
        before = set(subject.COMPONENT_TARGETS)
        with self.assertRaises(RuntimeError):
            self.load_component(value)
        self.assertEqual(subject.COMPONENT_TARGETS, before)

    def test_remove_files_retires_script_on_frozen_reload(self):
        plan = self.freeze()
        self.assertTrue(set(subject.retired.RETIRED_FILES) <= set(plan['remove_files']))
        _, _, _, rows, _ = self.reload()
        for name in self.baseline:
            if subject.retired.retired_program_path(name):
                self.assertNotIn(name, rows)
        self.assertFalse(plan['builtin_chat_model'])

    def test_retirement_is_exact_not_custom_llama_or_api_brand_matching(self):
        for name in ('models/my-custom-llama/model.gguf', 'runtime/local-api/client.js',
                     'models/qwen-user-model/model.gguf', 'integration/local_qwen_defaults.py'):
            self.assertFalse(subject.retired.retired_program_path(name))
        self.freeze()
        rows = self.reload()[3]
        for name in self.baseline:
            if not subject.retired.retired_program_path(name):
                self.assertEqual(rows[name], self.baseline[name])

    def test_component_receipt_mutation_after_freeze_fails_reload(self):
        self.freeze(self.component())
        self.put_json('reports/component.json', {'schema': 'changed'})
        with self.assertRaises(RuntimeError):
            self.reload()

    def test_component_file_mutation_after_freeze_fails_reload(self):
        value = self.component()
        self.freeze(value)
        (self.home / value['files'][0]['source']).write_bytes(b'changed after reviewed freeze')
        with self.assertRaises(RuntimeError):
            self.reload()

    def test_frozen_component_target_cannot_use_a_different_reviewed_source(self):
        name = 'runtime/mineru/runtime.json'
        blob = json.dumps(self.mineru_public_metadata()).encode('utf8')
        component = self.component('deepsteam-mineru-runtime-v1', [self.row(name, blob)])
        original = self.freeze(component)
        for label, replacement in (('same-public-bytes', blob),
                                   ('extra-private-field', json.dumps({'api_key': 'synthetic-not-a-secret'}).encode('utf8'))):
            plan = deepcopy(original)
            source = self.put('reviewed/alternate-' + label + '.json', replacement)
            row = next(item for item in plan['files'] if item['path'] == name)
            row.update(source=source.relative_to(self.home).as_posix(), bytes=source.stat().st_size, sha256=digest(source))
            subject.release.SPEC.write_text(json.dumps(plan), encoding='utf8')
            with self.subTest(replacement=label), self.assertRaises(RuntimeError):
                self.reload()

    def test_frozen_plan_cannot_omit_a_verified_component_target(self):
        component = self.component()
        plan = self.freeze(component)
        name = component['files'][-1]['target']
        plan['files'] = [row for row in plan['files'] if row['path'] != name]
        subject.release.SPEC.write_text(json.dumps(plan), encoding='utf8')
        with self.assertRaises(RuntimeError):
            self.reload()

    def test_frozen_plan_duplicate_target_rejected_before_component_binding(self):
        component = self.component()
        plan = self.freeze(component)
        name = component['files'][0]['target']
        plan['files'].append(deepcopy(next(row for row in plan['files'] if row['path'] == name)))
        subject.release.SPEC.write_text(json.dumps(plan), encoding='utf8')
        with self.assertRaises(RuntimeError):
            self.reload()

    def test_frozen_components_cannot_claim_overlapping_targets(self):
        component = self.component()
        plan = self.freeze(component)
        second = self.put_json('reports/component-second.json', component)
        plan['component_manifests'].append(subject.release.descriptor(second))
        subject.release.SPEC.write_text(json.dumps(plan), encoding='utf8')
        with self.assertRaises(RuntimeError):
            self.reload()

    def test_mineru_acceptance_must_match_selected_worker(self):
        component = self.component('deepsteam-mineru-runtime-v1')
        path = Path(component['acceptance']['source'])
        path.write_text(json.dumps({'passed': True, 'worker_sha256': '0' * 64}), encoding='utf8')
        component['acceptance'].update(sha256=digest(path), bytes=path.stat().st_size)
        with self.assertRaises(RuntimeError):
            self.freeze(component)

    def test_mineru_acceptance_mutation_after_freeze_fails_reload(self):
        component = self.component('deepsteam-mineru-runtime-v1')
        self.freeze(component)
        Path(component['acceptance']['source']).write_text(json.dumps({'passed': False}), encoding='utf8')
        with self.assertRaises(RuntimeError):
            self.reload()

    def test_validated_document_plan_cannot_restore_retired_baseline_script(self):
        plan = self.freeze()
        plan['remove_files'] = []
        subject.release.SPEC.write_text(json.dumps(plan), encoding='utf8')
        with self.assertRaises(RuntimeError):
            self.reload()

    def test_frozen_plan_hash_mismatch_rejected(self):
        self.freeze()
        with self.assertRaises(RuntimeError):
            subject.release.load_plan('0' * 64)

    def test_prepare_install_uses_document_tool_without_builtin_chat_model(self):
        # Do not import this executable installer script: it initializes ROOT from
        # argv and imports platform helpers. Inspect its entry-point contract only.
        text = (ROOT / 'installer/prepare_install.py').read_text('utf8')
        self.assertIn("mineru_worker), '--health'", text)
        self.assertIn("'bundled_local_model': False", text)
        self.assertNotIn('qwen_runtime.py', text)
        self.assertNotIn('llama-server', text)
        self.assertNotIn('shutil.rmtree', text)


if __name__ == '__main__':
    unittest.main()
