"""Real Windows listener/subprocess checks with explicit accept fault injection."""
import asyncio
from pathlib import Path
import socket
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from integration.server_event_loop import ServerProactor, server_loop_factory


def os_error(code):
    error = OSError("injected accept failure")
    error.winerror = code
    return error


class FaultProactor(ServerProactor):
    def __init__(self, codes=()):
        super().__init__()
        self.codes = list(codes)
        self.connections = []

    def _begin_accept(self, listener, connection):
        self.connections.append(connection)
        if self.codes:
            future = self._loop.create_future()
            future.set_exception(os_error(self.codes.pop(0)))
            return future
        return super()._begin_accept(listener, connection)


class ServerLoopTests(unittest.TestCase):
    def run_case(self, operation, proactor=None):
        factory = server_loop_factory if proactor is None else lambda: asyncio.ProactorEventLoop(proactor)
        with asyncio.Runner(loop_factory=factory) as runner:
            runner.run(operation())

    def test_reset_keeps_real_listener_and_next_client_works(self):
        proactor = FaultProactor([64, 64])

        async def case():
            async def echo(reader, writer):
                writer.write(await reader.readline())
                await writer.drain()
                writer.close()
                await writer.wait_closed()

            async with await asyncio.start_server(echo, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(b"listener survived\n")
                await writer.drain()
                self.assertEqual(await asyncio.wait_for(reader.readline(), 3), b"listener survived\n")
                writer.close()
                await writer.wait_closed()
                self.assertTrue(server.is_serving())
                self.assertEqual(proactor.codes, [])
                self.assertTrue(all(conn.fileno() == -1 for conn in proactor.connections[:2]))
        self.run_case(case, proactor)

    def test_other_os_errors_propagate_without_retry_or_socket_leak(self):
        proactor = FaultProactor([5])

        async def case():
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0)); listener.listen(); listener.setblocking(False)
                with self.assertRaises(OSError) as raised:
                    await proactor.accept(listener)
                self.assertEqual(raised.exception.winerror, 5)
                self.assertEqual(len(proactor.connections), 1)
                self.assertEqual(proactor.connections[0].fileno(), -1)
        self.run_case(case, proactor)

    def test_cancel_pending_accept_closes_accepted_socket(self):
        proactor = FaultProactor()

        async def case():
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0)); listener.listen(); listener.setblocking(False)
                pending = proactor.accept(listener)
                await asyncio.sleep(0.02)
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
                self.assertEqual(len(proactor.connections), 1)
                self.assertEqual(proactor.connections[0].fileno(), -1)
        self.run_case(case, proactor)

    def test_async_subprocess_remains_available(self):
        async def case():
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "-B", "-c", "print('document runtime available')",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            out, err = await asyncio.wait_for(process.communicate(), 10)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(out.strip(), b"document runtime available")
            self.assertEqual(err, b"")
        self.run_case(case)

    def test_real_aborted_connection_burst_then_valid_request(self):
        async def case():
            failures = []
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(lambda _loop, context: failures.append(context))

            class Reply(asyncio.Protocol):
                def connection_made(self, transport):
                    self.transport = transport

                def data_received(self, data):
                    self.transport.write(data)
                    self.transport.close()

            async with await loop.create_server(Reply, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]

                def reset_clients():
                    for _ in range(128):
                        with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
                            client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("HH", 1, 0))

                await asyncio.to_thread(reset_clients)
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(b"healthy"); await writer.drain()
                self.assertEqual(await asyncio.wait_for(reader.read(7), 5), b"healthy")
                writer.close(); await writer.wait_closed()
                self.assertTrue(server.is_serving())
                self.assertFalse([row for row in failures if "Accept failed" in row.get("message", "")
                                  or "never retrieved" in row.get("message", "")], failures)
        self.run_case(case)


if __name__ == "__main__":
    unittest.main(verbosity=2)
