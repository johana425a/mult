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
