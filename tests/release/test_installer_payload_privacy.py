"""Machine storage roots and old uninstall state never enter a new installer."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'installer'))
import build_standalone_release as builder


class PayloadPrivacyTests(unittest.TestCase):
    def test_private_state_excluded_program_code_retained(self):
        with tempfile.TemporaryDirectory(prefix='DeepSteam payload 中文 ') as tmp:
            root=Path(tmp)
            def put(name,text='fixture'):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,'utf-8')
            put('runtime/native-frontend.json',json.dumps({'root':'runtime/native-frontends/rc'}))
            private=['deepsteam-storage.json','.deepsteam-uninstall-manifest.json',
                'runtime/harness-state/profile/credentials.dpapi','runtime/desktop-profile/Default/Cookies',
                'runtime/deeptutor-home/data/user/settings/model_catalog.json','data/chat.json','logs/run.log']
            program=['scripts/storage_paths.py','installer/DeepSteamSetup.cs',
                'runtime/native-frontends/rc/server.js','runtime/harness/credentials.mjs']
            for name in private+program:put(name)
            with patch.object(builder,'ROOT',root):files,links,excluded,suspect,frontend=builder.scan()
            names={r[0] for r in files}
            self.assertTrue(set(private).isdisjoint(names))
            self.assertTrue(set(program).issubset(names))
            self.assertEqual(links,[])
            self.assertGreater(sum(excluded.values()),0)


if __name__=='__main__':unittest.main(verbosity=2)
