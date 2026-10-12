/** OpenAI wire conversion with strict image admission through the official attachment service. */
import { randomUUID } from 'node:crypto';
import { createUserMessage } from '@deepseek-ai/dsh-llm';
import Ajv from 'ajv';
import Ajv2020 from 'ajv/dist/2020.js';
import Ajv2019 from 'ajv/dist/2019.js';
import addFormats from 'ajv-formats';

function invalid(message) { return Object.assign(new Error(message), { status: 400, code: 'INVALID_REQUEST' }); }
function responseValidation(format) {
  if (!format || format.type === 'text') return {};
  if (format.type === 'json_object') return { system: 'Return a single valid JSON object, without Markdown fences or text outside JSON.', responseValidator: value => value !== null && typeof value === 'object' && !Array.isArray(value) };
  if (format.type !== 'json_schema' || !format.json_schema?.schema) throw invalid('Unsupported response_format');
  const schema = format.json_schema.schema;
  const Constructor = String(schema.$schema ?? '').includes('2020-12') ? Ajv2020 : String(schema.$schema ?? '').includes('2019-09') ? Ajv2019 : Ajv;
  const validator = new Constructor({ strict: false, logger: false, allErrors: false, validateFormats: true });
  addFormats(validator);
  let validate; try { validate = validator.compile(schema); } catch { throw invalid('JSON response schema cannot be validated'); }
  return { system: 'Return only valid JSON satisfying this JSON Schema. Do not use Markdown fences or add prose outside JSON. Schema:\n' + JSON.stringify(schema), responseValidator: value => Boolean(validate(value)) };
}

export async function convertRequest(body, ctx) {
  if (!Array.isArray(body.messages) || !body.messages.length || body.messages.length > 200) throw Object.assign(new Error('messages must be a nonempty array'), { status: 400 });
  const messages = [];
  for (const input of body.messages) {
    if (!['system', 'developer', 'user', 'assistant', 'tool'].includes(input.role)) throw Object.assign(new Error('Unsupported message role'), { status: 400 });
    const content = [];
    const parts = typeof input.content === 'string' ? [{ type: 'text', text: input.content }] : Array.isArray(input.content) ? input.content : [];
    for (const part of parts) {
      if (part.type === 'text' && typeof part.text === 'string') content.push({ type: 'text', text: part.text });
      else if (part.type === 'image_url' && input.role === 'user') {
        const image = /^data:(image\/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\r\n]+)$/.exec(part.image_url?.url ?? '');
        if (!image) throw Object.assign(new Error('Only inline data images are accepted by the local gateway'), { status: 400 });
        const data = Buffer.from(image[2], 'base64');
        const attachment = await ctx.attachments.saveImage({ data, mediaType: image[1] });
        content.push({ type: 'image', attachment });
      } else throw Object.assign(new Error('Unsupported content block'), { status: 400 });
    }
    if (input.role === 'user') messages.push(createUserMessage({ content, source: { kind: 'user' } }));
    else if (input.role === 'tool') {
      if (typeof input.tool_call_id !== 'string' || !input.tool_call_id) throw invalid('Tool result needs tool_call_id');
      messages.push({ role: 'tool', id: randomUUID(), toolCallId: input.tool_call_id, isError: false, content, source: { kind: 'tool', callId: input.tool_call_id } });
    }
    else if (input.role === 'assistant') messages.push({ role: 'assistant', id: randomUUID(), content: [...content, ...(input.tool_calls ?? []).map(call => ({ type: 'tool-call', id: call.id, name: call.function.name, arguments: call.function.arguments }))], source: { kind: 'model', provider: body.provider, model: body.model } });
    else messages.push({ role: input.role, id: randomUUID(), content, source: { kind: input.role === 'system' ? 'system-prompt' : 'user' } });
  }
  let tools = (body.tools ?? []).map(tool => {
    if (tool.type !== 'function' || !tool.function?.name) throw Object.assign(new Error('Unsupported tool declaration'), { status: 400 });
    return { name: tool.function.name, description: tool.function.description ?? '', parameters: tool.function.parameters ?? { type: 'object', properties: {} } };
  });
  const toolChoice = body.tool_choice ?? 'auto';
  let toolInstruction = '';
  if (toolChoice === 'none') tools = [];
  else if (toolChoice === 'required') { if (!tools.length) throw invalid('Required tool choice needs tools'); toolInstruction = 'You must call at least one provided tool in this response.'; }
  else if (typeof toolChoice === 'object' && toolChoice?.type === 'function' && typeof toolChoice.function?.name === 'string') {
    tools = tools.filter(tool => tool.name === toolChoice.function.name);
    if (!tools.length) throw invalid('Named tool choice is not declared');
    toolInstruction = 'You must call the provided tool named ' + toolChoice.function.name + ' in this response.';
  } else if (toolChoice !== 'auto') throw invalid('Unsupported tool_choice');
  if (body.top_p !== undefined && body.top_p !== 1) throw invalid('top_p is not supported by this Harness route');
  if (body.n !== undefined && body.n !== 1) throw invalid('Only one completion is supported');
  const response = responseValidation(body.response_format);
  const reasoningEffort = body.thinking?.type === 'disabled' ? 'off' : body.reasoning_effort;
  if (reasoningEffort !== undefined && !['off', 'low', 'high', 'max'].includes(reasoningEffort)) throw invalid('Unsupported reasoning_effort');
  return { messages, tools, ...response, system: [response.system, toolInstruction].filter(Boolean).join('\n\n') || undefined,
    toolChoice, parallelToolCalls: body.parallel_tool_calls, reasoningEffort, maxTokens: body.max_completion_tokens ?? body.max_tokens, temperature: body.temperature, stop: typeof body.stop === 'string' ? [body.stop] : body.stop };
}

