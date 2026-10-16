'use strict';

const { app, BrowserWindow, WebContentsView, dialog, ipcMain, shell, protocol, session, net, Tray, Menu, nativeImage } = require('electron');
const { Buffer } = require('node:buffer');
const { spawn } = require('node:child_process');
const tcp = require('node:net');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { isLocalPage, canonicalLocalPage, isOfficialLink, isExternalPage } = require('./policy.cjs');
const { SCHEME, PRIVILEGES, SERVICES, applicationOrigin, forwardRequest, socketUrl, websocketHeaders, sessionFetcher, verifyRetainedCookies, allowApplicationRequest, applicationHeaders } = require('./transport.cjs');
const { MIGRATION_PATH, MIGRATION_HTML, migrateOwnedOriginStorage } = require('./storage-migration.cjs');
const { createBilibiliBridge } = require('./bilibili.cjs');
const { createEmbeddedMediaBridge } = require('./embedded-media.cjs');

protocol.registerSchemesAsPrivileged([{ scheme: SCHEME, privileges: PRIVILEGES }]);

function resolveRoot() {
  const requested = process.argv.find((item) => item.startsWith('--install-root='));
  const candidates = [requested && requested.slice('--install-root='.length), path.resolve(__dirname, '..'), path.resolve(__dirname, '..', '..', '..', '..')];
  return candidates.find((candidate) => candidate && fs.existsSync(path.join(candidate, 'scripts', 'desktop_runtime.py')));
}
const root = resolveRoot();
if (!root) throw new Error('DeepSteam installation could not be located.');
const startInBackground = process.argv.includes('--background');
const pythonCandidates = [path.join(root, 'runtime', 'python', 'python.exe'), path.join(root, 'runtime', 'portal-venv', 'Scripts', 'python.exe')];
const python = pythonCandidates.find((candidate) => fs.existsSync(candidate));
if (!python) throw new Error('DeepSteam Python runtime is missing.');
// This product owns its Electron session, never another browser profile.
const storageFile = path.join(root, 'deepsteam-storage.json');
let stateRoot = root;
try { stateRoot = JSON.parse(fs.readFileSync(storageFile, 'utf8').replace(/^\uFEFF/, '')).state_root || root; } catch {}
for (const directory of [path.join(stateRoot, 'runtime', 'desktop-profile'), path.join(stateRoot, 'cache', 'desktop-session'), path.join(stateRoot, 'cache', 'desktop-browser'), path.join(stateRoot, 'cache', 'desktop-temp'), path.join(stateRoot, 'cache', 'desktop-crash'), path.join(stateRoot, 'logs', 'desktop')]) fs.mkdirSync(directory, { recursive: true });
app.setPath('userData', path.join(stateRoot, 'runtime', 'desktop-profile'));
app.setPath('sessionData', path.join(stateRoot, 'cache', 'desktop-session'));
app.setPath('temp', path.join(stateRoot, 'cache', 'desktop-temp'));
app.setPath('crashDumps', path.join(stateRoot, 'cache', 'desktop-crash'));
app.setAppLogsPath(path.join(stateRoot, 'logs', 'desktop'));
process.env.TEMP = path.join(stateRoot, 'cache', 'desktop-temp');
process.env.TMP = process.env.TEMP;
app.commandLine.appendSwitch('disk-cache-dir', path.join(stateRoot, 'cache', 'desktop-browser'));

let window = null;
let closing = false;
let explicitQuit = false;
let tray = null;
let stopped = false;
let lifecycle = null;
let startupStage = 'starting';
let startupAttempt = null;
let servicesStarted = false;
let claimNeedsCleanup = false;
let cancelPageLoad = null;
let workspaceDirectoryDialogPending = false;
let workspaceDirectoryWindowClosing = false;
let uninstallWindowProcess = null;
let applicationStorageReady = false;
let storageMigrationAbort = null;
const migrationContents = new Set();
const workspaceDirectoryGrants = new Map();
const claim = `${process.pid}-${Date.now()}`;
const startupFile = path.join(__dirname, 'starting.html');
const startupURL = pathToFileURL(startupFile).href;
const projectLogs = path.join(stateRoot, 'logs');
function recordCaptionEvent(event, details = {}) {
  // Fixed diagnostic labels only; never log credentials, URLs or caption text.
  const entry = { at: new Date().toISOString(), event, ...details };
  try { fs.appendFileSync(path.join(projectLogs, 'desktop', 'bilibili-events.jsonl'), JSON.stringify(entry) + '\n', 'utf8'); } catch {}
}

