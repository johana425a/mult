"""Public source inventory includes the new repaired code and release gates."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]


class SourceTests(unittest.TestCase):
    def test_manifest_hashes_and_release_sources_are_current(self):
        result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/verify_public_source.py')],
            capture_output=True,text=True,encoding='utf-8',timeout=180,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        rows={r['path'] for r in json.loads((ROOT/'PUBLIC-SOURCE-MANIFEST.json').read_text('utf-8'))['files']}
        required={'integration/model_failures.py','upstream/DeepTutor/web/lib/transcript-follow-dom.cjs',
            *[p.relative_to(ROOT).as_posix() for p in (ROOT/'tests/release').iterdir() if p.is_file()],
            *[p.relative_to(ROOT).as_posix() for p in (ROOT/'installer').glob('*release*.py')],
            'installer/accept_installed_candidate.py','installer/record_native_acceptance.py'}
        self.assertFalse(required-rows,'New source or regression files are absent from the source inventory')


if __name__=='__main__':unittest.main(verbosity=2)
