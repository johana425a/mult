'use strict';

// Own-product origin migration. Payloads remain in memory; the legacy origins
// are never cleared. This module must run before either application is loaded.
const { createHash } = require('node:crypto');
const MIGRATION_PATH = '/__deepsteam_storage_migration__';
const MIGRATION_HTML = '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'none\'; connect-src \'none\'"><title>DeepSteam</title>';
const MARKER = '__deepsteam_origin_migration_v1__';
const ALLOWED = new Map([
  ['http://127.0.0.1:3792', 'deepsteam://app'],
  ['http://127.0.0.1:3793', 'deepsteam://classroom'],
  ['http://127.0.0.1:3791', 'deepsteam://portal'],
]);

function migrationError(code) {
  return Object.assign(new Error('DeepSteam existing data could not be safely migrated.'), { code });
}

// Executed only in our inert documents, with no preload or Node integration.
// Chromium's structured-clone values are encoded explicitly for Electron IPC.
async function browserStorageOperation(operation, argument, markerKey) {
  const fail = (code) => { throw Object.assign(new Error(code), { migrationCode: code }); };
  const request = (req) => new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
    req.onblocked = () => reject(Object.assign(new Error('blocked'), { migrationCode: 'MIGRATION_DATABASE_BUSY' }));
  });
  const transactionDone = (tx) => new Promise((resolve, reject) => {
    tx.oncomplete = resolve;
    tx.onabort = () => reject(tx.error || new Error('aborted'));
    tx.onerror = () => {};
  });
  const openExisting = async (name) => {
    const req = indexedDB.open(name);
    req.onupgradeneeded = () => req.transaction.abort();
    return request(req);
  };
  const bytesToBase64 = (buffer) => {
    const bytes = new Uint8Array(buffer);
    let value = '';
    for (let i = 0; i < bytes.length; i += 32768) value += String.fromCharCode(...bytes.subarray(i, i + 32768));
    return btoa(value);
  };
  const base64ToBuffer = (value) => {
    const binary = atob(value);
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
    return out.buffer;
  };
  async function encode(value) {
    const seen = new Map();
    const nodes = [];
    async function visit(item) {
      if (item === undefined) return { special: 'undefined' };
      if (typeof item === 'bigint') return { special: 'bigint', value: String(item) };
      if (typeof item === 'number' && (!Number.isFinite(item) || Object.is(item, -0))) return { special: 'number', value: Object.is(item, -0) ? '-0' : String(item) };
      if (item === null || ['string', 'number', 'boolean'].includes(typeof item)) return item;
      if (typeof item !== 'object') fail('MIGRATION_UNSUPPORTED_VALUE');
      if (seen.has(item)) return { ref: seen.get(item) };
      const id = nodes.length;
      seen.set(item, id);
      const node = {};
      nodes.push(node);
      if (item instanceof File) Object.assign(node, { type: 'File', name: item.name, mime: item.type, modified: item.lastModified, data: bytesToBase64(await item.arrayBuffer()) });
      else if (item instanceof Blob) Object.assign(node, { type: 'Blob', mime: item.type, data: bytesToBase64(await item.arrayBuffer()) });
      else if (item instanceof ArrayBuffer) Object.assign(node, { type: 'ArrayBuffer', data: bytesToBase64(item) });
      else if (ArrayBuffer.isView(item)) Object.assign(node, { type: 'View', name: item.constructor.name, buffer: await visit(item.buffer), offset: item.byteOffset, length: item instanceof DataView ? item.byteLength : item.length });
      else if (item instanceof Date) Object.assign(node, { type: 'Date', value: Number.isNaN(item.getTime()) ? null : item.getTime() });
      else if (item instanceof RegExp) Object.assign(node, { type: 'RegExp', source: item.source, flags: item.flags });
      else if (item instanceof Map) {
        Object.assign(node, { type: 'Map', entries: [] });
        for (const [key, val] of item) node.entries.push([await visit(key), await visit(val)]);
      } else if (item instanceof Set) {
        Object.assign(node, { type: 'Set', entries: [] });
        for (const val of item) node.entries.push(await visit(val));
      } else if (Array.isArray(item)) {
        Object.assign(node, { type: 'Array', length: item.length, entries: [] });
        for (const key of Object.keys(item)) node.entries.push([key, await visit(item[key])]);
      } else if (Object.getPrototypeOf(item) === Object.prototype || Object.getPrototypeOf(item) === null) {
        Object.assign(node, { type: 'Object', entries: [] });
        for (const key of Object.keys(item)) node.entries.push([key, await visit(item[key])]);
      } else fail('MIGRATION_UNSUPPORTED_VALUE');
      return { ref: id };
    }
    const root = await visit(value);
    return { root, nodes };
  }
  function decode(encoded) {
    const decoded = new Map();
    function visit(item) {
      if (item === null || typeof item !== 'object') return item;
      if (item.special === 'undefined') return undefined;
      if (item.special === 'bigint') return BigInt(item.value);
      if (item.special === 'number') return item.value === '-0' ? -0 : Number(item.value);
      const id = item.ref;
      if (decoded.has(id)) return decoded.get(id);
      const node = encoded.nodes[id];
      let value;
      switch (node.type) {
        case 'File': value = new File([base64ToBuffer(node.data)], node.name, { type: node.mime, lastModified: node.modified }); break;
        case 'Blob': value = new Blob([base64ToBuffer(node.data)], { type: node.mime }); break;
        case 'ArrayBuffer': value = base64ToBuffer(node.data); break;
        case 'View': {
          const classes = { Int8Array, Uint8Array, Uint8ClampedArray, Int16Array, Uint16Array, Int32Array, Uint32Array, Float32Array, Float64Array, BigInt64Array, BigUint64Array, DataView };
          const Class = classes[node.name];
          if (!Class) fail('MIGRATION_UNSUPPORTED_VALUE');
          value = new Class(visit(node.buffer), node.offset, node.length);
          break;
        }
        case 'Date': value = new Date(node.value === null ? NaN : node.value); break;
        case 'RegExp': value = new RegExp(node.source, node.flags); break;
        case 'Map': value = new Map(); break;
        case 'Set': value = new Set(); break;
        case 'Array': value = new Array(node.length); break;
        case 'Object': value = {}; break;
        default: fail('MIGRATION_UNSUPPORTED_VALUE');
      }
      decoded.set(id, value);
      if (node.type === 'Map') for (const [key, val] of node.entries) value.set(visit(key), visit(val));
      if (node.type === 'Set') for (const val of node.entries) value.add(visit(val));
      if (node.type === 'Array' || node.type === 'Object') for (const [key, val] of node.entries) Object.defineProperty(value, key, { value: visit(val), enumerable: true, writable: true, configurable: true });
      return value;
    }
    return visit(encoded.root);
  }
  function schemaOf(db) {
    const names = Array.from(db.objectStoreNames);
    if (!names.length) return [];
    const tx = db.transaction(names, 'readonly');
    return names.map((name) => {
      const store = tx.objectStore(name);
      return { name, keyPath: store.keyPath, autoIncrement: store.autoIncrement, indexes: Array.from(store.indexNames).map((indexName) => {
        const index = store.index(indexName);
        return { name: index.name, keyPath: index.keyPath, unique: index.unique, multiEntry: index.multiEntry };
      }) };
    });
  }
  async function nextAutoKey(db, name) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(name, 'readwrite');
      const req = tx.objectStore(name).add({});
      let next;
      req.onsuccess = () => { next = req.result; tx.abort(); };
      req.onerror = () => {};
      tx.onerror = () => {};
      tx.oncomplete = () => reject(new Error('probe must abort'));
      tx.onabort = () => typeof next === 'number' ? resolve(next) : reject(new Error('cannot probe key generator'));
    });
  }
  async function exportDatabase(name) {
    const db = await openExisting(name);
    try {
      const schema = schemaOf(db);
      const names = schema.map((store) => store.name);
      const rows = Object.create(null);
      if (names.length) {
        const tx = db.transaction(names, 'readonly');
        const done = transactionDone(tx);
        for (const name of names) {
          rows[name] = [];
          const req = tx.objectStore(name).openCursor();
          req.onsuccess = () => {
            const cursor = req.result;
            if (cursor) { rows[name].push([cursor.key, cursor.value]); cursor.continue(); }
          };
        }
        await done;
      }
      for (const store of schema) if (store.autoIncrement) store.nextKey = await nextAutoKey(db, store.name);
      return { name: db.name, version: db.version, schema, records: await encode(rows), count: Object.values(rows).reduce((sum, values) => sum + values.length, 0) };
    } finally { db.close(); }
  }
  async function importDatabase(snapshot) {
    const existing = (await indexedDB.databases()).find((item) => item.name === snapshot.name);
    if (existing) {
      const previous = await exportDatabase(snapshot.name);
      if (JSON.stringify(previous) === JSON.stringify(snapshot)) return { reused: true };
      const stripGenerators = (schema) => schema.map(({ nextKey, ...store }) => store);
      if (previous.count || previous.schema.some((store) => store.autoIncrement && store.nextKey !== 1) || previous.version !== snapshot.version || JSON.stringify(stripGenerators(previous.schema)) !== JSON.stringify(stripGenerators(snapshot.schema))) fail('MIGRATION_DESTINATION_CONFLICT');
    }
    const req = indexedDB.open(snapshot.name, snapshot.version);
    req.onupgradeneeded = () => {
      const db = req.result;
      for (const definition of snapshot.schema) {
        const store = db.createObjectStore(definition.name, { keyPath: definition.keyPath, autoIncrement: definition.autoIncrement });
        for (const index of definition.indexes) store.createIndex(index.name, index.keyPath, { unique: index.unique, multiEntry: index.multiEntry });
      }
    };
    const db = await request(req);
    try {
      const rows = decode(snapshot.records);
      if (!snapshot.schema.length) return { reused: false };
      const tx = db.transaction(snapshot.schema.map((store) => store.name), 'readwrite');
      const done = transactionDone(tx);
      try {
        for (const definition of snapshot.schema) {
          const store = tx.objectStore(definition.name);
          for (const [key, value] of rows[definition.name]) definition.keyPath === null ? store.add(value, key) : store.add(value);
          // Explicit add/delete advances Chromium's key generator without
          // retaining a sentinel, including when the last source key was deleted.
          if (definition.autoIncrement && definition.nextKey > 1) {
            const key = definition.nextKey - 1;
            const existingKey = rows[definition.name].some(([candidate]) => typeof candidate === 'number' && candidate === key);
            if (!existingKey) {
              const value = {};
              if (definition.keyPath !== null) {
                const parts = definition.keyPath.split('.');
                let owner = value;
                for (const part of parts.slice(0, -1)) { owner[part] = {}; owner = owner[part]; }
                owner[parts[parts.length - 1]] = key;
                store.add(value);
              } else store.add(value, key);
              store.delete(key);
            }
          }
        }
      } catch (error) { tx.abort(); await done.catch(() => {}); throw error; }
      await done;
      return { reused: false };
    } finally { db.close(); }
  }
  try {
    let result;
    if (operation === 'catalog') {
      const entries = Object.keys(localStorage).filter((key) => key !== markerKey).sort().map((key) => [key, localStorage.getItem(key)]);
      result = { localStorage: entries, databases: (await indexedDB.databases()).map(({ name, version }) => ({ name, version })).sort((a, b) => a.name.localeCompare(b.name)), marker: localStorage.getItem(markerKey) };
    } else if (operation === 'export') result = await exportDatabase(argument);
    else if (operation === 'import') result = await importDatabase(argument);
    else if (operation === 'localStorage') {
      for (const [key, value] of argument) {
        const current = localStorage.getItem(key);
        if (current !== null && current !== value) fail('MIGRATION_DESTINATION_CONFLICT');
      }
      const added = [];
      try {
        for (const [key, value] of argument) if (localStorage.getItem(key) === null) { localStorage.setItem(key, value); added.push(key); }
      } catch (error) { for (const key of added) localStorage.removeItem(key); throw error; }
      result = { count: argument.length };
    } else if (operation === 'mark') { localStorage.setItem(markerKey, JSON.stringify(argument)); result = true; }
    else fail('MIGRATION_INVALID_OPERATION');
    return { ok: true, result };
  } catch (error) { return { ok: false, code: /^MIGRATION_[A-Z_]+$/.test(error.migrationCode || '') ? error.migrationCode : 'MIGRATION_STORAGE_ERROR' }; }
}

