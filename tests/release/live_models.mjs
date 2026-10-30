import {pathToFileURL} from 'node:url';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
const root=process.env.DS_TEST_PACKAGE,work=process.env.DS_TEST_WORK;
const base=`http://127.0.0.1:${process.env.DS_TEST_MODEL_PORT}`;
const {createHost}=await import(pathToFileURL(join(root,'runtime/harness/host.mjs')));
const {requestCredential,DeepSteamCredentials}=await import(pathToFileURL(join(root,'runtime/harness/credentials.mjs')));
const {convertRequest,openAiResponse}=await import(pathToFileURL(join(root,'runtime/harness/protocol.mjs')));
const load=DeepSteamCredentials.prototype.load;let grant;
DeepSteamCredentials.prototype.load=async function(){return grant??=await load.call({options:{...this.options,path:process.env.DS_TEST_CREDENTIAL_PATH}});};
DeepSteamCredentials.prototype.save=async value=>{grant=value;};
const profile=join(work,'isolated-profile'),workspace=join(work,'isolated-workspace');
await mkdir(profile,{recursive:true});await mkdir(workspace,{recursive:true});
await writeFile(join(workspace,'fixture.txt'),'RELEASE_FILE_OK_43\n');
const resolved=[];
const host=await createHost({profile,sessions:join(profile,'sessions'),port:Number(process.env.DS_TEST_HOST_PORT),
 python:join(root,'runtime/python/python.exe'),credentialHelper:join(root,'runtime/harness/credential_store.py'),
 documentHelper:join(root,'scripts/workspace_document_reader.py'),protectedPaths:[root],
 async resolveWorkspaceRoute(selection){
   const r=await fetch(base+'/freeze/'+encodeURIComponent(selection.model),{method:'POST',headers:{Authorization:'Bearer '+process.env.DS_TEST_GUARD}});
   if(!r.ok)throw Error('Model selection failed: HTTP '+r.status);
   const route=await r.json();resolved.push(route.resolved_model);
   return {...route,runWithCredentials:cb=>requestCredential.run({apiKey:route.api_key},cb)};
 },async resolveWorkspaceMetadata(){return null;}});
host.ctx.effect(()=>host.ctx.webServer.registerFallback(async(req,res)=>{
 if(req.url!=='/v1/chat/completions'||req.method!=='POST'){res.writeHead(404);res.end();return;}
 if(req.headers.authorization!=='Bearer '+process.env.DS_TEST_GUARD){res.writeHead(401);res.end();return;}
 const chunks=[];for await(const c of req)chunks.push(c);const body=JSON.parse(Buffer.concat(chunks));
 if(!['deepseek-flash','deepseek-v4-pro'].includes(body.model)){res.writeHead(400);res.end();return;}
 const converted=await convertRequest({...body,provider:'deepseek-account'},host.ctx);
 await openAiResponse(host.ctx,{...converted,provider:'deepseek-account',model:body.model,publicModel:body.model},res,Boolean(body.stream));
}));
const rows=[];
try{
 const registered=await host.workspaces.register({path:workspace,name:'Isolated release regression'});
 const matrix=['gpt-6.1-sol','deepseek-flash','deepseek-v4-pro'].flatMap(model=>['text','tool'].map(kind=>({model,kind})));
 matrix.push({model:'synthetic-connection-failure',kind:'fault'});
 for(const {model,kind} of matrix){
  const {session}=await host.workspaces.createSession({workspace_id:registered.workspace.id,title:'Release test '+kind});
  const started=Date.now(),firstRoute=resolved.length;
  const prompt=kind==='text'?'Isolated software regression test. Do not use tools. Reply with exactly RELEASE_TEXT_OK_17.':
    'Isolated software regression test, not a learning record. Use the read tool to read fixture.txt in the current workspace. Do not modify files, run shell, browse or delegate. Reply with exactly the complete token inside the file.';
  await host.workspaces.turn(session.id,{text:prompt,llm_selection:{model},access_level:'workspace'});
  let value;
  do{await new Promise(r=>setTimeout(r,250));value=await host.workspaces.events(session.id);}while(value.session.status==='running'&&Date.now()-started<120000);
  if(value.session.status==='running')await host.workspaces.cancel(session.id);
  const calls=value.events.filter(e=>e.type==='tool/call'),answers=value.events.filter(e=>e.type==='assistant/message');
  const final=answers.at(-1)?.text??'',errors=value.events.filter(e=>e.type==='turn/end'&&e.outcome==='error');
  const readResult=value.events.some(e=>e.type==='tool/result'&&e.tool_name==='read'&&!e.is_error&&e.text?.includes('RELEASE_FILE_OK_43'));
  const selections=resolved.slice(firstRoute),frozen=selections.length>0&&selections.every(x=>x.model===model&&x.reasoning_effort==='high');
  let passed=value.session.status!=='running'&&errors.length===0&&frozen&&
    (kind==='text'?final.trim()==='RELEASE_TEXT_OK_17'&&calls.length===0:
      final.trim()==='RELEASE_FILE_OK_43'&&calls.some(c=>c.tool_name==='read')&&readResult);
  let attempts;
  if(kind==='fault'){
    attempts=(await(await fetch(base+'/counts',{headers:{Authorization:'Bearer '+process.env.DS_TEST_GUARD}})).json()).attempts;
    passed=value.session.status!=='running'&&errors.length===1&&!final&&attempts===3;
  }
  // Synthetic content only. Do not serialize auth headers, route keys or grants.
  rows.push({model,case:kind,seconds:(Date.now()-started)/1000,status:value.session.status,
    tool_names:calls.map(c=>c.tool_name),tool_result_verified:readResult,answer:final,error_count:errors.length,frozen_selection:frozen,attempts,passed});
  await writeFile(join(work,'live-model-transcript.json'),JSON.stringify(rows,null,2));
  console.log(JSON.stringify(rows.at(-1)));
 }
}finally{await host.ctx.fiber.dispose();}
if(rows.length!==7||rows.some(x=>!x.passed))process.exitCode=1;