// A window close hides the UI; only an explicit quit stops owned services.
function showMainWindow() {
  if (!window || window.isDestroyed()) return;
  if (window.isMinimized()) window.restore();
  window.show();
  window.focus();
}

function requestQuit() {
  explicitQuit = true;
  app.quit();
}

function quitTargetsThisInstall(args) {
  const requested = args.find(item => item.startsWith('--install-root='));
  return args.includes('--quit') && Boolean(requested) &&
    path.resolve(requested.slice('--install-root='.length)).toLowerCase() === path.resolve(root).toLowerCase();
}

function createTray() {
  // Electron supplies these APIs; the guard also permits headless startup tests.
  if (!Tray || !Menu || !nativeImage) return;
  const size = 32;
  const pixels = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const rounded = x >= 5 && x < 27 || y >= 5 && y < 27 ||
      (x - (x < 16 ? 5 : 26)) ** 2 + (y - (y < 16 ? 5 : 26)) ** 2 <= 25;
    if (!rounded) continue;
    const book = y >= 18 && y <= 25 && x >= 7 && x <= 24 && x !== 15 && x !== 16;
    const steam = y >= 7 && y <= 14 && [10, 16, 22].some(cx => x === cx + (y % 4 < 2 ? 0 : 1));
    const color = book || steam ? [244, 240, 232, 255] : [211, 116, 75, 255];
    for (let c = 0; c < 4; c++) pixels[(y * size + x) * 4 + c] = color[c];
  }
  // DeepSteam 2026-10-15: brand icon file; the drawn bitmap stays as a fallback.
  const fileIcon = nativeImage.createFromPath(path.join(__dirname, 'tray.png'));
  tray = new Tray(fileIcon.isEmpty() ? nativeImage.createFromBitmap(pixels, { width: size, height: size }) : fileIcon);
  tray.setToolTip('DeepSteam · 后台任务继续运行');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开 DeepSteam', click: showMainWindow },
    { type: 'separator' },
    { label: '退出并暂停', click: requestQuit },
  ]));
  tray.on('double-click', showMainWindow);
  tray.on('click', showMainWindow);
}

function failureCode(error) {
  if (Number.isInteger(error?.errno)) return `NET_${error.errno}`;
  return /^[A-Z][A-Z0-9_-]{0,47}$/.test(error?.code || '') ? error.code : 'UNKNOWN';
}

function recordStartupFailure(phase, error, port = null) {
  // Never persist stderr, arbitrary error messages, URLs, or stack traces.
  if (!['service_start', 'page_open', 'owned_cleanup'].includes(phase)) return;
  const entry = { timestamp: new Date().toISOString(), phase, port: port === 3792 ? port : null, code: failureCode(error) };
  try { fs.appendFileSync(path.join(projectLogs, 'desktop', 'startup-events.jsonl'), `${JSON.stringify(entry)}\n`, 'utf8'); } catch {}
}

function recordStartupProgress(phase) {
  if (!['service_starting', 'services_ready', 'page_opening', 'page_loaded'].includes(phase)) return;
  const entry = { timestamp: new Date().toISOString(), phase, port: phase.startsWith('page_') ? 3792 : null, code: 'OK' };
  if (phase === 'page_loaded') entry.transport = isFrontendPage(window?.webContents.getURL()) ? 'desktop-scheme' : 'invalid';
  try { fs.appendFileSync(path.join(projectLogs, 'desktop', 'startup-events.jsonl'), `${JSON.stringify(entry)}\n`, 'utf8'); } catch {}
}

function updateStartupStage(stage) {
  if (!['starting', 'opening', 'error-services', 'error-page', 'error-cleanup'].includes(stage)) return;
  startupStage = stage;
  if (window && !window.isDestroyed() && window.webContents.getURL() === startupURL) window.webContents.send('deepsteam:startup-status', stage);
}