async function call(window, operation, argument = null) {
  const script = `(${browserStorageOperation.toString()})(${JSON.stringify(operation)},${JSON.stringify(argument)},${JSON.stringify(MARKER)})`;
  let reply;
  try { reply = await window.webContents.executeJavaScript(script, false); }
  catch { throw migrationError('MIGRATION_EXECUTION_FAILED'); }
  if (!reply?.ok) throw migrationError(/^MIGRATION_[A-Z_]+$/.test(reply?.code || '') ? reply.code : 'MIGRATION_EXECUTION_FAILED');
  return reply.result;
}
const digest = (value) => createHash('sha256').update(JSON.stringify(value)).digest('hex');

async function migrateOwnedOriginStorage({ BrowserWindow, session, origins, loadMigrationDocument, migrateCookies, signal }) {
  if (!Array.isArray(origins) || origins.some(({ from, to }) => ALLOWED.get(from) !== to)) throw migrationError('MIGRATION_INVALID_ORIGIN');
  if (typeof loadMigrationDocument !== 'function') throw migrationError('MIGRATION_INVALID_LOADER');
  const summary = { migratedOrigins: 0, alreadyMigratedOrigins: 0, databases: 0, records: 0, localStorageEntries: 0, cookies: 0 };
  const activeWindows = new Set();
  const cancel = () => { for (const win of activeWindows) if (!win.isDestroyed()) win.destroy(); };
  const checkCancelled = () => { if (signal?.aborted) throw migrationError('MIGRATION_CANCELLED'); };
  const load = async (win, origin) => {
    checkCancelled();
    await loadMigrationDocument(win, origin);
    checkCancelled();
    if (win.webContents.getURL() !== origin + MIGRATION_PATH) throw migrationError('MIGRATION_INVALID_DOCUMENT');
  };
  signal?.addEventListener('abort', cancel);
  try { for (const { from, to } of origins) {
    checkCancelled();
    const windows = [];
    try {
      const makeWindow = () => {
        const win = new BrowserWindow({ show: false, webPreferences: { session, nodeIntegration: false, contextIsolation: true, sandbox: true, devTools: false, backgroundThrottling: false } });
        win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
        windows.push(win);
        activeWindows.add(win);
        return win;
      };
      const target = makeWindow();
      await load(target, to);
      const destination = await call(target, 'catalog');
      let marker;
      try { marker = JSON.parse(destination.marker || 'null'); } catch {}
      if (marker?.version === 1 && marker?.from === from && marker?.to === to && marker?.complete === true) { summary.alreadyMigratedOrigins++; continue; }
      const source = makeWindow();
      await load(source, from);
      const original = await call(source, 'catalog');
      const sourceEntries = new Map(original.localStorage);
      if (destination.localStorage.some(([key, value]) => !sourceEntries.has(key) || sourceEntries.get(key) !== value) || destination.databases.some((database) => !original.databases.some((candidate) => candidate.name === database.name))) throw migrationError('MIGRATION_DESTINATION_CONFLICT');
      for (const database of original.databases) {
        checkCancelled();
        const snapshot = await call(source, 'export', database.name);
        await call(target, 'import', snapshot);
        const copied = await call(target, 'export', database.name);
        if (digest(snapshot) !== digest(copied)) throw migrationError('MIGRATION_VERIFY_FAILED');
        summary.databases++;
        summary.records += snapshot.count;
      }
      await call(target, 'localStorage', original.localStorage);
      const copiedCatalog = await call(target, 'catalog');
      if (digest(copiedCatalog.localStorage) !== digest(original.localStorage)) throw migrationError('MIGRATION_VERIFY_FAILED');
      // A transport may own a cookie bridge because Chromium custom schemes
      // do not necessarily admit HTTP cookies. Never silently drop old auth.
      const oldCookies = await session.cookies.get({ domain: new URL(from).hostname });
      if (oldCookies.length) {
        if (typeof migrateCookies !== 'function') throw migrationError('MIGRATION_COOKIE_BRIDGE_REQUIRED');
        const retained = await migrateCookies({ session, from, to, cookies: oldCookies });
        if (!Number.isSafeInteger(retained) || retained !== oldCookies.length) throw migrationError('MIGRATION_COOKIE_VERIFY_FAILED');
        summary.cookies += retained;
      }
      checkCancelled();
      await call(target, 'mark', { version: 1, from, to, complete: true });
      session.flushStorageData();
      summary.localStorageEntries += original.localStorage.length;
      summary.migratedOrigins++;
    } catch (error) {
      checkCancelled();
      throw /^MIGRATION_[A-Z_]+$/.test(error?.code || '') ? error : migrationError('MIGRATION_STORAGE_ERROR');
    } finally { for (const win of windows) { activeWindows.delete(win); if (!win.isDestroyed()) win.destroy(); } }
  } } finally { signal?.removeEventListener('abort', cancel); cancel(); }
  return summary;
}

module.exports = { MIGRATION_PATH, MIGRATION_HTML, migrateOwnedOriginStorage, browserStorageOperation, MARKER };
