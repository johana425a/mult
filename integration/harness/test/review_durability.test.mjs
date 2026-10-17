import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,unlink} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {createImmutableDeliveries} from '../immutable_deliveries.mjs';
import {createOperationReceipts} from '../operation_receipts.mjs';
import {configurationTransaction} from '../configuration_transaction.mjs';
import {installExtensionTools} from '../extensions.mjs';
const temporary=()=>mkdtemp(join(process.env.DEEPSTEAM_HARNESS_TEST_ROOT||tmpdir(),'review-durability-'));

test('delivery remains byte-identical after overwrite, delete and service reconstruction',async()=>{
  const root=await temporary(),source=join(root,'Chinese path with spaces.md');
  const validate=async paths=>Promise.all(paths.map(async path=>{const data=await readFile(path);return {sha256:createHash('sha256').update(data).digest('hex'),size_bytes:data.length,format:'md',verified:true};}));
  let store=await createImmutableDeliveries(join(root,'private'),validate);
  await writeFile(source,'original revision');const files=await store.capture('owner:task:call',[source]);
  await writeFile(source,'later revision');assert.equal((await store.read('owner:task:call',0)).binary.toString(),'original revision');
  await unlink(source);store=await createImmutableDeliveries(join(root,'private'),validate);
  assert.equal((await store.read('owner:task:call',0)).binary.toString(),'original revision');
  await writeFile(files[0].snapshot_path,'tampered');await assert.rejects(store.read('owner:task:call',0),{code:'DELIVERABLE_SNAPSHOT_CHANGED'});
});

test('completed operations replay receipts; uncertain effects and changed arguments never rerun',async()=>{
  const root=await temporary();let count=0;
  let store=await createOperationReceipts(root);
  const descriptor={name:'write',arguments:{path:'a'}};
  await store.execute(['owner','task','call'],descriptor,async()=>({count:++count}));
  store=await createOperationReceipts(root);
  assert.deepEqual(await store.execute(['owner','task','call'],descriptor,async()=>({count:++count})),{count:1});
  await assert.rejects(store.execute(['owner','task','call'],{name:'write',arguments:{path:'b'}},async()=>++count),{code:'OPERATION_IDENTITY_CONFLICT'});
  await assert.rejects(store.execute(['owner','task','crash'],descriptor,async()=>{count++;throw new Error('simulated crash after external effect');}));
  store=await createOperationReceipts(root);
  await assert.rejects(store.execute(['owner','task','crash'],descriptor,async()=>++count),{code:'OPERATION_OUTCOME_UNCERTAIN'});
  assert.equal(count,2);
});

test('two-file configuration recovers after either write and rejects unrelated edits',async()=>{
  for(const stop of [0,1]) {
    const root=await temporary(), paths=[join(root,'config.json'),join(root,'registry.json')],journal=join(root,'transaction.json');
    await Promise.all(paths.map(path=>writeFile(path,'{}')));
    const original=configurationTransaction(journal,paths,{afterWrite:index=>{if(index===stop)throw new Error('crash');}});
    await assert.rejects(original.commit([{servers:[{serverName:'memory'}]},{extensions:{memory:{enabled:true}}}]));
    await configurationTransaction(journal,paths).recover();
    const [a,b]=await Promise.all(paths.map(async path=>JSON.parse(await readFile(path,'utf8'))));
    assert.equal(a.deepsteam_generation,b.deepsteam_generation);assert.equal(a.servers.length,1);assert.equal(b.extensions.memory.enabled,true);
  }
});

test('MCP remove-remove-rollback is idempotent and restores the same activation',async()=>{
  const root=await temporary(), profile=join(root,'profile'),extensions=join(root,'extensions');await mkdir(profile);await mkdir(extensions);
  const server={serverName:'fixture',command:'node',args:['immutable-v1.js']};
  await writeFile(join(profile,'mcp-servers.json'),JSON.stringify({servers:[server]}));
  await writeFile(join(extensions,'registry.json'),JSON.stringify({schema:1,extensions:{fixture:{id:'fixture',type:'mcp',enabled:true,server,path:'retained'}}}));
  let tool;const ctx={effect:fn=>fn(),tools:{register:value=>{tool=value;}}};
  await installExtensionTools(ctx,{profile,extensionsRoot:extensions});
  const invoke=action=>tool.execute({action,id:'fixture'},{signal:new AbortController().signal});
  assert.equal((await invoke('remove')).status,'disabled');assert.equal((await invoke('remove')).reused,true);
  assert.equal((await invoke('rollback')).status,'rolled_back');
  const registry=JSON.parse(await readFile(join(extensions,'registry.json'),'utf8'));
  const config=JSON.parse(await readFile(join(profile,'mcp-servers.json'),'utf8'));
  assert.equal(registry.extensions.fixture.enabled,true);assert.equal(config.servers.length,1);assert.equal(registry.deepsteam_generation,config.deepsteam_generation);
});