// deepsteam:startup-services: which local services already accept connections.
// A row on the startup screen is ticked only when its port really answers.
const STARTUP_SERVICE_PORTS = Object.freeze({ engine: 8011, harness: 3796, classroom: 3793, renderer: 3794, interface: 3792, portal: 3791 });
let startupServiceTimer = null;
let startupServiceStates = {};
function probeStartupPort(port) {
  return new Promise((resolve) => {
    const socket = tcp.connect({ host: '127.0.0.1', port });
    const done = (ok) => { socket.destroy(); resolve(ok); };
    socket.setTimeout(400);
    socket.once('connect', () => done(true));
    socket.once('error', () => done(false));
    socket.once('timeout', () => done(false));
  });
}
function sendStartupServices() {
  if (window && !window.isDestroyed() && window.webContents.getURL() === startupURL) window.webContents.send('deepsteam:startup-services', startupServiceStates);
}
function watchStartupServices() {
  if (startupServiceTimer !== null) return;
  const tick = async () => {
    const entries = await Promise.all(Object.entries(STARTUP_SERVICE_PORTS).map(async ([name, port]) => [name, await probeStartupPort(port)]));
    if (startupServiceTimer === null) return;
    startupServiceStates = Object.fromEntries(entries);
    sendStartupServices();
  };
  startupServiceTimer = setInterval(() => { void tick(); }, 500);
  void tick();
}
function stopStartupServices(allReady) {
  if (startupServiceTimer !== null) clearInterval(startupServiceTimer);
  startupServiceTimer = null;
  if (allReady) { startupServiceStates = Object.fromEntries(Object.keys(STARTUP_SERVICE_PORTS).map(name => [name, true])); sendStartupServices(); }
}

function runLifecycle(action) {
  return new Promise((resolve, reject) => {
    const env = { ...process.env };
    for (const key of Object.keys(env)) if (key.endsWith('_API_KEY') || ['ANTHROPIC_AUTH_TOKEN', 'OPENAI_BASE_URL'].includes(key)) delete env[key];
    const child = spawn(python, ['-I', '-B', path.join(root, 'scripts', 'desktop_runtime.py'), action, '--claim', claim], { cwd: root, env, windowsHide: true, stdio: 'ignore' });
    lifecycle = child;
    child.once('error', (error) => { if (lifecycle === child) lifecycle = null; reject(error); });
    child.once('exit', (code) => { if (lifecycle === child) lifecycle = null; code === 0 ? resolve() : reject(Object.assign(new Error('Local service lifecycle failed.'), { code: Number.isInteger(code) ? `EXIT_${code}` : 'PROCESS_INTERRUPTED' })); });
  });
}

function isFrontendPage(value) {
  return applicationOrigin(value) === 'deepsteam://app';
}

