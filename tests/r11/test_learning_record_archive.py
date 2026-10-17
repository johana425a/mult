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
from integration.harness_turn import _learning_record, _source_snapshot

class ArchiveTests(unittest.IsolatedAsyncioTestCase):
    def test_native_snapshot_uses_store_revision_and_authoritative_grant(self):
        from fastapi import HTTPException
        context=NS(runtime=NS(workspace=NS(workspace_id='workspace')),metadata={
            'reading_material_id':'book','source_index':{'s':'Original source text'}})
        manifest=NS(revision=1,source_hash='same-bytes')
        with (patch('integration.execution_workspace_binding.owner_workspace_binding',return_value={'owner':'fixture','path':'original'}) as grant,
                patch('deeptutor.reading.store.ReadingStore',return_value=NS(manifest=lambda _:manifest))):
            old=_source_snapshot(context,'fixture')
            self.assertEqual(_source_snapshot(context,'fixture'),old)
            manifest.revision=2
            self.assertNotEqual(_source_snapshot(context,'fixture'),old)
            context.metadata['reading_material_revision']=1
            with self.assertRaises(HTTPException):_source_snapshot(context,'fixture')
            del context.metadata['reading_material_revision'];manifest.revision=1
            grant.return_value={'owner':'fixture','path':'moved'}
            self.assertNotEqual(_source_snapshot(context,'fixture'),old)
            grant.side_effect=HTTPException(403,'revoked')
            with self.assertRaises(HTTPException):_source_snapshot(context,'fixture')
    async def test_operation_identity_is_task_scoped_persistent_and_argument_bound(self):
        from fastapi import HTTPException
        from copy import deepcopy
        records=[]
        def add(_books,_type,title,_input,output,metadata):
            row={'id':'record-'+str(len(records)),'output':output,'metadata':metadata};records.append(row);return {'record':row}
        def update(_book,record_id,**fields):
            next(row for row in records if row['id']==record_id).update(fields)
        manager=NS(get_or_create_notebook=lambda *a,**k:{'id':'book'},get_records=lambda _:records,add_record=add,update_record=update)
        def body(task,conversation,content):
            return {'owner':'fixture','call_id':'call-1','operation':{'task_id':task,'agent_id':'agent','call_id':'call-1'},
                'arguments':{'workspace_id':'workspace','conversation_id':conversation,'action':'save_summary','content':content}}
        a,b=body('task-a','chat-a','Summary A'),body('task-b','chat-b','Summary B')
        with (patch('integration.execution_workspace_binding.owner_workspace_binding'),patch('integration.execution_workspace_binding.native_execution_owner',return_value=NS(id='fixture')),
            patch('deeptutor.multi_user.paths.user_context',return_value=nullcontext()),patch('deeptutor.services.workspace.context.workspace_context',side_effect=lambda _:nullcontext()),
            patch('deeptutor.services.notebook.get_notebook_manager',return_value=manager)):
            await _learning_record(a);await _learning_record(b)
            self.assertEqual([row['output'] for row in records],['Summary A','Summary B'])
            # Simulate store rehydration: only persisted metadata may deduplicate.
            records[:]=json.loads(json.dumps(records))
            self.assertTrue((await _learning_record(b))['reused'])
            different=deepcopy(b);different['arguments']['content']='Changed'
            with self.assertRaises(HTTPException) as raised:await _learning_record(different)
            self.assertEqual(raised.exception.detail['code'],'record_operation_conflict')
            append=body('task-append','chat-b','Additional');append['arguments'].update(action='append',record_id=records[1]['id'])
            await _learning_record(append);self.assertTrue((await _learning_record(append))['reused'])
            self.assertEqual(records[1]['output'],'Summary B\n\nAdditional')
            changed=deepcopy(append);changed['arguments']['action']='archive_chat'
            with self.assertRaises(HTTPException):await _learning_record(changed)
            legacy=body('ignored','chat-c','Legacy C');del legacy['operation']
            await _learning_record(legacy)
            legacy2=deepcopy(legacy);legacy2['arguments'].update(conversation_id='chat-d',content='Legacy D')
            await _learning_record(legacy2)
            self.assertEqual(len(records),4)
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
