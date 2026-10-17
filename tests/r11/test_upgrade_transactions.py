"""Hard-process-death fixtures; never touch the installed application."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'scripts/transactional_upgrade.py'
spec = importlib.util.spec_from_file_location('upgrade', SOURCE)
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


class TransactionTests(unittest.TestCase):
    def test_protected_and_journal_overlap_rejected_before_staging(self):
        for target, protected in [('data/token.json','data/token.json'),('data','data/token.json'),
                ('data/token.json','data'),('DATA\\token.json','data/token.json')]:
            folder=Path(tempfile.mkdtemp(prefix='upgrade-overlap-'));root=folder/'live';root.mkdir()
            candidate=folder/'candidate';candidate.write_text('new')
            journal=folder/'journal'
            with self.assertRaisesRegex(ValueError,'overlaps preserved'):
                upgrade.prepare(root,journal,[{'path':target,'source':str(candidate)}],[protected])
            self.assertFalse(journal.exists())
        folder=Path(tempfile.mkdtemp(prefix='upgrade-journal-'));root=folder/'live';root.mkdir()
        candidate=folder/'candidate';candidate.write_text('new')
        with self.assertRaisesRegex(ValueError,'journal'):
            upgrade.prepare(root,root/'program'/'transaction',[{'path':'program','source':str(candidate)}])

    def test_protected_change_and_invalid_old_receipt_never_commit_success(self):
        root,journal=self.fixture()
        before=(root/'one.py').read_bytes()
        (root/'user-data.json').write_text('independent edit')
        with self.assertRaisesRegex(ValueError,'before mutation'):upgrade.run(journal)
        self.assertEqual((root/'one.py').read_bytes(),before)
        self.assertEqual(json.loads((journal/'receipt.json').read_text())['status'],'failed_needs_recovery')
        root,journal=self.fixture()
        def changed(_index,phase):
            if phase=='installed_new':(root/'user-data.json').write_text('external change')
        with self.assertRaisesRegex(ValueError,'Preserved'):upgrade.run(journal,after_mutation=changed)
        self.assertNotEqual(json.loads((journal/'receipt.json').read_text())['status'],'applied')
        root,journal=self.fixture();record=json.loads((journal/'receipt.json').read_text())
        record['preserved_before']['one.py']=upgrade.snapshot(root/'one.py');upgrade.atomic(journal/'receipt.json',record)
        with self.assertRaisesRegex(ValueError,'overlaps preserved'):upgrade.run(journal)
        self.assertEqual((root/'one.py').read_text(),'old')

    def fixture(self):
        folder = Path(tempfile.mkdtemp(prefix='ds-upgrade-review-'))
        root, candidate, journal = [folder / name for name in ('live', 'candidate', 'journal')]
        for path in (root, candidate):
            (path / 'program').mkdir(parents=True)
        (root / 'one.py').write_text('old', encoding='utf-8')
        (candidate / 'one.py').write_text('new', encoding='utf-8')
        (root / 'program/old.js').write_text('old tree', encoding='utf-8')
        (candidate / 'program/new.js').write_text('new tree', encoding='utf-8')
        (root / 'user-data.json').write_text('{"record":"unchanged"}', encoding='utf-8')
        upgrade.prepare(root, journal, [{'path': name, 'source': str(candidate / name)} for name in ('one.py', 'program')], ['user-data.json'])
        return root, journal

    def crash(self, folder, phase, rollback=False):
        code = "import importlib.util,os,sys; s=importlib.util.spec_from_file_location('u',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m); m.run(sys.argv[2],rollback=sys.argv[4]=='1',after_mutation=lambda i,p:os._exit(77) if str(i)+':'+p==sys.argv[3] else None)"
        result = subprocess.run([sys.executable, '-c', code, str(SOURCE), str(folder), phase, '1' if rollback else '0'],
            capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 77, result.stderr.decode(errors='replace'))

    def test_apply_recovers_every_actual_mutation_before_status_save(self):
        for phase in ('0:installed_new', '1:moved_old', '1:installed_new'):
            with self.subTest(phase=phase):
                root, journal = self.fixture()
                self.crash(journal, phase)
                upgrade.run(journal)
                self.assertTrue(upgrade.verify(journal)['passed'])
                self.assertEqual((root / 'one.py').read_text(), 'new')
                upgrade.run(journal, rollback=True)
                self.assertTrue(upgrade.verify(journal, rollback=True)['passed'])

    def test_rollback_recovers_each_actual_mutation(self):
        for phase in ('0:removed_new', '0:restored_old', '1:removed_new', '1:restored_old'):
            with self.subTest(phase=phase):
                root, journal = self.fixture()
                upgrade.run(journal)
                self.crash(journal, phase, True)
                upgrade.run(journal, rollback=True)
                self.assertEqual((root / 'one.py').read_text(), 'old')
                self.assertTrue(upgrade.verify(journal, rollback=True)['passed'])

    def test_modified_tree_and_preserved_data_fail_verification(self):
        root, journal = self.fixture()
        upgrade.run(journal)
        (root / 'program/new.js').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'file/tree'):
            upgrade.verify(journal)
        with self.assertRaisesRegex(ValueError, 'unrelated edit'):
            upgrade.run(journal, rollback=True)

    def test_empty_and_overlapping_plans_never_pass(self):
        root, journal = self.fixture()
        record = json.loads((journal / 'receipt.json').read_text())
        record['rows'] = []
        upgrade.atomic(journal / 'receipt.json', record)
        with self.assertRaisesRegex(ValueError, 'Empty'):
            upgrade.verify(journal)


if __name__ == '__main__':
    unittest.main()
