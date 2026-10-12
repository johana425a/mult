'use strict';

// All processes, windows, and installation paths below are fixtures. These
// tests never execute an uninstaller or read the installed user's data.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');
const { pathToFileURL } = require('node:url');
const main = fs.readFileSync(path.join(__dirname, 'main.cjs'), 'utf8');
const preload = fs.readFileSync(path.join(__dirname, 'preload.cjs'), 'utf8');
const root = path.resolve(__dirname, '..');
const uninstallExe = path.join(root, 'Uninstall-DeepSteam.exe');
const flush = () => new Promise(resolve => setImmediate(resolve));

async function fixture(options = {}) {
  const handlers = new Map();
  const children = [];
  const windows = [];
  let quits = 0;
  const app = new EventEmitter();
  Object.assign(app, { setPath() {}, setAppLogsPath() {}, commandLine: { appendSwitch() {} }, requestSingleInstanceLock: () => true, whenReady: () => Promise.resolve(), quit() { quits++; } });
  class Window extends EventEmitter {
    constructor() {
      super(); this.destroyed = false;
      const contents = this.webContents = new EventEmitter();
      contents.currentURL = ''; contents.mainFrame = { url: '' }; contents.destroyed = false;
      contents.getURL = () => contents.currentURL;
      contents.isDestroyed = () => contents.destroyed;
      contents.isLoadingMainFrame = () => false;
      contents.send = () => {}; contents.stop = () => {}; contents.setWindowOpenHandler = () => {};
      contents.session = { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} };
      windows.push(this);
    }
    isDestroyed() { return this.destroyed; }
    setMenuBarVisibility() {}
    loadFile(file) { this.navigate(pathToFileURL(file).href); return Promise.resolve(); }
    loadURL(url) { this.navigate(url); return Promise.resolve(); }
    navigate(url) { this.webContents.currentURL = url; this.webContents.mainFrame.url = url; }
  }
  vm.runInNewContext(main, {
    __dirname, URL, setTimeout, clearTimeout, AbortController, AbortSignal,
    process: { argv: [], pid: 1234, env: { SystemRoot: 'C:\\Windows', TEMP: 'D:\\fixture-temp', PATH: 'fixture-path', OPENAI_API_KEY: 'not-exported', DEEPSEEK_TOKEN: 'not-exported', OPENAI_BASE_URL: 'not-exported' } },
    require(name) {
      if (name === 'electron') return {
        app, BrowserWindow: Window, dialog: {}, shell: {}, net: {},
        protocol: { registerSchemesAsPrivileged() {}, handle() {} },
        session: { defaultSession: { protocol: { handle() {}, unhandle() {} }, webRequest: { onBeforeRequest() {}, onBeforeSendHeaders() {} } } },
        ipcMain: { handle: (name, handler) => handlers.set(name, handler), on: (name, handler) => handlers.set(name, handler) },
      };
      if (name === './storage-migration.cjs') return { MIGRATION_PATH: '/__fixture__', MIGRATION_HTML: '', migrateOwnedOriginStorage: async () => {} };
      if (name === 'node:fs') return {
        existsSync: file => file === path.join(root, 'scripts', 'desktop_runtime.py') || file === path.join(root, 'runtime', 'python', 'python.exe'),
        readFileSync: () => '{}', mkdirSync() {}, appendFileSync() {},
        lstatSync(file) {
          assert.equal(file, uninstallExe);
          if (options.missing) throw new Error('missing fixture');
          return { isFile: () => !options.directory, isSymbolicLink: () => Boolean(options.link) };
        },
        realpathSync: file => file === uninstallExe && options.outside ? path.join(root, '..', 'outside', 'Uninstall-DeepSteam.exe') : file,
      };
      if (name === 'node:child_process') return { spawn: (program, args, config) => {
        if (program === uninstallExe && options.throwSpawn) throw new Error('fixture failure');
        const child = new EventEmitter(); child.unrefs = 0; child.unref = () => { child.unrefs++; };
        children.push({ program, args, config, child });
        if (program === uninstallExe && !options.manualSpawn) queueMicrotask(() => child.emit(options.error ? 'error' : 'spawn', new Error('fixture failure')));
        return child;
      } };
      return require(name);
    },
  });
  await flush();
  const window = windows[0]; window.navigate('deepsteam://app/settings/general');
  return { window, children, open: handlers.get('deepsteam:open-uninstaller'), event: () => ({ sender: window.webContents, senderFrame: window.webContents.mainFrame }), quits: () => quits };
}

