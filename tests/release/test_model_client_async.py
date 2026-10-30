"""SDK initialization yields to task leases and preserves per-loop/model pooling."""
import asyncio
from contextvars import ContextVar
import threading
import unittest
from unittest.mock import patch
from deeptutor.runtime.agentic import client as module

scope = ContextVar('client_test_scope', default='none')

class Handle:
    def __init__(self): self.closed = False
    async def close(self): self.closed = True

class AsyncClients(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self): await module.close_agentic_client_pool()
    def config(self, model='fixture'):
        return module.LLMClientConfig(binding='openai', model=model, api_key='test-only', base_url='http://127.0.0.1:1', wire_api='chat_completions')

    async def test_slow_construction_yields_and_reuses_same_model(self):
        entered, release = threading.Event(), threading.Event(); calls = []
        def build(config, **kwargs):
            calls.append((config.model, scope.get(), threading.get_ident(), kwargs)); entered.set()
            if not release.wait(2): raise AssertionError('Model setup blocked task lease')
            return Handle()
        token = scope.set('test-scope')
        try:
            with patch.object(module, 'load_system_settings', return_value={'disable_ssl_verify': False}), patch.object(module, '_build_openai_client', side_effect=build), patch('deeptutor.services.llm.metrics.instrument_client', side_effect=lambda c, **kw: c):
                task = asyncio.create_task(module.build_openai_client_async(self.config()))
                for _ in range(100):
                    if entered.is_set(): break
                    await asyncio.sleep(.005)
                self.assertTrue(entered.is_set()); self.assertFalse(task.done()); release.set()
                handle = await task
                self.assertIs(await module.build_openai_client_async(self.config()), handle)
                other = await module.build_openai_client_async(self.config('other'))
                self.assertIsNot(handle, other)
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0][:2], ('fixture', 'test-scope'))
                self.assertNotEqual(calls[0][2], threading.get_ident())
                self.assertIs(calls[0][3]['disable_ssl_verify'], False)
        finally: release.set(); scope.reset(token)

    async def test_cancel_cleans_unused_handle_without_publishing(self):
        entered, release = threading.Event(), threading.Event(); handle = Handle()
        def build(*args, **kwargs): entered.set(); release.wait(2); return handle
        with patch.object(module, 'load_system_settings', return_value={'disable_ssl_verify': False}), patch.object(module, '_build_openai_client', side_effect=build), patch('deeptutor.services.llm.metrics.instrument_client', side_effect=lambda c, **kw: c):
            task = asyncio.create_task(module.build_openai_client_async(self.config()))
            try:
                while not entered.is_set(): await asyncio.sleep(.005)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
                release.set()
                for _ in range(100):
                    if handle.closed: break
                    await asyncio.sleep(.005)
                self.assertTrue(handle.closed)
                self.assertEqual(module.agentic_client_pool_size(), 0)
            finally: release.set()

    async def test_concurrent_requests_share_one_published_handle(self):
        handles = []
        def build(*args, **kwargs):
            value = Handle(); handles.append(value); return value
        with patch.object(module, 'load_system_settings', return_value={'disable_ssl_verify': False}), patch.object(module, '_build_openai_client', side_effect=build), patch('deeptutor.services.llm.metrics.instrument_client', side_effect=lambda c, **kw: c):
            values = await asyncio.gather(*(module.build_openai_client_async(self.config()) for _ in range(5)))
            self.assertTrue(all(value is values[0] for value in values))
            await asyncio.sleep(.01)
            self.assertTrue(all(value is values[0] or value.closed for value in handles))
            self.assertEqual(module.agentic_client_pool_size(), 1)

if __name__ == '__main__': unittest.main(verbosity=2)