export function failureInfo(failure) {
  const code = failure?.code ?? 'MODEL_CONNECTION_FAILED';
  const messages = {
    ACCOUNT_SIGN_IN_REQUIRED: 'Sign in to DeepSeek on the official page first.', ACCOUNT_TOKEN_INVALID: 'DeepSeek authorization expired. Sign in again.',
    ACCOUNT_QUOTA: 'The DeepSeek account has insufficient quota. Check the official billing page.', QUOTA: 'The API has insufficient quota. Check the provider\'s official console.',
    MISSING_CREDENTIAL: 'Provide your API key through the secure input field.'
  };
  return { code, status: failure?.status ?? 502, message: messages[code] ?? 'The model request did not complete. Check the connection and account status, then retry.' };
}

/** Translate actual Harness stream events, preserving tool fragments, reasoning and terminal errors. */
export async function openAiResponse(ctx, options, res, streaming) {
  const id = 'chatcmpl-' + randomUUID(); const created = Math.floor(Date.now() / 1000);
  const base = { id, created, model: options.publicModel, object: streaming ? 'chat.completion.chunk' : 'chat.completion' };
  let text = '', reasoning = '', usage, finish = 'stop'; const tools = new Map(); const ended = new Set();
  let sent = false;
  const emit = delta => {
    if (!sent) { res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' }); sent = true; }
    res.write('data: ' + JSON.stringify({ ...base, choices: [{ index: 0, delta, finish_reason: null }] }) + '\n\n');
  };
  const { publicModel, responseValidator, toolChoice = 'auto', parallelToolCalls, ...modelOptions } = options;
  const bufferToolCalls = toolChoice !== 'auto' || parallelToolCalls === false;
  for await (const chunk of ctx.llm.stream(modelOptions)) {
    if (res.destroyed) break;
    if (chunk.type === 'text-delta') { text += chunk.text; if (streaming) emit({ content: chunk.text }); }
    else if (chunk.type === 'reasoning-delta') { reasoning += chunk.text; if (streaming) emit({ reasoning_content: chunk.text }); }
    else if (chunk.type === 'tool-call-delta') {
      let value = tools.get(chunk.index);
      if (!value) { value = { id: chunk.id, type: 'function', function: { name: chunk.name ?? '', arguments: '' }, index: tools.size }; tools.set(chunk.index, value); }
      if (chunk.name) value.function.name = chunk.name;
      value.function.arguments += chunk.argumentsDelta;
      if (streaming && !bufferToolCalls) emit({ tool_calls: [{ index: value.index, id: value.id, type: 'function', function: { ...(chunk.name ? { name: chunk.name } : {}), arguments: chunk.argumentsDelta } }] });
    } else if (chunk.type === 'block-end' && chunk.block.type === 'tool-call') {
      if (!tools.has(chunk.index)) { const block = chunk.block; const value = { id: block.id, type: 'function', function: { name: block.name, arguments: block.arguments }, index: tools.size }; tools.set(chunk.index, value); if (streaming && !bufferToolCalls) emit({ tool_calls: [value] }); }
      ended.add(chunk.index);
    } else if (chunk.type === 'usage') usage = { prompt_tokens: chunk.usage.inputTokens + (chunk.usage.cacheReadTokens ?? 0) + (chunk.usage.cacheWriteTokens ?? 0), completion_tokens: chunk.usage.outputTokens, total_tokens: chunk.usage.totalTokens ?? chunk.usage.inputTokens + chunk.usage.outputTokens };
    else if (chunk.type === 'finish') {
      if (['error', 'aborted'].includes(chunk.reason.kind)) {
        const error = failureInfo(chunk.reason.failure);
        if (sent) res.write('data: ' + JSON.stringify({ error }) + '\n\n'); else { res.writeHead(error.status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ error })); }
        if (sent) res.end('data: [DONE]\n\n'); return;
      }
      finish = chunk.reason.kind === 'tool-calls' ? 'tool_calls' : chunk.reason.kind === 'max-tokens' ? 'length' : 'stop';
    }
  }
  if (res.destroyed) return;
  let validationFailure;
  const toolCalls = [...tools.values()].map(({ index, ...call }) => call);
  if ((toolChoice === 'none' && toolCalls.length) || (toolChoice === 'required' && !toolCalls.length)
      || (typeof toolChoice === 'object' && (!toolCalls.length || toolCalls.some(call => call.function.name !== toolChoice.function.name)))
      || (parallelToolCalls === false && toolCalls.length > 1)) validationFailure = { code: 'TOOL_CHOICE_NOT_SATISFIED', message: 'The model did not follow the required tool selection. The operation is incomplete.' };
  if (!toolCalls.length && responseValidator) {
    try { if (!responseValidator(JSON.parse(text))) validationFailure = { code: 'STRUCTURED_OUTPUT_INVALID', message: 'The model output does not match the required format. Generation is incomplete.' }; }
    catch { validationFailure = { code: 'STRUCTURED_OUTPUT_INVALID', message: 'The model output does not match the required format. Generation is incomplete.' }; }
  }
  if (validationFailure) {
    if (sent) res.end('data: ' + JSON.stringify({ error: { ...validationFailure, status: 502 } }) + '\n\ndata: [DONE]\n\n');
    else { res.writeHead(502, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ error: validationFailure })); }
    return;
  }
  if (streaming) {
    if (bufferToolCalls && toolCalls.length) emit({ tool_calls: [...tools.values()] });
    if (!sent) emit({ role: 'assistant' });
    res.end('data: ' + JSON.stringify({ ...base, choices: [{ index: 0, delta: {}, finish_reason: finish }], ...(usage ? { usage } : {}) }) + '\n\ndata: [DONE]\n\n');
  } else {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ...base, choices: [{ index: 0, message: { role: 'assistant', content: text || (toolCalls.length ? null : ''), ...(reasoning ? { reasoning_content: reasoning } : {}), ...(toolCalls.length ? { tool_calls: toolCalls } : {}) }, finish_reason: finish }], ...(usage ? { usage } : {}) }));
  }
}
