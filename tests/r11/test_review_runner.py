import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('runner',Path(__file__).with_name('run_review_checks.py'))
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def test_full_suite_requires_complete_unique_same_run_and_source(self):
        expected=[str(i) for i in range(10)]
        identity={'run_id':'new','source_tree':'current','python':'fixture','node':'fixture'}
        rows=[{'case':name,'exit_code':0,'status':'passed','identity':identity,'command_sha256':'hash'} for name in expected]
        self.assertTrue(runner.assess(rows,expected,identity)['full_suite_passed'])
        for count in (1,9):
            result=runner.assess(rows[:count],expected,identity)
            self.assertTrue(result['selected_passed']);self.assertFalse(result['passed'])
        for bad in ([],rows+rows[:1],rows+[dict(rows[0],case='unknown')],
                [dict(row,identity={**identity,'source_tree':'old'}) for row in rows[:9]]+rows[9:],
                [dict(rows[0],identity={**identity,'run_id':'old'})]+rows[1:],
                [dict(rows[0],status='skipped')]+rows[1:],[dict(rows[0],exit_code=1)]+rows[1:]):
            self.assertFalse(runner.assess(bad,expected,identity)['full_suite_passed'])


if __name__=='__main__':unittest.main()
