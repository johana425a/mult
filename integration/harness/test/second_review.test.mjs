import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createExecutionTasks, executionTaskId} from '../execution_tasks.mjs';
import {createTaskLedger} from '../task_ledger.mjs';

const temporary = prefix => mkdtemp(join(process.env.DEEPSTEAM_HARNESS_TEST_ROOT || tmpdir(), prefix));
const input = {owner:'owner', source:'reading', surface:'reading', task_key:'same', workspace_id:'workspace', text:'Read the source'};
const interaction = {surface:'reading', context_ref:'one', tools:[], binding_identity:{owner:'owner',workspace:'workspace',conversation:'c'},
  source_snapshot:[{owner:'owner',scope:'workspace',source_id:'book',version:1,sha256:'same-bytes',grant_version:1}]};
function workspace() {
  let calls=0;
  return {get calls(){return calls;},async createSession(){return {session:{id:'s'}};},
    async events(){return {session:{status:'idle'},events:[],next_seq:-1};},
    async turn(){calls++;return {run_id:'run'};},async cancel(){}};
}

test('T1 persisted cancellation windows remain cancelled through retry, get, rebind and resume',async()=>{
  for(const status of ['queued','running','cancelling','interrupted','cancelled']) {
    const profile=await temporary('second-cancel-'), ws=workspace();
    const seed=await createExecutionTasks({profile,workspaces:ws,pollMs:1});
    const first=await seed.create({...input,interaction}); await seed.close();
    const path=join(profile,'execution-tasks','tasks.json'), saved=JSON.parse(await readFile(path,'utf8'));
    saved.tasks[first.task.id].status=status;
    saved.cancellations[first.task.id]={owner:input.owner,cancelled_at:'2026-10-17T00:00:00Z'};
    await writeFile(path,JSON.stringify(saved));
    const nextWs=workspace(), next=await createExecutionTasks({profile,workspaces:nextWs,pollMs:1});
    try {
      assert.equal((await next.create({...input,interaction})).task.status,'cancelled',status);
      assert.equal((await next.get(first.task.id,input.owner)).task.status,'cancelled');
      await assert.rejects(next.rebind(first.task.id,input.owner,{...interaction,context_ref:'fresh'}),{code:'execution_task_cancelled'});
      await assert.rejects(next.resume(first.task.id,input.owner,interaction),{code:'execution_task_cancelled'});
      assert.equal(nextWs.calls,0);
      assert.equal((await next.create({...input,task_key:'explicit-new',interaction})).reused,false);
    } finally {await next.close();}
  }
});

test('T1 legacy cancelling and cancelled parents also stop interrupted children',async()=>{
  const profile=await temporary('second-parent-');await mkdir(join(profile,'execution-tasks'));
  const parent=executionTaskId(input.owner,input.source,'parent'), child=executionTaskId(input.owner,input.source,'child');
  await writeFile(join(profile,'execution-tasks','tasks.json'),JSON.stringify({tasks:{
    [parent]:{...input,id:parent,prompt:'Parent',status:'cancelling'},
    [child]:{...input,id:child,prompt:'Child',status:'interrupted',parent_task_id:parent}},cancellations:{}}));
  const tasks=await createExecutionTasks({profile,workspaces:workspace()});
  try {assert.equal((await tasks.get(child,input.owner)).task.status,'cancelled');
    await assert.rejects(tasks.resume(child,input.owner),{code:'execution_task_cancelled'});
  } finally {await tasks.close();}
});

test('T2 only an identical source and grant snapshot may receive a new connection ref',async()=>{
  const profile=await temporary('second-rebind-'), tasks=await createExecutionTasks({profile,workspaces:workspace(),pollMs:1});
  try {
    const first=await tasks.create({...input,interaction});
    await tasks.rebind(first.task.id,input.owner,{...interaction,context_ref:'fresh'});
    for(const delta of [{version:2},{source_id:'other'},{scope:'other'},{grant_version:2},{sha256:'other'}]) {
      const changed={...interaction,context_ref:'changed',source_snapshot:[{...interaction.source_snapshot[0],...delta}]};
      await assert.rejects(tasks.rebind(first.task.id,input.owner,changed),{code:'execution_source_context_changed'});
      await assert.rejects(tasks.create({...input,interaction:changed}),{code:'execution_source_context_changed'});
    }
  } finally {await tasks.close();}
});

test('L1 cold concurrent ledger mutations preserve 2, 10 and 100 sources after reopening',async()=>{
  for(const count of [2,10,100]) {
    const profile=await temporary('second-ledger-');
    for(const existing of [false,true]) {
      const ledger=await createTaskLedger(profile);
      await Promise.all(Array.from({length:count},(_,index)=>ledger.recordDocument('s',`${existing?'new':'old'}-${index}.pdf`,{
        ok:true,document:{sha256:'hash-'+index,unit_count:0},units:[]})));
      assert.equal((await ledger.read('s')).coverage.source_count,count*(existing?2:1));
      assert.equal((await (await createTaskLedger(profile)).read('s')).coverage.source_count,count*(existing?2:1));
    }
  }
});

test('L2 same bytes at a new extraction version never inherit old completion or notes',async()=>{
  const profile=await temporary('second-version-');let version=1;
  const resolveSource=async(_id,path,result)=>result._source_binding || ({owner:'owner',scope:'workspace',source_id:'book',version,sha256:'raw',aliases:['book.pdf','C:/book.pdf',`reading:book@${version}`]});
  let ledger=await createTaskLedger(profile,{resolveSource});
  await ledger.recordDocument('s','book.pdf',{ok:true,document:{sha256:'raw',unit_count:1},units:[
    {unit_index:1,char_start:0,char_end:4,total_chars:4,unit_text_sha256:'text',locator:{page:1}}]});
  const old=(await ledger.read('s')).sources[0].path;
  await ledger.update('s',{source_path:old,source_summary:'Version one note'});
  assert.equal((await ledger.source('s','book.pdf')).complete,true);
  version=2;
  await ledger.recordTeaching('s',[{type:'reading',material_id:'book',material_revision:2,page:1,
    _source_binding:await resolveSource('s','book.pdf',{})}]);
  const current=await ledger.source('s','book.pdf');
  assert.equal(current.complete,false);assert.equal(current.source_summary,'');
  assert.equal((await ledger.source('s',old)).complete,true);
  assert.equal((await ledger.read('s')).coverage.complete_count,0);
  ledger=await createTaskLedger(profile,{resolveSource});
  assert.equal((await ledger.source('s','C:/book.pdf')).complete,false);
  assert.equal((await ledger.source('s',old)).source_summary,'Version one note');
});
