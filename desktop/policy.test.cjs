'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { isLocalPage, canonicalLocalPage, isOfficialLink, isExternalPage } = require('./policy.cjs');
test('desktop navigation remains loopback-only', () => {
  for (const value of ['http://127.0.0.1:3792/connect', 'http://127.0.0.1:3793/classroom/test', 'http://localhost:3792/connect']) assert.equal(isLocalPage(value), true);
  for (const value of ['http://localhost:1455/auth/callback', 'http://127.0.0.1:22/', 'https://evil.test/', 'http://127.0.0.1@evil.test:3792/', 'file:///C:/Users/']) assert.equal(isLocalPage(value), false);
  assert.equal(canonicalLocalPage('http://localhost:3792/settings?tab=llm'), 'deepsteam://app/settings?tab=llm');
  for (const value of ['deepsteam://app/connect', 'deepsteam://portal/', 'deepsteam://classroom/lesson']) assert.equal(isLocalPage(value), true);
  for (const value of ['deepsteam://unknown/', 'deepsteam://app:9999/', 'deepsteam://user@app/', 'deepsteam://app.evil.test/']) assert.equal(isLocalPage(value), false);
});
test('only exact official HTTPS hosts can open outside desktop', () => {
  assert.equal(isOfficialLink('https://platform.deepseek.com/api_keys'), true);
  for (const value of ['https://platform.deepseek.com.evil.test/', 'http://platform.deepseek.com/', 'https://user:password@platform.deepseek.com/', 'https://platform.deepseek.com:8888/', 'javascript:alert(1)']) assert.equal(isOfficialLink(value), false);
});
test('native provider OAuth is preserved without opening callbacks in desktop', () => {
  assert.equal(isOfficialLink('https://auth.openai.com/oauth/authorize?state=opaque&redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback'), true);
  assert.equal(isExternalPage('https://copilot.tencent.com/auth/authorize?state=opaque'), true);
  assert.equal(isExternalPage('https://www.codebuddy.ai/login?state=opaque'), true);
  for (const value of ['https://auth.openai.com/oauth/token', 'https://auth.openai.com.evil.test/oauth/authorize', 'https://copilot.tencent.com.evil.test/login', 'http://localhost:1455/auth/callback?code=secret', 'http://localhost:1457/auth/callback', 'file:///D:/secret']) {
    assert.equal(isOfficialLink(value), false);
    assert.equal(isLocalPage(value), false);
  }
});
test('reading and provider help links use browser policy without widening tool IPC', () => {
  for (const value of ['https://pubmed.ncbi.nlm.nih.gov/123/', 'https://platform.openai.com/api-keys', 'https://www.codebuddy.cn/docs/cli/quickstart']) {
    assert.equal(isExternalPage(value), true);
    assert.equal(isOfficialLink(value), false);
    assert.equal(isLocalPage(value), false);
  }
  for (const value of ['javascript:alert(1)', 'file:///D:/secret', 'https://user:pass@site.test/', 'http://localhost:1455/auth/callback?code=secret', 'data:text/html,test']) assert.equal(isExternalPage(value), false);
});
