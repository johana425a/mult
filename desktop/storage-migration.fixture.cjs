'use strict';

// Deterministic Electron acceptance; never opens a product profile or server.
const { app, BrowserWindow, protocol, session } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { MIGRATION_PATH, MIGRATION_HTML, migrateOwnedOriginStorage, browserStorageOperation, MARKER } = require('./storage-migration.cjs');
const fixtureRoot = process.argv.find((arg) => arg.startsWith('--fixture-root='))?.slice('--fixture-root='.length);
const phase = process.argv.find((arg) => arg.startsWith('--phase='))?.slice('--phase='.length) || 'seed';
const allowedParent = path.resolve(__dirname, '..', 'reports');
if (!fixtureRoot || !path.resolve(fixtureRoot).startsWith(allowedParent + path.sep) || !path.basename(fixtureRoot).startsWith('origin-migration-fixture-')) throw new Error('isolated fixture path required');
fs.mkdirSync(fixtureRoot, { recursive: true });
app.setPath('userData', path.join(fixtureRoot, 'profile'));
app.setPath('sessionData', path.join(fixtureRoot, 'session'));
app.commandLine.appendSwitch('disable-gpu');
protocol.registerSchemesAsPrivileged([{ scheme: 'deepsteam', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, stream: true } }]);
const origins = [
  { from: 'http://127.0.0.1:3792', to: 'deepsteam://app' },
  { from: 'http://127.0.0.1:3793', to: 'deepsteam://classroom' },
];
const reportFile = path.join(fixtureRoot, `result-${phase}.json`);
let openWindows = [];
async function windowAt(origin) {
  const win = new BrowserWindow({ show: false, webPreferences: { session: session.defaultSession, nodeIntegration: false, contextIsolation: true, sandbox: true } });
  openWindows.push(win);
  await win.loadURL(origin + MIGRATION_PATH);
  return win;
}
async function invoke(win, operation, argument = null) {
  const out = await win.webContents.executeJavaScript(`(${browserStorageOperation.toString()})(${JSON.stringify(operation)},${JSON.stringify(argument)},${JSON.stringify(MARKER)})`);
  if (!out.ok) throw Object.assign(new Error(out.code), { code: out.code });
  return out.result;
}
async function seedSource(win) {
  return win.webContents.executeJavaScript(`(async()=>{
    localStorage.setItem('fixture-login', 'synthetic-not-a-real-token');
    localStorage.setItem('fixture-theme', 'warm');
    const db = await new Promise((resolve,reject)=>{
      const req=indexedDB.open('MAIC-Database',7);
      req.onupgradeneeded=()=>{
        const records=req.result.createObjectStore('lessons',{keyPath:['course','lesson']});
        records.createIndex('compound',['course','title'],{unique:true});
        records.createIndex('tags','tags',{multiEntry:true});
        req.result.createObjectStore('auto',{keyPath:'nested.id',autoIncrement:true});
        req.result.createObjectStore('out',{autoIncrement:true});
      };
      req.onsuccess=()=>resolve(req.result); req.onerror=()=>reject(req.error);
    });
    await new Promise((resolve,reject)=>{
      const tx=db.transaction(['lessons','auto','out'],'readwrite');
      const buffer=new Uint8Array([1,2,3,4,5,6,7,8]).buffer;
      const cycle={word:'fixture'};cycle.self=cycle;
      const value={course:'course',lesson:'one',title:'Fixture',tags:['a','b'],
        image:new Blob([new Uint8Array([137,80,78,71])],{type:'image/png'}),
        file:new File(['fixture-file'],'image.txt',{type:'text/plain',lastModified:1700000000000}),
        when:new Date(1700000000000),buffer,view:new Uint16Array(buffer,2,2),
        dataView:new DataView(buffer,1,4),cycle,map:new Map([['a',new Set([1,'2'])]]),
        bigint:12345678901234567890n,nan:NaN,inf:Infinity,missing:undefined};
      tx.objectStore('lessons').add(value);
      tx.objectStore('auto').add({nested:{id:50},value:'removed-high-key'});
      tx.objectStore('auto').delete(50);
      tx.objectStore('auto').add({nested:{id:2},value:'kept'});
      tx.objectStore('out').add({value:'removed-high-key'},80);
      tx.objectStore('out').delete(80);
      tx.objectStore('out').add({value:'kept'},3);
      tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);
    });
    db.close();return true;
  })()`);
}
async function main() {
  await app.whenReady();
  const ses = session.defaultSession;
  const handler = (request) => {
    const url = new URL(request.url);
    if (url.pathname !== MIGRATION_PATH) return new Response('blocked', { status: 403 });
    return new Response(MIGRATION_HTML, { headers: { 'content-type': 'text/html; charset=utf-8' } });
  };
  ses.protocol.handle('http', handler);
  ses.protocol.handle('deepsteam', handler);
  const options = { BrowserWindow, session: ses, origins, loadMigrationDocument: (win, origin) => win.loadURL(origin + MIGRATION_PATH) };
  const checks = [];
  if (phase === 'seed') {
    const source = await windowAt(origins[1].from);
    await seedSource(source);
    const appSource = await windowAt(origins[0].from);
    await appSource.webContents.executeJavaScript("localStorage.setItem('fixture-login','synthetic-native-login'); true");
    const snapshot = await invoke(source, 'export', 'MAIC-Database');
    assert.equal(snapshot.schema.find((item) => item.name === 'auto').nextKey, 51);
    assert.equal(snapshot.schema.find((item) => item.name === 'out').nextKey, 81);
    checks.push('source-key-generators-preserved-by-aborted-probe');
    // Simulate a process exit after one database committed, before the marker.
    const destination = await windowAt(origins[1].to);
    await invoke(destination, 'import', snapshot);
    await invoke(destination, 'localStorage', [['fixture-theme', 'warm']]);
    const summary = await migrateOwnedOriginStorage(options);
    assert.equal(summary.migratedOrigins, 2);
    assert.equal(summary.databases, 1);
    assert.equal(summary.records, 3);
    assert.equal(summary.localStorageEntries, 3);
    assert.deepEqual(await invoke(source, 'export', 'MAIC-Database'), snapshot);
    assert.deepEqual(await invoke(destination, 'export', 'MAIC-Database'), snapshot);
    checks.push('localstorage-login-and-settings-copied', 'partial-retry-identical-database-reused', 'full-schema-compound-indexes-version-preserved', 'blob-file-buffer-views-date-map-set-cycle-bigint-roundtrip', 'old-source-database-unchanged');
    const actual = await destination.webContents.executeJavaScript(`(async()=>{
      const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('MAIC-Database');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});
      const result=await new Promise((resolve,reject)=>{
        const tx=db.transaction(['auto','out'],'readwrite');const a=tx.objectStore('auto').add({value:'next'});const b=tx.objectStore('out').add({value:'next'});
        tx.oncomplete=()=>resolve([a.result,b.result]);tx.onabort=()=>reject(tx.error);
      });db.close();return result;
    })()`);
    assert.deepEqual(actual, [51, 81]);
    checks.push('destination-next-auto-keys-match-source');
    await destination.webContents.executeJavaScript("localStorage.setItem('fixture-theme','new-user-choice'); true");
    const again = await migrateOwnedOriginStorage(options);
    assert.equal(again.alreadyMigratedOrigins, 2);
    assert.equal(await destination.webContents.executeJavaScript("localStorage.getItem('fixture-theme')"), 'new-user-choice');
    checks.push('completion-marker-does-not-overwrite-new-user-data');
    const oldPortal = await windowAt('http://127.0.0.1:3791');
    const newPortal = await windowAt('deepsteam://portal');
    await oldPortal.webContents.executeJavaScript("localStorage.setItem('fixture-conflict','old'); true");
    await newPortal.webContents.executeJavaScript("localStorage.setItem('fixture-conflict','new'); true");
    await assert.rejects(migrateOwnedOriginStorage({ ...options, origins: [{from:'http://127.0.0.1:3791',to:'deepsteam://portal'}] }), {code:'MIGRATION_DESTINATION_CONFLICT'});
    assert.equal(await newPortal.webContents.executeJavaScript("localStorage.getItem('fixture-conflict')"), 'new');
    checks.push('conflicting-destination-refused-untouched');
    await assert.rejects(migrateOwnedOriginStorage({...options, origins:[{from:'https://example.com',to:'deepsteam://app'}]}),{code:'MIGRATION_INVALID_ORIGIN'});
    checks.push('unrelated-origin-rejected');
    const aborted = new AbortController();
    aborted.abort();
    await assert.rejects(migrateOwnedOriginStorage({...options, signal:aborted.signal}), {code:'MIGRATION_CANCELLED'});
    const duringLoad = new AbortController();
    await assert.rejects(migrateOwnedOriginStorage({...options, signal:duringLoad.signal, loadMigrationDocument:async(win,origin)=>{duringLoad.abort();await win.loadURL(origin+MIGRATION_PATH);}}), {code:'MIGRATION_CANCELLED'});
    checks.push('pre-start-and-in-flight-cancellation-destroy-hidden-windows');
    await assert.rejects(migrateOwnedOriginStorage({...options, loadMigrationDocument:(win)=>win.loadURL('about:blank')}), {code:'MIGRATION_INVALID_DOCUMENT'});
    checks.push('non-inert-document-refused-before-data-read');
    await source.webContents.executeJavaScript(`(async()=>{
      const db=await new Promise((resolve,reject)=>{const req=indexedDB.open('atomic-fixture',1);req.onupgradeneeded=()=>req.result.createObjectStore('items',{keyPath:'id'});req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error)});
      await new Promise((resolve,reject)=>{const tx=db.transaction('items','readwrite');tx.objectStore('items').add({id:1,title:'duplicate'});tx.objectStore('items').add({id:2,title:'duplicate'});tx.oncomplete=resolve;tx.onabort=()=>reject(tx.error)});db.close();return true;
    })()`);
    const invalidSnapshot=await invoke(source,'export','atomic-fixture');
    invalidSnapshot.schema[0].indexes.push({name:'must-be-unique',keyPath:'title',unique:true,multiEntry:false});
    await assert.rejects(invoke(destination,'import',invalidSnapshot),{code:'MIGRATION_STORAGE_ERROR'});
    assert.equal((await invoke(destination,'export','atomic-fixture')).count,0);
    assert.equal((await invoke(source,'export','atomic-fixture')).count,2);
    checks.push('failed-database-import-atomically-rolls-back-all-records');
    for (const [win, highKey] of [[source,0],[destination,10]]) await win.webContents.executeJavaScript(`(async()=>{
      const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('generator-conflict',1);r.onupgradeneeded=()=>r.result.createObjectStore('items',{autoIncrement:true});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});
      if(${highKey})await new Promise((resolve,reject)=>{const tx=db.transaction('items','readwrite');tx.objectStore('items').add('removed',${highKey});tx.objectStore('items').delete(${highKey});tx.oncomplete=resolve;tx.onabort=()=>reject(tx.error)});
      db.close();return true;
    })()`);
    await assert.rejects(invoke(destination,'import',await invoke(source,'export','generator-conflict')),{code:'MIGRATION_DESTINATION_CONFLICT'});
    assert.equal((await invoke(destination,'export','generator-conflict')).schema[0].nextKey,11);
    checks.push('empty-but-previously-used-destination-generator-refused-untouched');
    await ses.cookies.set({url:'http://127.0.0.1:3791/',name:'fixture-owned-cookie',value:'synthetic-owned-cookie',path:'/'});
    await newPortal.webContents.executeJavaScript("localStorage.setItem('fixture-conflict','old'); true");
    const portalOptions={...options,origins:[{from:'http://127.0.0.1:3791',to:'deepsteam://portal'}]};
    await assert.rejects(migrateOwnedOriginStorage(portalOptions),{code:'MIGRATION_COOKIE_BRIDGE_REQUIRED'});
    await assert.rejects(migrateOwnedOriginStorage({...portalOptions,migrateCookies:async()=>0}),{code:'MIGRATION_COOKIE_VERIFY_FAILED'});
    const cookieSummary=await migrateOwnedOriginStorage({...portalOptions,migrateCookies:async({session:cookieSession,from,cookies})=>{
      const retained=await cookieSession.cookies.get({domain:new URL(from).hostname});
      assert(cookies.every((cookie)=>retained.some((item)=>item.name===cookie.name&&item.value===cookie.value&&item.path===cookie.path)));
      return cookies.length;
    }});
    assert.equal(cookieSummary.cookies,1);
    checks.push('legacy-cookie-retained-and-explicit-bridge-required-before-marker');
    // Check Electron's actual custom-scheme cookie support without real secrets.
    let cookieSupport = false;
    try {
      await ses.cookies.set({url:'deepsteam://app/',name:'fixture-cookie',value:'synthetic',path:'/'});
      cookieSupport = (await ses.cookies.get({url:'deepsteam://app/'})).some((cookie)=>cookie.name==='fixture-cookie');
    } catch {}
    ses.flushStorageData();
    fs.writeFileSync(reportFile, JSON.stringify({passed:true,phase,checks,summary,customSchemeCookieSupport:cookieSupport,cloudRequests:0,privateProductProfileOpened:false},null,2));
  } else if (phase === 'reopen') {
    const destination = await windowAt(origins[1].to);
    assert.equal(await destination.webContents.executeJavaScript("localStorage.getItem('fixture-theme')"), 'new-user-choice');
    const data = await invoke(destination, 'export', 'MAIC-Database');
    assert.equal(data.version, 7);
    assert.equal(data.count, 5);
    assert.equal(data.schema.find((item)=>item.name==='auto').nextKey,52);
    assert.equal(data.schema.find((item)=>item.name==='out').nextKey,82);
    const summary = await migrateOwnedOriginStorage(options);
    assert.equal(summary.alreadyMigratedOrigins, 2);
    checks.push('actual-process-restart-retains-localstorage-indexeddb-blobs-marker', 'new-data-and-auto-generators-retained-after-reopen');
    fs.writeFileSync(reportFile, JSON.stringify({passed:true,phase,checks,summary,cloudRequests:0,privateProductProfileOpened:false},null,2));
  } else throw new Error('unknown fixture phase');
}
main().then(() => { for(const win of openWindows) if(!win.isDestroyed()) win.destroy(); app.quit(); }).catch((error) => {
  fs.writeFileSync(reportFile, JSON.stringify({passed:false,phase,code:error.code||'FIXTURE_FAILED',message:error.message,stack:error.stack},null,2));
  for(const win of openWindows) if(!win.isDestroyed()) win.destroy(); app.exit(1);
});
