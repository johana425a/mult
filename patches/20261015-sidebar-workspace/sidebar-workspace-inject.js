/* DeepSteam local patch 2026-10-15: sidebar "Add workspace" (Harness-style).
   Injected into the SidebarShell module (63272). Scope names used here:
   a = react/jsx-runtime, d = react, c = next/navigation, f = react-i18next,
   n = workspace-scope (Iu = selectWorkspace), b = Tooltip (Ay), r = webpack require.
   Modules required lazily: 2123 = deepsteam-desktop (am = pick folder, q0 = can pick),
   47579 = workspaces-api (oS = openWorkspaceFolder, Z2 = workspaceChatHref). */
var __dsWsBusy = !1;
function __dsWsText(i18n) {
  var zh = !/^en/i.test(String((i18n && (i18n.resolvedLanguage || i18n.language)) || "zh"));
  if (zh) return { title: "工作区", add: "添加工作区", hint: "打开一个文件夹作为新工作区（Ctrl+O）", busy: "正在添加工作区…", failed: "无法添加工作区：" };
  return { title: "Workspaces", add: "Add workspace", hint: "Open a folder as a new workspace (Ctrl+O)", busy: "Adding workspace…", failed: "Could not add the workspace: " };
}
function __dsWsIcon(p) {
  if (p.busy)
    return (0, a.jsx)("svg", { width: p.size, height: p.size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true", className: "animate-spin", children: (0, a.jsx)("path", { d: "M21 12a9 9 0 1 1-6.219-8.56" }) });
  return (0, a.jsxs)("svg", { width: p.size, height: p.size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: p.strokeWidth || 1.7, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true", children: [
    (0, a.jsx)("path", { d: "M12 10v6" }),
    (0, a.jsx)("path", { d: "M9 13h6" }),
    (0, a.jsx)("path", { d: "M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" }),
  ] });
}
function __dsUseAddWorkspace(onCreated) {
  var tr = (0, f.Bd)(), text = __dsWsText(tr.i18n), router = (0, c.useRouter)();
  var st = (0, d.useState)(!1), busy = st[0], setBusy = st[1];
  var mt = (0, d.useState)(!1), mounted = mt[0], setMounted = mt[1];
  var alive = (0, d.useRef)(!0);
  (0, d.useEffect)(function () { alive.current = !0; setMounted(!0); return function () { alive.current = !1; }; }, []);
  var run = (0, d.useCallback)(async function () {
    if (__dsWsBusy) return;
    var desk = r(2123), api = r(47579);
    if (!desk.q0()) { (0, n.DU)("/settings/workspace", router.push); return; }
    __dsWsBusy = !0; setBusy(!0);
    try {
      var picked = await desk.am();
      if (!picked) return;
      var row = await api.oS(picked);
      if (onCreated) onCreated(row.workspace_id);
      else await (0, n.Iu)(row.workspace_id, api.Z2(row.workspace_id));
    } catch (err) {
      var message = text.failed + (err instanceof Error ? err.message : String(err));
      r.e(3200).then(r.bind(r, 83200)).then(function (m) { m.notify(message, { tone: "error" }); }).catch(function () { window.alert(message); });
    } finally {
      __dsWsBusy = !1;
      if (alive.current) setBusy(!1);
    }
  }, [onCreated, router, text.failed]);
  (0, d.useEffect)(function () {
    function onKey(e) {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && (e.key === "o" || e.key === "O")) { e.preventDefault(); run(); }
    }
    window.addEventListener("keydown", onKey);
    return function () { window.removeEventListener("keydown", onKey); };
  }, [run]);
  return { busy: busy, mounted: mounted, run: run, text: text };
}
function __dsWsHeader(p) {
  var h = __dsUseAddWorkspace(p.onCreated);
  if (!h.mounted) return null;
  return (0, a.jsxs)("div", { "data-ds-workspace-header": "", className: "mb-1 flex items-center gap-1 pl-2 pr-1", children: [
    (0, a.jsx)("span", { className: "min-w-0 flex-1 truncate text-xs text-[var(--muted-foreground)]", children: h.text.title }),
    (0, a.jsx)(b.Ay, { label: h.busy ? h.text.busy : h.text.hint, side: "top", children: (0, a.jsx)("button", {
      type: "button", "aria-label": h.text.add, "aria-keyshortcuts": "Control+O", "aria-busy": h.busy, disabled: h.busy,
      onClick: function () { h.run(); },
      className: "flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-background/60 hover:text-[var(--foreground)] disabled:opacity-60",
      children: (0, a.jsx)(__dsWsIcon, { size: 15, busy: h.busy }),
    }) }),
  ] });
}
function __dsWsRail(p) {
  var h = __dsUseAddWorkspace(p.onCreated);
  if (!h.mounted) return null;
  return (0, a.jsx)(b.Ay, { label: h.busy ? h.text.busy : h.text.hint, side: "right", children: (0, a.jsx)("button", {
    type: "button", "aria-label": h.text.add, "aria-keyshortcuts": "Control+O", "aria-busy": h.busy, disabled: h.busy,
    onClick: function () { h.run(); },
    className: "mb-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-foreground/85 transition-all duration-150 hover:bg-background/60 hover:text-[var(--foreground)] disabled:opacity-60",
    children: (0, a.jsx)(__dsWsIcon, { size: 18, strokeWidth: 1.6, busy: h.busy }),
  }) });
}
