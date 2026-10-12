"""In-memory publication gates; never publishes, starts services or calls models."""
from copy import deepcopy
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
ns = runpy.run_path(str(ROOT / 'reports/publish_r4_delivery_to_e.py'), run_name='r4_publication_gate_tests')


def cold_fixture():
    build = {'manifest_sha256': 'a' * 64, 'files_sha_verified': 100}
    record = {'sha256': 'b' * 64}
    installed = {'action': 'install', 'version': ns['VERSION'], 'actual_exe_installation_passed': True,
        'candidate_report_sha256': record['sha256'], 'installed_manifest_sha256': build['manifest_sha256'],
        'files_verified_by_actual_installer': 100, 'install_root': r'D:\DSr4c-202610111200',
        'installed_runtime_receipt_sha256': 'c' * 64, 'own_empty_workspace_initialized': True,
        'default_local_model_selected': True, 'user_data_imported': False, 'credentials_imported': False,
        'external_storage_config_present': False, 'source_machine_credentials_copied': False,
        # The real installation harness intentionally does not certify a full
        # classroom; explicit actual action and independent video proofs do.
        'cold_start_validated': False}
    actions = {}
    for action in ns['COLD_ACTIONS']:
        actions[action] = {'kind': 'actual-r4-cold-installation-action', 'version': ns['VERSION'],
            'action': action, 'action_passed': True, 'actual_install_root': installed['install_root'],
            'user_data_imported': False, 'credentials_imported': False, 'cloud_services_called': False,
            'written_to_e': False, 'installation': {'factory_manifest_sha256': build['manifest_sha256'],
                'files_verified_by_actual_installer': 100, 'installed_runtime_receipt_sha256': 'c' * 64},
            'preflight': {'listeners': [{'port': port, 'loopback_only': True, 'owned_by_cold_installation': True}
                for port in ns['PORTS']], 'portal_default_is_local': True, 'native_default_model_is_exact_local': True,
                'model_alias_verified': True, 'actual_storage_paths_owned_by_cold_installation': True,
                'stored_cloud_keys_present': False}}
    actions['native-chat']['native_chat'] = {'same_session_two_turns_passed': True}
    actions['vision']['vision'] = {'explicit_left_red_20_right_blue_80_passed': True,
                                  'content': 'Left: 20 red balls. Right: 80 blue balls.'}
    actions['tts']['tts'] = {'actual_wav_passed': True, 'provider_id': 'windows-system-tts', 'actual_duration_seconds': 1.2}
    actions['source-read']['source_read'] = {'actual_local_pdf_text_and_image_passed': True,
        'mathematical_punctuation_preserved': True, 'image_dimensions_and_source_mapping_preserved': True,
        'cloud_ocr_used': False}
    return build, record, installed, actions


class PublicationGates(unittest.TestCase):
    def test_complete_actual_cold_actions_bind_installation(self):
        self.assertEqual(ns['validate_cold'](*cold_fixture()), r'D:\DSr4c-202610111200')

    def test_plan_is_not_actual_install(self):
        args = cold_fixture()
        args[2]['action'] = 'plan'
        with self.assertRaises(RuntimeError):
            ns['validate_cold'](*args)

    def test_another_candidate_or_root_is_rejected(self):
        for mutation in ('manifest', 'root'):
            args = cold_fixture()
            if mutation == 'manifest':
                args[3]['vision']['installation']['factory_manifest_sha256'] = 'd' * 64
            else:
                args[3]['vision']['actual_install_root'] = r'D:\DSr4c-202610111201'
            with self.assertRaises(RuntimeError):
                ns['validate_cold'](*args)

    def test_missing_action_or_cloud_key_is_rejected(self):
        args = cold_fixture()
        del args[3]['source-read']
        with self.assertRaises(RuntimeError):
            ns['validate_cold'](*args)

    def test_old_false_positive_receipt_cannot_certify_200_800(self):
        args = cold_fixture()
        args[3]['vision']['vision']['content'] = 'Left: 200 red balls. Right: 800 blue balls.'
        with self.assertRaisesRegex(RuntimeError, 'incorrect mapping/count'):
            ns['validate_cold'](*args)
        args = cold_fixture()
        args[3]['tts']['preflight']['stored_cloud_keys_present'] = True
        with self.assertRaises(RuntimeError):
            ns['validate_cold'](*args)

    def test_video_without_original_authored_binding_is_rejected(self):
        feature = {'slides_layout_passed': True, 'explanations_complete': True,
            'full_narrated_video_passed': True, 'video_has_audio': True,
            'narration_coverage': {'written': 2, 'total': 2}}
        video = {'kind': 'actual-full-narrated-video-evidence', 'technicalPass': True, 'failedChecks': 0,
            'authoredSourceBinding': 'not_checked_without_actual_classroom'}
        with self.assertRaisesRegex(RuntimeError, 'original classroom'):
            ns['validate_teaching'](feature, video, {}, {}, {}, 'e' * 64)

    def test_model_status_and_real_independent_validator_are_both_required(self):
        feature = {'slides_layout_passed': True, 'explanations_complete': True,
            'full_narrated_video_passed': True, 'video_has_audio': True,
            'narration_coverage': {'written': 2, 'total': 2}, 'video_duration_seconds': 5.0}
        records = {'mp4': {'path': 'D:/public/video.mp4', 'sha256': 'a' * 64, 'bytes': 123},
                   'classroom': {'path': 'D:/public/classroom.json', 'sha256': 'b' * 64, 'bytes': 456}}
        video = {'kind': 'actual-full-narrated-video-evidence', 'technicalPass': True,
            'failedChecks': 0, 'authoredSourceBinding': ns['REVIEW_BINDING'],
            'actualVideo': {'durationSeconds': 5.0, 'audioCodec': 'aac'},
            'inputs': [{**records['mp4'], 'purpose': 'actual_rendered_mp4'},
                       {**records['classroom'], 'purpose': 'actual_source_classroom'}]}
        classroom = {'stage': {'id': 'classroom-test', 'sourceMaterial': {'complete': True, 'text': 'Actual test source'},
                              'sourceFidelity': {'status': 'needs_review'}}, 'scenes': [{'id': 'scene-1'}]}
        for status in ('needs_review', None):
            classroom['stage']['sourceFidelity']['status'] = status
            with self.assertRaisesRegex(RuntimeError, 'needs_review/legacy'):
                ns['validate_teaching'](feature, video, classroom, {}, records, 'e' * 64)
        classroom['stage']['sourceFidelity']['status'] = 'verified'
        with self.assertRaisesRegex(RuntimeError, 'actual-evidence validator'):
            ns['validate_teaching'](feature, video, classroom, {}, records, 'e' * 64)

    def test_report_binding_requires_size_and_path_as_well_as_sha(self):
        record = {'path': 'D:/public/foo.json', 'bytes': 123, 'sha256': 'a' * 64}
        self.assertTrue(ns['matches'](deepcopy(record), record))
        wrong = deepcopy(record)
        wrong['bytes'] = 124
        self.assertFalse(ns['matches'](wrong, record))

    def test_no_json_credential_can_enter_public_handoff(self):
        with self.assertRaises(RuntimeError):
            ns['reject_secrets']({'evidence': {'refresh_token': 'do-not-publish'}})


if __name__ == '__main__':
    unittest.main()
