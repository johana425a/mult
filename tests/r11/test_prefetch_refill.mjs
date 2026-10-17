import assert from 'node:assert/strict';
import {orderedPrefetch, classroomPrefetchWindow} from '../../upstream/OpenMAIC/lib/server/classroom-performance.ts';

const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((a,b) => {resolve=a; reject=b;});
  return {promise,resolve,reject};
}
function fixture(size, options={windowSize:2}) {
  const gates=Array.from({length:size},deferred), started=[], stopped=[];
  let active=0, maximum=0;
  const gen=orderedPrefetch(gates, async(gate,index,signal)=> {
    started.push(index); active++; maximum=Math.max(maximum,active);
    const abort=()=>gate.reject(signal.reason);
    signal.addEventListener('abort',abort,{once:true});
    try {return await gate.promise;} finally {
      signal.removeEventListener('abort',abort); active--; stopped.push(index);
    }
  },options);
  return {gates,started,stopped,gen,get active(){return active;},get maximum(){return maximum;}};
}
let passed=0;
{
  const f=fixture(5), first=f.gen.next(); await tick();
  assert.deepEqual(f.started,[0,1]);
  f.gates[1].resolve('one'); await tick(); f.gates[0].resolve('zero');
  assert.deepEqual((await first).value,{index:0,value:'zero'}); await tick();
  assert.deepEqual(f.started,[0,1,2],'Refill while the consumer is paused after a ready future result');
  assert.equal(f.active,1,'Only one content call can overlap narration');
  assert.deepEqual((await f.gen.next()).value,{index:1,value:'one'}); await tick();
  assert.deepEqual(f.started,[0,1,2],'An unfinished future must not start a second content call during narration');
  const third=f.gen.next(); await tick(); assert.deepEqual(f.started,[0,1,2,3]);
  f.gates[3].resolve('three'); await tick(); f.gates[2].resolve('two');
  assert.equal((await third).value.index,2); await tick(); assert.equal(f.active,1);
  f.gates[4].resolve('four');
  assert.equal((await f.gen.next()).value.index,3);
  assert.equal((await f.gen.next()).value.index,4);
  assert.equal((await f.gen.next()).done,true); assert.equal(f.maximum,2); passed++;
}
{
  const f=fixture(3), first=f.gen.next(); await tick(); f.gates[0].resolve('zero');
  await first; await tick(); assert.deepEqual(f.started,[0,1]);
  const returned=await f.gen.return(); assert.equal(returned.done,true);
  assert.equal(f.active,0); assert.deepEqual(f.stopped.sort(),[0,1]); passed++;
}
{
  const f=fixture(2,{windowSize:1}), first=f.gen.next(); await tick();
  f.gates[0].resolve('zero'); await first; await tick(); assert.deepEqual(f.started,[0]);
  const second=f.gen.next(); await tick(); assert.deepEqual(f.started,[0,1]);
  f.gates[1].resolve('one'); await second; await f.gen.next(); assert.equal(f.maximum,1); passed++;
}
{
  const f=fixture(4), first=f.gen.next(); await tick();
  const error=new Error('future failed'); f.gates[1].reject(error); await tick();
  f.gates[0].resolve('zero'); await first; await tick();
  assert.deepEqual(f.started,[0,1]);
  await assert.rejects(f.gen.next(),e=>e===error); assert.deepEqual(f.started,[0,1]);
  assert.equal(f.active,0); passed++;
}
{
  const controller=new AbortController(), f=fixture(4,{windowSize:2,signal:controller.signal});
  const first=f.gen.next(); await tick(); controller.abort();
  await assert.rejects(first,e=>e.name==='AbortError'); assert.equal(f.active,0); passed++;
}
{
  const controller=new AbortController(); controller.abort();
  const f=fixture(2,{windowSize:2,signal:controller.signal});
  await assert.rejects(f.gen.next(),e=>e.name==='AbortError'); assert.deepEqual(f.started,[]); passed++;
}
{
  const f=fixture(0); assert.equal((await f.gen.next()).done,true); assert.deepEqual(f.started,[]); passed++;
}
{
  const outlines=[{type:'slide'},{type:'quiz'}];
  assert.equal(classroomPrefetchWindow('gpt-6.1-sol',outlines,false,'2'),2);
  assert.equal(classroomPrefetchWindow('gpt-6.1-sol',outlines,true,'2'),1);
  assert.equal(classroomPrefetchWindow('other',outlines,false,'2'),1);
  assert.equal(classroomPrefetchWindow('gpt-6.1-sol',outlines,false,'1'),1); passed++;
}
console.log(JSON.stringify({passed,modelCalls:false,maximumConcurrentContentCalls:2,maximumContentCallsDuringNarration:1}));
