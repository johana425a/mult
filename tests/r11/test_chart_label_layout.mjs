import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { generateSceneContent, expandGeneratedSlidePages } from './generation-runtime.mjs';
const root=process.argv[2] || process.env.DEEPSTEAM_RETAINED_DRAFT_DIR;
if (!root) throw new Error('Supply a consented retained chart draft directory; private user fixtures are not distributed.');
const results=[];
for (const name of ['draft-1-scene-1-content-1.json','draft-1-scene-2-content-1.json','draft-1-scene-2-content-2.json']) {
  const retained=JSON.parse(fs.readFileSync(path.join(root,name),'utf8'));
  const raw=JSON.parse(retained.output.text);
  const failures=[];
  let result;
  try { result=await generateSceneContent({id:'native-retained',type:'slide',title:'Native regression',description:'Retained classroom draft',order:1},async()=>retained.output.text,{paginateSlides:true,onFailure:failure=>failures.push(failure)}); }
  catch(error) { console.log(JSON.stringify({name,error:String(error)})); process.exitCode=1; continue; }
  if (!result) { console.log(JSON.stringify({name,failures})); process.exitCode=1; continue; }
  const pages=expandGeneratedSlidePages(result), all=pages.flatMap(p=>p.elements);
  for(const element of raw.elements) {
    if(element.type==='text') assert(all.some(e=>e.type==='text'&&e.content.replace(/<[^>]+>/g,'')===element.content.replace(/<[^>]+>/g,'')),element.id);
    if(element.type==='latex') assert(all.some(e=>e.type==='latex'&&e.latex===element.latex),element.id);
    if(element.type==='chart') assert(all.some(e=>e.type==='chart'&&JSON.stringify(e.data)===JSON.stringify(element.data)),element.id);
  }
  assert.equal(all.filter(e=>e.type==='line').length,raw.elements.filter(e=>e.type==='line').length);
  results.push({name,pages:pages.length,contentPreserved:true,types:all.map(e=>e.type)});
}
console.log(JSON.stringify(results,null,2));
