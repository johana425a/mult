"""Real scoped SQLite import, migration and continuation admission."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.workspace.context import WorkspaceScope, workspace_context


class ImportedWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='DeepSteam import scope ')
        self.root=Path(self.temp.name)
        self.scope=WorkspaceScope('study',self.root,self.root/'study')
        self.scope.content_root.mkdir()
        self.db=self.root/'history.db'
        paths=patch('deeptutor.services.session.sqlite_store.get_path_service',return_value=SimpleNamespace(project_root=self.root,get_chat_history_db=lambda:self.db))
        migration=patch.object(SQLiteSessionStore,'_migrate_legacy_db',lambda *_:None)
        paths.start();migration.start()
        self.addCleanup(paths.stop);self.addCleanup(migration.stop)
        self.messages=[{'role':'user','content':'20, 30, 40'}, {'role':'assistant','content':'Mean is 30'}]

    def tearDown(self):self.temp.cleanup()

    async def test_new_import_is_pinned_and_admits_continuation(self):
        with workspace_context(self.scope):
            store=SQLiteSessionStore(self.db)
            await store.import_session('imported_chatgpt_test','Saved',1,2,{'import':{'source':'chatgpt'}},self.messages)
            row=await store.get_session('imported_chatgpt_test')
            self.assertEqual(row['preferences'].get('workspace_id'),'study')
            result=store._reserve_submission_sync('continue-1','digest','imported_chatgpt_test')
            self.assertEqual(result,'imported_chatgpt_test')

    async def test_old_missing_scope_is_backfilled_without_rewriting_history(self):
        with workspace_context(self.scope):
            store=SQLiteSessionStore(self.db)
            await store.import_session('imported_chatgpt_old','Old',1,2,{'import':{'source':'chatgpt'}},self.messages)
            with store._connect() as conn:
                conn.execute('UPDATE sessions SET preferences_json=? WHERE id=?',(json.dumps({'import':{'source':'chatgpt'},'custom':'keep'}),'imported_chatgpt_old'))
                before=[tuple(x) for x in conn.execute('SELECT * FROM messages ORDER BY id')]
                conn.commit()
            reopened=SQLiteSessionStore(self.db)
            row=await reopened.get_session('imported_chatgpt_old')
            self.assertEqual(row['preferences']['workspace_id'],'study')
            self.assertEqual(row['preferences']['custom'],'keep')
            self.assertEqual((row['title'],row['created_at'],row['updated_at']),('Old',1,2))
            with reopened._connect() as conn:self.assertEqual([tuple(x) for x in conn.execute('SELECT * FROM messages ORDER BY id')],before)
            self.assertEqual(await reopened.migrate_workspace_preferences(),0)

    async def test_explicit_other_scope_is_never_reassigned(self):
        with workspace_context(self.scope):
            store=SQLiteSessionStore(self.db)
            await store.import_session('imported_chatgpt_other','Other',1,2,{'workspace_id':'other','import':{'source':'chatgpt'}},self.messages)
            reopened=SQLiteSessionStore(self.db)
            self.assertEqual((await reopened.get_session('imported_chatgpt_other'))['preferences']['workspace_id'],'other')
            with self.assertRaisesRegex(RuntimeError,'another workspace'):
                reopened._reserve_submission_sync('continue-other','digest','imported_chatgpt_other')

if __name__=='__main__':unittest.main(verbosity=2)
