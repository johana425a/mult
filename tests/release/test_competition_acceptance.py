"""Reject partial journey claims without calling models or operating a desktop."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'installer'))
import competition_acceptance as policy
from competition_fixtures import fixtures


class CompetitionAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.profile=json.loads((ROOT/'upstream/DeepTutor/deeptutor/config/competition-features.json').read_text('utf-8'))
        self.context={'required_models':['gpt','flash','pro'],'artifacts':[{'sha256':'synthetic-hash'}]}
        self.reports=fixtures(self.context,{'path':'synthetic-fixture'},self.profile)

    def check(self,kind):
        policy.verify(kind,self.reports[kind],self.context,lambda _:None,self.profile)

    def test_complete_synthetic_policy_cases_validate(self):
        for kind in policy.KINDS:self.check(kind)

    def test_missing_model_round_cold_start_real_model_and_timing_fail(self):
        original=copy.deepcopy(self.reports['core-flows'])
        for mutation in ('missing','mock','warm','time','zero','backend'):
            self.reports['core-flows']=copy.deepcopy(original);row=self.reports['core-flows']
            if mutation=='missing':row['model_rounds'].pop()
            elif mutation=='mock':row['model_rounds'][0]['real_model']=False
            elif mutation=='warm':row['model_rounds'][0]['start_mode']='warm'
            elif mutation=='time':row['model_rounds'][0]['model_seconds']=-1
            elif mutation=='zero':row['cases'][0]['assertions']=0
            else:row['cases'][0]['interface']='backend-only'
            with self.assertRaises(ValueError):self.check('core-flows')

    def test_sleep_mock_short_gap_wrong_candidate_and_growth_fail_soak(self):
        original=copy.deepcopy(self.reports['mixed-use'])
        for mutation in ('short','gap','candidate','mock','growth','idle'):
            self.reports['mixed-use']=copy.deepcopy(original);row=self.reports['mixed-use']
            if mutation=='short':row['finished_at']-=1
            elif mutation=='gap':row['samples'].pop(20)
            elif mutation=='candidate':row['samples'][0]['artifact_sha256s']=['old']
            elif mutation=='mock':row['evidence_class']='mock'
            elif mutation=='growth':row['unbounded_resource_growth']=True
            else:row['actions']['quiz']=0
            with self.assertRaises(ValueError):self.check('mixed-use')

    def test_local_install_and_retained_program_residue_are_not_acceptance(self):
        row=self.reports['install-lifecycle']
        row['machine_id']=row['build_machine_id']
        with self.assertRaises(ValueError):self.check('install-lifecycle')
        row['machine_id']='other';row['owned_program_removed']=False
        with self.assertRaises(ValueError):self.check('install-lifecycle')

    def test_lost_input_duplicate_or_false_completion_fail(self):
        for key in ('input_preserved','records_preserved','terminated_or_recoverable','no_duplicate_output','no_false_completion'):
            row=self.reports['fault-recovery']['cases'][0];row[key]=False
            with self.assertRaises(ValueError):self.check('fault-recovery')
            row[key]=True

    def test_unverified_visible_feature_or_hidden_core_fail(self):
        row=self.reports['feature-coverage']['features'][0]
        row['steps']['reopen']=False
        with self.assertRaises(ValueError):self.check('feature-coverage')
        row['steps']['reopen']=True;row['enabled']=False
        with self.assertRaises(ValueError):self.check('feature-coverage')


if __name__=='__main__':unittest.main(verbosity=2)
