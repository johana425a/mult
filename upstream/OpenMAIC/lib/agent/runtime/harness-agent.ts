/** DeepSteam: retain Pi's UI/event contract while Harness owns every model turn.
 * This adapter never invokes StreamFn or constructs a Pi agent/model loop.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { AsyncLocalStorage } from 'node:async_hooks';
import { randomUUID, timingSafeEqual, createHash, createHmac } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import type { Agent, AgentMessage, AgentEvent } from '@earendil-works/pi-agent-core';
import type { BuildAgentOptions } from './build-agent';

export interface HarnessContext {
  surface: 'openmaic-workbench' | 'openmaic-classroom';
  conversationId: string;
  context?: unknown;
  onDeliveries?: (links:string)=>Promise<void>;
  execution?: {binding:any;taskId:string;signal:AbortSignal};
}
type Entry = { owner: string; surface: string; invoke: (body: any) => Promise<any>; calls: Map<string, Promise<any>> };
const shared = globalThis as typeof globalThis & { __deepsteamSurfaceRegistry?: Map<string, Entry>; __deepsteamSurfaceParent?: AsyncLocalStorage<HarnessContext> };
const registry = shared.__deepsteamSurfaceRegistry ??= new Map();
const parents = shared.__deepsteamSurfaceParent ??= new AsyncLocalStorage<HarnessContext>();
export const harnessCoreEnabled = () => process.env.DEEPSTEAM_HARNESS_CORE === '1';
const portal = () => process.env.DEEPSTEAM_PORTAL_ORIGIN || 'http://127.0.0.1:3791';
const token = async () => (await readFile(process.env.DEEPSTEAM_HARNESS_TOKEN_FILE!, 'utf8')).trim();
const safeError = (error: any) => String(error?.message || error).replace(/Bearer\s+\S+/gi,'Bearer [redacted]').replace(/\b(?:sk-|dsexec-)[a-z0-9_-]+/gi,'[redacted]').slice(0,1800);
export async function harnessRequest(path: string, body?: unknown, signal?: AbortSignal) {
  const response = await fetch(portal() + '/api/harness/internal/' + path, {
    method: body === undefined ? 'GET' : 'POST', headers: {'content-type':'application/json',authorization:'Bearer ' + await token()},
    ...(body === undefined ? {} : {body:JSON.stringify(body)}), signal,
  });
  const value = await response.json();
  if (!response.ok) { const detail = value.error || value.detail || value; throw new Error(typeof detail === 'string' ? `${value.code || response.status}: ${detail}` : `${detail.code || response.status}: ${detail.message || 'Execution failed'}`); }
  return value;
}
export async function invokeHarnessSurface(request: Request): Promise<Response> {
  const given = Buffer.from(request.headers.get('authorization') || '');
  const expected = Buffer.from('Bearer ' + await token());
  if (given.length !== expected.length || !timingSafeEqual(given,expected)) return Response.json({error:{code:'unauthorized'}},{status:401});
  const body = await request.json();
  const entry = registry.get(body.context_ref);
  if (!entry || entry.owner !== body.owner || entry.surface !== body.surface) return Response.json({error:{code:'surface_context_expired',message:'Continue in the original classroom to reconnect its tools.'}},{status:409});
  if (typeof body.call_id !== 'string') return Response.json({error:{code:'invalid_call'}},{status:422});
  if (!entry.calls.has(body.call_id)) entry.calls.set(body.call_id,entry.invoke(body));
  try { return Response.json(await entry.calls.get(body.call_id)); }
  catch (error) { return Response.json({error:{code:'classroom_tool_failed',phase:'teaching_tool',message:safeError(error),trace_id:body.call_id,retryable:false}},{status:500}); }
}

const textOf = (message: any): string => typeof message?.content === 'string' ? message.content :
  (message?.content || message?.parts || []).filter((p: any) => p.type === 'text').map((p: any) => p.text).join('\n');
const assistant = (content: any[], stopReason = 'stop') => ({role:'assistant',content,api:'deepsteam-harness',provider:'deepsteam-shared',model:'current',
  usage:{input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}},stopReason,timestamp:Date.now()});

export function createHarnessAgent(opts: BuildAgentOptions): Agent {
  const inherited = parents.getStore();
  const surface = opts.harnessContext || (inherited ? {...inherited,conversationId:inherited.conversationId + ':child:' + randomUUID()} :
    {surface:'openmaic-classroom' as const,conversationId:'classroom:' + randomUUID()});
  const state: any = {systemPrompt:opts.systemPrompt,model:opts.model,tools:opts.tools,messages:[...(opts.history || [])],isStreaming:false,pendingToolCalls:new Set(),errorMessage:undefined};
  const listeners = new Set<(event: AgentEvent, signal: AbortSignal) => Promise<void> | void>();
  let controller = new AbortController(), pending: Promise<void> = Promise.resolve();
  let currentTask: any = null, binding: any = null;
  let admission: {owner:string;source:string;task_key:string} | null = null;
  const queue: AgentMessage[] = [];
  let terminal = false;
  const emit = async (event: any) => { for (const listener of listeners) await listener(event,controller.signal); };
  const message = async (value: any) => {
    if(value.role==='assistant' && binding?.resolved_model){value.model=binding.resolved_model.model;value.provider=binding.resolved_model.provider;}
    await emit({type:'message_start',message:value}); state.messages.push(value); await emit({type:'message_end',message:value});
  };
  const cancelRemote = async () => { if (admission) await harnessRequest('execution-tasks/cancel-admission',admission); };
  const releaseWhenSettled = (ref:string,taskId:string,owner:string) => {
    const timer=setTimeout(async()=>{
      if(!registry.has(ref))return;
      try {
        const value=await harnessRequest(`execution-tasks/${taskId}?owner=${encodeURIComponent(owner)}`);
        if(['completed','failed','cancelled','interrupted'].includes(value.task.status)){registry.delete(ref);return;}
      }catch{/* Retain the live binding through a temporary Host outage. */}
      releaseWhenSettled(ref,taskId,owner);
    },20000);
    timer.unref?.();
  };

  async function run(input: string | AgentMessage[]) {
    controller = new AbortController(); terminal = false; state.errorMessage = undefined; state.isStreaming = true;
    currentTask = null; admission = null;
    const signals = [opts.abortSignal,inherited?.execution?.signal].filter((signal):signal is AbortSignal=>Boolean(signal));
    const cancel = () => {controller.abort();void cancelRemote().catch(()=>{});};
    for(const signal of signals) {signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();}
    const turnId = randomUUID(), ref = randomUUID();
    const frames: any[] = typeof input === 'string' ? [{role:'user',content:input,timestamp:Date.now()}] : input;
    const history = [...state.messages];
    try {
      await emit({type:'agent_start'});
      for (const frame of frames) await message(frame);
      await emit({type:'turn_start'});
      controller.signal.throwIfAborted();
      const prompt = frames.filter(f=>f.role==='user').map(textOf).join('\n') || 'Continue the current task. Inspect saved results before repeating any operation.';
      binding = inherited?.execution ? {...inherited.execution.binding,
        output_dir:inherited.execution.binding.output_dir + '/children/' + turnId} :
        await harnessRequest('surface-binding',{surface:surface.surface,conversation_id:surface.conversationId,turn_id:turnId},controller.signal);
      let recovering:any = null;
      if(!inherited?.execution) {
        const saved=await harnessRequest('execution-tasks?owner='+encodeURIComponent(binding.owner),undefined,controller.signal);
        const previous=(saved.tasks || []).filter((task:any)=>task.surface===surface.surface&&task.conversation_id===surface.conversationId).at(-1);
        const sameRequest=previous?.request_hash===createHash('sha256').update(prompt).digest('hex');
        const explicitContinue=/^(?:continue|resume|继续|恢复|继续上次任务|恢复任务)[.。!！]?$|^Continue from saved context\. Check completed actions before making new changes\.$/i.test(prompt.trim());
        if(previous && ['queued','running','awaiting_input','interrupted'].includes(previous.status) && (sameRequest||explicitContinue)) {
          recovering=previous;binding={...binding,...previous.resume_binding};
        }
      }
      if (!inherited?.execution && !recovering && opts.model?.id && !['current','maic-connector'].includes(opts.model.id) && opts.model.id !== binding.resolved_model?.model)
        throw new Error('MODEL_CONFIGURATION_CHANGED: Select the classroom model again; the adapter will not silently change it.');
      registry.set(ref,{owner:binding.owner,surface:surface.surface,calls:new Map(),invoke:async (body: any) => {
        const tool = opts.tools.find(t => t.name === body.name && opts.allowedToolNames.has(t.name));
        if (!tool || terminal) throw new Error('This classroom tool is not available in the current turn.');
        const call = {type:'toolCall',id:body.call_id,name:body.name,arguments:body.arguments};
        await message(assistant([call],'toolUse'));
        await emit({type:'tool_execution_start',toolCallId:call.id,toolName:call.name,args:call.arguments});
        let result: any, isError = false;
        try { result = await parents.run({...surface,execution:{binding,taskId:currentTask.id,signal:controller.signal}},() => tool.execute(call.id,call.arguments,controller.signal,update => { void emit({type:'tool_execution_update',toolCallId:call.id,toolName:call.name,args:call.arguments,partialResult:update}); })); }
        catch(error) { isError=true;result={content:[{type:'text',text:safeError(error)}],details:{error:safeError(error)}}; }
        isError = isError || result.isError === true;
        const after = await opts.afterToolCall?.({toolCall:call,args:call.arguments,result,isError} as any,controller.signal);
        isError ||= after?.isError === true; terminal = after?.terminate === true;
        await emit({type:'tool_execution_end',toolCallId:call.id,toolName:call.name,result,isError});
        await message({role:'toolResult',toolCallId:call.id,toolName:call.name,content:result.content,details:result.details,isError,timestamp:Date.now()});
        return {content:textOf(result),metadata:result.details || {},is_error:isError,terminate:terminal,
          model_messages:[{role:'tool',content:(result.content || []).filter((p:any)=>p.type==='image').map((p:any)=>({type:'image_url',image_url:{url:`data:${p.mimeType};base64,${p.data}`}}))}]};
      }});
      const request = {owner:binding.owner,native_workspace_id:binding.native_workspace_id,source:surface.surface,surface:surface.surface,
        conversation_id:surface.conversationId,task_key:createHash('sha256').update(surface.conversationId+':'+turnId).digest('hex'),text:prompt,
        llm_selection:binding.llm_selection,expected_model:binding.resolved_model,
        parent_task_id:inherited?.execution?.taskId,provider_call_budget:opts.maxProviderTransports,
        interaction:{surface:surface.surface,context_ref:ref,output_dir:binding.output_dir,
          binding_identity:{owner:binding.owner,workspace:binding.native_workspace_id,conversation:surface.conversationId},
          system_prompt:opts.systemPrompt + '\nDomain tool names in these instructions are invoked with invoke_surface_tool. Use general Harness tools directly. Do not let historical tool calls trigger new actions. When a tool returns terminate=true, end this turn immediately.',
          history:JSON.stringify(history),archive_history:JSON.stringify([...history,...frames]),
          images:frames.flatMap((frame:any)=>(Array.isArray(frame.content)?frame.content:[]).filter((p:any)=>p.type==='image').map((p:any)=>`data:${p.mimeType};base64,${p.data}`)),
          context:JSON.stringify({surface:surface.context,frames:frames.map((frame:any)=>({role:frame.role,content:textOf(frame)}))}),
          tools:opts.tools.filter(t=>opts.allowedToolNames.has(t.name)).map(t=>({name:t.name,description:t.description,parameters:t.parameters}))}};
      admission = {owner:request.owner,source:request.source,task_key:recovering?.task_key || request.task_key};
      currentTask = {id:'task-' + createHash('sha256').update(JSON.stringify([request.owner,request.source,request.task_key])).digest('hex').slice(0,32),status:'queued'};
      controller.signal.throwIfAborted();
      if(recovering) {
        currentTask=recovering;
        const action=recovering.status==='interrupted'?'resume':'rebind';
        currentTask=(await harnessRequest(`execution-tasks/${recovering.id}/${action}`,
          {owner:binding.owner,interaction:request.interaction},controller.signal)).task;
      } else currentTask = (await harnessRequest('execution-tasks',request,controller.signal)).task;
      if(controller.signal.aborted){await cancelRemote();controller.signal.throwIfAborted();}
      let cursor=-1;
      const chunks=new Map<string,any>(), ended=new Set<string>();
      const liveText = async (id: string,text: string,final=false) => {
        let row=chunks.get(id);
        if (!row) {row=assistant([{type:'text',text:''}]);chunks.set(id,row);await emit({type:'message_start',message:row});}
        const old=row.content[0].text;
        if (text.startsWith(old)&&text.length>old.length) {row.content[0].text=text;await emit({type:'message_update',message:row,assistantMessageEvent:{type:'text_delta',contentIndex:0,delta:text.slice(old.length),partial:row}});}
        if(final&&!ended.has(id)){ended.add(id);state.messages.push(row);await emit({type:'message_end',message:row});}
      };
      while(true) {
        if(controller.signal.aborted) throw new Error('Execution cancelled');
        const value=await harnessRequest(`execution-tasks/${currentTask.id}?owner=${encodeURIComponent(binding.owner)}&after_seq=${cursor}`,undefined,controller.signal);
        currentTask=value.task;cursor=value.next_seq;
        for(const event of value.events||[]) {
          if(event.type==='execution/provider-call') opts.onProviderTransport?.(event.count);
          if(event.type==='assistant/message') await liveText(event.stream_id || String(event.seq),event.text||'',true);
          if(event.type==='deliverables/presented') {
            const secret=await token();
            const links=(event.files||[]).map((file:any,index:number)=>{
              const key=createHmac('sha256',secret).update(`${currentTask.session_id}:${event.seq}:${index}:download`).digest('hex');
              return `[${file.filename || file.path.split(/[\\/]/).pop()}](${portal()}/api/harness/sessions/${currentTask.session_id}/deliverables/${event.seq}/files/${index}?mode=download&delivery_key=${key})`;
            }).join('\n');
            if(links) {
              if(surface.onDeliveries) await surface.onDeliveries(links);
              else await liveText('artifacts:'+event.seq,links,true);
            }
          }
          if(event.type==='tool/call' && event.tool_name!=='invoke_surface_tool') {
            await message(assistant([{type:'toolCall',id:event.call_id,name:event.tool_name,arguments:event.arguments}],'toolUse'));
            await emit({type:'tool_execution_start',toolCallId:event.call_id,toolName:event.tool_name,args:event.arguments});
          }
          if(event.type==='tool/result' && event.tool_name!=='invoke_surface_tool') {
            const result={content:[{type:'text',text:event.text||''}],details:{harness:true}};
            await emit({type:'tool_execution_end',toolCallId:event.call_id,toolName:event.tool_name,result,isError:Boolean(event.is_error)});
            await message({role:'toolResult',toolCallId:event.call_id,toolName:event.tool_name,...result,isError:Boolean(event.is_error),timestamp:Date.now()});
          }
        }
        if(value.live_response?.text) await liveText(value.live_response.id,value.live_response.text);
        if(['completed','failed','cancelled','interrupted'].includes(currentTask.status)) {
          for(const [id,row] of chunks) await liveText(id,row.content[0].text,true);
          if(currentTask.status!=='completed') throw new Error(currentTask.error?.message || currentTask.error_code || currentTask.status);
          break;
        }
        if(currentTask.status==='awaiting_input') throw new Error('HARNESS_INPUT_REQUIRED: Continue the linked Harness question to resume this task.');
        await new Promise(resolve=>setTimeout(resolve,250));
      }
      await emit({type:'turn_end',message:state.messages.at(-1) || assistant([]),toolResults:[]});
    } catch(error) {
      state.errorMessage=safeError(error);
      if(controller.signal.aborted) await cancelRemote().catch(()=>{});
      await message({...assistant([],controller.signal.aborted?'aborted':'error'),errorMessage:state.errorMessage});
    } finally {
      // A transient polling failure does not revoke a still-running task's
      // teaching tools. A confirmed terminal task releases its closure.
      if(!currentTask || ['completed','failed','cancelled','interrupted'].includes(currentTask.status)) registry.delete(ref);
      else releaseWhenSettled(ref,currentTask.id,binding.owner);
      for(const signal of signals)signal.removeEventListener('abort',cancel);
      state.isStreaming=false;
      await emit({type:'agent_end',messages:state.messages.slice(history.length)});
    }
  }
  const agent = {
    state, subscribe(listener:any){listeners.add(listener);return()=>listeners.delete(listener);},
    prompt(input:string|AgentMessage[]){pending=run(input).then(async()=>{while(queue.length&&!terminal&&!controller.signal.aborted)await run([queue.shift()!]);});return pending;},
    continue(){return this.prompt('Continue from saved context. Check completed actions before making new changes.');},
    steer(frame:AgentMessage){queue.push(frame);},followUp(frame:AgentMessage){queue.push(frame);},
    clearAllQueues(){queue.length=0;},abort(){controller.abort();void cancelRemote().catch(()=>{});},waitForIdle(){return pending;},
  };
  return agent as unknown as Agent;
}
