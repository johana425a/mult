"""Render the actual settings store and provider workflows in isolated JSDOM."""
from pathlib import Path
import json, os, subprocess, tempfile, unittest

ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'upstream/DeepTutor/web'

class SettingsUsabilityTests(unittest.TestCase):
    def test_rendered_preferences_and_provider_setup(self):
        node=os.environ.get('DEEPSTEAM_NODE') or 'node'
        package=Path(os.environ.get('DEEPSTEAM_WEB_TEST_DEPENDENCIES',str(WEB/'package.json')))
        entry=package.parent/'node_modules/vitest/vitest.mjs'
        self.assertTrue(entry.is_file(), 'Locked frontend test dependencies are required')
        with tempfile.TemporaryDirectory(prefix='DS settings tests ') as temporary:
            report=Path(temporary)/'vitest.json'
            result=subprocess.run([node,str(entry),'run','tests/settings-unified-draft.spec.tsx',
                'tests/provider-registry-workflow.spec.tsx','tests/model-settings-store.spec.tsx',
                '--reporter=json','--reporter=default','--outputFile='+str(report),'--maxWorkers=1'],cwd=WEB,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=150,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:
                print(result.stdout.decode('utf-8','replace')[-5000:])
                print(result.stderr.decode('utf-8','replace')[-5000:])
            data=json.loads(report.read_text('utf-8')) if report.exists() else {}
            failures=[{'test':case.get('fullName'), 'errors':[message[:1500] for message in case.get('failureMessages',[])]}
                for suite in data.get('testResults',[]) for case in suite.get('assertionResults',[])
                if case.get('status')=='failed']
            self.assertEqual(result.returncode,0,json.dumps(failures,ensure_ascii=False))
            self.assertTrue(data.get('success'))
            self.assertGreaterEqual(data.get('numPassedTests',0),20)
            self.assertEqual(data.get('numPendingTests'),0)
            print('Rendered settings cases passed:',data['numPassedTests'])

if __name__=='__main__':unittest.main(verbosity=2)
