"""Pure schema/negative gate tests; no model, service, installer or E access."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('technical_delivery_under_test', ROOT / 'reports/r4_technical_delivery.py')
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


class TechnicalGates(unittest.TestCase):
    @contextmanager
    def source_fixture(self, extras):
        publisher = delivery.library('publisher')
        with tempfile.TemporaryDirectory(prefix='technical-source-extra-gate-') as directory:
            root = Path(directory)
            content = {'producer.py': b'current producer', 'reports/r4_technical_delivery.py': b'current entry',
                       'tests/test_r4_technical_delivery_gates.py': b'gate test', 'reports/manual.md': b'public manual'}
            for name, blob in content.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(blob)
            row = {'source': 'producer.py', 'bytes': len(content['producer.py']),
                   'sha256': hashlib.sha256(content['producer.py']).hexdigest()}
            inventory = root / 'reports/production.json'
            inventory.write_text(json.dumps({'files': [row]}), encoding='utf-8')
            manual = {'path': str(root / 'reports/manual.md'), 'bytes': len(content['reports/manual.md']),
                      'sha256': hashlib.sha256(content['reports/manual.md']).hexdigest()}
            archive_path = root / 'source.zip'
            with zipfile.ZipFile(archive_path, 'x') as archive:
                for name, blob in content.items():
                    archive.writestr('DeepSteam/' + name, blob)
                for name, blob in extras.items():
                    archive.writestr(name, blob)
            with patch.object(delivery, 'ROOT', root), patch.object(delivery, 'PRODUCTION', 'reports/production.json'), \
                 patch.object(delivery, 'PRODUCTION_SHA', delivery.digest(inventory)), \
                 patch.object(delivery, 'read_json', side_effect=lambda path: json.loads(Path(path).read_text('utf-8'))), \
                 patch.object(delivery, 'library', return_value=publisher):
                yield {'path': str(archive_path)}, manual

    def scope(self):
        return {**delivery.QUALITY, 'kind': delivery.KIND, 'schema_version': 1,
                'classroom_origin': 'authored-software-fixture', 'model_generation_executed': False}

    def test_truthful_software_scope_allows_no_teaching_claim(self):
        delivery.scope_contract(self.scope())

    def test_explanations_cannot_be_faked_to_old_gate(self):
        value = self.scope()
        value['explanations_complete'] = True
        with self.assertRaisesRegex(RuntimeError, 'truthful'):
            delivery.scope_contract(value)

    def test_semantic_claim_is_rejected(self):
        for key in ('semantic_verified', 'teaching_accuracy_passed', 'manual_content_passed'):
            with self.subTest(key=key):
                value = self.scope()
                value[key] = True
                with self.assertRaisesRegex(RuntimeError, 'not accepted'):
                    delivery.scope_contract(value)

    def test_integer_zero_is_not_false_quality_evidence(self):
        value = self.scope()
        value['source_coverage_asserted'] = 0
        with self.assertRaises(RuntimeError):
            delivery.scope_contract(value)

    def test_not_model_generated_teaching_fixture(self):
        value = self.scope()
        value['model_generation_executed'] = True
        with self.assertRaisesRegex(RuntimeError, 'labelled'):
            delivery.scope_contract(value)

    def test_schema_has_no_fabricated_actual_pass(self):
        schema = delivery.describe_schema()
        self.assertIsNone(schema['slides_layout_passed'])
        self.assertIsNone(schema['full_narrated_video_passed'])
        self.assertEqual(schema['content_quality_acceptance'], 'not_performed')
        self.assertIs(schema['explanations_complete'], False)
        self.assertTrue(schema['schema_only_not_actual_evidence'])

    def connection(self):
        return {'kind': 'actual-r4-runtime-connection-evidence', 'passed': True,
                'build_ids': {'native': 'n', 'openmaic': 'o', 'next': 'nx'},
                'program_root': 'D:/software-test',
                'listeners': [{'port': p, 'loopback_only': True, 'owned_by_installation': True}
                              for p in (3791, 3792, 3793, 3794, 3795, 8011)],
                'health_checks': [{'port': p, 'status': 200} for p in (3791, 3792, 3793, 3794, 3795, 8011)],
                'local_model_alias_verified': True, 'cloud_services_called': False}

    def test_connection_requires_all_actual_owned_loopback_services(self):
        value = self.connection()
        with patch.object(delivery, 'library', return_value={'PORTS': {3791, 3792, 3793, 3794, 3795, 8011}}):
            self.assertEqual(delivery.validate_connection(value, value['build_ids']), 'D:/software-test')
            value['listeners'][0]['loopback_only'] = False
            with self.assertRaisesRegex(RuntimeError, 'local and owned'):
                delivery.validate_connection(value, value['build_ids'])

    def test_connection_wrong_build_is_rejected(self):
        value = self.connection()
        with self.assertRaisesRegex(RuntimeError, 'another frontend build'):
            delivery.validate_connection(value, {'native': 'other', 'openmaic': 'o', 'next': 'nx'})

    def test_connection_unhealthy_port_is_rejected(self):
        value = self.connection()
        value['health_checks'][2]['status'] = 502
        with patch.object(delivery, 'library', return_value={'PORTS': {3791, 3792, 3793, 3794, 3795, 8011}}):
            with self.assertRaisesRegex(RuntimeError, 'health'):
                delivery.validate_connection(value, value['build_ids'])

    def protection(self):
        return {'kind': 'actual-source-review-export-protection', 'passed': True,
                'classroom': {'path': '/fixture', 'sha256': 'a' * 64, 'bytes': 10}, 'classroom_id': 'cid',
                'request': {'method': 'POST', 'endpoint': '/api/education/narrated-export', 'course_id': 'cid'},
                'response': {'status': 409, 'body': {'success': False, 'errorCode': 'INVALID_REQUEST',
                                                   'reason': 'source_review_required'}},
                'cloud_services_called': False}

    def test_protection_requires_real_needs_review_and_specific_409(self):
        value = self.protection()
        classroom = {'stage': {'id': 'cid', 'sourceFidelity': {'status': 'needs_review'}}, 'scenes': [{'id': 's'}]}
        with patch.object(delivery, 'public_artifact', return_value=(Path('/fixture'), value['classroom'])), \
             patch.object(delivery, 'read_json', return_value=classroom):
            delivery.validate_protection(value)
            value['response']['status'] = 200
            with self.assertRaisesRegex(RuntimeError, '409'):
                delivery.validate_protection(value)

    def test_protection_unknown_draft_cannot_stand_for_review_gate(self):
        value = self.protection()
        classroom = {'stage': {'id': 'cid'}, 'scenes': [{'id': 's'}]}
        with patch.object(delivery, 'public_artifact', return_value=(Path('/fixture'), value['classroom'])), \
             patch.object(delivery, 'read_json', return_value=classroom):
            with self.assertRaisesRegex(RuntimeError, 'real retained needs_review'):
                delivery.validate_protection(value)

    def test_visual_readability_must_use_actual_observations(self):
        keys = ('text_readable', 'formula_complete_readable', 'original_image_aspect_ratio_preserved',
                'line_endpoints_attached_and_arrowheads_correct',
                'quiz_all_stem_options_answer_analysis_visible_or_scrolled', 'ending_visible')
        report = {'technical_checks': {key: True for key in keys}, 'content_quality_acceptance': 'not_performed'}
        delivery.validate_readability(report)
        report['technical_checks']['formula_complete_readable'] = None
        with self.assertRaisesRegex(RuntimeError, 'formula_complete_readable'):
            delivery.validate_readability(report)

    def test_incomplete_plan_is_readonly_and_not_ready(self):
        args = delivery.parser().parse_args(['plan'])
        plan, rows = delivery.publication_plan(args)
        self.assertIs(plan['ready_to_copy'], False)
        self.assertIs(plan['written_to_e'], False)
        self.assertIs(plan['source_coverage_asserted'], False)
        self.assertEqual(rows, [])

    def test_publish_cannot_skip_actual_receipts(self):
        args = delivery.parser().parse_args(['publish'])
        with self.assertRaisesRegex(RuntimeError, 'every actual software gate'):
            delivery.publication_plan(args)

    def test_clean_source_must_include_current_helper_and_production_bytes(self):
        with tempfile.TemporaryDirectory(prefix='technical-delivery-gate-') as directory:
            root = Path(directory)
            content = {'producer.py': b'current producer', 'reports/r4_technical_delivery.py': b'current entry',
                       'tests/test_r4_technical_delivery_gates.py': b'gate test', 'reports/manual.md': b'public manual'}
            for name, blob in content.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(blob)
            row = {'source': 'producer.py', 'bytes': len(content['producer.py']),
                   'sha256': hashlib.sha256(content['producer.py']).hexdigest()}
            inventory = root / 'reports/production.json'
            inventory.write_text(json.dumps({'files': [row]}), encoding='utf-8')
            manual = {'path': str(root / 'reports/manual.md'), 'bytes': len(content['reports/manual.md']),
                      'sha256': hashlib.sha256(content['reports/manual.md']).hexdigest()}
            current, stale = root / 'current.zip', root / 'stale.zip'
            for path, stale_source in ((current, False), (stale, True)):
                with zipfile.ZipFile(path, 'x') as archive:
                    for name, blob in content.items():
                        archive.writestr('DeepSteam/' + name,
                                         b'earlier producer' if stale_source and name == 'producer.py' else blob)
            with patch.object(delivery, 'ROOT', root), patch.object(delivery, 'PRODUCTION', 'reports/production.json'), \
                 patch.object(delivery, 'PRODUCTION_SHA', delivery.digest(inventory)), \
                 patch.object(delivery, 'read_json', side_effect=lambda path: json.loads(Path(path).read_text('utf-8'))):
                delivery.validate_source_zip({'path': str(current)}, manual)
                with self.assertRaisesRegex(RuntimeError, 'earlier/different'):
                    delivery.validate_source_zip({'path': str(stale)}, manual)

    def test_extra_credentials_are_rejected_even_when_required_sources_match(self):
        with self.source_fixture({'DeepSteam/private/credentials.json': b'{"access_token":"synthetic-test-token"}'}) as args:
            with self.assertRaisesRegex(RuntimeError, 'private state'):
                delivery.validate_source_zip(*args)

    def test_extra_credentials_basename_is_case_insensitive(self):
        with self.source_fixture({'DeepSteam/reports/CREDENTIALS.JSON': b'{"access_token":"synthetic-test-token"}'}) as args:
            with self.assertRaisesRegex(RuntimeError, 'machine credentials'):
                delivery.validate_source_zip(*args)

    def test_cancelled_experiment_extra_is_case_insensitive(self):
        with self.source_fixture({'DeepSteam/reports/STOPPED-LOCAL-QUALITY-EXPERIMENT/main.ts': b'cancelled'}) as args:
            with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
                delivery.validate_source_zip(*args)

    def test_extra_text_is_scanned_for_credential_patterns(self):
        # Synthetic key is assembled at test runtime so the public test source
        # itself does not contain a secret-looking contiguous token.
        fake_key = b'AKIA' + b'0' * 16
        with self.source_fixture({'DeepSteam/reports/extra.md': b'key=' + fake_key}) as args:
            with self.assertRaisesRegex(RuntimeError, 'credential pattern'):
                delivery.validate_source_zip(*args)

    def test_extra_json_nonempty_token_is_rejected(self):
        with self.source_fixture({'DeepSteam/reports/config.json': b'{"access_token":"synthetic-test-token"}'}) as args:
            with self.assertRaisesRegex(RuntimeError, 'credential field'):
                delivery.validate_source_zip(*args)

    def test_legitimate_auth_data_source_and_empty_examples_remain_allowed(self):
        examples = {'DeepSteam/upstream/OpenMAIC/app/api/auth/route.ts': b'export const route = true;',
                    'DeepSteam/upstream/DeepTutor/src/data/module.py': b'VALUE = 1',
                    'DeepSteam/upstream/OpenMAIC/.env.example': b'API_KEY=\n',
                    'DeepSteam/reports/empty-example.json': b'{"api_key":"","access_token":null}'}
        with self.source_fixture(examples) as args:
            delivery.validate_source_zip(*args)

    def test_export_snapshot_retains_source_timeline_id_with_explicit_origin(self):
        classroom = {'stage': {'id': 'source'}}
        narrated = {'courseId': 'clone', 'originalCourseId': 'source', 'provenance': {'kind': 'export-snapshot'}}
        self.assertTrue(delivery.snapshot_course_identity({'stage': {'id': 'source'}}, narrated, classroom))
        self.assertTrue(delivery.snapshot_course_identity({'stage': {'id': 'clone'}}, narrated, classroom))

    def test_export_snapshot_wrong_missing_or_empty_origin_is_rejected(self):
        classroom, manifest = {'stage': {'id': 'source'}}, {'stage': {'id': 'source'}}
        invalid = [
            {'courseId': 'clone', 'originalCourseId': 'source'},
            {'courseId': 'clone', 'originalCourseId': 'source', 'provenance': {}},
            {'courseId': 'clone', 'originalCourseId': 'source', 'provenance': {'kind': 'unrelated'}},
            {'courseId': 'clone', 'originalCourseId': 'wrong', 'provenance': {'kind': 'export-snapshot'}},
            {'courseId': 'clone', 'originalCourseId': '', 'provenance': {'kind': 'export-snapshot'}},
            {'courseId': '', 'originalCourseId': 'source', 'provenance': {'kind': 'export-snapshot'}},
            {'courseId': 'clone', 'originalCourseId': 'source', 'provenance': 'export-snapshot'},
        ]
        for narrated in invalid:
            with self.subTest(narrated=narrated):
                self.assertFalse(delivery.snapshot_course_identity(manifest, narrated, classroom))

    def test_export_snapshot_unrelated_source_or_timeline_is_rejected(self):
        narrated = {'courseId': 'clone', 'originalCourseId': 'source', 'provenance': {'kind': 'export-snapshot'}}
        self.assertFalse(delivery.snapshot_course_identity({'stage': {'id': 'wrong'}}, narrated, {'stage': {'id': 'source'}}))
        self.assertFalse(delivery.snapshot_course_identity({'stage': {'id': 'source'}}, narrated, {'stage': {'id': 'wrong'}}))

    def test_direct_export_still_requires_same_source_and_timeline(self):
        classroom, manifest = {'stage': {'id': 'source'}}, {'stage': {'id': 'source'}}
        self.assertTrue(delivery.snapshot_course_identity(manifest, {'courseId': 'source'}, classroom))
        self.assertFalse(delivery.snapshot_course_identity(manifest, {'courseId': 'other'}, classroom))
        self.assertFalse(delivery.snapshot_course_identity(manifest, {'courseId': 'source', 'originalCourseId': 'wrong'}, classroom))

    def test_frozen_media_only_identity_predicate_is_adapted_in_memory(self):
        media = delivery.library('media')
        self.assertIs(media['_technical_snapshot_course_identity'], delivery.snapshot_course_identity)
        names = media['verify_video'].__code__.co_names
        self.assertIn('_technical_snapshot_course_identity', names)
        self.assertIn('check_pairs', names)
        self.assertIn('finite_positive', names)
        self.assertEqual(delivery.digest(ROOT / delivery.LIBRARIES['media'][0]), delivery.LIBRARIES['media'][1])


if __name__ == '__main__':
    unittest.main()
