"""Contract checks only: these synthetic inputs are not actual export evidence."""
import copy
import importlib.util
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("narrated_video_verifier", ROOT / "reports" / "verify_full_narrated_video.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def fixture():
    source = {"stage": {"id": "actual-test"}, "scenes": [
        {"id": "lecture", "order": 0, "type": "slide", "actions": [{"type": "speech", "id": "lecture-speech", "text": "Mechanism explanation🙂."}],
         "content": {"type": "slide"}},
        {"id": "quiz", "order": 1, "type": "quiz", "title": "Mechanism question", "actions": [], "content": {"type": "quiz", "questions": [
            {"id": "q1", "type": "single", "question": "What happens when the condition changes?", "options": [{"value": "A", "label": "Increase"}, {"value": "B", "label": "Decrease"}],
             "answer": ["A"], "analysis": "The changed condition promotes the reaction, so it increases."}]}}]}
    identity = VERIFY.sha_bytes(b"quiz\n0\nq1")[:24]
    qid, aid = "export-%s-question" % identity, "export-%s-analysis" % identity
    question = source["scenes"][1]["content"]["questions"][0]
    explanation = "Expected answer: A, increase.\nExisting explanation: " + question["analysis"]
    definitions = [
        ("lecture", "slide", "lecture-speech", "Mechanism explanation🙂.", None, False),
        ("quiz", "quiz", "intro", "Think before answering.", None, False),
        (qid, "quiz", qid + "-speech", "Question 1. What happens when the condition changes?\nOption A. Increase.\nOption B. Decrease.\nPause the video, think independently, and answer.", question, True),
        (aid, "quiz", aid + "-speech", "Question 1 explanation.\n" + explanation,
         {"id": "q1-export-analysis", "type": "short_answer", "question": question["question"] + "\n\n" + explanation}, False),
    ]
    scenes, clips, assets, subtitles = [], [], [], []
    cursor = 0
    for index, (sid, kind, action, text, question, pause) in enumerate(definitions):
        ref, asset_id = "audio/%d.wav" % index, "voice-%d" % index
        speech = {"actionId": action, "actionIndex": 0, "startMs": cursor, "durationMs": 2000, "text": text,
                  "audio": {"assetId": asset_id, "assetRef": ref, "durationMs": 2000, "source": "stored", "present": True}}
        visual = [] if question is None else [{"kind": "quiz-question-list", "startMs": cursor, "durationMs": 7000 if pause else 2000,
                                              "questions": [copy.deepcopy(question)], "scrollDistancePx": 0}]
        narration = [speech]
        if pause:
            narration.append({"actionId": "export-%s-pause" % identity, "actionIndex": 1, "startMs": cursor + 2000,
                              "durationMs": 5000, "text": "", "audio": {"durationMs": 5000, "source": "stored", "present": False}})
        scenes.append({"id": sid, "index": index, "title": sid, "type": kind, "startMs": cursor, "durationMs": 7000 if pause else 2000,
                       "supported": True, "base": {"kind": "slide-snapshot" if kind == "slide" else "visual-segments"}, "narration": narration,
                       "visuals": visual, "effects": [], "videos": [], "markers": []})
        clips.append({"sceneId": sid, "actionId": action, "audioId": asset_id, "characters": VERIFY.js_length(text),
                      "textSha256": VERIFY.sha_bytes(text.encode("utf-8")), "generated": True})
        assets.append({"assetId": asset_id, "kind": "audio", "path": ref, "present": True})
        # Two trimmed cues; punctuation remains exact and timings tile the speech.
        seam = text.find(".") + 1
        subtitles.extend([{"sceneId": sid, "actionId": action, "startMs": cursor, "endMs": cursor + 1000, "text": text[:seam].strip()},
                          {"sceneId": sid, "actionId": action, "startMs": cursor + 1000, "endMs": cursor + 2000, "text": text[seam:].strip()}]
                         if text[seam:].strip() else [{"sceneId": sid, "actionId": action, "startMs": cursor, "endMs": cursor + 2000, "text": text}])
        cursor += 7000 if pause else 2000
    manifest = {"schema": "openmaic.videoTimeline", "version": 4, "stage": {"id": "actual-test"},
                "canvas": {"aspectRatio": "16:9", "pixelBase": {"width": 1000, "height": 562.5}},
                "config": {"playbackSpeed": 1, "ttsEnabled": True}, "totalDurationMs": cursor,
                "scenes": scenes, "subtitles": subtitles, "assets": {"entries": assets}, "diagnostics": []}
    narration = {"version": 1, "courseId": "actual-test", "sourceSha256": "a" * 64, "exportSha256": "b" * 64,
                 "quizVideoMode": "read-question-options-pause-then-authored-answer-and-analysis",
                 "coverage": {"sceneCount": 4, "voicedSceneCount": 4, "speechCount": 4, "voicedSpeechCount": 4,
                              "spokenCharacters": sum(clip["characters"] for clip in clips), "quizQuestionCount": 1, "quizAnalysisCount": 1, "clips": clips}}
    return manifest, narration, source


class NarratedVideoVerifierTests(unittest.TestCase):
    def test_full_contract_accepts_absolute_times_utf16_split_cues_and_silent_pause(self):
        manifest, narration, source = fixture()
        before = copy.deepcopy((manifest, narration, source))
        audit = VERIFY.Audit()
        scenes, speeches, pauses = VERIFY.validate_timeline(manifest, narration, audit)
        VERIFY.validate_source_classroom(source, scenes, narration, audit)
        self.assertTrue(audit.passed, [item for item in audit.checks if not item["passed"]])
        self.assertEqual((len(speeches), len(pauses)), (4, 1))
        self.assertEqual((manifest, narration, source), before)

    def test_original_identity_requires_snapshot_provenance_and_matching_original(self):
        for mutation in (None, "no_provenance", "saved_provenance", "wrong_original", "missing_course"):
            with self.subTest(mutation=mutation):
                manifest, narration, source = fixture()
                narration.update(courseId="snapshot-storage-id", originalCourseId="actual-test",
                                 provenance={"kind": "export-snapshot"})
                if mutation == "no_provenance":
                    narration.pop("provenance")
                elif mutation == "saved_provenance":
                    narration["provenance"]["kind"] = "saved-classroom"
                elif mutation == "wrong_original":
                    narration["originalCourseId"] = "unrelated-course"
                elif mutation == "missing_course":
                    narration.pop("courseId")
                before = copy.deepcopy((manifest, narration, source))
                audit = VERIFY.Audit()
                scenes, _, _ = VERIFY.validate_timeline(manifest, narration, audit)
                VERIFY.validate_source_classroom(source, scenes, narration, audit)
                identity_checks = [check for check in audit.checks if check["code"] in
                                   {"course_identity", "source_course_identity"}]
                self.assertEqual([check["passed"] for check in identity_checks], [mutation is None] * 2)
                self.assertEqual((manifest, narration, source), before)

    def test_native_unicode_asset_plan_paths_bind_zip_and_directory_without_suffix_guessing(self):
        manifest, narration, _ = fixture()
        plan = "audio/001-Images-And-Formulas/speech-001.wav"
        frame = "frames/001-Images-And-Formulas.png"
        manifest["assets"]["entries"] = [
            {"assetId": "voice", "kind": "audio", "path": plan, "present": True},
            {"assetId": "frame", "kind": "frame", "path": frame, "present": True},
        ]
        pcm_metrics = {"samples": 16000, "activeBlocks": 1, "durationSeconds": 1}

        def fake_decode(path, stem, output):
            result = output / (stem + ".pcm")
            result.write_bytes(b"synthetic unit-test PCM")
            return result

        for mode in ("zip", "directory", "wrong-prefix"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                resources = {"assets/" + plan: b"synthetic audio", "assets/" + frame: b"synthetic frame",
                             "assets/audio/Unreferenced.wav": b"synthetic unreferenced audio"}
                if mode == "wrong-prefix":
                    resources[plan] = resources.pop("assets/" + plan)
                metadata = {"openmaic-video-manifest.json": json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
                            "narrated-export.json": json.dumps(narration, ensure_ascii=False).encode("utf-8")}
                if mode == "directory":
                    for name, data in {**metadata, **resources}.items():
                        destination = root / Path(*PurePosixPath(name).parts)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(data)
                    args = SimpleNamespace(zip=None, manifest=root / "openmaic-video-manifest.json",
                                           narrated_export=root / "narrated-export.json", project_root=root)
                else:
                    archive = root / "actual-native-format.zip"
                    with zipfile.ZipFile(archive, "w") as output:
                        for name, data in {**metadata, **resources}.items():
                            output.writestr(name, data)
                    with zipfile.ZipFile(archive) as check:
                        self.assertTrue(check.getinfo("assets/" + frame).flag_bits & 0x800)
                    args = SimpleNamespace(zip=archive)
                audit = VERIFY.Audit()
                export = VERIFY.ExportInput(args, audit)
                evidence = root / "evidence"
                evidence.mkdir()
                try:
                    with patch.object(VERIFY, "probe", return_value={}), patch.object(VERIFY, "decode", side_effect=fake_decode), \
                            patch.object(VERIFY, "pcm_metrics", return_value=pcm_metrics):
                        audio, by_path = VERIFY.verify_assets(export, manifest, evidence, audit)
                    records = json.loads((evidence / "internal-audio-evidence.json").read_text(encoding="utf-8"))
                    # ZIP input also checks undeclared internal audio; directory
                    # input reads its declared assets without traversing a tree.
                    self.assertEqual(len(records), 1 if mode == "directory" else 2)
                    self.assertEqual(plan in audio, mode != "wrong-prefix")
                    self.assertEqual(audit.passed, mode != "wrong-prefix")
                    self.assertEqual(by_path[plan][0]["assetId"], "voice")
                    if mode != "wrong-prefix":
                        self.assertEqual(audio[plan]["record"]["path"], "assets/" + plan)
                        self.assertEqual(audio[plan]["record"]["assetPlanPaths"], [plan])
                    for record in records:
                        for field in ("evidenceFile", "decodedPcm"):
                            self.assertNotIn("\\", record[field])
                            self.assertTrue((evidence / Path(*PurePosixPath(record[field]).parts)).is_file())
                finally:
                    export.close()

    def test_evidence_indexes_are_contained_posix_paths_on_windows_and_posix(self):
        for kind, base in ((PureWindowsPath, "D:/reports/evidence"), (PurePosixPath, "/reports/evidence")):
            with self.subTest(kind=kind.__name__):
                output = kind(base)
                frame = output / "actual-mp4-frames" / "001-Scene.png"
                self.assertEqual(VERIFY.evidence_relative_path(frame, output), "actual-mp4-frames/001-Scene.png")
                with self.assertRaises(ValueError):
                    VERIFY.evidence_relative_path(output.parent / "outside.png", output)

    def test_success_metadata_cannot_hide_missing_or_changed_speech(self):
        for mutation in ("wrong_hash", "missing_clip", "missing_subtitle", "estimated", "scene_gap", "wrong_pause"):
            with self.subTest(mutation=mutation):
                manifest, narration, _ = fixture()
                if mutation == "wrong_hash":
                    narration["coverage"]["clips"][0]["textSha256"] = "0" * 64
                elif mutation == "missing_clip":
                    narration["coverage"]["clips"].pop()
                elif mutation == "missing_subtitle":
                    manifest["subtitles"].pop()
                elif mutation == "estimated":
                    manifest["scenes"][0]["narration"][0]["audio"]["source"] = "estimated"
                elif mutation == "scene_gap":
                    manifest["scenes"][1]["startMs"] += 500
                else:
                    manifest["scenes"][2]["narration"][1]["durationMs"] = 2000
                audit = VERIFY.Audit()
                VERIFY.validate_timeline(manifest, narration, audit)
                self.assertFalse(audit.passed)

    def test_authored_quiz_analysis_option_and_source_order_cannot_be_substituted(self):
        for mutation in ("option", "analysis", "order"):
            with self.subTest(mutation=mutation):
                manifest, narration, source = fixture()
                if mutation == "option":
                    source["scenes"][1]["content"]["questions"][0]["options"][0]["label"] = "Another option"
                elif mutation == "analysis":
                    source["scenes"][1]["content"]["questions"][0]["analysis"] = "A different, inconsistent explanation."
                else:
                    source["scenes"][0]["order"] = 10
                audit = VERIFY.Audit()
                VERIFY.validate_source_classroom(source, manifest["scenes"], narration, audit)
                self.assertFalse(audit.passed)

    def test_audio_asset_dedup_is_allowed_but_zip_collision_and_escape_are_rejected(self):
        manifest, narration, _ = fixture()
        manifest["assets"]["entries"].append({**manifest["assets"]["entries"][0], "dedupOf": "voice-0"})
        audit = VERIFY.Audit()
        VERIFY.validate_timeline(manifest, narration, audit)
        self.assertTrue(audit.passed)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "test.zip"
            with self.assertRaises(ValueError):
                VERIFY.safe_relative("audio\\outside.wav")
            for unsafe in ("../outside.wav", "C:/outside.wav"):
                with self.subTest(unsafe=unsafe), zipfile.ZipFile(archive, "w") as output:
                    output.writestr(unsafe, b"not audio")
                with self.assertRaises(ValueError):
                    VERIFY.ExportInput(SimpleNamespace(zip=archive), VERIFY.Audit())
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("audio/one.wav", b"one")
                output.writestr("audio/ONE.wav", b"two")
            with self.assertRaises(ValueError):
                VERIFY.ExportInput(SimpleNamespace(zip=archive), VERIFY.Audit())

    def test_rms_and_pcm_binding_reject_silence_and_different_audio(self):
        # Unit-test PCM, not a rendered video fixture or evidence of a real export.
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            pcm = VERIFY.array.array("h", (int(12000 * math.sin(index / 13.7) * (0.6 + 0.3 * math.sin(index / 347)))
                                           for index in range(VERIFY.SAMPLE_RATE * 2)))
            source, matching, wrong, silent = [directory / name for name in ("source.pcm", "match.pcm", "wrong.pcm", "silent.pcm")]
            source.write_bytes(pcm.tobytes())
            matching.write_bytes(b"\0" * 3200 + pcm.tobytes())
            wrong.write_bytes(VERIFY.array.array("h", (int(12000 * math.sin(index / 7.1)) for index in range(len(pcm) + 1600))).tobytes())
            silent.write_bytes(b"\0" * len(pcm) * 2)
            metrics = VERIFY.pcm_metrics(source)
            self.assertGreater(metrics["activeBlocks"], 0)
            self.assertEqual(VERIFY.pcm_metrics(silent)["activeBlocks"], 0)
            self.assertGreater(VERIFY.pcm_correlation(source, matching, 100, metrics)["correlation"], 0.99)
            self.assertTrue(VERIFY.pcm_correlation(source, matching, 100, metrics)["allAudibleWindowsMatched"])
            self.assertLess(VERIFY.pcm_correlation(source, wrong, 100, metrics)["correlation"], 0.60)

    def test_zip_crc_covers_even_unreferenced_internal_audio(self):
        manifest, narration, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "actual-format-unit-input.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
                output.writestr("openmaic-video-manifest.json", json.dumps(manifest))
                output.writestr("narrated-export.json", json.dumps(narration))
                output.writestr("audio/unreferenced.wav", b"UNIQUE-AUDIO-PAYLOAD")
            data = archive.read_bytes().replace(b"UNIQUE-AUDIO-PAYLOAD", b"UNIQUE-AUDIO-PAYLOAd")
            archive.write_bytes(data)
            audit = VERIFY.Audit()
            export = VERIFY.ExportInput(SimpleNamespace(zip=archive), audit)
            try:
                self.assertIn("audio/unreferenced.wav", export.audio_names)
                self.assertFalse(audit.passed)
                self.assertEqual(audit.checks[0]["code"], "zip_crc_all_entries")
            finally:
                export.close()


if __name__ == "__main__":
    unittest.main()
