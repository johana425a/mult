import asyncio
import ast
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from integration.harness_execution import ExecutionClient

class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_forwards_record_operation_without_accepting_unknown_fields(self):
        from integration.harness_bridge import HarnessError
        source=Path(__file__).resolve().parents[2]/'portal/app.py'
        nodes=[node for node in ast.parse(source.read_text('utf-8')).body
            if isinstance(node,ast.AsyncFunctionDef) and node.name in {'workspace_input','internal_surface_tool'}]
        for node in nodes:node.decorator_list=[]
        forwarded=[];authenticated=[]
        class Transport:
            async def native_service(self,method,path,body):
                forwarded.append((method,path,body));return {'accepted':True}
        class Bridge:transport=Transport()
        namespace={'Request':object,'json':json,'HarnessError':HarnessError,
            'authenticate_service':lambda request:authenticated.append(request),'harness_bridge':lambda:Bridge()}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),namespace)
        payload={'owner':'fixture','context_ref':'native-records','surface':'learning-records','name':'learning_records',
            'arguments':{'workspace_id':'ws','action':'save_summary','content':'one'},'call_id':'call-1',
            'operation':{'task_id':'task-a','agent_id':'agent-a','call_id':'call-1'}}
        class Request:
            async def body(self):return json.dumps(payload).encode()
        self.assertEqual(await namespace['internal_surface_tool'](Request()),{'accepted':True})
        self.assertEqual(forwarded[0],('POST','surface-tools/invoke',payload));self.assertEqual(len(authenticated),1)
        payload['unexpected_private_field']='rejected'
        with self.assertRaises(HarnessError):await namespace['internal_surface_tool'](Request())
        self.assertEqual(len(forwarded),1)

    async def test_cancel_during_admission_still_sends_stable_cancellation(self):
        client=ExecutionClient(transport=object());calls=[];started=asyncio.Event()
        async def request(method,path,body=None):
            calls.append((method,path,body))
            if path=='':started.set();await asyncio.Event().wait()
            return {'task':{'status':'cancelled'}}
        client.request=request
        job=asyncio.create_task(client.execute(text='probe',workspace_id='ws',source='chat',task_key='stable',owner='fixture'))
        await started.wait();job.cancel()
        with self.assertRaises(asyncio.CancelledError):await job
        self.assertEqual(calls[-1],('POST','/cancel-admission',{'owner':'fixture','source':'chat','task_key':'stable'}))
    async def test_reconnect_uses_original_id_and_fresh_context(self):
        client=ExecutionClient(transport=object());calls=[]
        task={'id':'task-existing','task_key':'original','surface':'chat','conversation_id':'conversation',
            'native_workspace_id':'ws','status':'interrupted'}
        async def request(method,path,body=None):
            calls.append((method,path,body))
            if path.startswith('?'):return {'tasks':[task]}
            if path.endswith('/resume'):return {'task':{**task,'status':'running'}}
            return {'task':{**task,'status':'completed'},'events':[],'next_seq':3}
        client.request=request
        result=await client.execute(text='继续',workspace_id='ws',source='chat',task_key='new',owner='fixture',
            conversation_id='conversation',surface='chat',interaction={'context_ref':'fresh'})
        self.assertEqual(result['id'],'task-existing')
        self.assertFalse(any(path=='' for _,path,_ in calls))
        self.assertEqual(calls[1][2]['interaction']['context_ref'],'fresh')

if __name__=='__main__':unittest.main()
