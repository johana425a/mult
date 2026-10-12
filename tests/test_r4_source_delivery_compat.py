"""Pure source compatibility tests; no models, services, installer or E writes."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('r4_source_compatibility_under_test', ROOT / 'reports/r4_source_delivery_compat.py')
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


def contract(node=None):
    return {'openapi': '3.1.0', 'paths': {}, 'components': {'schemas': {'Request': {'properties': {
        'api_key': node if node is not None else {'title': 'Api Key', 'type': 'string', 'default': ''},
        'password': {'title': 'Password', 'type': 'string'},
    }}}}}


class SourceCompatibility(unittest.TestCase):
    def scan(self, name, contents):
        data = contents.encode('utf-8') if isinstance(contents, str) else contents
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name, data)
        buffer.seek(0)
        with zipfile.ZipFile(buffer) as archive:
            compat.scan_source_entry(archive, archive.getinfo(name))

    def test_exact_openapi_definition_is_allowed(self):
        compat.source_json_credentials(contract(), compat.OPENAPI)

    def test_actual_openapi_source_contract_is_allowed(self):
        source = ROOT / 'upstream/DeepTutor/web/contracts/schema/openapi.json'
        compat.source_json_credentials(json.loads(source.read_text('utf-8-sig')), compat.OPENAPI)

    def test_schema_nonempty_credential_default_remains_rejected(self):
        node = {'type': 'string', 'default': 'synthetic-secret'}
        with self.assertRaisesRegex(RuntimeError, 'nonempty credential'):
            compat.source_json_credentials(contract(node), compat.OPENAPI)

    def test_schema_nonempty_example_or_enum_is_rejected(self):
        for annotation in ({'example': 'synthetic-secret'}, {'examples': ['synthetic-secret']}, {'enum': ['synthetic-secret']}):
            with self.subTest(annotation_key=next(iter(annotation))):
                with self.assertRaisesRegex(RuntimeError, 'nonempty credential'):
                    compat.source_json_credentials(contract({'type': 'string', **annotation}), compat.OPENAPI)

    def test_schema_combiners_are_checked_recursively(self):
        node = {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'title': 'Api Key'}
        compat.source_json_credentials(contract(node), compat.OPENAPI)
        node['anyOf'][0]['default'] = 'synthetic-secret'
        with self.assertRaisesRegex(RuntimeError, 'nonempty credential'):
            compat.source_json_credentials(contract(node), compat.OPENAPI)

    def test_probe_api_key_array_schema_is_definition_not_key_data(self):
        node = {'anyOf': [{'type': 'string'}, {'type': 'array', 'items': {'type': 'string'}}, {'type': 'null'}]}
        compat.source_json_credentials(contract(node), compat.OPENAPI)
        node['anyOf'][1]['default'] = ['synthetic-secret']
        with self.assertRaisesRegex(RuntimeError, 'nonempty credential'):
            compat.source_json_credentials(contract(node), compat.OPENAPI)

    def test_real_string_cannot_pose_as_api_schema_node(self):
        with self.assertRaisesRegex(RuntimeError, 'nonempty credential'):
            compat.source_json_credentials(contract('synthetic-secret'), compat.OPENAPI)

    def test_schema_exception_never_applies_to_other_path(self):
        with self.assertRaisesRegex(RuntimeError, 'nonempty credential'):
            compat.source_json_credentials(contract(), 'DeepSteam/reports/openapi.json')

    def test_openapi_still_rejects_credential_data_outside_exact_property_position(self):
        doc = contract()
        doc['sample_config'] = {'api_key': 'synthetic-secret'}
        with self.assertRaisesRegex(RuntimeError, 'nonempty credential'):
            compat.source_json_credentials(doc, compat.OPENAPI)

    def test_actual_six_flat_ui_locale_labels_are_allowed(self):
        for language in compat.LOCALE_LABEL_SHA:
            entry = 'DeepSteam/upstream/DeepTutor/web/locales/' + language + '/app.json'
            source = ROOT / 'upstream/DeepTutor/web/locales' / language / 'app.json'
            with self.subTest(language=language):
                compat.source_json_credentials(json.loads(source.read_text('utf-8-sig')), entry)

    def test_locale_label_exception_has_exact_public_label_hash(self):
        entry = 'DeepSteam/upstream/DeepTutor/web/locales/en/app.json'
        with self.assertRaisesRegex(RuntimeError, 'nonempty credential'):
            compat.source_json_credentials({'Password': 'synthetic-secret'}, entry)

    def test_locale_other_credential_field_remains_rejected(self):
        source = ROOT / 'upstream/DeepTutor/web/locales/en/app.json'
        doc = json.loads(source.read_text('utf-8-sig'))
        doc['access_token'] = 'synthetic-secret'
        with self.assertRaisesRegex(RuntimeError, 'nonempty credential'):
            compat.source_json_credentials(doc, 'DeepSteam/upstream/DeepTutor/web/locales/en/app.json')

    def test_locale_exception_does_not_allow_other_path_or_nested_state(self):
        doc = {'Password': 'Password'}
        for entry in ('DeepSteam/reports/app.json', 'DeepSteam/upstream/DeepTutor/web/locales/unknown/app.json'):
            with self.subTest(entry=entry):
                with self.assertRaisesRegex(RuntimeError, 'nonempty credential'):
                    compat.source_json_credentials(doc, entry)
        doc['nested'] = {'api_key': 'synthetic-secret'}
        with self.assertRaisesRegex(RuntimeError, 'nonempty credential'):
            compat.source_json_credentials(doc, 'DeepSteam/upstream/DeepTutor/web/locales/en/app.json')

    def test_jsonc_tokenizer_preserves_urls_quoted_comments_and_escaped_strings(self):
        text = '{ // comment\n "url": "https://example.test/a/*b*/", "value": "quoted \\\" text", /* comment */ "array": [1,2,], }'
        parsed = compat.parse_jsonc(text)
        self.assertEqual(parsed['url'], 'https://example.test/a/*b*/')
        self.assertEqual(parsed['value'], 'quoted " text')
        self.assertEqual(parsed['array'], [1, 2])

    def test_bad_jsonc_is_rejected_without_evaluation(self):
        bad = ('{/* unterminated', '{"value":"unterminated}', '{bareKey:1}', '{"value":callFunction()}', '[1,,]', '{"value":undefined}')
        for text in bad:
            with self.subTest(syntax_kind=text[:12]):
                with self.assertRaises((RuntimeError, json.JSONDecodeError)):
                    compat.parse_jsonc(text)

    def test_all_five_actual_typescript_jsonc_sources_parse(self):
        for entry in compat.JSONC_PATHS:
            source = ROOT / entry.removeprefix('DeepSteam/')
            with self.subTest(entry=entry):
                value = compat.parse_jsonc(source.read_text('utf-8-sig'))
                self.assertIsInstance(value, dict)
                compat.source_json_credentials(value, entry)

    def test_jsonc_compatibility_is_exact_path_only(self):
        text = '{ /* comment */ "value": 1, }'
        self.scan(next(iter(compat.JSONC_PATHS)), text)
        with self.assertRaises(json.JSONDecodeError):
            self.scan('DeepSteam/reports/tsconfig.json', text)

    def test_jsonc_nonempty_credentials_remain_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'nonempty credential'):
            self.scan(next(iter(compat.JSONC_PATHS)), '{ /* comment */ "api_key":"synthetic-secret", }')

    def test_secret_pattern_inside_jsonc_comment_is_still_scanned(self):
        fake = b'AKIA' + b'0' * 16
        with self.assertRaisesRegex(RuntimeError, 'credential pattern'):
            self.scan(next(iter(compat.JSONC_PATHS)), b'{ /* ' + fake + b' */ "compilerOptions": {}, }')

    def test_ci_fixture_is_excluded_even_if_api_key_is_empty(self):
        with self.assertRaisesRegex(RuntimeError, 'CI credential fixture'):
            self.scan(compat.CI_EXCLUDED, '{"api_key":""}')

    def test_original_machine_state_policy_is_unchanged(self):
        original = compat.original_namespace()
        self.assertEqual(compat.digest(compat.ORIGINAL), compat.ORIGINAL_SHA)
        self.assertIs(original['scan_source_entry'], compat.scan_source_entry)
        self.assertEqual(Path(original['source_entry_policy'].__code__.co_filename), compat.ORIGINAL)
        for name in ('DeepSteam/private/credentials.json', 'DeepSteam/reports/STOPPED-LOCAL-QUALITY-EXPERIMENT/main.ts'):
            with self.subTest(name=name):
                with self.assertRaises(RuntimeError):
                    original['source_entry_policy'](zipfile.ZipInfo(name))

    def test_compat_adapter_and_test_bytes_must_be_in_source_zip(self):
        with tempfile.TemporaryDirectory(prefix='source-compat-binding-') as directory:
            current, stale = Path(directory) / 'current.zip', Path(directory) / 'stale.zip'
            for target, stale_bytes in ((current, False), (stale, True)):
                with zipfile.ZipFile(target, 'x') as archive:
                    for source in (Path(compat.__file__), compat.OWN_TEST):
                        name = 'DeepSteam/' + source.relative_to(ROOT).as_posix()
                        archive.writestr(name, b'stale' if stale_bytes else source.read_bytes())
            compat.verify_adapter_sources({'path': str(current)})
            with self.assertRaisesRegex(RuntimeError, 'bytes differ'):
                compat.verify_adapter_sources({'path': str(stale)})

    def test_readonly_missing_plan_retains_original_gates_and_truthful_adapter_metadata(self):
        args = compat.parser().parse_args(['plan'])
        plan, files = compat.original_namespace()['publication_plan'](args)
        self.assertIs(plan['ready_to_copy'], False)
        self.assertIs(plan['written_to_e'], False)
        self.assertIs(plan['source_coverage_asserted'], False)
        self.assertEqual(plan['content_quality_acceptance'], 'not_performed')
        self.assertEqual(files, [])
        metadata = plan['source_format_compatibility']
        self.assertEqual(metadata['original_technical_validator']['sha256'], compat.ORIGINAL_SHA)
        self.assertEqual(metadata['adapter']['sha256'], compat.digest(Path(compat.__file__)))
        self.assertIs(metadata['candidate_or_cold_install_rebuilt'], False)


if __name__ == '__main__':
    unittest.main()
