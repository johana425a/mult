'use strict';

// Native-dialog and Electron ownership fixtures only. These tests never open
// a real dialog, inspect a user's directory, or start any backend service.
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
const flush = () => new Promise(resolve => setImmediate(resolve));
const selectedDirectory = path.join(root, 'fixture-selected-directory');

async function pickerFixture(options = {}) {
  const ipc = new Map();
  const dialogs = [];
  const children = [];
  const windows = [];
  const openedPaths = [];
  const app = new EventEmitter();
  Object.assign(app, { setPath() {}, setAppLogsPath() {}, commandLine: { appendSwitch() {} }, requestSingleInstanceLock: () => true, whenReady: () => Promise.resolve(), quit() {} });
  class TestWindow extends EventEmitter {
    constructor() {
      super(); this.destroyed = false;
      const contents = this.webContents = new EventEmitter();
      contents.currentURL = ''; contents.destroyed = false;
      contents.mainFrame = { url: '' };
      contents.getURL = () => contents.currentURL;
      contents.isDestroyed = () => contents.destroyed;
      contents.isLoadingMainFrame = () => false;
      contents.send = () => {};
      contents.stop = () => {};
      contents.setWindowOpenHandler = () => {};
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
    __dirname, URL, setTimeout, clearTimeout, AbortSignal, AbortController,
    fetch: options.fetch || (async () => ({ ok: true, headers: { get: () => null }, text: async () => JSON.stringify({ workspace_id: 'workspace-fixture', path: selectedDirectory }) })),
    process: { argv: [], env: {}, pid: 1234 },
    require(module) {
      if (module === 'electron') return {
        app, BrowserWindow: TestWindow, protocol: { registerSchemesAsPrivileged() {}, handle() {} }, session: { defaultSession: { protocol: { handle() {}, unhandle() {} }, webRequest: { onBeforeRequest() {}, onBeforeSendHeaders() {} } } }, net: { fetch() {} },
        ipcMain: { handle: (name, handler) => ipc.set(name, handler), on: (name, handler) => ipc.set(name, handler) },
        dialog: { showErrorBox() {}, showOpenDialog: async (...args) => {
          dialogs.push(args);
          if (options.showOpenDialog) return options.showOpenDialog(...args);
          return { canceled: false, filePaths: [selectedDirectory] };
        } },
        shell: { openExternal: async () => {}, openPath: async directory => { openedPaths.push(directory); return options.openPath ? options.openPath(directory) : ''; } },
      };
      if (module === './storage-migration.cjs') return { MIGRATION_PATH: '/__fixture__', MIGRATION_HTML: '', migrateOwnedOriginStorage: async () => {} };
      if (module === 'node:child_process') return { spawn: (_program, args) => { const child = new EventEmitter(); child.args = args; children.push(child); return child; } };
      if (module === 'node:fs') return {
        existsSync: file => file === path.join(root, 'scripts', 'desktop_runtime.py') || file === path.join(root, 'runtime', 'python', 'python.exe'),
        readFileSync: file => file.endsWith('control-token') ? 'fixture-product-control-token-1234567890' : '{}', mkdirSync() {}, appendFileSync() {},
        statSync: file => {
          if (options.statSync) return options.statSync(file);
          if (file !== selectedDirectory) throw new Error('Fixture directory is unavailable.');
          return { isDirectory: () => true };
        },
      };
      return require(module);
    },
  });
  await flush();
  const ownedWindow = windows[0];
  ownedWindow.navigate('deepsteam://app/workspace');
  return {
    app, window: ownedWindow, children, dialogs, openedPaths,
    picker: ipc.get('deepsteam:pick-workspace-directory'),
    openDirectory: ipc.get('deepsteam:open-workspace-directory'),
    openRegisteredDirectory: ipc.get('deepsteam:open-registered-workspace-directory'),
    event: () => ({ sender: ownedWindow.webContents, senderFrame: ownedWindow.webContents.mainFrame }),
  };
}

