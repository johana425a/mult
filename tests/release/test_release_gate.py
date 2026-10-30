"""Positive synthetic promotion and negative release attempts (no real release)."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'installer'))
import release_gate as gate
from run_release_regressions import execute_case
from accept_installed_candidate import verify_payload, safe_member
from competition_fixtures import fixtures


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='DeepSteam gate fixture ')
        self.base=Path(self.temp.name);self.source=self.base/'source';self.source.mkdir()
        subprocess.run(['git','init','-q',str(self.source)],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (self.source/'code.py').write_text('fixture = 1\n','utf-8')
        profile_path='upstream/DeepTutor/deeptutor/config/competition-features.json'
        self.profile=json.loads((ROOT/profile_path).read_text('utf-8'))
        (self.source/profile_path).parent.mkdir(parents=True)
        (self.source/profile_path).write_text(json.dumps(self.profile),'utf-8')
        self.artifact=self.base/'SYNTHETIC-NOT-AN-INSTALLER.bin';self.artifact.write_bytes(b'test-only')
        self.run=self.base/'acceptance';self.dest=self.base/'promoted-fixture'
        self.ctx=gate.begin(self.source,[self.artifact],self.run,'fixture-only')
        self.evidence=self.base/'fixture-evidence.txt';self.evidence.write_text('Synthetic gate unit-test evidence only','utf-8')
        desc=gate.descriptor(self.evidence)
        generation=self.base/'generation-fixture.json'
        generation.write_text(json.dumps({'passed':True,'files':[desc]}),'utf-8')
        self.reports={
          'regressions':dict(passed=True,generation_build=gate.descriptor(generation),source_after=self.ctx['source'],cases=[dict(case=n,status='passed',exit_code=0,assertions=1,log=desc) for n in gate.REQUIRED_CASES]),
          'live-models':dict(passed=True,evidence_class='live-provider',models=[dict(model=n,text_passed=True,tool_passed=True,tool_result_verified=True,frozen_selection=True,tool_names=['read'],reasoning_effort='high') for n in gate.LIVE_MODELS],transcript=desc,synthetic_recovery={'passed':True,'attempts':3,'answer':'','error_count':1}),
          'installed-package':dict(passed=True,self_test_passed=True,all_payload_hashes_passed=True,source_binding_passed=True,isolated_install=True,files_verified=1,report=desc),
          'native-fullscreen':dict(passed=True,evidence_class='native-ui',product='DeepSteam',reviewer='synthetic-unit-test',steps={s:True for s in gate.NATIVE_STEPS},max_scroll_drift_px=0,samples=30,recording=desc)}
        self.reports.update(fixtures(self.ctx,desc,self.profile))
        self.write_reports()

    def tearDown(self):self.temp.cleanup()

    def write_reports(self):
        for name,fields in self.reports.items():
            (self.run/(name+'.json')).write_text(json.dumps(gate.receipt(self.ctx,name,**fields)),'utf-8')

    def blocked(self):
        self.assertFalse(gate.check(self.run)['passed'])
        with self.assertRaisesRegex(ValueError,'BLOCKED'):gate.promote(self.run,self.dest)
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.artifact.read_bytes(),b'test-only')

    def test_complete_synthetic_evidence_promotes_exact_bytes(self):
        self.assertTrue(gate.promote(self.run,self.dest)['passed'])
        self.assertEqual(gate.digest(self.dest/self.artifact.name),gate.digest(self.artifact))
        self.assertTrue((self.dest/'RELEASE-ACCEPTANCE.json').is_file())

    def test_missing_native_evidence_blocks(self):
        (self.run/'native-fullscreen.json').unlink();self.blocked()

    def test_missing_competition_evidence_blocks(self):
        for kind in gate.competition.KINDS:
            (self.run/(kind+'.json')).unlink();self.blocked();self.write_reports()

    def test_missing_failed_skipped_duplicate_and_zero_assertions_block(self):
        cases=self.reports['regressions']['cases']
        for mutation in ('missing','failed','skipped','duplicate','zero','nonzero_exit'):
            original=json.loads(json.dumps(cases))
            if mutation=='missing':cases.pop()
            elif mutation=='duplicate':cases[-1]=cases[0]
            else:cases[0].update({'failed':{'status':'failed'},'skipped':{'status':'skipped'},'zero':{'assertions':0},'nonzero_exit':{'exit_code':1}}[mutation])
            self.write_reports();self.blocked();cases[:]=original

    def test_old_other_run_and_mock_provider_evidence_block(self):
        row=gate.receipt(self.ctx,'live-models',**self.reports['live-models'])
        for changes in ({'binding':'another-run'},{'created_at':self.ctx['created_at']-1},{'evidence_class':'mock'},{'passed':False}):
            (self.run/'live-models.json').write_text(json.dumps({**row,**changes}),'utf-8');self.blocked()

    def test_source_changes_invalidate_all_acceptance(self):
        (self.source/'code.py').write_text('fixture = 2\n','utf-8');self.blocked()

    def test_artifact_tampering_is_detected(self):
        self.artifact.write_bytes(b'changed')
        self.assertFalse(gate.check(self.run)['passed'])
        with self.assertRaises(ValueError):gate.promote(self.run,self.dest)
        self.assertFalse(self.dest.exists())

    def test_log_and_native_recording_tampering_block(self):
        self.evidence.write_text('different','utf-8');self.blocked()

    def test_expired_or_future_context_blocks(self):
        for stamp in (time.time()-gate.MAX_AGE-10,time.time()+100):
            context={**self.ctx,'created_at':stamp}
            (self.run/'context.json').write_text(json.dumps(context),'utf-8');self.blocked()

    def test_browser_only_or_unstable_fullscreen_blocks(self):
        row=self.reports['native-fullscreen']
        for key,value in (('evidence_class','browser'),('max_scroll_drift_px',32),('samples',0)):
            old=row[key];row[key]=value;self.write_reports();self.blocked();row[key]=old

    def test_missing_model_or_tool_cannot_pass(self):
        row=self.reports['live-models'];row['models'][0]['tool_passed']=False
        self.write_reports();self.blocked()
        row['models'].pop();self.write_reports();self.blocked()

    def test_existing_output_and_existing_run_are_never_overwritten(self):
        self.dest.mkdir();(self.dest/'preserve.txt').write_text('keep','utf-8')
        with self.assertRaises(ValueError):gate.promote(self.run,self.dest)
        self.assertEqual((self.dest/'preserve.txt').read_text(),'keep')
        with self.assertRaises(ValueError):gate.begin(self.source,[self.artifact],self.run,'fixture')

    def test_installed_payload_empty_duplicate_tampered_or_escaping_fails(self):
        folder=self.base/'payload';folder.mkdir();file=folder/'part.txt';file.write_text('original','utf-8')
        row={**gate.descriptor(file),'path':'part.txt'}
        self.assertEqual(verify_payload(folder,{'files':[row]},[]),1)
        for files in ([],[row,row],[{**row,'sha256':'0'*64}]):
            with self.assertRaises(ValueError):verify_payload(folder,{'files':files},[])
        for name in ('../outside','C:/outside','/absolute','bad\\member'):
            with self.assertRaises(ValueError):safe_member(folder,name)

    def test_old_direct_release_entrypoints_exit_before_build(self):
        env=dict(os.environ,PYTHONUTF8='1')
        for command,reason in (([sys.executable,str(ROOT/'installer/build_standalone_release.py')],b'Direct release is disabled'),
                        ([sys.executable,str(ROOT/'installer/build_document_release.py'),'share','--version','fixture','--artifact',str(self.base/'forbidden')],b'Legacy build/share cannot bypass')):
            result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertNotEqual(result.returncode,0)
            self.assertIn(reason,result.stderr)
        self.assertFalse((self.base/'forbidden').exists())

    def test_runner_rejects_zero_assertions_crash_skip_and_timeout(self):
        commands=[("print('PASS')",180),("raise RuntimeError('fixture')",180),
                  ("print('Ran 1 test in 0.1s\\nOK (skipped=1)')",180),
                  ('import time; time.sleep(5)',0.1)]
        for i,(code,timeout) in enumerate(commands):
            row=execute_case([sys.executable,'-c',code],self.base,self.base/f'bad-{i}.log',dict(os.environ),timeout)
            self.assertEqual(row['status'],'failed')


if __name__=='__main__':unittest.main(verbosity=2)
