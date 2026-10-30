const assert = require('node:assert/strict');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const result=spawnSync(process.execPath,['--test',path.resolve(__dirname,'../../desktop/uninstall-entry.test.cjs')],{
  encoding:'utf8',windowsHide:true,timeout:30000,
});
assert.equal(result.status,0,result.stdout+'\n'+result.stderr);
assert.match(result.stdout,/(?:#|ℹ) tests 7/);
assert.match(result.stdout,/(?:#|ℹ) fail 0/);
console.log('Desktop uninstall capability: 7 isolated entry, concurrency and permission cases passed.');
