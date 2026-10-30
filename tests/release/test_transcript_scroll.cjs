'use strict';
// Deterministic geometry replay of the actual source helper. This does NOT
// count as the required native Electron fullscreen acceptance.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {observeTranscriptFollow}=require('../../upstream/DeepTutor/web/lib/transcript-follow-dom.cjs');
const component=fs.readFileSync(path.join(__dirname,'../../upstream/DeepTutor/web/components/reading/workspace/MediaReadingStage.tsx'),'utf8');
assert.match(component,/observeTranscriptFollow\(list\)/,'Component must use the tested helper');
assert.doesNotMatch(component,/transcriptFollowScrollTop\(/,'Old dynamic helper must not remain wired');
let cases=0;
for(const [width,height] of [[1280,720],[1920,1080],[960,640]]) {
  let outerTop=80, frames=[], active=2, disconnected=0, outerScroll=0;
  const events=new Map();
  const win={innerWidth:width,innerHeight:height,getComputedStyle:p=>({overflowY:p.overflowY||'visible'}),
    requestAnimationFrame:cb=>{frames.push(cb);return frames.length;},cancelAnimationFrame:()=>{},
    addEventListener:(n,cb)=>events.set(n,cb),removeEventListener:(n)=>events.delete(n),
    ResizeObserver:class {observe(){} disconnect(){disconnected++;}},
    MutationObserver:class {observe(){} disconnect(){disconnected++;}}};
  const parent={overflowY:'auto',clientTop:0,clientHeight:height,parentElement:null,
    getBoundingClientRect:()=>({top:0})};
  const list={ownerDocument:{defaultView:win},parentElement:parent,style:{maxHeight:'',minHeight:'',overflowAnchor:''},
    clientTop:0,clientHeight:Math.min(height*.48,460),scrollHeight:48*60,scrollTop:0,
    getBoundingClientRect:()=>({top:outerTop}),
    querySelector:()=>({clientHeight:48,getBoundingClientRect:()=>({top:outerTop+active*48-list.scrollTop})}),
    scrollTo:({top,behavior})=>{assert.equal(behavior,'instant');list.scrollTop=top;}};
  const cleanup=observeTranscriptFollow(list);
  const flush=()=>{const todo=frames;frames=[];todo.forEach(cb=>cb());};flush();
  const initialHeight=list.style.maxHeight;
  for(const top of [80,16,-40,-160,-280,40,80]) {
    outerTop=top;outerScroll=80-top;
    events.get('scroll')({target:parent});flush();
    const before=[list.scrollTop,list.style.maxHeight,outerScroll];
    for(let i=0;i<30;i++){events.get('scroll')({target:parent});flush();}
    assert.deepEqual([list.scrollTop,list.style.maxHeight,outerScroll],before,'Stable scroll must not feed back into size/outer position');
    assert.equal(list.style.maxHeight,initialHeight);cases++;
  }
  active=59;outerTop=80;events.get('resize')({});flush();
  const rect=list.querySelector().getBoundingClientRect();
  assert(rect.top>=outerTop&&rect.top+48<=outerTop+list.clientHeight+1,'Last cue must stay visible');
  const count=frames.length;events.get('scroll')({target:list});assert.equal(frames.length,count,'Do not respond to own scroll');
  cleanup();assert.equal(events.size,0);assert.equal(disconnected,2);assert.equal(list.style.maxHeight,'');
}
console.log(JSON.stringify({passed:cases,evidenceClass:'deterministic-dom-geometry',nativeFullscreen:false}));
