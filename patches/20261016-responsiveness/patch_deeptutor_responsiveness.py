"""DeepSteam 2026-10-15: DeepTutor responsiveness fixes.

Usage: python patch_deeptutor_responsiveness.py <dir containing the deeptutor package>

1. Workspace registry reads are cached per database file (re-read when the
   file changes or this process writes it). Every scoped request used to open
   the registry several times.
2. A workspace folder that passed the write check stays trusted for 60 s
   instead of creating and deleting a probe file on every request.
3. Codex: a reasoning level the model does not accept (for example "none"
   for gpt-6.1-sol) is mapped to the nearest level the model declares.
4. A message sent right after Stop, or right after an answer finished while
   its title was still being written, waits for that turn to finish instead
   of being rejected as "not sent".
Idempotent: files already carrying the marker are left alone.
"""
import py_compile
import sys
import tempfile
from pathlib import Path

MARK = "DeepSteam 2026-10-15 responsiveness"
MARK2 = "DeepSteam 2026-10-16 titles"


def edit(path, replacements, extra_check=None):
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        print("unchanged", path)
        return
    for old, new in replacements:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{path.name}: anchor found {count} times: {old[:80]!r}")
        text = text.replace(old, new)
    if MARK not in text:
        raise SystemExit(f"{path.name}: marker missing after edit")
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(text)
    py_compile.compile(handle.name, doraise=True)
    Path(handle.name).unlink()
    path.write_text(text, encoding="utf-8", newline="")
    print("patched", path)


def edit2(path, replacements):
    text = path.read_text(encoding="utf-8")
    if MARK2 in text:
        print("unchanged", path)
        return
    for old, new in replacements:
        if text.count(old) != 1:
            raise SystemExit(f"{path.name}: anchor found {text.count(old)} times: {old[:80]!r}")
        text = text.replace(old, new)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(text)
    py_compile.compile(handle.name, doraise=True)
    Path(handle.name).unlink()
    path.write_text(text, encoding="utf-8", newline="")
    print("patched", path)