async function migrateApplicationStorage() {
  if (applicationStorageReady) return;
  const origins = Object.entries(SERVICES).filter(([name]) => name !== 'gateway').map(([name, port]) => ({ from: `http://127.0.0.1:${port}`, to: `deepsteam://${name}` }));
  const legacy = new Set(origins.map(item => `${item.from}${MIGRATION_PATH}`));
  // The old-origin migration document is inert and belongs only to this
  // product's existing Electron session. Original browser stores are retained.
  await session.defaultSession.protocol.handle('http', request => {
    if (legacy.has(request.url) && request.method === 'GET') return new Response(MIGRATION_HTML, { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
    return net.fetch(request, { bypassCustomProtocolHandlers: true });
  });
  try {
    storageMigrationAbort = new AbortController();
    await migrateOwnedOriginStorage({ BrowserWindow, session: session.defaultSession, origins,
      loadMigrationDocument: (migrationWindow, origin) => {
        const id = migrationWindow.webContents.id;
        migrationContents.add(id);
        migrationWindow.once('closed', () => migrationContents.delete(id));
        return migrationWindow.loadURL(`${origin}${MIGRATION_PATH}`);
      },
      // HTTP and WebSocket transport deliberately reuse this product's
      // original cookie jar. No authentication token enters renderer storage.
      migrateCookies: verifyRetainedCookies, signal: storageMigrationAbort.signal });
    applicationStorageReady = true;
  } finally { storageMigrationAbort = null; session.defaultSession.protocol.unhandle('http'); }
}

function installApplicationTransport() {
  const fetchOwnedService = sessionFetcher(session.defaultSession);
  session.defaultSession.webRequest.onBeforeRequest({ urls: ['deepsteam://*/*'] }, (details, callback) => {
    callback({ cancel: !allowApplicationRequest(details, window?.webContents, migrationContents, MIGRATION_PATH) });
  });
  protocol.handle(SCHEME, async request => {
    const origin = applicationOrigin(request.url);
    if (origin && new URL(request.url).pathname === MIGRATION_PATH && request.method === 'GET') return new Response(MIGRATION_HTML, { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
    const response=await forwardRequest(request, fetchOwnedService);
    if(request.url==='deepsteam://app/connect')recordCaptionEvent('app_document_response',{status:response.status});
    return response;
  });
  session.defaultSession.webRequest.onBeforeSendHeaders({ urls: ['deepsteam://*/*', 'ws://127.0.0.1/*', 'wss://127.0.0.1/*'] }, async (details, callback) => {
    if (applicationOrigin(details.url)) { callback(applicationHeaders(details, window?.webContents, migrationContents, MIGRATION_PATH)); return; }
    const result = websocketHeaders(details, window?.webContents);
    if (result.cancel) { callback(result); return; }
    try {
      const cookies = await session.defaultSession.cookies.get({ url: details.url.replace(/^ws:/, 'http:') });
      // A pending cookie lookup cannot authorize a replaced/navigated frame.
      if (websocketHeaders(details, window?.webContents).cancel) { callback({ cancel: true }); return; }
      result.requestHeaders.cookie = cookies.map(cookie => `${cookie.name}=${cookie.value}`).join('; ');
      callback(result);
    } catch { callback({ cancel: true }); }
  });
}

// DeepSteam 2026-10-16 transition: the startup art spirals into its center point, then the app fades in.
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
  const activeWindow = window;
  const contents = activeWindow.webContents;
  const target = 'deepsteam://app/connect';
  return new Promise((resolve, reject) => {
    let settled = false;
    let aborted = false;
    let redirectObserved = false;
    let loadingStopped = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(deadline);
      contents.removeListener('did-finish-load', onLoaded);
      contents.removeListener('did-fail-load', onFailed);
      contents.removeListener('did-start-navigation', onNavigation);
      contents.removeListener('did-stop-loading', onStopped);
      if (cancelPageLoad === cancel) cancelPageLoad = null;
      error ? reject(error) : resolve();
    };
    const onLoaded = () => {
      if (isFrontendPage(contents.getURL())) finish();
    };
    const onFailed = (_event, errorCode, _description, _url, isMainFrame) => {
      if (!isMainFrame || errorCode === -3) return;
      finish(Object.assign(new Error('Local page failed to load.'), { errno: errorCode }));
    };
    const onNavigation = (_event, url, _isInPlace, isMainFrame) => {
      if (isMainFrame && isFrontendPage(url)) {
        loadingStopped = false;
        if (url !== target) redirectObserved = true;
      }
    };
    const onStopped = () => {
      loadingStopped = true;
      if (aborted && !contents.isLoadingMainFrame()) finish(Object.assign(new Error('Local navigation was interrupted.'), { code: 'ERR_ABORTED', errno: -3 }));
    };
    const cancel = () => finish(Object.assign(new Error('Desktop closed.'), { code: 'CANCELLED' }));
    // This deadline limits a stuck navigation; it never delays a successful
    // load, and closing the window clears it immediately.
    const deadline = setTimeout(() => finish(Object.assign(new Error('Local page load timed out.'), { code: 'PAGE_LOAD_TIMEOUT' })), 45000);
    cancelPageLoad = cancel;
    contents.on('did-finish-load', onLoaded);
    contents.on('did-fail-load', onFailed);
    contents.on('did-start-navigation', onNavigation);
    contents.on('did-stop-loading', onStopped);
    fadeInFrontend(contents);
    void activeWindow.loadURL(target).then(() => {
      // Electron resolves loadURL only after did-finish-load. Check the actual
      // destination too; a promise result alone cannot bless a remote page.
      if (isFrontendPage(contents.getURL())) finish();
      else finish(Object.assign(new Error('Unexpected page destination.'), { code: 'PAGE_DESTINATION_INVALID' }));
    }).catch((error) => {
      if (settled) return;
      const wasAborted = error?.code === 'ERR_ABORTED' || error?.errno === -3;
      const stillLoading = contents.isLoadingMainFrame();
      if (wasAborted && loadingStopped && !stillLoading) {
        finish(error);
        return;
      }
      if (wasAborted && stillLoading && (redirectObserved || isFrontendPage(contents.getURL()))) {
        // A legal registration/login redirect may cancel the original URL.
        // Its real finish/fail/stop event decides the outcome, without a sleep.
        aborted = true;
        return;
      }
      finish(error);
    });
  });
}

async function showStartupFailure(stage, phase, error, port = null) {
  recordStartupFailure(phase, error, port);
  if (closing || !window || window.isDestroyed()) return false;
  updateStartupStage(stage);
  if (window.webContents.getURL() !== startupURL) {
    try { await window.loadFile(startupFile); }
    catch {
      dialog.showErrorBox('DeepSteam 页面未能打开', '本机页面未能打开。已有数据和模型设置已保留，请重新打开应用或查看本项目日志。');
      return false;
    }
  }
  updateStartupStage(stage);
  return false;
}

function startStartup() {
  if (closing || !window || window.isDestroyed()) return Promise.resolve(false);
  if (startupAttempt) return startupAttempt;
  startupAttempt = Promise.resolve().then(async () => {
    if (!servicesStarted) {
      updateStartupStage('starting');
      if (claimNeedsCleanup) {
        try { await runLifecycle('stop-owned'); claimNeedsCleanup = false; }
        catch (error) { return showStartupFailure('error-cleanup', 'owned_cleanup', error); }
      }
      if (closing) return false;
      claimNeedsCleanup = true;
      recordStartupProgress('service_starting');
      watchStartupServices();
      try { await runLifecycle('start-owned'); servicesStarted = true; stopStartupServices(true); recordStartupProgress('services_ready'); }
      catch (error) { stopStartupServices(false); return showStartupFailure('error-services', 'service_start', error); }
    }
    if (closing || !window || window.isDestroyed()) return false;
    updateStartupStage('opening');
    recordStartupProgress('page_opening');
    try { await migrateApplicationStorage(); await playStartupExit(); await loadHomepage(); recordStartupProgress('page_loaded'); return true; }
    catch (error) {
      if (closing || error?.code === 'CANCELLED') return false;
      return showStartupFailure('error-page', 'page_open', error, 3792);
    }
  }).finally(() => { startupAttempt = null; });
  return startupAttempt;
}

function isStartupSender(event) {
  return !closing && event.sender === window?.webContents && !window.isDestroyed() && event.sender.getURL() === startupURL;
}

function isWorkspaceDirectorySender(event, ownedWindow = window) {
  try {
    if (closing || workspaceDirectoryWindowClosing || !ownedWindow || ownedWindow !== window || ownedWindow.isDestroyed()) return false;
    const contents = ownedWindow.webContents;
    return event.sender === contents && !contents.isDestroyed()
      && event.senderFrame === contents.mainFrame
      && isFrontendPage(contents.getURL()) && isFrontendPage(event.senderFrame?.url);
  } catch { return false; }
}

function openUninstaller(event, ...args) {
  // This capability only opens our fixed confirmation window. It cannot take
  // a path or flags from a renderer, stop services, or authorize deletion.
  if (args.length || !isWorkspaceDirectorySender(event)) return Promise.resolve({ status: 'denied' });
  if (uninstallWindowProcess) return Promise.resolve({ status: 'already-open' });
  const executable = path.join(root, 'Uninstall-DeepSteam.exe');
  try {
    const entry = fs.lstatSync(executable);
    if (!entry.isFile() || entry.isSymbolicLink()
        || path.dirname(fs.realpathSync(executable)).toLowerCase() !== fs.realpathSync(root).toLowerCase()) {
      return Promise.resolve({ status: 'unavailable' });
    }
  } catch { return Promise.resolve({ status: 'unavailable' }); }
  return new Promise((resolve) => {
    try {
      // The native confirmation window needs only ordinary Windows paths, not
      // model keys, endpoint overrides, or other inherited provider settings.
      const env = {};
      const allowed = new Set(['systemroot', 'windir', 'path', 'pathext', 'temp', 'tmp', 'userprofile', 'appdata', 'localappdata', 'programdata', 'homedrive', 'homepath', 'comspec']);
      for (const [key, value] of Object.entries(process.env)) if (allowed.has(key.toLowerCase())) env[key] = value;
      const child = spawn(executable, [], { cwd: root, env, windowsHide: true, stdio: 'ignore', shell: false });
      uninstallWindowProcess = child;
      const clear = () => { if (uninstallWindowProcess === child) uninstallWindowProcess = null; };
      child.once('error', () => { clear(); resolve({ status: 'failed' }); });
      child.once('exit', clear);
      child.once('spawn', () => { child.unref(); resolve({ status: 'opened' }); });
    } catch { uninstallWindowProcess = null; resolve({ status: 'failed' }); }
  });
}

async function pickWorkspaceDirectory(event) {
  if (!isWorkspaceDirectorySender(event) || workspaceDirectoryDialogPending) return null;
  const ownedWindow = window;
  workspaceDirectoryDialogPending = true;
  try {
    const result = await dialog.showOpenDialog(ownedWindow, {
      title: '选择 DeepSteam 工作区文件夹',
      buttonLabel: '选择此文件夹',
      properties: ['openDirectory'],
    });
    // A dialog result cannot grant a capability to a newly navigated page or
    // a window that has started closing. Selection alone changes no files.
    if (!isWorkspaceDirectorySender(event, ownedWindow) || result.canceled || result.filePaths?.length !== 1) return null;
    const selected = result.filePaths[0];
    if (typeof selected !== 'string' || !path.isAbsolute(selected) || !fs.statSync(selected).isDirectory()) return null;
    const directory = path.normalize(selected);
    workspaceDirectoryGrants.set(directory.toLowerCase(), directory);
    return directory;
  } catch {
    return null;
  } finally {
    workspaceDirectoryDialogPending = false;
  }
}

async function openWorkspaceDirectory(event, value) {
  if (!isWorkspaceDirectorySender(event) || typeof value !== 'string' || !path.isAbsolute(value)) return false;
  // The renderer can only reopen a folder selected in this desktop lifetime.
  // A saved workspace from a previous session needs a fresh native selection.
  const directory = workspaceDirectoryGrants.get(path.normalize(value).toLowerCase());
  if (!directory) return false;
  try {
    if (!fs.statSync(directory).isDirectory()) return false;
    return (await shell.openPath(directory)) === '' && isWorkspaceDirectorySender(event);
  } catch { return false; }
}

async function openRegisteredWorkspaceDirectory(event, workspaceId) {
  if (!isWorkspaceDirectorySender(event) || typeof workspaceId !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(workspaceId)) return false;
  const ownedWindow = window;
  try {
    // This token belongs only to DeepSteam's service bridge. It is never sent
    // to the renderer, a model, an external server, or the application log.
    const token = fs.readFileSync(path.join(stateRoot, 'runtime', 'harness-state', 'control-token'), 'utf8').trim();
    if (!/^[A-Za-z0-9_-]{24,200}$/.test(token)) return false;
    const response = await fetch(`http://127.0.0.1:3791/api/harness/internal/workspaces/${encodeURIComponent(workspaceId)}`, {
      headers: { Authorization: `Bearer ${token}` }, redirect: 'error', signal: AbortSignal.timeout(5000),
    });
    if (!response.ok || Number(response.headers.get('content-length') || 0) > 65536) return false;
    const body = await response.text();
    if (body.length > 65536) return false;
    const registration = JSON.parse(body);
    if (registration.workspace_id !== workspaceId || typeof registration.path !== 'string' || !path.isAbsolute(registration.path)) return false;
    if (!isWorkspaceDirectorySender(event, ownedWindow) || !fs.statSync(registration.path).isDirectory()) return false;
    return (await shell.openPath(path.normalize(registration.path))) === '' && isWorkspaceDirectorySender(event, ownedWindow);
  } catch { return false; }
}

async function openOfficial(value) {
  if (!isOfficialLink(value)) return false;
  return openExternalPage(value);
}
async function openExternalPage(value) {
  if (!isExternalPage(value)) return false;
  try { await shell.openExternal(value); return true; }
  catch {
    if (window && !window.isDestroyed()) dialog.showErrorBox('未能打开浏览器', '请检查系统默认浏览器，然后重新点击链接。');
    return false;
  }
}

function makeWindow() {
  const loginPlaceholders = new Set();
  workspaceDirectoryWindowClosing = false;
  window = new BrowserWindow({ width: 1320, height: 900, minWidth: 860, minHeight: 640, title: 'DeepSteam', backgroundColor: '#1c1814', icon: path.join(__dirname, 'icon.png'), show: !startInBackground,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true, allowRunningInsecureContent: false } });
  window.setMenuBarVisibility(false);
  let frontendErrors=0;
  window.webContents.on('console-message', (...args) => {
    const details=args[1];
    const level=typeof details==='object'?details.level:details;
    const message=typeof details==='object'?details.message:args[2];
    if(frontendErrors>=10 || !isFrontendPage(window?.webContents.getURL() || '') || !['error',3].includes(level))return;
    frontendErrors++;
    recordCaptionEvent('frontend_error',{message:String(message).replace(/https?:\/\/\S+/g,'[url]').slice(0,260)});
  });
  window.webContents.on('render-process-gone',(_event,details)=>recordCaptionEvent('renderer_gone',{reason:details.reason,exitCode:details.exitCode}));
  window.webContents.setWindowOpenHandler(({ url }) => {
    // Existing provider cards reserve a blank popup before an async login
    // request. It never receives our preload or displays an external page.
    if (url === 'about:blank' && loginPlaceholders.size < 2) return { action: 'allow', overrideBrowserWindowOptions: { show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, preload: path.join(__dirname, 'oauth-placeholder.cjs') } } };
    if (isExternalPage(url)) void openExternalPage(url);
    else if (isLocalPage(url)) void window.loadURL(canonicalLocalPage(url));
    return { action: 'deny' };
  });
  window.webContents.on('did-create-window', (child) => {
    loginPlaceholders.add(child);
    child.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    const forward = (event, url) => {
      event.preventDefault();
      if (isExternalPage(url)) void openExternalPage(url);
      child.close();
    };
    child.webContents.on('will-navigate', forward);
    child.webContents.on('will-redirect', forward);
    const timeout = setTimeout(() => { if (!child.isDestroyed()) child.close(); }, 120000);
    child.on('closed', () => { clearTimeout(timeout); loginPlaceholders.delete(child); });
  });
  window.webContents.on('will-navigate', (event, url) => {
    const local = canonicalLocalPage(url);
    if (local === url) return;
    event.preventDefault();
    if (local) void window.loadURL(local);
    else if (isExternalPage(url)) void openExternalPage(url);
  });
  window.webContents.on('will-redirect', (event, url) => {
    const local = canonicalLocalPage(url);
    if (local === url) return;
    event.preventDefault();
    if (local) void window.loadURL(local);
  });
  window.webContents.session.setPermissionRequestHandler((contents, permission, callback, details) => {
    if (contents !== window?.webContents || permission !== 'media' || !isLocalPage(details.requestingUrl || contents.getURL()) || !details.mediaTypes?.length || details.mediaTypes.some(type => type !== 'audio')) return callback(false);
    void dialog.showMessageBox(window, { type: 'question', title: 'DeepSteam 麦克风访问', message: '是否允许这次学习使用麦克风？', detail: '仅用于你打开的本机学习页面。', buttons: ['不允许', '允许'], defaultId: 0, cancelId: 0 }).then(({ response }) => callback(response === 1)).catch(() => callback(false));
  });
  window.webContents.session.setPermissionCheckHandler((contents, permission, requestingOrigin) => permission === 'media' && contents === window?.webContents && isLocalPage(requestingOrigin));
  window.webContents.on('did-finish-load', () => { updateStartupStage(startupStage); sendStartupServices(); });
  void window.loadFile(startupFile).catch((error) => recordStartupFailure('page_open', error));
  window.on('close', (event) => {
    if (tray && !explicitQuit) { event.preventDefault(); window.hide(); return; }
    workspaceDirectoryWindowClosing = true;
    storageMigrationAbort?.abort();
    for (const child of loginPlaceholders) if (!child.isDestroyed()) child.close();
  });
  window.on('query-session-end', () => { explicitQuit = true; });
  window.on('closed', () => { workspaceDirectoryGrants.clear(); window = null; });
  return window;
}