test('owned frontend main frame receives one normalized existing-directory selection', async () => {
  const fixture = await pickerFixture();
  assert.equal(await fixture.picker(fixture.event(), 'C:/caller-supplied-path'), path.normalize(selectedDirectory));
  assert.equal(fixture.dialogs.length, 1);
  assert.equal(fixture.dialogs[0][0], fixture.window);
  assert.deepEqual(Array.from(fixture.dialogs[0][1].properties), ['openDirectory']);
  assert.equal(fixture.dialogs[0][1].defaultPath, undefined);
});

test('other windows and external placeholders cannot open a directory dialog', async () => {
  const fixture = await pickerFixture();
  const outsider = { getURL: () => 'deepsteam://app/workspace', mainFrame: fixture.window.webContents.mainFrame };
  assert.equal(await fixture.picker({ sender: outsider, senderFrame: outsider.mainFrame }), null);
  assert.equal(await fixture.picker({ sender: { getURL: () => 'about:blank' }, senderFrame: { url: 'about:blank' } }), null);
  assert.equal(fixture.dialogs.length, 0);
});

test('subframes and missing frame identities cannot open a directory dialog', async () => {
  const fixture = await pickerFixture();
  assert.equal(await fixture.picker({ sender: fixture.window.webContents, senderFrame: { url: 'deepsteam://app/workspace' } }), null);
  assert.equal(await fixture.picker({ sender: fixture.window.webContents }), null);
  assert.equal(fixture.dialogs.length, 0);
});

test('startup files, other local applications, remote origins, and frame URL mismatches are rejected', async () => {
  const fixture = await pickerFixture();
  for (const url of [pathToFileURL(path.join(__dirname, 'starting.html')).href, 'http://127.0.0.1:3793/', 'http://127.0.0.1:3791/', 'https://127.0.0.1:3792/', 'https://example.test/', 'about:blank', 'deepsteam://app@example.test/']) {
    fixture.window.navigate(url);
    assert.equal(await fixture.picker(fixture.event()), null, url);
  }
  fixture.window.navigate('deepsteam://app/workspace');
  fixture.window.webContents.mainFrame.url = 'https://example.test/';
  assert.equal(await fixture.picker(fixture.event()), null);
  assert.equal(fixture.dialogs.length, 0);
});

test('cancellation and dialog failure return null and allow a later selection', async () => {
  let attempt = 0;
  const fixture = await pickerFixture({ showOpenDialog: () => {
    attempt++;
    if (attempt === 1) return { canceled: true, filePaths: [selectedDirectory] };
    if (attempt === 2) throw new Error('Fixture cancellation failure');
    return { canceled: false, filePaths: [selectedDirectory] };
  } });
  assert.equal(await fixture.picker(fixture.event()), null);
  assert.equal(await fixture.picker(fixture.event()), null);
  assert.equal(await fixture.picker(fixture.event()), path.normalize(selectedDirectory));
});

test('concurrent requests do not create a second dialog', async () => {
  let finish;
  const fixture = await pickerFixture({ showOpenDialog: () => new Promise(resolve => { finish = resolve; }) });
  const first = fixture.picker(fixture.event());
  assert.equal(await fixture.picker(fixture.event()), null);
  assert.equal(fixture.dialogs.length, 1);
  finish({ canceled: false, filePaths: [selectedDirectory] });
  assert.equal(await first, path.normalize(selectedDirectory));
});

test('closing or destroying the window or its contents invalidates a pending selection', async () => {
  for (const destroy of [fixture => { fixture.window.emit('close'); }, fixture => { fixture.window.destroyed = true; }, fixture => { fixture.window.webContents.destroyed = true; }, fixture => { fixture.window.emit('closed'); }]) {
    let finish;
    const fixture = await pickerFixture({ showOpenDialog: () => new Promise(resolve => { finish = resolve; }) });
    const result = fixture.picker(fixture.event());
    destroy(fixture);
    finish({ canceled: false, filePaths: [selectedDirectory] });
    assert.equal(await result, null);
    assert.equal(await fixture.picker(fixture.event()), null);
  }
});

