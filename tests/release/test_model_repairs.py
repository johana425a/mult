from pathlib import Path
import sys,unittest,asyncio,importlib.util
from types import SimpleNamespace as NS
APP=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(APP),str(APP/'upstream/DeepTutor')]
from integration.model_failures import invoke_with_recovery,failure_details,ModelExecutionFailure
from deeptutor.services.llm.provider_core.base import LLMResponse
from deeptutor.services.llm.provider_core import openai_compat_provider as module

class Compatibility(unittest.TestCase):
    def test_every_non_mistral_provider_keeps_tool_ids(self):
        for provider in ['openai','deepseek','anthropic','gemini','qwen','kimi','ollama',None]:
            with self.subTest(provider=provider):
                client=object.__new__(module.OpenAICompatProvider);client._spec=NS(name=provider)
                ids=['call_00_abc123def456','toolu_01AbCdEf','functions.read:17']
                messages=[{'role':'assistant','content':None,'tool_calls':[{'id':item,'type':'function','function':{'name':'read','arguments':'{}'}} for item in ids]},*[{'role':'tool','tool_call_id':item,'content':'done'} for item in ids]]
                clean=client._sanitize_messages(messages)
                self.assertEqual([x['id'] for x in clean[0]['tool_calls']],ids)
                self.assertEqual([x['tool_call_id'] for x in clean[1:]],ids)
    def test_mistral_retains_its_specific_id_format(self):
        client=object.__new__(module.OpenAICompatProvider);client._spec=NS(name='mistral')
        messages=[{'role':'assistant','content':None,'tool_calls':[{'id':'call_long_identifier','function':{'name':'read','arguments':'{}'}}]}, {'role':'tool','tool_call_id':'call_long_identifier','content':'ok'}]
        cleaned=client._sanitize_messages(messages)
        self.assertEqual(len(cleaned[0]['tool_calls'][0]['id']),9)
        self.assertEqual(cleaned[0]['tool_calls'][0]['id'],cleaned[1]['tool_call_id'])
    def test_nonstream_response_keeps_provider_id(self):
        response=NS(choices=[NS(finish_reason='tool_calls',message=NS(content=None,tool_calls=[NS(id='call_00_original',function=NS(name='read',arguments='{}'))]))],usage=None)
        client=object.__new__(module.OpenAICompatProvider)
        self.assertEqual(client._parse(response).tool_calls[0].id,'call_00_original')
    def test_stream_response_keeps_provider_id(self):
        tc=NS(index=0,id='call_00_original',function=NS(name='read',arguments='{}'))
        response=NS(choices=[NS(finish_reason='tool_calls',delta=NS(content=None,tool_calls=[tc]))],usage=None)
        self.assertEqual(module.OpenAICompatProvider._parse_chunks([response]).tool_calls[0].id,'call_00_original')

class Recovery(unittest.IsolatedAsyncioTestCase):
    async def test_transient_connection_recovers_without_duplicate_output(self):
        count=0;output=[]
        async def content(value):output.append(value)
        async def request(on_content,on_reasoning):
            nonlocal count;count+=1
            if count==1:return LLMResponse('Error calling LLM: Codex connection failed [ConnectError].',finish_reason='error')
            await on_content('OK');return LLMResponse('OK')
        result=await invoke_with_recovery(request,on_content=content,delays=(0,0))
        self.assertEqual((result.content,count,output),('OK',2,['OK']))
    async def test_no_retry_after_partial_output(self):
        count=0;output=[]
        async def content(value):output.append(value)
        async def request(on_content,on_reasoning):
            nonlocal count;count+=1;await on_content('kept');raise ConnectionError('synthetic disconnect')
        with self.assertRaises(ModelExecutionFailure) as ctx:await invoke_with_recovery(request,on_content=content,delays=(0,0))
        self.assertEqual((count,output),(1,['kept']));self.assertTrue(ctx.exception.details['partial_output'])
    async def test_no_retry_after_reasoning_output(self):
        count=0
        async def request(content,reasoning):
            nonlocal count;count+=1;await reasoning('test metadata');raise TimeoutError()
        with self.assertRaises(ModelExecutionFailure):await invoke_with_recovery(request,delays=(0,0))
        self.assertEqual(count,1)
    async def test_auth_bad_request_quota_and_tls_are_not_retried(self):
        for message in ['HTTP 400 tool identity','HTTP 401 expired','HTTP 429 quota','TLS certificate verification failed']:
            count=0
            async def request(a,b):
                nonlocal count;count+=1;return LLMResponse(message,finish_reason='error')
            with self.assertRaises(ModelExecutionFailure):await invoke_with_recovery(request,delays=(0,0))
            self.assertEqual(count,1)
    async def test_retry_is_bounded_and_error_has_reference(self):
        count=0
        async def request(a,b):
            nonlocal count;count+=1;raise ConnectionError('Bearer private_test_value https://private.test/?token=private')
        with self.assertRaises(ModelExecutionFailure) as ctx:await invoke_with_recovery(request,delays=(0,0))
        self.assertEqual(count,3);self.assertTrue(ctx.exception.details['trace_id'])
        self.assertNotIn('private',str(ctx.exception.details))
    async def test_cancellation_is_terminal(self):
        count=0
        async def request(a,b):
            nonlocal count;count+=1;raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):await invoke_with_recovery(request,delays=(0,0))
        self.assertEqual(count,1)

if __name__=='__main__':unittest.main(verbosity=2)
