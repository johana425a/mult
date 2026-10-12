"""Local narration must neither require nor decrypt a cloud credential."""
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integration.openmaic_bridge import OpenMAICBridge
from portal.storage import Store


class LocalNarrationModeTests(unittest.TestCase):
    def test_fresh_store_enables_local_narration(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            value = store.settings()
            self.assertTrue(value['tts_enabled'])
            self.assertEqual(value['tts_mode'], 'local')

    def test_local_mode_preserves_but_does_not_decrypt_cloud_key(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            with patch('portal.storage.protect', return_value='protected'):
                store.save_settings({'tts_mode': 'api', 'tts_api_key': 'test-only-placeholder'})
            store.save_settings({'tts_mode': 'local'})
            with patch('portal.storage.protect', side_effect=AssertionError('must not decrypt')):
                self.assertEqual(store.settings(secret=True)['tts_api_key'], '')
                self.assertTrue(store.settings()['tts_key_set'])

    def test_legacy_api_choice_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.save_settings({'tts_enabled': False, 'tts_base_url': 'https://example.invalid/v1', 'tts_model': 'old-model'})
            value = store.settings()
            self.assertEqual(value['tts_mode'], 'api')
            self.assertFalse(value['tts_enabled'])

    def test_windows_headers_carry_only_explicit_narration_selection(self):
        value = OpenMAICBridge._headers({'model': 'fixture-model', 'base_url': 'http://127.0.0.1:3795/v1', 'tts_enabled': True, 'tts_provider': 'windows-system-tts', 'tts_model': 'system-speech', 'tts_voice': 'auto-en'})
        self.assertEqual(value['x-contest-tts-provider'], 'windows-system-tts')
        self.assertEqual(value['x-contest-tts-model'], 'system-speech')
        self.assertNotIn('x-contest-tts-api-key', value)
        self.assertNotIn('x-contest-tts-base-url', value)


if __name__ == '__main__':
    unittest.main()
