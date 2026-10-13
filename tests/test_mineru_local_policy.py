"""Local-only MinerU policy across entry points. No model inference runs here."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from integration import document_jobs as jobs
from integration import mineru_local

ROOT = Path(__file__).resolve().parents[1]


class LocalMinerUPolicyTests(unittest.TestCase):
    def test_default_tier_is_basic_first_with_local_vlm_for_complex_pages(self):
        self.assertEqual(jobs.DEFAULT_MINERU_TIER, 'adaptive')
        self.assertEqual(jobs.DEFAULT_AUTO_TIER, 'adaptive')
        self.assertEqual(mineru_local.DEFAULT_TIER, 'adaptive')
        self.assertEqual(jobs.MINERU_TIERS, {'adaptive', 'basic', 'standard', 'advanced'})
        python, helper = jobs.mineru_runtime()
        self.assertEqual(python, ROOT / 'runtime/mineru/python.exe')  # fixed path, never PATH lookup
        self.assertEqual(helper, ROOT / 'scripts/mineru_document_worker.py')

    def test_missing_runtime_is_an_explicit_error_not_a_fallback(self):
        with mock.patch.object(jobs, 'mineru_runtime', return_value=(ROOT / 'runtime/absent/python.exe', ROOT / 'scripts/mineru_document_worker.py')):
            status = jobs.engine_status()
            self.assertFalse(status['ok'])
            self.assertFalse(status['remote_api'])
            self.assertEqual(status['error']['code'], 'document_engine_unavailable')
            with tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / 'scan.pdf'
                source.write_bytes(b'%PDF-1.7 synthetic')
                with self.assertRaises(mineru_local.LocalMinerUError) as caught:
                    mineru_local.parse_to_directory(source, Path(tmp) / 'out')
                self.assertEqual(caught.exception.code, 'document_engine_unavailable')
                self.assertIn('no remote', str(caught.exception))

    def test_engine_status_action_needs_no_workspace(self):
        result = jobs.handle({'action': 'engine_status'})
        self.assertIn('default_tier', result)
        self.assertEqual(result['default_tier'], 'adaptive')
        self.assertIn('tables or display formulas', result['tiers']['adaptive'])
        self.assertFalse(result['remote_api'])

    def test_mineru4_blocks_map_to_deeptutor_content_list(self):
        result = {'units': [{'locator': {'page': 3, 'page_idx': 2}, 'blocks': [
            {'type': 'title', 'content': 'Synthetic heading'},
            {'type': 'text', 'content': 'Synthetic body'},
            {'type': 'interline_equation', 'content': 'E=mc^2', 'image_path': 'images/eq.png'},
            {'type': 'table', 'html': '<table><tr><td>1</td></tr></table>', 'captions': [{'content': 'Table 1'}]},
            {'type': 'image', 'image_path': 'images/fig.png', 'content': 'A bar chart of two values', 'captions': [{'content': 'Figure 1'}]},
        ]}]}
        blocks = mineru_local.content_list(result)
        self.assertEqual([block['type'] for block in blocks], ['text', 'text', 'equation', 'table', 'image'])
        self.assertEqual(blocks[0]['text_level'], 1)
        self.assertTrue(all(block['page_idx'] == 2 for block in blocks))
        self.assertEqual(blocks[3]['table_caption'], ['Table 1'])
        self.assertEqual(blocks[4]['image_caption'], ['Figure 1', 'A bar chart of two values'])

    @unittest.skipUnless(importlib.util.find_spec('pydantic') is not None, 'DeepTutor dependencies not installed')
    def test_deeptutor_cloud_mode_is_refused_inside_deepsteam(self):
        sys.path.insert(0, str(ROOT / 'upstream/DeepTutor'))
        try:
            from deeptutor.services.parsing.engines.mineru import backend, readiness
            from deeptutor.services.parsing.engines.mineru.config import MinerUConfig, MinerUError
        except ImportError as exc:
            self.skipTest(f'DeepTutor import unavailable: {exc}')
        finally:
            sys.path.remove(str(ROOT / 'upstream/DeepTutor'))
        cloud = MinerUConfig(mode='cloud', api_token='synthetic-token')
        self.assertEqual(readiness.mineru_readiness(cloud).reason, 'cloud_disabled')
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'scan.pdf'
            source.write_bytes(b'%PDF-1.7 synthetic')
            with mock.patch('deeptutor.services.parsing.engines.mineru.cloud.parse_cloud') as cloud_call:
                with self.assertRaises(MinerUError) as caught:
                    backend.parse_document_to_workdir(source, Path(tmp) / 'out', config=cloud)
                cloud_call.assert_not_called()
            self.assertEqual(caught.exception.code, 'cloud_disabled')
            local = MinerUConfig(mode='local')
            with mock.patch.object(mineru_local, 'installed', return_value=False):
                self.assertEqual(readiness.mineru_readiness(local).reason, 'local_runtime_missing')
            with mock.patch.object(backend, 'local_cli_probe') as cli, \
                    mock.patch.object(mineru_local, 'parse_to_workdir', side_effect=mineru_local.LocalMinerUError('vlm_unavailable', 'synthetic')):
                with self.assertRaises(MinerUError) as caught:
                    backend.parse_document_to_workdir(source, Path(tmp) / 'out', config=local)
                cli.assert_not_called()  # no PATH CLI fallback
            self.assertEqual(caught.exception.code, 'vlm_unavailable')


if __name__ == '__main__':
    unittest.main()