test('a disposed sender frame cannot throw out of the IPC ownership check', async () => {
  const fixture = await pickerFixture();
  Object.defineProperty(fixture.window.webContents.mainFrame, 'url', { get() { throw new Error('Fixture frame disposed'); } });
  assert.equal(await fixture.picker(fixture.event()), null);
  assert.equal(fixture.dialogs.length, 0);
});

test('closing during a dialog invalidates late results without changing lifecycle ownership', async () => {
  let finish;
  const fixture = await pickerFixture({ showOpenDialog: () => new Promise(resolve => { finish = resolve; }) });
  const result = fixture.picker(fixture.event());
  fixture.app.emit('before-quit', { preventDefault() {} });
  finish({ canceled: false, filePaths: [selectedDirectory] });
  assert.equal(await result, null);
  assert.equal(await fixture.picker(fixture.event()), null);
  fixture.children[0].emit('exit', 0); await flush();
  assert.equal(fixture.children[1].args[3], 'stop-owned');
  assert.equal(fixture.children[1].args[5], fixture.children[0].args[5]);
  fixture.children[1].emit('exit', 0); await flush();
});

test('navigation or main-frame replacement while the dialog is open discards the result', async () => {
  for (const navigate of [fixture => fixture.window.navigate('https://example.test/'), fixture => fixture.window.navigate('http://127.0.0.1:3793/'), fixture => { fixture.window.webContents.mainFrame = { url: 'deepsteam://app/workspace' }; }]) {
    let finish;
    const fixture = await pickerFixture({ showOpenDialog: () => new Promise(resolve => { finish = resolve; }) });
    const result = fixture.picker(fixture.event());
    navigate(fixture);
    finish({ canceled: false, filePaths: [selectedDirectory] });
    assert.equal(await result, null);
  }
});

test('invalid, missing, relative, multiple, and non-directory results are rejected', async () => {
  for (const result of [{ canceled: false, filePaths: [] }, { canceled: false, filePaths: ['relative-folder'] }, { canceled: false, filePaths: [selectedDirectory, selectedDirectory] }, { canceled: false, filePaths: [null] }, { canceled: false, filePaths: [path.join(root, 'not-found')] }]) {
    const fixture = await pickerFixture({ showOpenDialog: () => result });
    assert.equal(await fixture.picker(fixture.event()), null);
  }
  const fixture = await pickerFixture({ statSync: () => ({ isDirectory: () => false }) });
  assert.equal(await fixture.picker(fixture.event()), null);
});

test('preload exposes only the no-argument directory selection method through the dedicated IPC', async () => {
  let exposed;
  const invocations = [];
  vm.runInNewContext(preload, {
    window: { location: { protocol: 'http:' }, addEventListener() {} },
    document: {},
    require: () => ({
      contextBridge: { exposeInMainWorld: (_name, value) => { exposed = value; } },
      ipcRenderer: { on() {}, invoke: async (...args) => { invocations.push(args); return selectedDirectory; } },
    }),
  });
  assert.equal(await exposed.pickWorkspaceDirectory('ignored-argument'), selectedDirectory);
  assert.deepEqual(Array.from(invocations[0]), ['deepsteam:pick-workspace-directory']);
  assert.equal(Object.isFrozen(exposed), true);
});

test('Explorer opening uses a previously selected grant and rejects arbitrary renderer paths', async () => {
  const fixture = await pickerFixture();
  assert.equal(await fixture.openDirectory(fixture.event(), selectedDirectory), false);
  await fixture.picker(fixture.event());
  assert.equal(await fixture.openDirectory(fixture.event(), path.join(root, 'unselected-directory')), false);
  assert.equal(await fixture.openDirectory(fixture.event(), selectedDirectory), true);
  assert.deepEqual(fixture.openedPaths, [path.normalize(selectedDirectory)]);
  assert.equal(await fixture.openDirectory({ sender: fixture.window.webContents, senderFrame: { url: 'deepsteam://app/workspace' } }, selectedDirectory), false);
  fixture.window.navigate('https://example.test/');
  assert.equal(await fixture.openDirectory(fixture.event(), selectedDirectory), false);
  assert.equal(fixture.openedPaths.length, 1);
});

