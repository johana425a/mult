"""Fresh standalone language defaults must not override an existing user choice."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
if os.environ.get('DEEPSTEAM_PYTHON_DEPENDENCIES'):
    sys.path.insert(0,os.environ['DEEPSTEAM_PYTHON_DEPENDENCIES'])
sys.path.insert(0,str(ROOT/'upstream/DeepTutor'))
from deeptutor.services.settings import interface_settings as settings


class StandaloneLocaleTests(unittest.TestCase):
    def test_fresh_source_defaults_to_english(self):
        with patch.dict(os.environ,{},clear=True):
            module=importlib.reload(settings)
            self.assertEqual(module.resolve_languages({}),{'language':'en','response_language':'en'})

    def test_fresh_packaged_default_is_chinese(self):
        with patch.dict(os.environ,{'DEEPSTEAM_DEFAULT_LANGUAGE':'zh'}):
            module=importlib.reload(settings)
            with tempfile.TemporaryDirectory() as directory,patch.object(module,'_interface_settings_file',return_value=Path(directory)/'interface.json'):
                current=module.get_ui_settings()
                self.assertEqual((current['language'],current['response_language']),('zh','zh'))

    def test_saved_choices_survive_an_upgrade(self):
        with patch.dict(os.environ,{'DEEPSTEAM_DEFAULT_LANGUAGE':'zh'}):
            module=importlib.reload(settings)
            for saved,expected in [({'language':'en'},{'language':'en','response_language':'en'}),
                                   ({'language':'zh','response_language':'en'},{'language':'zh','response_language':'en'}),
                                   ({'language':'en','response_language':'zh-tw'},{'language':'en','response_language':'zh-tw'})]:
                self.assertEqual(module.resolve_languages(saved),expected)
            with tempfile.TemporaryDirectory() as directory:
                target=Path(directory)/'interface.json'
                target.write_text(json.dumps({'language':'en'}),encoding='utf-8')
                before=target.read_bytes()
                with patch.object(module,'_interface_settings_file',return_value=target):
                    self.assertEqual(module.get_ui_settings()['language'],'en')
                self.assertEqual(target.read_bytes(),before)


if __name__=='__main__':unittest.main(verbosity=2)
