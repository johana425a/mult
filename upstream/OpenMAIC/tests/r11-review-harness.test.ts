import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {mkdtemp,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {createHarnessAgent,invokeHarnessSurface} from '../lib/agent/runtime/harness-agent';
import {withAgentToolTimeout} from '../lib/agent/runtime/tool-timeout';

let calls:any[],handler:(path:string,body:any,init:any)=>Promise<any>;
const binding={owner:'fixture',workspace_id:'host-workspace',native_workspace_id:'native-workspace',
  resolved_model:{model:'frozen-A',configuration_revision:'original'},llm_selection:{model_id:'frozen-A'},output_dir:'fixture-output'};
const response=(value:any)=>Response.json(value);
const options=(extra:any={})=>({systemPrompt:'Fixture',tools:[],allowedToolNames:new Set<string>(),streamFn:()=>{throw Error('Pi transport must not run');},
  harnessContext:{surface:'openmaic-classroom',conversationId:'fixture-conversation'},...extra} as any);
beforeEach(async()=>{
  calls=[];process.env.DEEPSTEAM_HARNESS_TOKEN_FILE=join(await mkdtemp(join(tmpdir(),'ds-review-')),'token');
  await writeFile(process.env.DEEPSTEAM_HARNESS_TOKEN_FILE,'fixture-only');
  handler=async(path,body)=>{
    if(path==='surface-binding')return binding;
    if(path.startsWith('execution-tasks?'))return {tasks:[]};
    if(path==='execution-tasks')return {task:{...body,id:'task-'+calls.length,status:'running'}};
    return {task:{id:'done',status:'completed'},next_seq:2,events:[]};
  };
  vi.stubGlobal('fetch',async(url:any,init:any={})=>{
    const path=String(url).split('/api/harness/internal/')[1];
    const body=init.body?JSON.parse(init.body):undefined;calls.push({path,body});
    return response(await handler(path,body,init));
  });
});
afterEach(()=>{vi.unstubAllGlobals();delete process.env.OPENMAIC_AGENT_TOOL_TIMEOUT_MS;});

it('teacher inherits the parent model, owner, workspace and cancellation context',async()=>{
  const base=handler;
  handler=async(path,body,init)=>{
    if(path==='execution-tasks' && !body.parent_task_id){
      const request=new Request('http://fixture',{method:'POST',headers:{authorization:'Bearer fixture-only','content-type':'application/json'},
        body:JSON.stringify({owner:body.owner,surface:body.surface,context_ref:body.interaction.context_ref,call_id:'teacher-call',name:'teacher',arguments:{}})});
      const result=await invokeHarnessSurface(request);expect(result.status).toBe(200);
    }
    return base(path,body,init);
  };
  const teacher={name:'teacher',description:'Fixture',parameters:{},execute:async()=>{
    const child=createHarnessAgent(options({harnessContext:undefined,model:{id:'new-global-B'}}));
    await child.prompt('Child task');expect(child.state.errorMessage).toBeUndefined();
    return {content:[{type:'text',text:'Child finished'}]};
  }};
  const agent=createHarnessAgent(options({tools:[teacher],allowedToolNames:new Set(['teacher'])}));
  await agent.prompt('Parent task');expect(agent.state.errorMessage).toBeUndefined();
  const admissions=calls.filter(call=>call.path==='execution-tasks');expect(admissions).toHaveLength(2);
  const child=admissions.find(call=>call.body.parent_task_id)!.body;
  expect(child.expected_model).toEqual(binding.resolved_model);expect(child.llm_selection).toEqual(binding.llm_selection);
  expect(child.owner).toBe(binding.owner);expect(child.native_workspace_id).toBe(binding.native_workspace_id);
  expect(calls.filter(call=>call.path==='surface-binding')).toHaveLength(1);
});

it('cancellation before the POST response cancels the stable admission key',async()=>{
  const cancel=new AbortController(),base=handler;
  handler=async(path,body,init)=>{
    if(path==='execution-tasks'){cancel.abort();throw new DOMException('Cancelled','AbortError');}
    return base(path,body,init);
  };
  await createHarnessAgent(options({abortSignal:cancel.signal})).prompt('Write fixture');
  const admitted=calls.find(call=>call.path==='execution-tasks')!.body;
  expect(calls.some(call=>call.path==='execution-tasks/cancel-admission'&&call.body.task_key===admitted.task_key)).toBe(true);
});

it('reconnect rebinds the original task and frozen model instead of submitting again',async()=>{
  const base=handler;
  handler=async(path,body,init)=>{
    if(path==='surface-binding')return {...binding,resolved_model:{model:'new-global-B'}};
    if(path.startsWith('execution-tasks?'))return {tasks:[{id:'task-existing',task_key:'original-key',surface:'openmaic-classroom',
      conversation_id:'fixture-conversation',status:'interrupted',request_hash:createHash('sha256').update('Read source').digest('hex'),resume_binding:binding}]};
    if(path==='execution-tasks/task-existing/resume')return {task:{id:'task-existing',status:'running'}};
    return base(path,body,init);
  };
  const agent=createHarnessAgent(options());await agent.prompt('Read source');
  expect(agent.state.errorMessage).toBeUndefined();expect(calls.some(call=>call.path==='execution-tasks')).toBe(false);
  expect(calls.find(call=>call.path.endsWith('/resume'))?.body.interaction.output_dir).toBe(binding.output_dir);
});

it('provider-call budget and actual transport count survive the adapter',async()=>{
  const counts:number[]=[],base=handler;
  handler=async(path,body,init)=>path.includes('&after_seq=')?{task:{id:'done',status:'completed'},next_seq:3,
    events:[{seq:3,type:'execution/provider-call',count:2}]}:base(path,body,init);
  const agent=createHarnessAgent(options({maxProviderTransports:2,onProviderTransport:(count:number)=>counts.push(count)}));
  await agent.prompt('Bounded task');expect(calls.find(call=>call.path==='execution-tasks')?.body.provider_call_budget).toBe(2);
  expect(counts).toEqual([2]);
});

it('tool timeout aborts the actual derived signal',async()=>{
  process.env.OPENMAIC_AGENT_TOOL_TIMEOUT_MS='15';let observed:AbortSignal|undefined;
  const tool=withAgentToolTimeout({name:'fixture-hung',execute:async(_id:any,_args:any,signal:AbortSignal)=>{observed=signal;return new Promise(()=>{});}} as any);
  await expect(tool.execute('call',{},new AbortController().signal)).rejects.toThrow('execution budget');
  expect(observed?.aborted).toBe(true);
});

it.each(['openmaic-workbench','openmaic-classroom'])('child questions hand off once through the native %s tool',async(surface)=>{
  for(const questions of [[{question:'Which source?',options:[{id:'a',label:'A'},{id:'b',label:'B'}]}],
    [{question:'Describe your goal'}],[{question:'Select topics',multiSelect:true,options:[{id:'a',label:'A'},{id:'b',label:'B'}]},{question:'How much time?'}]]) {
    const shown:any[]=[],base=handler;
    const invoke=async(body:any,name:string,args:any,callId:string)=>invokeHarnessSurface(new Request('http://fixture',{method:'POST',
      headers:{authorization:'Bearer fixture-only','content-type':'application/json'},body:JSON.stringify({owner:body.owner,surface:body.surface,
        context_ref:body.interaction.context_ref,name,arguments:args,call_id:callId})}));
    handler=async(path,body,init)=>{
      if(path==='execution-tasks') {
        if(body.parent_task_id) {
          expect(body.interaction.tools.some((t:any)=>t.name==='request_parent_input')).toBe(true);
          const first=await invoke(body,'request_parent_input',{questions},'child-question');expect(first.status).toBe(200);
          expect((await first.json()).terminate).toBe(true);
        } else {
          expect((await invoke(body,'teacher',{},'teacher-call')).status).toBe(200);
          // HTTP retry must not show the same question again.
          expect((await invoke(body,'teacher',{},'teacher-call')).status).toBe(200);
        }
      }
      return base(path,body,init);
    };
    const native=surface==='openmaic-workbench'?'ask_user':'cue_user';
    const teacher={name:'teacher',parameters:{},execute:async()=>{
      const child=createHarnessAgent(options({harnessContext:undefined}));await child.prompt('Teach');
      expect(child.state.errorMessage).toBeUndefined();
      expect((child.state as any).needsInput.questions).toEqual(questions);
      return {content:[{type:'text',text:'Teacher needs user input'}]};
    }};
    const ask={name:native,parameters:{},execute:async(_id:any,args:any)=>{shown.push(args);return {content:[{type:'text',text:'Question displayed'}],details:{emitted:true}};}};
    const before=calls.filter(c=>c.path==='execution-tasks').length;
    const agent=createHarnessAgent(options({harnessContext:{surface,conversationId:'q'},tools:[teacher,ask],allowedToolNames:new Set(['teacher',native]),
      afterToolCall:({toolCall}:any)=>({terminate:toolCall.name===native})}));
    await agent.prompt('Teach and ask');expect(agent.state.errorMessage).toBeUndefined();
    expect(shown).toHaveLength(1);expect(JSON.stringify(shown)).toContain(questions[0].question);
    for(const question of questions)expect(JSON.stringify(shown)).toContain(question.question);
    if(native==='ask_user'&&questions.length===1)expect(shown[0]).toEqual(questions[0]);
    expect(calls.filter(c=>c.path==='execution-tasks').length-before).toBe(2);
    handler=base;
  }
});

it('a pre-existing generic waiting task reconnects and transfers its actual envelope without a new admission or fake answer',async()=>{
  const base=handler;const shown:any[]=[];
  handler=async(path,body,init)=>{
    if(path.startsWith('execution-tasks?'))return {tasks:[{id:'task-waiting',task_key:'original',surface:'openmaic-workbench',conversation_id:'waiting',status:'awaiting_input',
      request_hash:createHash('sha256').update('Question').digest('hex'),resume_binding:binding}]};
    if(path.endsWith('/rebind'))return {task:{id:'task-waiting',status:'running'}};
    if(path.includes('&after_seq='))return {task:{id:'task-waiting',status:'awaiting_input'},next_seq:1,events:[],
      capabilities:{pending_questions:[{id:'original-question',questions:[{id:'q',question:'Pick a source',options:[{label:'A'},{label:'B'}]}]}]}};
    return base(path,body,init);
  };
  const ask={name:'ask_user',parameters:{},execute:async(_id:any,args:any)=>{shown.push(args);return {content:[{type:'text',text:'Shown'}]};}};
  const agent=createHarnessAgent(options({harnessContext:{surface:'openmaic-workbench',conversationId:'waiting'},tools:[ask],allowedToolNames:new Set(['ask_user'])}));
  await agent.prompt('Question');expect(agent.state.errorMessage).toBeUndefined();expect(shown).toHaveLength(1);
  expect(shown[0].options[0]).toEqual({id:'q-1',label:'A'});
  expect(calls.some(c=>c.path==='execution-tasks')).toBe(false);expect(calls.some(c=>c.path.endsWith('/answer'))).toBe(false);
  expect(calls.filter(c=>c.path==='execution-tasks/cancel-admission')).toHaveLength(1);
  expect(calls.find(c=>c.path==='execution-tasks/cancel-admission')?.body.task_key).toBe('original');
});

it('OpenMAIC rebind fingerprints source versions but ignores connection refs and question text',async()=>{
  const snapshots:any[]=[];
  for(const version of [1,1,2]) {
    const agent=createHarnessAgent(options({harnessContext:{surface:'openmaic-workbench',conversationId:'source',sourceSnapshot:{source_id:'book',version}}}));
    await agent.prompt('Read');snapshots.push(calls.filter(c=>c.path==='execution-tasks').at(-1)?.body.interaction.source_snapshot);
  }
  expect(snapshots[0]).toEqual(snapshots[1]);expect(snapshots[1]).not.toEqual(snapshots[2]);
});
