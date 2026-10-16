'use strict';

// Deterministic Electron/DOM fixtures. No services, network, or credentials.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '..');
const main = fs.readFileSync(path.join(__dirname, 'main.cjs'), 'utf8');
const preload = fs.readFileSync(path.join(__dirname, 'preload.cjs'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, 'starting.html'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

async function desktopFixture(options = {}) {
  const children = [];
  const windows = [];
  const diagnostics = [];
  const events = [];
  const ipc = new Map();
  const openedPaths = [];
  const alerts = [];
  const timers = new Map();
  let timerSequence = 0;
  const app = new EventEmitter();
  let quits = 0;
  Object.assign(app, { setPath() {}, setAppLogsPath() {}, commandLine: { appendSwitch() {} }, requestSingleInstanceLock: () => true, whenReady: () => Promise.resolve(), quit() { quits++; } });
  class TestWindow extends EventEmitter {
    constructor() {
      super(); this.sent = []; this.navigations = []; this.webContents = new EventEmitter();
      const contents = this.webContents;
      contents.currentURL = ''; contents.loading = false;
      contents.getURL = () => contents.currentURL;
      contents.isLoadingMainFrame = () => contents.loading;
      contents.send = (...args) => this.sent.push(args);
      contents.setWindowOpenHandler = () => {};
      contents.stop = () => { contents.loading = false; };
      contents.session = { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} };
      windows.push(this);
    }
    isDestroyed() { return false; }
    setMenuBarVisibility() {}
    loadFile(file) { this.webContents.currentURL = pathToFileURL(file).href; queueMicrotask(() => this.webContents.emit('did-finish-load')); return Promise.resolve(); }
    loadURL(url) {
      this.navigations.push(url);
      if (options.loadURL) return options.loadURL(this.webContents, url, this.navigations.length);
      this.webContents.currentURL = url;
      queueMicrotask(() => this.webContents.emit('did-finish-load'));
      return Promise.resolve();
    }
  }
  const fakeFs = {
    existsSync: file => file === path.join(root, 'scripts', 'desktop_runtime.py') || file === path.join(root, 'runtime', 'python', 'python.exe'),
    readFileSync: () => '{}', mkdirSync() {},
    appendFileSync: (_file, value) => { const entry = JSON.parse(value); events.push(entry); if (entry.code !== 'OK') diagnostics.push(entry); },
  };
  vm.runInNewContext(main, {
    __dirname: options.asar ? path.join(root, 'runtime', 'desktop', 'resources', 'app.asar') : __dirname,
    process: { argv: [], env: { FAKE_API_KEY: 'must-not-inherit' }, pid: 1234 },
    setTimeout: options.fakeTimers ? (callback, milliseconds) => { const id = ++timerSequence; timers.set(id, { callback, milliseconds }); return id; } : setTimeout,
    clearTimeout: options.fakeTimers ? id => timers.delete(id) : clearTimeout,
    URL, AbortController,
    require(module) {
      if (module === 'electron') return {
        app, BrowserWindow: TestWindow, protocol: { registerSchemesAsPrivileged() {}, handle() {} }, session: { defaultSession: { protocol: { handle() {}, unhandle() {} }, webRequest: { onBeforeRequest() {}, onBeforeSendHeaders() {} } } }, net: { fetch() {} }, dialog: { showErrorBox: (...args) => alerts.push(args) },
        ipcMain: { handle: (name, handler) => ipc.set(name, handler), on: (name, handler) => ipc.set(name, handler) },
        shell: { openExternal() {}, openPath: async value => { openedPaths.push(value); return ''; } },
      };
      if (module === './storage-migration.cjs') return { MIGRATION_PATH: '/__fixture__', MIGRATION_HTML: '', migrateOwnedOriginStorage: async () => {} };
      if (module === 'node:child_process') return { spawn: (_program, args, config) => { const child = new EventEmitter(); child.args = args; child.config = config; children.push(child); return child; } };
      if (module === 'node:fs') return fakeFs;
      if (module === './policy.cjs') return require('./policy.cjs');
      return require(module);
    },
  });
  await flush();
  return { app, children, window: windows[0], diagnostics, events, ipc, openedPaths, alerts, timers, quits: () => quits };
}

function eventFor(fixture) { return { sender: fixture.window.webContents }; }
function stages(fixture) { return fixture.window.sent.map(([, stage]) => stage); }
async function startServices(fixture, code = 0) { fixture.children[0].emit('exit', code); await flush(); }

test('startup waits for the actual service result, works from app.asar, and inherits no API key', async () => {
  const fixture = await desktopFixture({ asar: true });
  assert.equal(fixture.window.navigations.length, 0);
  assert.equal(stages(fixture).includes('opening'), false);
  assert.equal(fixture.children[0].config.env.FAKE_API_KEY, undefined);
  assert.equal(fixture.children[0].config.stdio, 'ignore');
  await startServices(fixture);
  assert.equal(stages(fixture).includes('opening'), true);
  assert.equal(fixture.window.navigations[0], 'deepsteam://app/connect');
  assert.equal(fixture.alerts.length, 0);
  assert.equal(fixture.events.some(entry => entry.phase === 'page_loaded' && entry.port === 3792 && entry.code === 'OK'), true);
});

test('a failed service start is separate from a failed page and diagnostics contain only fixed fields', async () => {
  const fixture = await desktopFixture();
  await startServices(fixture, 1);
  assert.equal(stages(fixture).includes('error-services'), true);
  assert.equal(fixture.window.navigations.length, 0);
  assert.equal(fixture.events.some(entry => entry.phase === 'page_loaded'), false);
  assert.deepEqual(Object.keys(fixture.diagnostics[0]).sort(), ['code', 'phase', 'port', 'timestamp']);
  assert.equal(fixture.diagnostics[0].phase, 'service_start');
  assert.equal(fixture.diagnostics[0].code, 'EXIT_1');
});

test('a real page failure remains visible without reporting a service failure', async () => {
  const fixture = await desktopFixture({ loadURL: () => Promise.reject(Object.assign(new Error('https://secret.test/?api_key=not-for-logs'), { code: 'ERR_CONNECTION_REFUSED', errno: -102 })) });
  await startServices(fixture);
  assert.equal(stages(fixture).includes('error-page'), true);
  assert.equal(stages(fixture).includes('error-services'), false);
  assert.equal(fixture.diagnostics[0].phase, 'page_open');
  assert.equal(fixture.diagnostics[0].port, 3792);
  assert.equal(fixture.diagnostics[0].code, 'NET_-102');
  assert.doesNotMatch(JSON.stringify(fixture.diagnostics), /secret|api_key|https|stack/);
  assert.equal(fixture.alerts.length, 0);
  assert.equal(fixture.events.some(entry => entry.phase === 'page_loaded'), false);
});

test('ERR_ABORTED is accepted only when an observed local login redirect actually finishes', async () => {
  const fixture = await desktopFixture({ loadURL: contents => {
    contents.loading = true;
    contents.emit('did-start-navigation', {}, 'deepsteam://app/register', false, true);
    setImmediate(() => {
      contents.currentURL = 'deepsteam://app/register';
      contents.emit('did-finish-load');
      contents.loading = false;
      contents.emit('did-stop-loading');
    });
    return Promise.reject(Object.assign(new Error('aborted'), { code: 'ERR_ABORTED', errno: -3 }));
  } });
  await startServices(fixture); await flush();
  assert.equal(stages(fixture).some(stage => stage.startsWith('error-')), false);
  assert.equal(fixture.window.webContents.getURL(), 'deepsteam://app/register');
  assert.equal(fixture.diagnostics.length, 0);
  assert.equal(fixture.alerts.length, 0);
  assert.equal(fixture.events.some(entry => entry.phase === 'page_loaded'), true);
});

test('ERR_ABORTED without a successful local navigation is a real visible failure', async () => {
  const fixture = await desktopFixture({ loadURL: () => Promise.reject(Object.assign(new Error('aborted'), { code: 'ERR_ABORTED', errno: -3 })) });
  await startServices(fixture);
  assert.equal(stages(fixture).includes('error-page'), true);
  assert.equal(fixture.diagnostics[0].code, 'NET_-3');
});

test('a redirected main-frame load that fails is not hidden behind ERR_ABORTED', async () => {
  const fixture = await desktopFixture({ loadURL: contents => {
    contents.loading = true;
    contents.emit('did-start-navigation', {}, 'deepsteam://app/login', false, true);
    setImmediate(() => contents.emit('did-fail-load', {}, -102, 'do not log raw errors', 'deepsteam://app/login', true));
    return Promise.reject(Object.assign(new Error('aborted'), { code: 'ERR_ABORTED', errno: -3 }));
  } });
  await startServices(fixture); await flush();
  assert.equal(stages(fixture).includes('error-page'), true);
  assert.equal(fixture.diagnostics[0].code, 'NET_-102');
});

test('a redirected load that stops without finish remains a failure', async () => {
  const fixture = await desktopFixture({ loadURL: contents => {
    contents.loading = true;
    contents.emit('did-start-navigation', {}, 'deepsteam://app/login', false, true);
    setImmediate(() => { contents.loading = false; contents.emit('did-stop-loading'); });
    return Promise.reject(Object.assign(new Error('aborted'), { code: 'ERR_ABORTED', errno: -3 }));
  } });
  await startServices(fixture); await flush();
  assert.equal(stages(fixture).includes('error-page'), true);
});

test('stop-before-ERR_ABORTED-rejection immediately shows a recoverable error', async () => {
  const fixture = await desktopFixture({ loadURL: contents => {
    contents.loading = true;
    contents.emit('did-start-navigation', {}, 'deepsteam://app/login', false, true);
    contents.loading = false;
    contents.emit('did-stop-loading');
    return Promise.reject(Object.assign(new Error('aborted'), { code: 'ERR_ABORTED', errno: -3 }));
  } });
  await startServices(fixture);
  assert.equal(stages(fixture).includes('error-page'), true);
  assert.equal(fixture.diagnostics[0].code, 'NET_-3');
  assert.equal(fixture.events.some(entry => entry.phase === 'page_loaded'), false);
  assert.equal(fixture.ipc.get('deepsteam:retry-startup')(eventFor(fixture)), true);
  await flush();
  assert.equal(fixture.children.length, 1);
});

test('finish-before-ERR_ABORTED-rejection remains a successful actual local load', async () => {
  const fixture = await desktopFixture({ loadURL: contents => {
    contents.loading = true;
    contents.emit('did-start-navigation', {}, 'deepsteam://app/login', false, true);
    contents.currentURL = 'deepsteam://app/login';
    contents.emit('did-finish-load');
    contents.loading = false;
    contents.emit('did-stop-loading');
    return Promise.reject(Object.assign(new Error('aborted'), { code: 'ERR_ABORTED', errno: -3 }));
  } });
  await startServices(fixture);
  assert.equal(stages(fixture).some(stage => stage.startsWith('error-')), false);
  assert.equal(fixture.diagnostics.length, 0);
  assert.equal(fixture.events.some(entry => entry.phase === 'page_loaded'), true);
  assert.equal(fixture.window.webContents.getURL(), 'deepsteam://app/login');
});

test('a stuck page load has a bounded deadline and remains retryable without a real wait', async () => {
  const fixture = await desktopFixture({ fakeTimers: true, loadURL: contents => { contents.loading = true; return new Promise(() => {}); } });
  await startServices(fixture);
  const deadline = [...fixture.timers.values()].find(timer => timer.milliseconds === 45000);
  assert.ok(deadline);
  deadline.callback(); await flush();
  assert.equal(stages(fixture).includes('error-page'), true);
  assert.equal(fixture.diagnostics[0].code, 'PAGE_LOAD_TIMEOUT');
  assert.equal(fixture.events.some(entry => entry.phase === 'page_loaded'), false);
  assert.equal(fixture.timers.size, 0);
  assert.equal(fixture.ipc.get('deepsteam:retry-startup')(eventFor(fixture)), true);
  await flush();
  fixture.app.emit('before-quit', { preventDefault() {} }); await flush();
  assert.equal(fixture.timers.size, 0);
  fixture.children[1].emit('exit', 0); await flush();
});

test('service retry is single flight and cleans its own failed claim before starting again', async () => {
  const fixture = await desktopFixture();
  await startServices(fixture, 1);
  const retry = fixture.ipc.get('deepsteam:retry-startup');
  assert.equal(retry(eventFor(fixture)), true);
  assert.equal(retry(eventFor(fixture)), false);
  await flush();
  assert.equal(fixture.children[1].args[3], 'stop-owned');
  fixture.children[1].emit('exit', 0); await flush();
  assert.equal(fixture.children[2].args[3], 'start-owned');
  assert.equal(fixture.children[2].args[5], fixture.children[0].args[5]);
  fixture.children[2].emit('exit', 0); await flush();
  assert.equal(fixture.window.navigations.length, 1);
});

test('failed ownership cleanup prevents a retry from starting another service set', async () => {
  const fixture = await desktopFixture();
  await startServices(fixture, 1);
  fixture.ipc.get('deepsteam:retry-startup')(eventFor(fixture)); await flush();
  fixture.children[1].emit('exit', 1); await flush();
  assert.equal(fixture.children.length, 2);
  assert.equal(stages(fixture).includes('error-cleanup'), true);
});

test('page retry does not start or stop services that are already ready', async () => {
  const fixture = await desktopFixture({ loadURL: (contents, url, attempt) => {
    if (attempt === 1) return Promise.reject(Object.assign(new Error('failure'), { errno: -102 }));
    contents.currentURL = url; queueMicrotask(() => contents.emit('did-finish-load')); return Promise.resolve();
  } });
  await startServices(fixture);
  assert.equal(fixture.ipc.get('deepsteam:retry-startup')(eventFor(fixture)), true);
  await flush();
  assert.equal(fixture.children.length, 1);
  assert.equal(fixture.window.navigations.length, 2);
});

test('closing cancels page recovery and shutdown uses the same owned claim', async () => {
  const fixture = await desktopFixture({ loadURL: contents => { contents.loading = true; return new Promise(() => {}); } });
  await startServices(fixture);
  fixture.app.emit('before-quit', { preventDefault() {} }); await flush();
  assert.equal(fixture.diagnostics.length, 0);
  assert.equal(fixture.children[1].args[3], 'stop-owned');
  assert.equal(fixture.children[1].args[5], fixture.children[0].args[5]);
  assert.equal(fixture.ipc.get('deepsteam:retry-startup')(eventFor(fixture)), false);
  fixture.children[1].emit('exit', 0); await flush();
  assert.equal(fixture.quits(), 1);
});

test('closing during service startup waits for its ownership journal then stops only that claim', async () => {
  const fixture = await desktopFixture();
  fixture.app.emit('before-quit', { preventDefault() {} });
  assert.equal(fixture.children.length, 1);
  await startServices(fixture);
  assert.equal(fixture.window.navigations.length, 0);
  assert.equal(fixture.children[1].args[3], 'stop-owned');
  fixture.children[1].emit('exit', 0); await flush();
});

test('log opening accepts only the packaged startup window and never a caller-supplied path', async () => {
  const fixture = await desktopFixture();
  await startServices(fixture, 1);
  const openLogs = fixture.ipc.get('deepsteam:open-startup-logs');
  assert.equal(await openLogs({ sender: { getURL: () => fixture.window.webContents.getURL() } }), false);
  assert.equal(await openLogs(eventFor(fixture), 'C:/not-our-data'), true);
  assert.deepEqual(fixture.openedPaths, [path.join(root, 'logs')]);
  fixture.window.webContents.currentURL = 'deepsteam://app/connect';
  assert.equal(await openLogs(eventFor(fixture)), false);
});

test('dark startup markup remains accessible, indeterminate and motion respectful', () => {
  assert.match(html, /role="progressbar"/);
  assert.doesNotMatch(html, /aria-valuenow/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /prefers-reduced-motion:\s*reduce/);
  assert.match(html, /color-scheme:\s*dark/);
  assert.match(html, /#1a1918/); assert.match(html, /#242220/); assert.match(html, /#d4734b/);
  assert.match(html, /default-src 'none'; style-src 'unsafe-inline'/);
  assert.doesNotMatch(html, /<script|https?:\/\//);
});

test('preload distinguishes error phases and exposes no retry/log capability to model pages', async () => {
  const { JSDOM } = require(path.join(root, 'upstream', 'DeepTutor', 'web', 'node_modules', 'jsdom', 'lib', 'api.js'));
  const dom = new JSDOM(html, { url: pathToFileURL(path.join(__dirname, 'starting.html')).href });
  let receive; let exposed;
  vm.runInNewContext(preload, { window: dom.window, document: dom.window.document, require: () => ({
    contextBridge: { exposeInMainWorld: (_name, value) => { exposed = value; } },
    ipcRenderer: { on: (_event, handler) => { receive = handler; }, invoke: async () => false },
  }) });
  dom.window.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
  receive({}, 'error-page');
  assert.match(dom.window.document.getElementById('startup-status').textContent, /服务已启动/);
  assert.equal(dom.window.document.getElementById('startup-progress').hidden, true);
  assert.equal(dom.window.document.getElementById('startup-actions').hidden, false);
  assert.equal(dom.window.document.getElementById('startup-retry').disabled, false);
  receive({}, 'starting');
  assert.equal(dom.window.document.getElementById('startup-actions').hidden, true);
  assert.equal(dom.window.document.getElementById('startup-progress').hidden, false);
  receive({}, 'error-services');
  assert.match(dom.window.document.getElementById('startup-status').textContent, /未能完成启动/);
  assert.deepEqual(Object.keys(exposed).sort(), ['openOfficial', 'openRegisteredWorkspaceDirectory', 'openWorkspaceDirectory', 'pickWorkspaceDirectory', 'version', 'webSocketUrl']);
  dom.window.close();
});

function startupDisplayFixture(options = {}) {
  const { JSDOM } = require(path.join(root, 'upstream', 'DeepTutor', 'web', 'node_modules', 'jsdom', 'lib', 'api.js'));
  const dom = new JSDOM(html, { url: options.appPage ? 'deepsteam://app/connect' : pathToFileURL(path.join(__dirname, 'starting.html')).href, pretendToBeVisual: true });
  const timers = new Map();
  const mediaListeners = new Set();
  const media = { matches: !!options.reducedMotion, addEventListener: (_event, callback) => mediaListeners.add(callback) };
  let timerSequence = 0;
  let hidden = false;
  let receive;
  Object.defineProperty(dom.window.document, 'hidden', { get: () => hidden });
  dom.window.matchMedia = () => media;
  dom.window.setInterval = (callback, delay) => { const id = ++timerSequence; timers.set(id, { callback, delay }); return id; };
  dom.window.clearInterval = id => timers.delete(id);
  vm.runInNewContext(preload, { window: dom.window, document: dom.window.document, require: () => ({
    contextBridge: { exposeInMainWorld() {} },
    ipcRenderer: { on: (_event, handler) => { receive = handler; }, invoke: async () => false },
  }) });
  dom.window.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
  return {
    dom, timers, receive,
    element: id => dom.window.document.getElementById(id),
    hidden(value) { hidden = value; dom.window.document.dispatchEvent(new dom.window.Event('visibilitychange')); },
    reducedMotion(value) { media.matches = value; for (const callback of mediaListeners) callback(); },
  };
}

test('startup tips rotate readably without changing or advancing real readiness', () => {
  const fixture = startupDisplayFixture();
  const status = fixture.element('startup-status').textContent;
  const firstTip = fixture.element('startup-tip').textContent;
  assert.equal(fixture.timers.size, 1);
  const timer = [...fixture.timers.values()][0];
  assert.equal(timer.delay, 4200);
  for (let i = 0; i < 20; i++) timer.callback();
  assert.notEqual(fixture.element('startup-tip').textContent, firstTip);
  assert.equal(fixture.element('startup-status').textContent, status);
  assert.equal(fixture.element('startup-step-services').dataset.state, 'active');
  assert.equal(fixture.element('startup-step-page').dataset.state, 'pending');
  assert.equal(fixture.element('startup-progress').hasAttribute('aria-valuenow'), false);
  fixture.receive({}, 'opening');
  assert.equal(fixture.element('startup-step-services').dataset.state, 'complete');
  assert.equal(fixture.element('startup-step-page').getAttribute('aria-current'), 'step');
  assert.equal(fixture.element('startup-phase-label').textContent, '即将进入');
  assert.equal(fixture.timers.size, 1);
  fixture.receive({}, 'untrusted invented stage');
  assert.equal(fixture.element('startup-step-services').dataset.state, 'complete');
  fixture.dom.window.dispatchEvent(new fixture.dom.window.Event('pagehide'));
  assert.equal(fixture.timers.size, 0);
  fixture.dom.window.close();
});

test('hidden, failed and reduced-motion startup pages stop tip timers and resume only when appropriate', () => {
  const fixture = startupDisplayFixture({ reducedMotion: true });
  assert.equal(fixture.timers.size, 0);
  fixture.reducedMotion(false);
  assert.equal(fixture.timers.size, 1);
  fixture.hidden(true);
  assert.equal(fixture.timers.size, 0);
  assert.equal(fixture.dom.window.document.documentElement.dataset.startupPaused, 'true');
  fixture.hidden(false);
  assert.equal(fixture.timers.size, 1);
  fixture.receive({}, 'error-page');
  assert.equal(fixture.timers.size, 0);
  assert.equal(fixture.element('startup-step-services').dataset.state, 'complete');
  assert.equal(fixture.element('startup-progress').hidden, true);
  assert.equal(fixture.element('startup-actions').hidden, false);
  fixture.hidden(false);
  assert.equal(fixture.timers.size, 0);
  fixture.receive({}, 'starting');
  assert.equal(fixture.timers.size, 1);
  assert.equal(fixture.element('startup-step-services').dataset.state, 'active');
  assert.equal(fixture.element('startup-step-page').dataset.state, 'pending');
  fixture.reducedMotion(true);
  assert.equal(fixture.timers.size, 0);
  fixture.dom.window.close();
});

test('startup presentation and timers never activate on application pages', () => {
  const fixture = startupDisplayFixture({ appPage: true });
  fixture.receive({}, 'error-services');
  assert.equal(fixture.timers.size, 0);
  assert.equal(fixture.element('startup-actions').hidden, true);
  assert.equal(fixture.dom.window.document.documentElement.dataset.startupStage, 'starting');
  fixture.dom.window.close();
});
