"""Exercise the candidate finalization branches with a tiny synthetic payload."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'installer'))
import build_standalone_release as builder


class CandidateFinalizationTests(unittest.TestCase):
    def run_candidate(self, embedded, changed=False):
        with tempfile.TemporaryDirectory(prefix='DS packaging fixture ') as directory:
            base = Path(directory)
            source_root = base / 'source'; source_root.mkdir()
            runtime = base / 'runtime'; runtime.mkdir()
            out = base / 'fixture.candidate'
            identity = {'root': str(source_root), 'tree_sha256': 'original', 'files': 1}
            later = {**identity, 'tree_sha256': 'changed'} if changed else dict(identity)
            def compile_stub(path):
                path.write_bytes(b'SYNTHETIC-NOT-AN-EXECUTABLE')
            def zip_stub(files, links, version, archive, log, binding):
                archive.write_bytes(b'SYNTHETIC-PAYLOAD')
                return []
            def self_test_stub(args, **kwargs):
                Path(args[-1]).write_text('PASS synthetic fixture only', 'utf-8')
                return type('Result', (), {'returncode': 0})()
            with patch.object(builder, 'ROOT', runtime), \
                 patch.object(builder.release_gate, 'source_identity', side_effect=[identity, later]), \
                 patch.object(builder.release_gate, 'runtime_binding', return_value={'source': identity}), \
                 patch.object(builder.release_gate, 'begin') as begin, \
                 patch.object(builder, 'scan', return_value=([], [], {}, [], 'frontend')), \
                 patch.object(builder, 'program_version', return_value='fixture'), \
                 patch.object(builder, 'compile_exe', side_effect=compile_stub), \
                 patch.object(builder, 'build_zip', side_effect=zip_stub), \
                 patch.object(builder.subprocess, 'run', side_effect=self_test_stub), \
                 patch.object(builder, 'MAX_PE_BYTES', 10000 if embedded else 1), \
                 patch.object(sys, 'argv', ['build', '--candidate-only', '--source-root', str(source_root), '--out', str(out)]), \
                 contextlib.redirect_stdout(io.StringIO()):
                result = builder.main()
            report = json.loads((out / 'build-report.json').read_text('utf-8'))
            self.assertEqual(result, 1 if changed else 0)
            self.assertEqual(begin.call_count, 0 if changed else 1)
            self.assertEqual(report['source_binding']['source'], identity)
            self.assertEqual(report['self_test_exit'], 0)
            self.assertEqual('embedded' in report['container'], embedded)
            self.assertEqual((out / 'DeepSteam-Setup-fixture-x64.payload.dat').exists(), not embedded)
            if not changed:
                self.assertEqual(begin.call_args.args[0], str(source_root))
                self.assertEqual(len(begin.call_args.args[1]), 1 if embedded else 2)

    def test_embedded_payload_retains_source_identity(self):
        self.run_candidate(True)

    def test_sidecar_payload_retains_source_identity(self):
        self.run_candidate(False)

    def test_source_drift_still_blocks_candidate(self):
        self.run_candidate(True, changed=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
