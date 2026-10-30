'use strict';
// Count actual node:assert calls, not a test script's self-reported PASS text.
let count=0;
for(const api of new Set([require('node:assert'),require('node:assert/strict')])) {
  for(const key of ['ok','equal','notEqual','deepEqual','notDeepEqual','strictEqual','notStrictEqual',
    'deepStrictEqual','notDeepStrictEqual','throws','doesNotThrow','rejects','doesNotReject','match','doesNotMatch','ifError']) {
    if(typeof api[key]!=='function')continue;
    const original=api[key];api[key]=function(...args){count++;return original.apply(this,args);};
  }
}
process.on('exit',()=>console.log('DEEPSTEAM_ASSERTIONS='+count));
