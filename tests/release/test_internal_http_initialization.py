"""Internal HTTP setup must not block UI polling or disable TLS validation."""
import asyncio
from pathlib import Path
import ssl
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from integration import harness_bridge as bridge


class Client:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.closed = False
    async def __aenter__(self): return self
    async def __aexit__(self, *args): self.closed = True


class InternalInitialization(unittest.IsolatedAsyncioTestCase):
    async def test_slow_certificate_read_does_not_block_heartbeat(self):
        entered, release = threading.Event(), threading.Event()
        token = object(); threads = []; clients = []
        def load():
            threads.append(threading.get_ident()); entered.set()
            if not release.wait(2): raise AssertionError('Server loop blocked')
            return token
        def create(**kwargs):
            client = Client(**kwargs); clients.append(client); return client
        async def request():
            async with bridge._internal_http_client(timeout=20) as client:
                self.assertIs(client.options['verify'], token)
                self.assertIs(client.options['trust_env'], False)
        with patch.object(bridge, '_load_internal_context', side_effect=load), patch.object(bridge.httpx, 'AsyncClient', side_effect=create):
            pending = asyncio.create_task(request())
            try:
                for _ in range(100):
                    if entered.is_set(): break
                    await asyncio.sleep(.005)
                self.assertTrue(entered.is_set())
                self.assertFalse(pending.done()); release.set(); await pending
            finally: release.set()
        self.assertNotEqual(threads[0], threading.get_ident())
        self.assertTrue(clients[0].closed)

    async def test_cancel_during_initialization_opens_no_client(self):
        entered, release = threading.Event(), threading.Event()
        def load():
            entered.set(); release.wait(2); return object()
        async def request():
            async with bridge._internal_http_client(timeout=20): pass
        with patch.object(bridge, '_load_internal_context', side_effect=load), patch.object(bridge.httpx, 'AsyncClient') as create:
            pending = asyncio.create_task(request())
            try:
                while not entered.is_set(): await asyncio.sleep(.005)
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError): await pending
                release.set(); await asyncio.sleep(.01)
                create.assert_not_called()
            finally: release.set()

    async def test_tls_failure_is_not_replaced_with_unverified_client(self):
        with patch.object(bridge, '_load_internal_context', side_effect=ssl.SSLError('bad certificate file')), patch.object(bridge.httpx, 'AsyncClient') as create:
            with self.assertRaises(ssl.SSLError):
                async with bridge._internal_http_client(timeout=20): pass
            create.assert_not_called()

    async def test_verified_context_is_reused_and_certificate_change_invalidates(self):
        bridge._verified_internal_context.cache_clear()
        first, second = object(), object()
        with patch.object(bridge.ssl, 'create_default_context', side_effect=[first, second]) as create:
            self.assertIs(bridge._verified_internal_context('bundle.pem', 1, 10), first)
            self.assertIs(bridge._verified_internal_context('bundle.pem', 1, 10), first)
            self.assertIs(bridge._verified_internal_context('bundle.pem', 2, 10), second)
            self.assertEqual(create.call_count, 2)
            create.assert_called_with(cafile='bundle.pem')
        bridge._verified_internal_context.cache_clear()


if __name__ == '__main__': unittest.main(verbosity=2)
