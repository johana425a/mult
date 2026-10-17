import asyncio
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from integration.harness_execution import ExecutionClient

class ClientTests(unittest.IsolatedAsyncioTestCase):
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