if (!app.requestSingleInstanceLock()) app.quit();
else if (process.argv.includes('--quit')) app.quit();
else {
  const { createDomesticMediaBridge } = require('./domestic-media.cjs');
  const domesticMedia = createDomesticMediaBridge({ WebContentsView, getWindow: () => window,
    getBilibiliSession: () => session.defaultSession,
    authorize: isWorkspaceDirectorySender,
    serviceRequest: async (route, options = {}) => {
      const token = fs.readFileSync(path.join(stateRoot, 'runtime', 'harness-state', 'control-token'), 'utf8').trim();
      if (!/^[A-Za-z0-9_-]{24,200}$/.test(token)) throw new Error('INTERNAL_SERVICE_UNAVAILABLE');
      const response = await fetch('http://127.0.0.1:8011' + route, {
        method: options.method || 'GET', redirect: 'error', signal: AbortSignal.timeout(15000),
        headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
        ...(options.body ? { body: JSON.stringify(options.body) } : {}) });
      if (!response.ok) throw new Error('INTERNAL_SERVICE_UNAVAILABLE');
      return response.json();
    } });
  ipcMain.handle('deepsteam:domestic-video', domesticMedia.handle);
  app.on('before-quit', domesticMedia.close);
  if(process.argv.includes('--verify-video-quality'))app.whenReady().then(()=>{
    require('./video-quality-acceptance.cjs').run({BrowserWindow,WebContentsView,session,output:path.join(stateRoot,'logs','desktop','video-quality-acceptance.json')}).catch(()=>{});
  });
  const embeddedMedia = createEmbeddedMediaBridge({ getWindow: () => window, authorize: isWorkspaceDirectorySender, diagnostic: recordCaptionEvent });
  ipcMain.handle('deepsteam:bilibili-playback', embeddedMedia.playback);
  const bilibiliBridge = createBilibiliBridge({ BrowserWindow, getWindow: () => window,
    getSession: () => session.defaultSession, authorize: isWorkspaceDirectorySender,
    diagnostic: recordCaptionEvent,
    serviceRequest: async (route, options = {}) => {
      const token = fs.readFileSync(path.join(stateRoot, 'runtime', 'harness-state', 'control-token'), 'utf8').trim();
      if (!/^[A-Za-z0-9_-]{24,200}$/.test(token)) throw new Error('INTERNAL_SERVICE_UNAVAILABLE');
      const response = await fetch('http://127.0.0.1:8011' + route, {
        method: options.method || 'GET', redirect: 'error', signal: AbortSignal.timeout(15000),
        headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
        ...(options.body ? { body: JSON.stringify(options.body) } : {}) });
      recordCaptionEvent('internal_response', { http_status: response.status });
      if (!response.ok) throw new Error('INTERNAL_SERVICE_UNAVAILABLE');
      return response.json();
    } });
  for (const [channel, action] of [['deepsteam:bilibili-login', bilibiliBridge.openLogin], ['deepsteam:bilibili-subtitles', bilibiliBridge.importSubtitles], ['deepsteam:bilibili-status', bilibiliBridge.sessionStatus]]) {
    ipcMain.handle(channel, async (event, options) => {
      recordCaptionEvent('bridge_request', { channel, authorized: isWorkspaceDirectorySender(event) });
      try {
        const result = await action(event, options);
        recordCaptionEvent('bridge_result', { channel, status: result.status });
        return result;
      } catch {
        recordCaptionEvent('bridge_result', { channel, status: 'request_failed' });
        return { status: 'request_failed' };
      }
    });
  }
  app.on('second-instance', (_event, args = []) => {
    if (quitTargetsThisInstall(args)) requestQuit();
    else if (!args.includes('--background')) showMainWindow();
  });
  ipcMain.handle('deepsteam:open-official', (event, url) => isWorkspaceDirectorySender(event) && openOfficial(url));
  ipcMain.on('deepsteam:websocket-url', (event, value) => { event.returnValue = isWorkspaceDirectorySender(event) ? socketUrl(value) : null; });
  ipcMain.handle('deepsteam:pick-workspace-directory', pickWorkspaceDirectory);
  ipcMain.handle('deepsteam:open-workspace-directory', openWorkspaceDirectory);
  ipcMain.handle('deepsteam:open-registered-workspace-directory', openRegisteredWorkspaceDirectory);
  ipcMain.handle('deepsteam:open-uninstaller', openUninstaller);
  ipcMain.handle('deepsteam:retry-startup', (event) => {
    if (!isStartupSender(event) || startupAttempt || !startupStage.startsWith('error-')) return false;
    void startStartup();
    return true;
  });
  ipcMain.handle('deepsteam:open-startup-logs', async (event) => {
    if (!isStartupSender(event)) return false;
    try { return (await shell.openPath(projectLogs)) === ''; } catch { return false; }
  });
  app.whenReady().then(async () => {
    const cacheVersionFile=path.join(stateRoot,'runtime','video-follow-cache-version');
    if(!fs.existsSync(cacheVersionFile)||fs.readFileSync(cacheVersionFile,'utf8')!=='20261016-domestic-5'){
      await session.defaultSession.clearCache();
      fs.writeFileSync(cacheVersionFile,'20261016-domestic-5');
    }
    installApplicationTransport();
    makeWindow();
    bilibiliBridge.observeSessionChanges(() => {
      if (window && !window.isDestroyed() && isFrontendPage(window.webContents.getURL()))
        window.webContents.send('deepsteam:bilibili-session-changed');
    });
    createTray();
    await startStartup();
  });
  app.on('window-all-closed', () => { if (!tray || explicitQuit) app.quit(); });
  app.on('before-quit', (event) => {
    explicitQuit = true;
    if (stopped) return;
    event.preventDefault();
    if (closing) return;
    closing = true;
    storageMigrationAbort?.abort();
    cancelPageLoad?.();
    if (window && !window.isDestroyed()) window.webContents.stop();
    // Disappear at once; stopping the local services continues in the background.
    if (window && !window.isDestroyed()) window.hide();
    tray?.destroy();
    tray = null;
    // Wait for any in-progress start to record its ownership before cleanup.
    const wait = startupAttempt || Promise.resolve();
    void wait.catch(() => {}).then(() => runLifecycle('stop-owned')).catch(() => {}).finally(() => {
      stopped = true;
      tray?.destroy();
      tray = null;
      app.quit();
    });
  });
}
