'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../desktop/main.cjs'), 'utf8');
const { isLocalPage } = require('../../desktop/policy.cjs');
const begin = source.indexOf('  window.webContents.session.setPermissionRequestHandler(');
const end = source.indexOf("  window.webContents.on('did-finish-load'", begin);
assert(begin >= 0 && end > begin);
let request, check, prompts = 0;
const contents = { getURL: () => 'deepsteam://app/education', session: {
  setPermissionRequestHandler: fn => { request=fn; },
  setPermissionCheckHandler: fn => { check=fn; },
}};
vm.runInNewContext(source.slice(begin,end), {
  window:{webContents:contents}, isLocalPage,
  dialog:{showMessageBox:async () => { prompts++; return {response:0}; }},
});
function requestResult(wc, permission, requestingUrl, extra={}) {
  let result;
  request(wc,permission,value=>{result=value;},{requestingUrl,...extra});
  return result;
}
assert.equal(check(contents,'fullscreen','deepsteam://app'),true);
assert.equal(check(contents,'fullscreen','deepsteam://classroom'),true);
assert.equal(requestResult(contents,'fullscreen','deepsteam://app/education'),true);
assert.equal(requestResult(contents,'fullscreen','deepsteam://classroom/classroom/test'),true);
assert.equal(check(contents,'fullscreen','https://example.com'),false);
assert.equal(requestResult(contents,'fullscreen','https://example.com'),false);
assert.equal(requestResult({},'fullscreen','deepsteam://app'),false);
assert.equal(requestResult(contents,'automatic-fullscreen','deepsteam://app'),false);
assert.equal(requestResult(contents,'media','deepsteam://app',{mediaTypes:['video']}),false);
assert.equal(check(contents,'geolocation','deepsteam://app'),false);
assert.equal(prompts,0);
console.log('Ten native permission handler checks passed; no microphone or external permission expansion.');
