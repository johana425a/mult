/** Keyless integration fixtures exercise the official Host and persistence, not model quality. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, readFile, readdir } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { createHost } from '../host.mjs';
import { convertRequest, openAiResponse } from '../protocol.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const python = process.env.DEEPSTEAM_HARNESS_TEST_PYTHON;

async function fixtureHost() {
  const profile = await mkdtemp(join(process.env.DEEPSTEAM_HARNESS_TEST_ROOT ?? tmpdir(), 'deepsteam-keyless-'));
  const requests = [];
  const server = createServer(async (req, res) => {
    let raw = ''; for await (const part of req) raw += part;
    const request = JSON.parse(raw); requests.push(request);
    const toolDone = request.messages.some(message => message.role === 'tool');
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const delta = toolDone ? { content: 'FIXTURE: Official instructions were read. Choose account sign-in or secure key entry.' }
      : { tool_calls: [{ index: 0, id: 'fixture-guide', type: 'function', function: { name: 'get_provider_guide', arguments: '{"provider":"deepseek"}' } }] };
    const chunk = (value, reason) => JSON.stringify({ id: 'fixture-completion', object: 'chat.completion.chunk', created: 0, model: 'qwen3.5-4b-local', choices: [{ index: 0, delta: value, finish_reason: reason }] });
    res.end('data: ' + chunk(delta, null) + '\n\ndata: ' + chunk({}, toolDone ? 'stop' : 'tool_calls') + '\n\ndata: [DONE]\n\n');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const options = { profile, sessions: join(profile, 'sessions'), port: 0, python,
    credentialHelper: join(here, '../credential_store.py'), localBase: 'http://127.0.0.1:' + server.address().port + '/v1',
    toolRpc: async body => ({ ok: true, fixture: true, action: 'choose_connection', provider: body.arguments.provider, official_url: 'https://platform.deepseek.com' }) };
  const host = await createHost(options);
  return { host, options, profile, requests, async close() { await host.ctx.fiber.dispose(); await new Promise(resolve => server.close(resolve)); } };
}

test('Host has no bundled chat provider or retired onboarding tools', { skip: !python }, async () => {
  const fixture = await fixtureHost();
  try {
    assert.equal(fixture.host.assistant, undefined);
    assert.ok(!fixture.host.ctx.llm.listProviders().some(provider => provider.id === 'deepsteam-local'));
    assert.ok(!fixture.host.ctx.tools.schemas().some(tool => tool.name === 'get_provider_guide'));
    assert.equal(fixture.requests.length, 0);
  } finally { await fixture.close(); }
});

test('OpenAI gateway preserves inline images through official attachment admission', { skip: !python }, async () => {
  const fixture = await fixtureHost();
  try {
    const sharp = (await import('sharp')).default;
    const image = (await sharp({ create: { width: 8, height: 8, channels: 3, background: { r: 220, g: 0, b: 0 } } }).png().toBuffer()).toString('base64');
    const request = await convertRequest({ messages: [{ role: 'user', content: [{ type: 'text', text: 'test image' }, { type: 'image_url', image_url: { url: 'data:image/png;base64,' + image } }] }] }, fixture.host.ctx);
    assert.equal(request.messages[0].content[1].type, 'image');
    const saved = await fixture.host.ctx.attachments.readImage(request.messages[0].content[1].attachment);
    assert.ok(saved.data.length);
    await assert.rejects(convertRequest({ messages: [{ role: 'user', content: [{ type: 'image_url', image_url: { url: 'https://example.com/private.png' } }] }] }, fixture.host.ctx), /inline data/);
  } finally { await fixture.close(); }
});

test('official credential seam grants round-trip through DPAPI without plaintext file storage', { skip: !python }, async () => {
  const fixture = await fixtureHost();
  try {
    await fixture.host.ctx.credentials.modifyRecord('fixture/roundtrip', async () => ({ kind: 'grant', payload: { token: 'fixture-nonprivate-grant' } }));
    assert.equal((await fixture.host.ctx.credentials.readRecord('fixture/roundtrip')).payload.token, 'fixture-nonprivate-grant');
    const bytes = await readFile(join(fixture.profile, 'credentials.dpapi'));
    assert.equal(bytes.includes(Buffer.from('fixture-nonprivate-grant')), false);
    await fixture.host.ctx.credentials.deleteRecord('fixture/roundtrip');
    assert.equal(await fixture.host.ctx.credentials.readRecord('fixture/roundtrip'), undefined);
  } finally { await fixture.close(); }
});

function responseCapture() {
  return { destroyed: false, body: '', status: 0, writeHead(status) { this.status = status; }, write(text) { this.body += text; }, end(text = '') { this.body += text; this.writableEnded = true; } };
}
test('gateway streams tool fragments, text, usage and terminal errors', async () => {
  const fixture = { llm: { async *stream() {
    yield { type: 'text-delta', index: 0, text: 'FIXTURE' };
    yield { type: 'tool-call-delta', index: 1, id: 'call-1', name: 'test', argumentsDelta: '{"x":' };
    yield { type: 'tool-call-delta', index: 1, id: 'call-1', argumentsDelta: '1}' };
    yield { type: 'usage', usage: { inputTokens: 2, outputTokens: 4, totalTokens: 6 } };
    yield { type: 'finish', reason: { kind: 'tool-calls' } };
  } } };
  const streaming = responseCapture(); await openAiResponse(fixture, { publicModel: 'fixture' }, streaming, true);
  assert.match(streaming.body, /arguments/); assert.match(streaming.body, /tool_calls/); assert.match(streaming.body, /\[DONE\]/);
  const combined = responseCapture(); await openAiResponse(fixture, { publicModel: 'fixture' }, combined, false);
  const value = JSON.parse(combined.body); assert.equal(value.choices[0].message.tool_calls[0].function.arguments, '{"x":1}'); assert.equal(value.usage.total_tokens, 6);
  const failure = responseCapture();
  await openAiResponse({ llm: { async *stream() { yield { type: 'finish', reason: { kind: 'error', failure: { code: 'ACCOUNT_TOKEN_INVALID', status: 401 } } }; } } }, { publicModel: 'fixture' }, failure, false);
  assert.equal(failure.status, 401); assert.equal(JSON.parse(failure.body).error.code, 'ACCOUNT_TOKEN_INVALID');
});

test('structured responses and forced tool choices validate before a success finish', async () => {
  const ctx = { llm: { async *stream() { yield { type: 'text-delta', index: 0, text: '{"answer":4}' }; yield { type: 'finish', reason: { kind: 'stop' } }; } } };
  const options = await convertRequest({ messages: [{ role: 'user', content: 'question' }], response_format: { type: 'json_schema', json_schema: { name: 'result', strict: true, schema: { type: 'object', properties: { answer: { type: 'integer' } }, required: ['answer'], additionalProperties: false } } } }, {});
  const valid = responseCapture(); await openAiResponse(ctx, { ...options, publicModel: 'fixture' }, valid, false); assert.equal(valid.status, 200);
  const invalid = responseCapture(); await openAiResponse({ llm: { async *stream() { yield { type: 'text-delta', index: 0, text: '{"answer":"wrong"}' }; yield { type: 'finish', reason: { kind: 'stop' } }; } } }, { ...options, publicModel: 'fixture' }, invalid, true);
  assert.match(invalid.body, /STRUCTURED_OUTPUT_INVALID/); assert.doesNotMatch(invalid.body, /finish_reason":"stop/);
  const required = await convertRequest({ messages: [{ role: 'user', content: 'call' }], tools: [{ type: 'function', function: { name: 'only', parameters: { type: 'object', properties: {} } } }], tool_choice: 'required' }, {});
  const missing = responseCapture(); await openAiResponse(ctx, { ...required, publicModel: 'fixture' }, missing, false); assert.equal(JSON.parse(missing.body).error.code, 'TOOL_CHOICE_NOT_SATISFIED');
  const none = await convertRequest({ messages: [{ role: 'user', content: 'no call' }], tools: [{ type: 'function', function: { name: 'only' } }], tool_choice: 'none' }, {}); assert.equal(none.tools.length, 0);
  const toolResult = await convertRequest({ messages: [{ role: 'tool', tool_call_id: 'test-id', content: 'done' }] }, {}); assert.equal(toolResult.messages[0].toolCallId, 'test-id');
});
