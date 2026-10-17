import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'upstream/DeepTutor')]
from integration.harness_turn import _learning_record

class ArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_message_parts_survive_text_projection_and_repeat(self):
        folder=Path(tempfile.mkdtemp(prefix='archive-review-'));records=[]
        def add_record(_books,_type,title,_input,output,metadata):
            row={'id':'record-one','output':output,'metadata':metadata};records.append(row);return {'record':row}
        manager=NS(get_or_create_notebook=lambda *a,**k:{'id':'book-one'},get_records=lambda _:records,add_record=add_record)
        history=[{'role':'user','content':[{'type':'text','text':'原始问题'},{'type':'image','attachment_id':'original-image'}]},
            {'role':'assistant','content':[{'type':'text','text':'原始回答'},{'type':'toolCall','id':'call-1','name':'read','arguments':{'path':'book.pdf'}}]}]
        body={'owner':'fixture','call_id':'once','arguments':{'action':'archive_chat','workspace_id':'workspace','conversation_id':'classroom',
            'history':json.dumps(history,ensure_ascii=False)}}
        with (patch('integration.execution_workspace_binding.owner_workspace_binding'),patch('integration.execution_workspace_binding.native_execution_owner',return_value=NS(id='fixture')),
            patch('deeptutor.multi_user.paths.user_context',return_value=nullcontext()),patch('deeptutor.services.notebook.get_notebook_manager',return_value=manager),
            patch('deeptutor.services.workspace.context.workspace_context',side_effect=lambda value:nullcontext()) as scope,
            patch('deeptutor.services.workspace.get_content_workspace_service',return_value=NS(binding_by_id=lambda _:NS(root=folder)))):
            result=await _learning_record(body);again=await _learning_record(body)
        self.assertEqual(scope.call_count,2);scope.assert_called_with('workspace')
        info=result['archive_snapshot'];data=(folder/info['path']).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),info['sha256'])
        self.assertEqual(json.loads(data)['messages'],history)
        self.assertEqual(info['display_kind'],'text_projection');self.assertTrue(again['reused']);self.assertEqual(len(records),1)
        self.assertIn('原始回答',records[0]['output'])

    async def test_native_history_uses_admitted_workspace_and_rejects_empty_archive(self):
        from contextlib import contextmanager
        from fastapi import HTTPException
        from unittest.mock import AsyncMock
        active=[];records=[];folder=Path(tempfile.mkdtemp(prefix='archive-scope-'))
        @contextmanager
        def scope(value):
            active.append(value)
            try:yield
            finally:active.pop()
        async def messages(_sid):
            self.assertEqual(active,['source-workspace'])
            return [{'role':'user','parts':[{'type':'text','text':'Scoped original question'}]}]
        def manager_factory():
            self.assertEqual(active,['source-workspace'])
            return NS(get_or_create_notebook=lambda *a,**k:{'id':'scoped-book'},get_records=lambda _:records,
                add_record=lambda *a,**k: {'record':{'output':a[4],'metadata':k['metadata']}})
        store=NS(get_messages=AsyncMock(side_effect=messages))
        body={'owner':'fixture','call_id':'scope-once','arguments':{'action':'archive_chat','workspace_id':'source-workspace','conversation_id':'unified_scoped'}}
        with (patch('integration.execution_workspace_binding.owner_workspace_binding'),patch('integration.execution_workspace_binding.native_execution_owner',return_value=NS(id='fixture')),
            patch('deeptutor.multi_user.paths.user_context',return_value=nullcontext()),patch('deeptutor.services.workspace.context.workspace_context',side_effect=scope),
            patch('deeptutor.services.notebook.get_notebook_manager',side_effect=manager_factory),patch('deeptutor.services.session.get_session_store',return_value=store),
            patch('deeptutor.services.workspace.get_content_workspace_service',return_value=NS(binding_by_id=lambda _:NS(root=folder)))):
            result=await _learning_record(body)
            self.assertIn('Scoped original question',result['record']['output'])
            self.assertEqual(result['archive_snapshot']['message_count'],1)
            store.get_messages=AsyncMock(return_value=[])
            with self.assertRaises(HTTPException) as raised:await _learning_record(body)
            self.assertEqual(raised.exception.detail['code'],'chat_history_unavailable')
        self.assertEqual(active,[])

if __name__=='__main__':unittest.main()