def main():
    pkg = Path(sys.argv[1]) / "deeptutor"
    if not (pkg / "__init__.py").is_file():
        raise SystemExit(f"not a deeptutor package: {pkg}")

    # ---- 1. registry cache --------------------------------------------------
    edit(pkg / "services/workspace/catalog.py", [
        ("import sqlite3\nfrom typing import TYPE_CHECKING, Any\nimport uuid\n",
         "import sqlite3\nimport threading\nimport time\nfrom typing import TYPE_CHECKING, Any\nimport uuid\n"),
        ('_INTERNAL_DIR = ".deeptutor"\n',
         '_INTERNAL_DIR = ".deeptutor"\n'
         '\n'
         f'# {MARK}: scoped requests read this registry several times each, with a\n'
         '# fresh SQLite connection every time. Keep the raw rows per database file and\n'
         '# read again whenever the file changes or this process writes to it.\n'
         '_CATALOG_CACHE: dict[str, tuple[tuple[int, int], float, list[str], dict[str, str]]] = {}\n'
         '_CATALOG_CACHE_LOCK = threading.Lock()\n'
         '_CATALOG_CACHE_MAX_AGE = 5.0\n'
         '\n'
         '\n'
         'def _catalog_signature(path: Path) -> tuple[int, int] | None:\n'
         '    try:\n'
         '        stat = path.stat()\n'
         '    except OSError:\n'
         '        return None\n'
         '    return (stat.st_mtime_ns, stat.st_size)\n'
         '\n'
         '\n'
         'def _forget_catalog(path: Path) -> None:\n'
         '    with _CATALOG_CACHE_LOCK:\n'
         '        _CATALOG_CACHE.pop(str(path), None)\n'),
        ("""        conn = sqlite3.connect(path, timeout=30)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            with conn:
                yield conn
        finally:
            conn.close()
""", """        conn = sqlite3.connect(path, timeout=30)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            with conn:
                yield conn
        finally:
            changed = conn.total_changes
            conn.close()
            if changed:
                _forget_catalog(path)

    def _catalog_snapshot(self) -> tuple[list[str], dict[str, str]] | None:
        path = self._catalog_file()
        signature = _catalog_signature(path)
        if signature is None:
            return None
        key = str(path)
        now = time.monotonic()
        with _CATALOG_CACHE_LOCK:
            cached = _CATALOG_CACHE.get(key)
        if cached is not None and cached[0] == signature and now - cached[1] < _CATALOG_CACHE_MAX_AGE:
            return cached[2], cached[3]
        with self._catalog_connection() as conn:
            payloads = [row[0] for row in conn.execute("SELECT payload FROM workspaces ORDER BY rowid")]
            metadata = {row[0]: row[1] for row in conn.execute("SELECT key, value FROM metadata")}
        with _CATALOG_CACHE_LOCK:
            _CATALOG_CACHE[key] = (signature, now, payloads, metadata)
        return payloads, metadata
"""),
        ("""        try:
            with self._catalog_connection() as conn:
                rows = [
                    json.loads(row[0])
                    for row in conn.execute("SELECT payload FROM workspaces ORDER BY rowid")
                ]
        except (sqlite3.Error, ValueError) as exc:""", """        try:
            snapshot = self._catalog_snapshot()
            rows = [json.loads(payload) for payload in (snapshot[0] if snapshot else [])]
        except (sqlite3.Error, ValueError) as exc:"""),
        ("""        with self._catalog_connection() as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None
""", """        snapshot = self._catalog_snapshot()
        value = snapshot[1].get(key) if snapshot else None
        return json.loads(value) if value is not None else None
"""),
    ])

    # ---- 2. folder readiness ------------------------------------------------
    edit(pkg / "services/workspace/service.py", [
        ("import tempfile\nfrom typing import Any, Iterable, Mapping\n",
         "import tempfile\nimport time\nfrom typing import Any, Iterable, Mapping\n"),
        ("_SAFE_COMPONENT = re.compile(r\"[^A-Za-z0-9._-]+\")\n",
         "_SAFE_COMPONENT = re.compile(r\"[^A-Za-z0-9._-]+\")\n"
         f"# {MARK}: a folder that passed the write check is trusted for a\n"
         "# minute instead of creating and deleting a probe file on every request.\n"
         "_READY_ROOTS: dict[str, float] = {}\n"
         "_READY_TTL_SECONDS = 60.0\n"),
        ("""        root = binding.root
        if not root.exists() or not root.is_dir():
            raise WorkspaceError("The selected workspace folder does not exist.")
        self._assert_allowed_root(root)
        if not os.access(root, os.R_OK):
            raise WorkspaceError("The selected workspace folder is not readable.")
        output = root / "outputs"
        try:""", """        root = binding.root
        if not root.exists() or not root.is_dir():
            _READY_ROOTS.pop(str(root), None)
            raise WorkspaceError("The selected workspace folder does not exist.")
        self._assert_allowed_root(root)
        checked = _READY_ROOTS.get(str(root))
        if (
            checked is not None
            and time.monotonic() - checked < _READY_TTL_SECONDS
            and (root / "outputs").is_dir()
        ):
            return
        _READY_ROOTS.pop(str(root), None)
        if not os.access(root, os.R_OK):
            raise WorkspaceError("The selected workspace folder is not readable.")
        output = root / "outputs"
        try:"""),
        ("""        except OSError as exc:
            raise WorkspaceError("The workspace outputs folder is not writable.") from exc

    def validate(self, path: str | Path | None) -> dict[str, Any]:""", """        except OSError as exc:
            raise WorkspaceError("The workspace outputs folder is not writable.") from exc
        _READY_ROOTS[str(root)] = time.monotonic()

    def validate(self, path: str | Path | None) -> dict[str, Any]:"""),
    ])

    # ---- 3. Codex reasoning levels -----------------------------------------
    edit(pkg / "services/llm/provider_core/openai_codex_provider.py", [
        ('DEFAULT_ORIGINATOR = "DeepTutor"\n', '''DEFAULT_ORIGINATOR = "DeepTutor"

# %s: callers send "none" to switch reasoning off, but most
# Codex models accept only their own levels and reject the whole request
# ("'none' is not supported with the 'gpt-6.1-sol' model").
_CODEX_EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
_CODEX_OFF_EFFORTS = frozenset({"none", "minimal", "minimum", "off"})


def _declared_codex_levels(model_slug: str) -> list[str] | None:
    try:
        from deeptutor.services.config.model_catalog import get_model_catalog_service

        catalog = get_model_catalog_service().load()
    except Exception:
        return None
    profiles = ((catalog.get("services") or {}).get("llm") or {}).get("profiles") or []
    for profile in profiles:
        if not isinstance(profile, dict) or profile.get("binding") != "openai_codex":
            continue
        for model in profile.get("models") or []:
            if isinstance(model, dict) and model.get("model") == model_slug:
                levels = model.get("codex_supported_reasoning_levels")
                if isinstance(levels, list):
                    return [str(level).strip().lower() for level in levels if str(level).strip()]
    return None


def _codex_reasoning_effort(model_slug: str, requested: str | None) -> str | None:
    """Map a requested level onto one the model declares."""
    if not requested:
        return requested
    effort = str(requested).strip().lower()
    levels = _declared_codex_levels(model_slug)
    if not levels:
        # Unknown support: leave the level out rather than risk "off".
        return None if effort in _CODEX_OFF_EFFORTS else requested
    if effort in levels:
        return effort
    ordered = [level for level in _CODEX_EFFORT_ORDER if level in levels] or levels
    if effort in _CODEX_OFF_EFFORTS or effort not in _CODEX_EFFORT_ORDER:
        return ordered[0]
    rank = _CODEX_EFFORT_ORDER.index(effort)
    lower = [
        level
        for level in ordered
        if level in _CODEX_EFFORT_ORDER and _CODEX_EFFORT_ORDER.index(level) < rank
    ]
    return lower[-1] if lower else ordered[0]
''' % MARK),
        ("""        model_slug = _strip_model_prefix(model_name)
        system_prompt, input_items = convert_messages(messages)
""", """        model_slug = _strip_model_prefix(model_name)
        reasoning_effort = _codex_reasoning_effort(model_slug, reasoning_effort)
        system_prompt, input_items = convert_messages(messages)
"""),
    ])

    # ---- 4a. title generation as its own cancellable task --------------------
    edit(pkg / "services/session/turns/executor.py", [
        ("""                try:
                    await self._maybe_generate_session_title(
                        execution=execution,
                        session_id=session_id,
                        ui_language=str(payload.get("language", "en") or "en"),
                    )
                except Exception:""", f"""                try:
                    # {MARK}: the title runs as its own task so a
                    # message sent right away can take over the session
                    # (start_turn cancels it) instead of being rejected.
                    title_task = asyncio.create_task(
                        self._maybe_generate_session_title(
                            execution=execution,
                            session_id=session_id,
                            ui_language=str(payload.get("language", "en") or "en"),
                        )
                    )
                    execution.title_task = title_task
                    try:
                        await title_task
                    except asyncio.CancelledError:
                        current = asyncio.current_task()
                        if current is not None and current.cancelling():
                            title_task.cancel()
                            raise
                except Exception:"""),
    ])

    # ---- 4b. wait for a finishing turn instead of rejecting -----------------
    edit(pkg / "services/session/turns/request_preparer.py", [
        ("""            if lease is None:
                raise RuntimeError("Session already has an active or recovering turn")
""", """            if lease is None:
                lease = await self._acquire_after_finishing_turn(
                    turn_id,
                    f"{self._coordination_scope}:{session['id']}",
                    session["id"],
                )
            if lease is None:
                raise RuntimeError("Session already has an active or recovering turn")
"""),
        ("""    @workspace_writer
    async def start_turn(
""", f"""    async def _acquire_after_finishing_turn(
        self, turn_id: str, scope: str, session_id: str
    ) -> Any:
        \"\"\"{MARK}: wait briefly for a turn that is only finishing.

        Stop sends ``cancel_turn`` and closes the socket, and the next message
        arrives on a new socket before the stopped turn has unwound. A finished
        answer also keeps its session while the conversation title is written.
        Both used to reject the new message ("not sent"). A turn that is still
        generating its answer is not waited for.
        \"\"\"
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            active = await self.store.get_active_turn(session_id)
            if active is None:
                async with self._lock:
                    tails = [
                        execution
                        for execution in self._executions.values()
                        if execution.session_id == session_id
                    ]
                for execution in tails:
                    title_task = getattr(execution, "title_task", None)
                    if title_task is not None and not title_task.done():
                        title_task.cancel()
            else:
                active_id = str(active.get("id") or active.get("turn_id") or "")
                commands = await self.coordinator.read_commands(active_id) if active_id else []
                if not any(str(command.kind) == "cancel" for _stream_id, command in commands):
                    return None
            await asyncio.sleep(0.05)
            lease = await self.coordinator.acquire_turn(turn_id, scope, self.owner_id)
            if lease is not None:
                return lease
        return None

    @workspace_writer
    async def start_turn(
"""),
    ])


    # ---- 5. local account scope ---------------------------------------------
    edit(pkg / "multi_user/paths.py", [
        ("import threading\nfrom typing import Iterator\n",
         "import threading\nimport time\nfrom typing import Iterator\n"),
        ("""def admin_scope() -> UserScope:
    return UserScope(kind="admin", user_id=LOCAL_ADMIN_ID, root=ADMIN_WORKSPACE_ROOT.resolve())
""", f"""# {MARK}: the local account's root used to be resolved on
# every call (dozens of times per request); resolve it at most once a minute.
_ADMIN_SCOPE_CACHE: tuple[float, UserScope] | None = None


def admin_scope() -> UserScope:
    global _ADMIN_SCOPE_CACHE
    cached = _ADMIN_SCOPE_CACHE
    now = time.monotonic()
    if cached is not None and now - cached[0] < 60.0:
        return cached[1]
    scope = UserScope(kind="admin", user_id=LOCAL_ADMIN_ID, root=ADMIN_WORKSPACE_ROOT.resolve())
    _ADMIN_SCOPE_CACHE = (now, scope)
    return scope
"""),
    ])


    # ---- 6. conversation titles without the reasoning model -------------------
    edit2(pkg / "services/session/turns/title_service.py", [
        ("""            with task_llm_scope(TaskKind.SESSION_TITLE):
                raw_title = await asyncio.wait_for(_collect_title(), timeout=20.0)
""", f"""            # {MARK2}: without a dedicated task model the title
            # used to run on the conversation's own model (often a slow
            # reasoning model, up to 20 s and paid). Use the first message then.
            with task_llm_scope(TaskKind.SESSION_TITLE) as task_config:
                if task_config is None:
                    raw_title = ""
                else:
                    raw_title = await asyncio.wait_for(_collect_title(), timeout=20.0)
"""),
    ])


if __name__ == "__main__":
    main()
