"""Evidence-gate regression tests, never real classroom/model/video acceptance.

All constructed media/review files live in a deleted TemporaryDirectory. The
tiny synthetic MP4 bytes are intentionally not playable: these tests exercise
receipt binding and rejection, not the actual decoder or the model quality.
No fixture success is written into the workspace's acceptance reports.
"""
from __future__ import annotations

from contextlib import redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('actual_gate', ROOT / 'reports/validate_r4_actual_feature_evidence.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def blob_sha(data):
    return hashlib.sha256(data).hexdigest()


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 16, 9, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + b'\0' * 48) * 9)) + chunk(b'IEND', b''))


class SyntheticEvidence:
    """Independent validator schema fixture, explicitly not live acceptance."""
    def __init__(self, folder):
        self.folder = Path(folder)
        self.paths = {}
        self.cid = 'unit-fixture-class'
        self.source = 'UNIT TEST ORIGINAL SOFTWARE SOURCE. Red probability is 0.2 with equal chance.'
        self.classroom = {'stage': {'id': self.cid, 'sourceFidelity': {'status': 'verified'},
            'sourceMaterial': {'complete': True, 'text': self.source}}, 'scenes': [
            {'id': 'slide-original', 'order': 0, 'type': 'slide', 'content': {'canvas': {'elements': [
                {'id': 'el1', 'type': 'text', 'content': 'Equal chance is a prerequisite for 0.2.'}]}},
             'actions': [{'id': 'speech-slide', 'type': 'speech', 'text': 'Equal chance is a prerequisite for 0.2.'}]},
            {'id': 'interactive-original', 'order': 1, 'type': 'interactive',
             'content': {'html': '<p>Fixed source conditions, expectation is n times p.</p>'},
             'actions': [{'id': 'speech-interactive', 'type': 'speech', 'text': 'Fixed source conditions, expectation is n times p.'}]},
            {'id': 'quiz-original', 'order': 2, 'type': 'quiz', 'content': {'type': 'quiz', 'questions': [
                {'id': 'q1', 'question': 'Expected count?', 'answer': ['B'],
                 'options': [{'value': 'A', 'label': '1'}, {'value': 'B', 'label': '2'}],
                 'analysis': 'Expected count is ten times 0.2, which equals two.'}]},
             'actions': [{'id': 'speech-quiz', 'type': 'speech', 'text': 'Read the complete question before answering.'}]}]}
        self.write('classroom', self.classroom)
        self.write('mp4', b'UNIT TEST NOT PLAYABLE MEDIA. Never actual acceptance.')
        self.write('measurements', {'notice': 'UNIT TEST ONLY', 'geometry': [0, 0, 24]})
        qidentity = blob_sha(b'quiz-original\n0\nq1')[:24]
        ids = ['slide-original', 'interactive-original', 'quiz-original',
               'export-' + qidentity + '-question', 'export-' + qidentity + '-analysis']
        self.export = []
        for index, sid in enumerate(ids):
            action = ['speech-slide', 'speech-interactive', 'speech-quiz', 'question-voice', 'analysis-voice'][index]
            text = self.classroom['scenes'][index]['actions'][0]['text'] if index < 3 else 'Unit fixture derived narration.'
            self.export.append({'id': sid, 'index': index, 'type': 'slide', 'startMs': index * 1000,
                'durationMs': 1000, 'narration': [{'actionId': action, 'text': text, 'durationMs': 1000,
                    'audio': {'source': 'stored', 'present': True, 'durationMs': 1000}}], 'visuals': []})
        self.export[3]['visuals'] = [{'kind': 'quiz-question-list', 'scrollDistancePx': 12}]
        self.export[4]['visuals'] = [{'kind': 'quiz-question-list', 'scrollDistancePx': 0}]
        self.manifest = {'schema': 'openmaic.videoTimeline', 'version': 4, 'stage': {'id': self.cid},
                         'scenes': self.export, 'totalDurationMs': 5000}
        self.narrated = {'version': 1, 'courseId': self.cid, 'originalCourseId': self.cid,
                         'coverage': {'speechCount': 5, 'voicedSpeechCount': 5, 'sceneCount': 5, 'voicedSceneCount': 5}}
        self.write_zip()
        self.checks = []
        for code in ('source_expanded_scene_order_exact', 'coverage_exact_speech_set', 'mp4_audio_video_streams',
                     'mp4_full_timeline_duration', 'mp4_full_pcm_nonsilent',
                     'decoded_totals_match_verified_narration', 'ending_last_speech_not_truncated'):
            self.checks.append({'code': code, 'passed': True, 'detail': {'notice': 'UNIT TEST ONLY'}})
        for scene in self.classroom['scenes']:
            self.checks.append({'code': 'source_speech_retained', 'passed': True,
                'detail': {'sceneId': scene['id'], 'actionId': scene['actions'][0]['id']}})
        for scene in self.export:
            pair = {'sceneId': scene['id'], 'actionId': scene['narration'][0]['actionId']}
            for code in ('stored_audio_per_speech', 'speech_text_audio_binding', 'speech_internal_asset_binding',
                         'speech_real_audio_duration', 'speech_audible_in_actual_mp4'):
                detail = {**pair, 'decodedSeconds': 1, 'declaredMs': 1000, 'segmentMs': 1000,
                    'sourceCorrelation': {'allAudibleWindowsMatched': True, 'correlation': .9},
                    'videoPcm': {'activeBlocks': 5}}
                self.checks.append({'code': code, 'passed': True, 'detail': detail})
        self.write('checks', self.checks, 'verification-checks.json')
        self.video = {'kind': 'actual-full-narrated-video-evidence', 'technicalPass': True, 'failedChecks': 0,
            'passedChecks': len(self.checks), 'authoredSourceBinding': gate.SOURCE_BINDING,
            'inputs': [{'purpose': purpose, **self.record(role)} for purpose, role in (
                ('actual_source_classroom', 'classroom'), ('actual_rendered_mp4', 'mp4'), ('actual_export_zip', 'zip'))],
            'copiedManifests': [{'name': name, 'sha256': sha} for name, sha in self.zip_hashes.items()],
            'speechCount': 5, 'sceneCount': 5,
            'actualVideo': {'durationSeconds': 5, 'width': 16, 'height': 9, 'videoCodec': 'h264', 'audioCodec': 'aac'}}
        self.write('video_verification', self.video)
        self.semantic = {'kind': 'independent-classroom-content-review', 'basis': 'manual_source_and_actual_teaching_review',
            'reviewer': 'UNIT TEST FIXTURE NOT A HUMAN AUDIT', 'passed': True, 'classroom_id': self.cid,
            'classroom_sha256': self.record('classroom')['sha256'], 'source_text_sha256': blob_sha(self.source.encode()),
            'complete_source_reviewed': True, 'not_inferred_from_model_source_audit': True,
            'review_scope': list(gate.CONTENT_SCOPE), 'unresolved_issues': [], 'scene_findings': []}
        for scene in self.classroom['scenes']:
            row = {'scene_id': scene['id'], 'passed': True, 'conclusion': 'UNIT TEST synthetic specific content finding.',
                   'evidence': [{'kind': 'teacher_speech', 'action_id': scene['actions'][0]['id'], 'quote': scene['actions'][0]['text']}]}
            if scene['type'] == 'quiz':
                row['quiz_reviews'] = [{'question_id': 'q1', 'answer': ['B'], 'passed': True,
                                        'conclusion': 'UNIT TEST synthetic correct answer finding.'}]
            if scene['type'] == 'interactive':
                row['interaction_checks'] = [{'name': name, 'passed': True, 'conclusion': 'UNIT TEST synthetic control finding.'}
                    for name in ('source_conditions', 'state_and_formula_consistency', 'observation_vs_simulation')]
            self.semantic['scene_findings'].append(row)
        self.write('semantic_review', self.semantic)
        self.geometry = {'kind': 'actual-classroom-geometry-review', 'basis': 'actual_classroom_geometry_measurement',
            'reviewer': 'UNIT TEST FIXTURE', 'classroom_sha256': self.record('classroom')['sha256'], 'passed': True,
            'unresolved_issues': [], 'scene_findings': [{'scene_id': 'slide-original', 'passed': True,
                'conclusion': 'UNIT TEST synthetic geometry measurements.', 'measurements': {'overlap_count': 0,
                'out_of_bounds_count': 0, 'minimum_body_font_px': 24, 'image_aspect_ratio_preserved': True},
                'evidence': [self.record('measurements')]}]}
        self.write('geometry_review', self.geometry)
        self.frames = []
        (self.folder / 'frames').mkdir()
        for index, scene in enumerate(self.export):
            labels = ['scene']
            if index == 3:
                labels += ['quiz-top', 'quiz-bottom']
            if index == 4:
                labels += ['quiz-top', 'ending']
            for label in labels:
                relative = 'frames/%d-%s.png' % (index, label)
                data = png() + ('UNIT TEST %d-%s' % (index, label)).encode()
                (self.folder / relative).write_bytes(data)
                self.frames.append({'sceneId': scene['id'], 'label': label, 'atSeconds': index + (.9 if label == 'ending' else .5),
                                    'path': relative, 'sha256': blob_sha(data)})
        self.write('index', self.frames, 'actual-mp4-frame-index.json')
        self.checks += [{'code': 'actual_mp4_scene_frame', 'passed': True,
                         'detail': {'sceneId': f['sceneId'], 'label': f['label'], 'seconds': f['atSeconds']}}
                        for f in self.frames]
        self.video['actualVideo']['frameCount'] = len(self.frames)
        self.video['passedChecks'] = len(self.checks)
        self.write('checks', self.checks, 'verification-checks.json')
        self.write('video_verification', self.video)
        self.visual = {'kind': 'independent-actual-mp4-visual-review', 'basis': 'actual_mp4_decoded_frame_review',
            'reviewer': 'UNIT TEST FIXTURE', 'passed': True, 'unresolved_issues': [],
            'classroom_sha256': self.record('classroom')['sha256'], 'mp4_sha256': self.record('mp4')['sha256'],
            'frame_index_sha256': self.record('index')['sha256'], 'scene_findings': [
                {'scene_id': sid, 'passed': True, 'conclusion': 'UNIT TEST synthetic per-scene frame finding.',
                 'frame_sha256s': [f['sha256'] for f in self.frames if f['sceneId'] == sid]} for sid in ids]}
        self.write('visual_review', self.visual)
        self.flat = {'slides_layout_passed': True, 'explanations_complete': True, 'full_narrated_video_passed': True,
            'narration_coverage': {'written': 5, 'total': 5}, 'video_has_audio': True, 'video_duration_seconds': 5,
            'actual_evidence': {'schema_version': 1, 'classroom_id': self.cid}}
        self.refresh_flat()

    def write(self, role, value, filename=None):
        path = self.folder / (filename or role + ('.mp4' if role == 'mp4' else '.json'))
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode())
        self.paths[role] = path

    def record(self, role):
        path = self.paths[role]
        return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': blob_sha(path.read_bytes())}

    def write_zip(self):
        path = self.folder / 'export.zip'
        self.zip_hashes = {}
        with zipfile.ZipFile(path, 'w') as archive:
            for name, doc in (('openmaic-video-manifest.json', self.manifest), ('narrated-export.json', self.narrated)):
                data = json.dumps(doc).encode()
                archive.writestr(name, data)
                self.zip_hashes[name] = blob_sha(data)
        self.paths['zip'] = path

    def refresh_flat(self):
        self.flat['actual_evidence'].update({key: self.record(key) for key in gate.ARTIFACT_KEYS})
        self.write('flat', self.flat)

    def run(self, geometry_status='passed', visual_status='passed'):
        return gate.validate(self.paths['flat'], self.record('flat')['sha256'], geometry_status, visual_status)


class EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='unit-evidence-not-acceptance-', dir=ROOT / 'tests')
        self.addCleanup(self.temp.cleanup)
        self.fixture = SyntheticEvidence(self.temp.name)

    def rejected(self, pattern):
        with self.assertRaisesRegex(gate.EvidenceError, pattern):
            self.fixture.run()

    def test_schema_fixture_counts_bind_entire_video_and_no_file_is_written(self):
        before = {p: p.read_bytes() for p in Path(self.temp.name).rglob('*') if p.is_file()}
        result = self.fixture.run()
        self.assertTrue(result['passed'])
        self.assertFalse(result['model_source_status_used_as_manual_pass'])
        self.assertEqual(5, result['checks_summary']['total_speech_count'])
        self.assertEqual(8, len(result['inputs']))
        self.assertEqual(before, {p: p.read_bytes() for p in Path(self.temp.name).rglob('*') if p.is_file()})

    def test_verified_model_cannot_replace_independent_content_review(self):
        self.fixture.semantic['not_inferred_from_model_source_audit'] = False
        self.fixture.write('semantic_review', self.fixture.semantic)
        self.fixture.refresh_flat()
        self.rejected('not independent content review')

    def test_needs_review_cannot_bypass_release_with_manual_pass(self):
        self.fixture.classroom['stage']['sourceFidelity']['status'] = 'needs_review'
        self.fixture.write('classroom', self.fixture.classroom)
        self.fixture.refresh_flat()
        self.rejected('newly source-verified')

    def test_review_for_different_classroom_or_source_is_rejected(self):
        for field in ('classroom_sha256', 'source_text_sha256'):
            with self.subTest(field=field):
                original = self.fixture.semantic[field]
                self.fixture.semantic[field] = '0' * 64
                self.fixture.write('semantic_review', self.fixture.semantic)
                self.fixture.refresh_flat()
                self.rejected('different classroom|entire actual source')
                self.fixture.semantic[field] = original

    def test_hidden_distractor_and_wrong_quiz_answer_cannot_be_manual_evidence(self):
        quiz = self.fixture.semantic['scene_findings'][2]
        quiz['evidence'] = [{'kind': 'quiz_option', 'quote': 'Wrong option text'}]
        self.fixture.write('semantic_review', self.fixture.semantic)
        self.fixture.refresh_flat()
        self.rejected('hidden/distractor')
        quiz['evidence'] = [{'kind': 'quiz_analysis', 'question_id': 'q1', 'quote': 'Expected count is ten times'}]
        quiz['quiz_reviews'][0]['answer'] = ['A']
        self.fixture.write('semantic_review', self.fixture.semantic)
        self.fixture.refresh_flat()
        self.rejected('Correct quiz answer')

    def test_interactive_and_geometry_need_specific_full_review(self):
        self.fixture.semantic['scene_findings'][1]['interaction_checks'].pop()
        self.fixture.write('semantic_review', self.fixture.semantic)
        self.fixture.refresh_flat()
        self.rejected('Interactive semantic review')
        self.fixture.semantic['scene_findings'][1]['interaction_checks'].append({
            'name': 'observation_vs_simulation', 'passed': True, 'conclusion': 'UNIT TEST synthetic control finding.'})
        self.fixture.write('semantic_review', self.fixture.semantic)
        self.fixture.geometry['scene_findings'][0]['measurements']['out_of_bounds_count'] = 1
        self.fixture.write('geometry_review', self.fixture.geometry)
        self.fixture.refresh_flat()
        self.rejected('overlap or overflow')

    def test_full_video_requires_source_binding_and_every_segment_not_one_sample(self):
        self.fixture.video['authoredSourceBinding'] = 'not_checked_without_actual_classroom'
        self.fixture.write('video_verification', self.fixture.video)
        self.fixture.refresh_flat()
        self.rejected('full source speech/quiz binding')
        self.fixture.video['authoredSourceBinding'] = gate.SOURCE_BINDING
        self.fixture.checks = [c for c in self.fixture.checks if not (
            c['code'] == 'speech_audible_in_actual_mp4' and c['detail']['sceneId'] == 'interactive-original')]
        self.fixture.video['passedChecks'] = len(self.fixture.checks)
        self.fixture.write('checks', self.fixture.checks, 'verification-checks.json')
        self.fixture.write('video_verification', self.fixture.video)
        self.fixture.refresh_flat()
        self.rejected('every actual segment')

    def test_each_speech_needs_positive_duration_and_all_audible_windows(self):
        audible = next(c for c in self.fixture.checks if c['code'] == 'speech_audible_in_actual_mp4')
        audible['detail']['sourceCorrelation']['allAudibleWindowsMatched'] = False
        self.fixture.write('checks', self.fixture.checks, 'verification-checks.json')
        self.rejected('throughout its audible PCM windows')
        audible['detail']['sourceCorrelation']['allAudibleWindowsMatched'] = True
        self.fixture.write('checks', self.fixture.checks, 'verification-checks.json')
        self.fixture.manifest['scenes'][0]['narration'][0]['durationMs'] = 0
        self.fixture.write_zip()
        self.fixture.video['copiedManifests'] = [{'name': n, 'sha256': h} for n, h in self.fixture.zip_hashes.items()]
        self.fixture.video['inputs'][-1].update(self.fixture.record('zip'))
        self.fixture.write('video_verification', self.fixture.video)
        self.fixture.refresh_flat()
        self.rejected('positive duration')

    def test_flat_initial_tts_count_and_audio_duration_cannot_claim_full_video(self):
        self.fixture.flat['narration_coverage'] = {'written': 3, 'total': 3}
        self.fixture.refresh_flat()
        self.rejected('full video, not only initial')
        self.fixture.flat['narration_coverage'] = {'written': 5, 'total': 5}
        self.fixture.flat['video_duration_seconds'] = 3
        self.fixture.refresh_flat()
        self.rejected('duration/audio')

    def test_changed_actual_media_or_frame_is_rejected_by_sha(self):
        self.fixture.paths['mp4'].write_bytes(b'Changed actual media bytes')
        self.rejected('byte count changed|SHA mismatch')
        self.fixture.write('mp4', b'UNIT TEST NOT PLAYABLE MEDIA. Never actual acceptance.')
        frame = self.fixture.frames[0]
        (self.fixture.folder / frame['path']).write_bytes(b'changed frame')
        self.rejected('decoded frame bytes changed')

    def test_visual_review_cannot_omit_quiz_bottom_or_video_ending(self):
        self.fixture.frames = [frame for frame in self.fixture.frames if frame['label'] != 'ending']
        self.fixture.write('index', self.fixture.frames, 'actual-mp4-frame-index.json')
        self.fixture.visual['frame_index_sha256'] = self.fixture.record('index')['sha256']
        for row in self.fixture.visual['scene_findings']:
            row['frame_sha256s'] = [f['sha256'] for f in self.fixture.frames if f['sceneId'] == row['scene_id']]
        self.fixture.write('visual_review', self.fixture.visual)
        self.fixture.checks = [check for check in self.fixture.checks if not (
            check['code'] == 'actual_mp4_scene_frame' and check['detail']['label'] == 'ending')]
        self.fixture.video['actualVideo']['frameCount'] = len(self.fixture.frames)
        self.fixture.video['passedChecks'] = len(self.fixture.checks)
        self.fixture.write('checks', self.fixture.checks, 'verification-checks.json')
        self.fixture.write('video_verification', self.fixture.video)
        self.fixture.refresh_flat()
        self.rejected('final ending evidence')

    def test_configured_status_still_requires_underlying_measurements_and_frames(self):
        for role, document in (('geometry_review', self.fixture.geometry), ('visual_review', self.fixture.visual)):
            document['human_review'] = {'accepted': document.pop('passed')}
            self.fixture.write(role, document)
        self.fixture.refresh_flat()
        self.assertTrue(self.fixture.run('human_review.accepted', 'human_review.accepted')['passed'])
        self.fixture.geometry['scene_findings'][0]['evidence'] = []
        self.fixture.write('geometry_review', self.fixture.geometry)
        self.fixture.refresh_flat()
        with self.assertRaisesRegex(gate.EvidenceError, 'actual measurement/render evidence'):
            self.fixture.run('human_review.accepted', 'human_review.accepted')

    def test_default_cli_failure_does_not_write_and_schema_never_contains_pass(self):
        bad = self.fixture.folder / 'bad-flat.json'
        bad.write_text('{"slides_layout_passed":true}', encoding='utf-8')
        before = set(self.fixture.folder.rglob('*'))
        out = io.StringIO()
        with redirect_stdout(out):
            code = gate.main(['--feature-receipt', str(bad), '--feature-receipt-sha256', blob_sha(bad.read_bytes())])
        self.assertEqual(1, code)
        self.assertFalse(json.loads(out.getvalue())['passed'])
        self.assertEqual(before, set(self.fixture.folder.rglob('*')))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(0, gate.main(['--describe-schema']))
        schema = json.loads(out.getvalue())
        self.assertIsNone(schema['flat_receipt']['full_narrated_video_passed'])
        self.assertIsNone(schema['semantic_review']['passed'])

    def test_explicit_output_is_fresh_failure_only_and_never_overwrites(self):
        bad = self.fixture.folder / 'bad-flat.json'
        bad.write_text('{}', encoding='utf-8')
        output = self.fixture.folder / 'UNIT-TEST-failure-only.json'
        args = ['--feature-receipt', str(bad), '--feature-receipt-sha256', blob_sha(bad.read_bytes()),
                '--receipt-output', str(output)]
        with patch.object(gate, 'REPORTS', self.fixture.folder), redirect_stdout(io.StringIO()):
            self.assertEqual(1, gate.main(args))
            self.assertFalse(json.loads(output.read_text())['passed'])
            original = output.read_bytes()
            with self.assertRaisesRegex(gate.EvidenceError, 'fresh JSON receipt'):
                gate.main(args)
            self.assertEqual(original, output.read_bytes())


if __name__ == '__main__':
    unittest.main(verbosity=2)
