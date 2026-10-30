"""Windows server loop that survives a peer resetting an unfinished accept.

DeepSteam 2026-10-18: keep Proactor subprocess/pipe support. CPython's
default accept failure path closes the listening socket on WinError 64,
leaving a live process that can no longer answer local requests. Only that
peer disconnect is retried; cancellation and other OS failures propagate.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import struct
import sys

LOG = logging.getLogger(__name__)

if sys.platform == "win32":
    import _overlapped
    from asyncio.windows_events import IocpProactor

    class ServerProactor(IocpProactor):
        def _begin_accept(self, listener, connection):
            self._register_with_iocp(listener)
            operation = _overlapped.Overlapped(0)
            operation.AcceptEx(listener.fileno(), connection.fileno())

            def completed(_transferred, _key, pending):
                pending.getresult()
                connection.setsockopt(
                    socket.SOL_SOCKET, _overlapped.SO_UPDATE_ACCEPT_CONTEXT,
                    struct.pack("@P", listener.fileno()),
                )
                connection.settimeout(listener.gettimeout())
                return connection, connection.getpeername()

            return self._register(operation, listener, completed)

        def accept(self, listener):
            async def receive():
                resets = 0
                while True:
                    connection = self._get_accept_socket(listener.family)
                    try:
                        return await self._begin_accept(listener, connection)
                    except OSError as error:
                        connection.close()
                        if getattr(error, "winerror", None) != 64 or listener.fileno() < 0:
                            raise
                        resets += 1
                        if resets == 1 or resets & (resets - 1) == 0:
                            LOG.warning("Local peer disconnected during accept; listener retained (count=%s)", resets)
                        # Avoid spinning under a burst of aborted connections.
                        await asyncio.sleep(min(0.001 * resets, 0.005))
                    except BaseException:
                        connection.close()
                        raise

            return self._loop.create_task(receive())


def server_loop_factory():
    """Uvicorn custom factory; no global policy or bundled library mutation."""
    if sys.platform == "win32":
        return asyncio.ProactorEventLoop(ServerProactor())
    return asyncio.new_event_loop()
