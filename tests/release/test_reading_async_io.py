"""Long local transcript reads must not starve live task coordination."""
import asyncio
from contextvars import ContextVar
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from deeptutor.api.routers import reading, reading_extensions

scope = ContextVar('isolated_reading_test_scope', default='wrong')


class ReadingAsyncIOTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_read_yields_to_heartbeat_and_keeps_scope(self):
        started = threading.Event(); release = threading.Event(); seen = []
        def slow_read(material_id):
            seen.append((material_id, scope.get(), threading.get_ident()))
            started.set()
            if not release.wait(2): raise AssertionError('Server heartbeat was starved by disk IO')
            return {'segments': [{'text': '原始字幕'}]}
        token = scope.set('owner-and-workspace')
        try:
            with patch.object(reading, '_read_transcript', side_effect=slow_read):
                job = asyncio.create_task(reading.get_transcript('material'))
                deadline = asyncio.get_running_loop().time() + 1
                while not started.is_set() and asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(.005)
                self.assertTrue(started.is_set())
                release.set()
                value = await job
            self.assertEqual(value['segments'][0]['text'], '原始字幕')
            self.assertEqual(seen[0][:2], ('material', 'owner-and-workspace'))
            self.assertNotEqual(seen[0][2], threading.get_ident())
        finally:
            release.set(); scope.reset(token)

    async def test_permission_denial_is_preserved(self):
        with patch.object(reading, 'assert_learning_material', side_effect=PermissionError('Denied')):
            with self.assertRaises(HTTPException) as raised:
                await reading.get_transcript('material')
        self.assertEqual(raised.exception.status_code, 403)

    async def test_extension_discovery_yields_with_authenticated_scope(self):
        started, release = threading.Event(), threading.Event()
        def discover():
            value = scope.get(); started.set()
            if not release.wait(2): raise AssertionError('Plugin disk scan blocked heartbeat')
            return [{'scope': value}]
        token = scope.set('owner-and-workspace')
        try:
            with patch.object(reading_extensions, '_list_extensions', side_effect=discover):
                task = asyncio.create_task(reading_extensions.list_extensions())
                for _ in range(100):
                    if started.is_set(): break
                    await asyncio.sleep(.005)
                self.assertTrue(started.is_set()); release.set()
                self.assertEqual(await task, [{'scope': 'owner-and-workspace'}])
        finally: release.set(); scope.reset(token)


if __name__ == '__main__': unittest.main(verbosity=2)
