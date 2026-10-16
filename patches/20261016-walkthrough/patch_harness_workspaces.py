"""DeepSteam 2026-10-16 workspace agent fixes for workspaces.mjs (both runtime and integration copies).

1. transcript: only messages the user typed show as "you". The official harness
   also appends internal context as user messages (runtime-context snapshot,
   working-directory notices, approval-policy notices, deferred tool images,
   reminders); they stay in the model context but are not displayed.
2. stop-then-send: a run the user just stopped may still be unwinding; wait for
   it (max 15 s) instead of refusing the next message as busy.
"""
import sys, pathlib
for name in sys.argv[1:]:
    p = pathlib.Path(name); s = p.read_text(encoding='utf-8'); changed = False
    old = """    if (event.type === 'user/message') return { ...base, text: textContent(data.content),
      ...(data.source?.kind ? { source_kind: data.source.kind } : {}) };"""
    new = """    // DeepSteam 2026-10-16 transcript: internal context the harness adds as user
    // messages (runtime-context, working-directory, ...) is not something the user said.
    if (event.type === 'user/message' && data.source?.kind && data.source.kind !== 'user') return null;
    if (event.type === 'user/message') return { ...base, text: textContent(data.content),
      ...(data.source?.kind ? { source_kind: data.source.kind } : {}) };"""
    if 'DeepSteam 2026-10-16 transcript' not in s:
        assert s.count(old) == 1, (name, 'transcript anchor'); s = s.replace(old, new); changed = True
    old2 = "      if (busy.has(sessionId) || agent.status !== 'idle') throw new Error('workspace_session_busy');\n"
    new2 = """      // DeepSteam 2026-10-16 stop-then-send: a run the user just stopped is still
      // unwinding (agent idle wait + session flush). Wait for it instead of refusing.
      if ((busy.has(sessionId) || agent.status !== 'idle') && operations.get(sessionId)?.signal.aborted) {
        const deadline = Date.now() + 15000;
        while ((busy.has(sessionId) || agent.status !== 'idle') && Date.now() < deadline && !signal?.aborted) await new Promise(r => setTimeout(r, 50));
      }
""" + old2
    if 'stop-then-send' not in s:
        assert s.count(old2) == 1, (name, 'busy anchor'); s = s.replace(old2, new2); changed = True
    if changed: p.write_text(s, encoding='utf-8', newline='')
    print(name, 'patched' if changed else 'already patched')