test('opens only the pinned uninstaller confirmation without flags, service shutdown, or secrets', async () => {
  const f = await fixture();
  assert.equal((await f.open(f.event())).status, 'opened');
  assert.equal(f.children.length, 2); // Existing startup lifecycle + confirmation only.
  const launch = f.children[1];
  assert.equal(launch.program, uninstallExe);
  assert.deepEqual(Array.from(launch.args), []);
  assert.equal(launch.config.cwd, root);
  assert.equal(launch.config.shell, false);
  assert.equal(launch.config.windowsHide, true);
  assert.equal(launch.config.stdio, 'ignore');
  assert.equal(launch.config.env.OPENAI_API_KEY, undefined);
  assert.equal(launch.config.env.DEEPSEEK_TOKEN, undefined);
  assert.equal(launch.config.env.OPENAI_BASE_URL, undefined);
  assert.equal(launch.config.env.SystemRoot, 'C:\\Windows');
  assert.equal(launch.child.unrefs, 1);
  assert.equal(f.quits(), 0);
});

test('rejects all renderer arguments, foreign windows, iframes, and missing frames', async () => {
  const f = await fixture();
  for (const args of [['--quiet'], ['C:\\untrusted.exe'], [{ cleanData: true }]]) assert.equal((await f.open(f.event(), ...args)).status, 'denied');
  for (const event of [{ sender: {} }, { sender: f.window.webContents }, { sender: f.window.webContents, senderFrame: { url: 'deepsteam://app/settings/general' } }]) assert.equal((await f.open(event)).status, 'denied');
  assert.equal(f.children.length, 1);
});

test('rejects startup, other application surfaces, remote pages, disposed frames, and closing windows', async () => {
  const f = await fixture();
  for (const url of ['file:///fixture/starting.html', 'https://example.test/', 'about:blank', 'deepsteam://classroom/', 'http://127.0.0.1:3792/settings/general']) {
    f.window.navigate(url); assert.equal((await f.open(f.event())).status, 'denied');
  }
  f.window.navigate('deepsteam://app/settings/general');
  f.window.webContents.mainFrame.url = 'https://example.test/';
  assert.equal((await f.open(f.event())).status, 'denied');
  f.window.navigate('deepsteam://app/settings/general');
  f.window.emit('close');
  assert.equal((await f.open(f.event())).status, 'denied');
  assert.equal(f.children.length, 1);
  const disposed = await fixture();
  Object.defineProperty(disposed.window.webContents.mainFrame, 'url', { get() { throw new Error('Disposed frame'); } });
  assert.equal((await disposed.open(disposed.event())).status, 'denied');
  assert.equal(disposed.children.length, 1);
});

test('missing, linked, directory, or escaped executables cannot launch', async () => {
  for (const options of [{ missing: true }, { link: true }, { directory: true }, { outside: true }]) {
    const f = await fixture(options);
    assert.equal((await f.open(f.event())).status, 'unavailable');
    assert.equal(f.children.length, 1);
  }
});

test('concurrent requests reuse the open window and allow a fresh confirmation after exit', async () => {
  const f = await fixture({ manualSpawn: true });
  const first = f.open(f.event());
  assert.equal((await f.open(f.event())).status, 'already-open');
  assert.equal(f.children.length, 2);
  f.children[1].child.emit('spawn');
  assert.equal((await first).status, 'opened');
  f.children[1].child.emit('exit', 0); // User cancels native confirmation.
  const next = f.open(f.event());
  assert.equal(f.children.length, 3);
  f.children[2].child.emit('spawn');
  assert.equal((await next).status, 'opened');
});

test('spawn errors return a recoverable failure, not an uninstall success', async () => {
  for (const options of [{ error: true }, { throwSpawn: true }]) {
    const f = await fixture(options);
    assert.equal((await f.open(f.event())).status, 'failed');
    assert.equal((await f.open(f.event())).status, 'failed');
    assert.equal(f.quits(), 0);
  }
});

test('preload publishes only a no-argument confirmation capability', async () => {
  let bridge;
  const calls = [];
  vm.runInNewContext(preload, {
    window: { addEventListener() {} },
    require: () => ({ contextBridge: { exposeInMainWorld: (_name, value) => { bridge = value; } }, ipcRenderer: { on() {}, invoke: (...args) => { calls.push(args); return Promise.resolve({ status: 'opened' }); } } }),
  });
  await bridge.openUninstaller('C:\\untrusted.exe', '--quiet');
  assert.deepEqual(calls, [['deepsteam:open-uninstaller']]);
});
