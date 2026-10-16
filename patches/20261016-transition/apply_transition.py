"""DeepSteam 2026-10-16 transition: startup page collapses into its center point, app fades in."""
import sys, pathlib
d = pathlib.Path(sys.argv[1])
MARK = 'DeepSteam 2026-10-16 transition'

# starting.html: exit animation
p = d / 'starting.html'; s = p.read_text(encoding='utf-8')
if MARK not in s:
    css = """
      /* %s: dots spiral back into the center point, the page dissolves. */
      .ds-exit .art { animation: ds-exit-art 900ms cubic-bezier(.6, 0, .2, 1) forwards !important; }
      .ds-exit .masthead, .ds-exit .hero > div:first-child > *, .ds-exit .launch-card, .ds-exit footer { animation: ds-exit-fade 520ms cubic-bezier(.4, 0, 1, 1) forwards !important; }
      .ds-exit .launch-card { animation-delay: 60ms !important; }
      .ds-exit body::before { animation: ds-exit-fade 900ms ease-in forwards !important; }
      @keyframes ds-exit-art { 0%% { transform: none; opacity: 1; filter: none; } 70%% { transform: scale(.06) rotate(220deg); opacity: 1; filter: brightness(1.8); } 100%% { transform: scale(0) rotate(260deg); opacity: 0; filter: brightness(2.4); } }
      @keyframes ds-exit-fade { to { opacity: 0; transform: translateY(-10px) scale(.99); filter: blur(6px); } }
      @media (prefers-reduced-motion: reduce) { .ds-exit main { opacity: 0; } }
""" % MARK
    i = s.index('</style>'); s = s[:i] + css + s[i:]
    p.write_text(s, encoding='utf-8')

# preload.cjs: IPC hook
p = d / 'preload.cjs'; s = p.read_text(encoding='utf-8')
if MARK not in s:
    anchor = "ipcRenderer.on('deepsteam:startup-status',"
    add = "// %s\nipcRenderer.on('deepsteam:startup-exit', () => {\n  if (isStartupDocument()) document.documentElement.classList.add('ds-exit');\n});\n" % MARK
    assert s.count(anchor) == 1; s = s.replace(anchor, add + anchor)
    p.write_text(s, encoding='utf-8')

# main.cjs: play exit before navigating, fade the app in
p = d / 'main.cjs'; s = p.read_text(encoding='utf-8')
if MARK not in s:
    old = "    try { await migrateApplicationStorage(); await loadHomepage(); recordStartupProgress('page_loaded'); return true; }"
    new = """    try { await migrateApplicationStorage(); await playStartupExit(); await loadHomepage(); recordStartupProgress('page_loaded'); return true; }"""
    assert s.count(old) == 1; s = s.replace(old, new)
    old2 = "function loadHomepage() {\n"
    helper = """// %s: the startup art spirals into its center point, then the app fades in.
const APP_FADE_CSS = '@keyframes dsAppIn{from{opacity:0}to{opacity:1}}body{animation:dsAppIn .55s cubic-bezier(.16,1,.3,1) both}';
function playStartupExit() {
  if (closing || !window || window.isDestroyed() || window.webContents.getURL() !== startupURL) return Promise.resolve();
  try { window.webContents.send('deepsteam:startup-exit'); } catch { return Promise.resolve(); }
  return new Promise((resolve) => setTimeout(resolve, 900));
}
function fadeInFrontend(contents) {
  const onReady = () => { if (isFrontendPage(contents.getURL())) contents.insertCSS(APP_FADE_CSS).catch(() => {}); };
  contents.on('dom-ready', onReady);
  setTimeout(() => contents.removeListener('dom-ready', onReady), 15000);
}

function loadHomepage() {
""" % MARK
    assert s.count(old2) == 1; s = s.replace(old2, helper, 1)
    old3 = "    void activeWindow.loadURL(target).then(() => {"
    assert s.count(old3) == 1; s = s.replace(old3, "    fadeInFrontend(contents);\n" + old3)
    p.write_text(s, encoding='utf-8')
print('ok')
