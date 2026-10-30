"""Real disk transaction tests with precisely injected Windows rename failures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deeptutor.reading.directory_commit import publish, recover, journal_path, ReadingStorageBusy
from deeptutor.reading import ReadingStore


class ReadingDirectoryCommitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='DeepSteam reading 中文 path ')
        self.root=Path(self.temp.name)
        self.store=ReadingStore(self.root)
        self.mid='a'*16
        self.store.ingest_units(self.mid,filename='original.txt',units=['Original fact 73'],unit='section')
        self.material=self.root/self.mid;self.stage=self.root/'.candidate.staging';self.backup=self.root/'.previous.backup'
        self.stage.mkdir()
        (self.stage/'manifest.json').write_bytes((self.material/'manifest.json').read_bytes())
        (self.stage/'new.txt').write_text('new version',encoding='utf-8')

    def tearDown(self):self.temp.cleanup()

    def test_transient_denial_retries_then_commits_once(self):
        original=Path.replace;attempts=[]
        def replace(src,dst):
            if src==self.stage:
                attempts.append(str(src))
                if len(attempts)<3:raise PermissionError('injected transient Windows sharing lock')
            return original(src,dst)
        with patch.object(Path,'replace',replace),patch('deeptutor.services.file_io.time.sleep'):
            publish(self.material,self.stage,self.backup)
        self.assertEqual(len(attempts),3)
        self.assertEqual((self.material/'new.txt').read_text(),'new version')
        self.assertFalse(self.backup.exists());self.assertFalse(journal_path(self.material).exists())

    def test_persistent_new_version_lock_restores_original(self):
        original=Path.replace
        def replace(src,dst):
            if src==self.stage:raise PermissionError('injected persistent publish lock')
            return original(src,dst)
        with patch.object(Path,'replace',replace),patch('deeptutor.services.file_io.time.sleep'):
            with self.assertRaises(ReadingStorageBusy) as error:publish(self.material,self.stage,self.backup)
        self.assertEqual(error.exception.code,'reading_storage_busy')
        self.assertEqual(self.store.unit_text(self.mid,1),'Original fact 73')
        self.assertFalse(self.backup.exists());self.assertFalse(self.stage.exists())

    def test_double_failure_retains_backup_and_new_store_recovers(self):
        original=Path.replace
        def replace(src,dst):
            if src in (self.stage,self.backup):raise PermissionError('injected publish and rollback lock')
            return original(src,dst)
        with patch.object(Path,'replace',replace),patch('deeptutor.services.file_io.time.sleep'):
            with self.assertRaises(ReadingStorageBusy):publish(self.material,self.stage,self.backup)
        self.assertTrue(self.backup.exists());self.assertTrue(self.stage.exists())
        self.assertEqual((self.backup/'units/0001.txt').read_text('utf-8'),'Original fact 73')
        self.assertTrue(journal_path(self.material).exists())
        reopened=ReadingStore(self.root)
        self.assertEqual(reopened.list_materials()[0].material_id,self.mid)
        self.assertEqual(reopened.unit_text(self.mid,1),'Original fact 73')
        self.assertFalse(self.backup.exists());self.assertFalse(self.stage.exists())
        recover(self.material)
        self.assertEqual(reopened.unit_text(self.mid,1),'Original fact 73')

    def test_current_directory_lock_does_not_remove_original(self):
        original=Path.replace
        def replace(src,dst):
            if src==self.material:raise PermissionError('injected open original directory')
            return original(src,dst)
        with patch.object(Path,'replace',replace),patch('deeptutor.services.file_io.time.sleep'):
            with self.assertRaises(ReadingStorageBusy):publish(self.material,self.stage,self.backup)
        self.assertEqual(self.store.unit_text(self.mid,1),'Original fact 73')

    def test_invalid_journal_never_touches_an_outside_directory(self):
        outside=self.root/'preserve';outside.mkdir();(outside/'keep.txt').write_text('keep')
        journal_path(self.material).write_text(json.dumps({'schema':1,'material':self.mid,'stage':'../preserve',
            'backup':'.previous.backup','diagnostic_id':'fixture'}))
        with self.assertRaisesRegex(Exception,'Invalid reading recovery'):recover(self.material)
        self.assertEqual((outside/'keep.txt').read_text(),'keep')

    def test_normal_refresh_keeps_revision_idempotence(self):
        for i in range(20):
            self.store.ingest_units(self.mid,filename='original.txt',units=[f'Fact {i}'],unit='section')
            self.assertEqual(self.store.unit_text(self.mid,1),f'Fact {i}')
        self.assertFalse(list(self.root.glob('*.replace.json')))


if __name__=='__main__':unittest.main(verbosity=2)