test('deleted directories, Explorer failure, closing, and new desktop sessions cannot reuse grants', async () => {
  let exists = true;
  const fixture = await pickerFixture({ statSync: () => { if (!exists) throw new Error('Fixture directory deleted'); return { isDirectory: () => true }; }, openPath: () => 'Fixture Explorer failure' });
  await fixture.picker(fixture.event());
  assert.equal(await fixture.openDirectory(fixture.event(), selectedDirectory), false);
  exists = false;
  assert.equal(await fixture.openDirectory(fixture.event(), selectedDirectory), false);
  assert.equal(fixture.openedPaths.length, 1);
  const fresh = await pickerFixture();
  assert.equal(await fresh.openDirectory(fresh.event(), selectedDirectory), false);
  fresh.app.emit('before-quit', { preventDefault() {} });
  assert.equal(await fresh.openDirectory(fresh.event(), selectedDirectory), false);
  fresh.children[0].emit('exit', 0); await flush();
  fresh.children[1].emit('exit', 0); await flush();
});

test('persisted Explorer opening resolves a registered ID server-side without a picker grant', async () => {
  let requested;
  const fixture = await pickerFixture({ fetch: async (url, init) => { requested = { url, init }; return { ok: true, headers: { get: () => null }, text: async () => JSON.stringify({ workspace_id: 'workspace-fixture', path: selectedDirectory }) }; } });
  assert.equal(await fixture.openRegisteredDirectory(fixture.event(), 'workspace-fixture'), true);
  assert.equal(fixture.dialogs.length, 0);
  assert.deepEqual(fixture.openedPaths, [path.normalize(selectedDirectory)]);
  assert.equal(requested.url, 'http://127.0.0.1:3791/api/harness/internal/workspaces/workspace-fixture');
  assert.match(requested.init.headers.Authorization, /^Bearer fixture-product-control-token-/);
  assert.equal(requested.init.redirect, 'error');
});

test('persisted Explorer rejects arbitrary paths, foreign IDs, subframes, and failed lookup', async () => {
  const fixture = await pickerFixture();
  assert.equal(await fixture.openRegisteredDirectory(fixture.event(), selectedDirectory), false);
  assert.equal(await fixture.openRegisteredDirectory(fixture.event(), '../escape'), false);
  assert.equal(await fixture.openRegisteredDirectory(fixture.event(), 'foreign-id'), false);
  assert.equal(await fixture.openRegisteredDirectory({ sender: fixture.window.webContents, senderFrame: {} }, 'workspace-fixture'), false);
  const failed = await pickerFixture({ fetch: async () => ({ ok: false }) });
  assert.equal(await failed.openRegisteredDirectory(failed.event(), 'workspace-fixture'), false);
  assert.equal(fixture.openedPaths.length, 0);
});

test('persisted Explorer discards lookup after navigation, close, or directory deletion', async () => {
  for (const mutate of [fixture => fixture.window.navigate('https://example.test/'), fixture => fixture.window.emit('close')]) {
    let finish;
    const fixture = await pickerFixture({ fetch: () => new Promise(resolve => { finish = resolve; }) });
    const opening = fixture.openRegisteredDirectory(fixture.event(), 'workspace-fixture');
    mutate(fixture);
    finish({ ok: true, headers: { get: () => null }, text: async () => JSON.stringify({ workspace_id: 'workspace-fixture', path: selectedDirectory }) });
    assert.equal(await opening, false);
    assert.equal(fixture.openedPaths.length, 0);
  }
  const deleted = await pickerFixture({ statSync: () => { throw new Error('Deleted fixture directory'); } });
  assert.equal(await deleted.openRegisteredDirectory(deleted.event(), 'workspace-fixture'), false);
});
