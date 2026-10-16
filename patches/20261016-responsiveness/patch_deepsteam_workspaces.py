"""DeepSteam 2026-10-16: workspace removal and listing.

Usage: python patch_deepsteam_workspaces.py <DeepSteam root>

1. Renaming, removing and restoring a workspace no longer takes the
   account-wide exclusive data lock (it failed whenever any chat was still
   finishing anywhere). Registry work runs off the event loop and failures
   report their real cause.
2. The portal reuses the learning-service workspace list for a moment instead
   of fetching it once per workspace on every Harness listing.
Idempotent: files already carrying the marker are left alone.
"""
import py_compile
import sys
import tempfile
from pathlib import Path

MARK = "DeepSteam 2026-10-16 workspaces"


def edit(path, replacements):
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        print("unchanged", path)
        return
    for old, new in replacements:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{path.name}: anchor found {count} times: {old[:90]!r}")
        text = text.replace(old, new)
    if MARK not in text:
        raise SystemExit(f"{path.name}: marker missing after edit")
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(text)
    py_compile.compile(handle.name, doraise=True)
    Path(handle.name).unlink()
    path.write_text(text, encoding="utf-8", newline="")
    print("patched", path)


def main():
    root = Path(sys.argv[1]) / "integration"

    provider = root / "deeptutor_shared_provider.py"
    text = provider.read_text(encoding="utf-8")
    start = text.find("        patch = {key: body[key] for key in ('name', 'archived') if key in body}\n")
    end = text.find("    @app.get('/api/contest/internal/workspaces/{workspace_id}')\n")
    if MARK not in text and (start < 0 or end < 0 or end < start):
        raise SystemExit("deeptutor_shared_provider.py: manage block not found")
    old_manage = text[start:end] if MARK not in text else ""
    if old_manage and "with workspace_activity():" not in old_manage:
        raise SystemExit("deeptutor_shared_provider.py: unexpected manage block")
    new_manage = f"""        patch = {{key: body[key] for key in ('name', 'archived') if key in body}}

        def apply_change():
            # {MARK}: renaming, removing and restoring only edit
            # this registry row; folders, chats and answers in progress are
            # left alone. The account-wide exclusive data lock taken here before
            # failed whenever any chat (in any workspace) was still finishing or
            # a background import was running, so a workspace could not be
            # removed after chatting. A pending data-migration recovery still
            # blocks changes, and the registry update is itself transactional.
            check_workspace_recovery()
            service = workspace_service()
            row = next((item for item in service.list_workspaces()
                        if item.get('workspace_id') == workspace_id), None)
            if row is None:
                raise HTTPException(404, {{'code': 'workspace_missing', 'message': 'Workspace not found.'}})
            if row.get('kind') != 'workspace':
                raise HTTPException(403, {{'code': 'workspace_protected',
                    'message': 'System and general workspaces cannot be renamed or removed.'}})
            if expected is not None and (row.get('display_name') != expected['name']
                    or bool(row.get('archived')) != expected['archived']
                    or ('kind' in expected and row.get('kind') != expected['kind'])
                    or ('path' in expected and os.path.normcase(os.path.normpath(row.get('path', '')))
                        != os.path.normcase(os.path.normpath(expected['path'])))):
                raise HTTPException(409, {{'code': 'workspace_revision_changed',
                    'message': 'The workspace state changed. Refresh and retry.'}})
            return {{'workspace': service.update_workspace(workspace_id, **patch)}}

        try:
            return await asyncio.to_thread(apply_change)
        except HTTPException:
            raise
        except Exception as exc:
            from deeptutor.services.workspace.models import WorkspaceError
            message = str(exc).strip() if isinstance(exc, WorkspaceError) else ''
            raise HTTPException(409, {{'code': 'workspace_update_failed',
                'message': message or 'The workspace could not be updated. Retry shortly; files and chats are unchanged.'}}) from None

"""
    edit(provider, [
        ("import hmac\nimport os\n", "import asyncio\nimport hmac\nimport os\n"),
        ("            return {'workspaces': workspace_service().list_workspaces()}\n",
         "            return {'workspaces': await asyncio.to_thread(lambda: workspace_service().list_workspaces())}\n"),
        ("""        row = next((item for item in workspace_service().list_workspaces()
                    if item.get('workspace_id') == workspace_id and not item.get('archived')), None)
""", """        rows = await asyncio.to_thread(lambda: workspace_service().list_workspaces())
        row = next((item for item in rows
                    if item.get('workspace_id') == workspace_id and not item.get('archived')), None)
"""),
        *([(old_manage, new_manage)] if old_manage else []),
    ])

    edit(root / "harness_bridge.py", [
        ("""                    'workspace_catalog_unavailable': 'The workspace directory is temporarily unavailable. Retry shortly.'}
                raise HarnessError(code, messages.get(code, 'The workspace service is temporarily unavailable. Files and sessions are retained.'), response.status_code)
""", f"""                    'workspace_catalog_unavailable': 'The workspace directory is temporarily unavailable. Retry shortly.'}}
                # {MARK}: show the service's own reason when it gives one.
                reason = detail.get('message') if isinstance(detail, dict) else None
                message = messages.get(code) or (reason.strip() if isinstance(reason, str) and reason.strip() else
                    'The workspace service is temporarily unavailable. Files and sessions are retained.')
                raise HarnessError(code, message, response.status_code)
"""),
    ])

    edit(root / "workspace_management.py", [
        ("import asyncio\nfrom copy import deepcopy\nimport os\nimport re\n",
         "import asyncio\nfrom copy import deepcopy\nimport os\nimport re\nimport time\n"),
        ("""class WorkspaceManager:
    def __init__(self, transport):
        self.transport = transport
        self.lock = asyncio.Lock()

    async def native_catalog(self):
        result = await self.transport.native_workspace_service('GET', 'workspaces')
        return [native_row(item) for item in result.get('workspaces', [])]
""", f"""class WorkspaceManager:
    # {MARK}: one Harness listing asks for metadata once per
    # workspace, and every request fetched the whole learning-service list.
    # Share one fetch for a moment; any change made here drops it at once.
    NATIVE_CACHE_SECONDS = 1.5

    def __init__(self, transport):
        self.transport = transport
        self.lock = asyncio.Lock()
        self._native_generation = 0
        self._native_cached = None
        self._native_pending = None

    def forget_native_catalog(self):
        self._native_generation += 1
        self._native_cached = None
        self._native_pending = None

    async def _fetch_native_catalog(self):
        result = await self.transport.native_workspace_service('GET', 'workspaces')
        return [native_row(item) for item in result.get('workspaces', [])]

    async def native_catalog(self):
        generation = self._native_generation
        cached = self._native_cached
        if cached and cached[1] == generation and time.monotonic() - cached[0] < self.NATIVE_CACHE_SECONDS:
            return deepcopy(cached[2])
        pending = self._native_pending
        if pending is None or pending[1] != generation:
            pending = (asyncio.ensure_future(self._fetch_native_catalog()), generation)
            self._native_pending = pending
        task = pending[0]
        try:
            rows = await asyncio.shield(task)
        finally:
            if self._native_pending is pending and task.done():
                self._native_pending = None
        if generation == self._native_generation:
            self._native_cached = (time.monotonic(), generation, rows)
        return deepcopy(rows)
"""),
        ("""        async with self.lock:
            rows = (await self._catalog())['workspaces']
            row = next((item for item in rows if identity in (item['id'], item['native_workspace_id'], item['harness_workspace_id'])), None)
""", """        async with self.lock:
            self.forget_native_catalog()
            rows = (await self._catalog())['workspaces']
            row = next((item for item in rows if identity in (item['id'], item['native_workspace_id'], item['harness_workspace_id'])), None)
"""),
        ("""                if native:
                    await self._native_change(native, patch, native)
""", """                if native:
                    try:
                        await self._native_change(native, patch, native)
                    finally:
                        self.forget_native_catalog()
"""),
        ("""            except HarnessError as error:
                if not host_id or not await self._recover_failed_apply(host_id, transaction_id, error):
                    raise error
""", """            except HarnessError as error:
                self.forget_native_catalog()
                if not host_id or not await self._recover_failed_apply(host_id, transaction_id, error):
                    raise error
"""),
    ])


if __name__ == "__main__":
    main()
