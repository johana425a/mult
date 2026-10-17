import assert from 'node:assert/strict';
import fs from 'node:fs';
import {generateSceneContent,expandGeneratedSlidePages,layoutGeneratedSlidePages} from './generation-runtime.mjs';
const fixture=process.argv[2] || process.env.DEEPSTEAM_RETAINED_DRAFT;
if (!fixture) throw new Error('Supply a consented retained compact draft JSON path; private user fixtures are not distributed.');
const retained=JSON.parse(fs.readFileSync(fixture,'utf8'));
const raw=JSON.parse(retained.output.text);
const output=await generateSceneContent({id:'native-compact-draft',type:'slide',title:'Mechanism',description:'Complete mechanism and formulas',order:1},async()=>retained.output.text,{paginateSlides:true});
assert(output);
const pages=expandGeneratedSlidePages(output);
const elements=pages.flatMap(page=>page.elements);
for(const before of raw.elements.filter(e=>e.type==='text')) {
  const text=before.content.replace(/<[^>]+>/g,'');
  assert(elements.some(e=>e.type==='text'&&e.content.replace(/<[^>]+>/g,'')===text),before.id);
}
assert.equal(elements.filter(e=>e.type==='line').length,3);
const diagramPage=pages.find(page=>page.elements.some(e=>e.type==='shape'));
for(const label of ['底物','抑制剂','活性位点','酶']) assert(diagramPage.elements.some(e=>e.type==='text'&&e.content.replace(/<[^>]+>/g,'')===label),label);
// Explicitly overlapping labels must remain an error, not a silent pass.
const label={id:'a',type:'text',left:50,top:150,width:120,height:70,rotate:0,groupId:'g',content:'<p style="font-size:24px">A</p>',defaultFontName:'Arial',defaultColor:'#000'};
assert.throws(()=>layoutGeneratedSlidePages({type:'slide',elements:[label,{...label,id:'b',top:160}]}),/overlaps/);
console.log(JSON.stringify({result:'PASS',actualRetainedDraft:true,pages:pages.length,bodyPreserved:true,allFourNodeLabelsWithDiagram:true,realOverlapRejected:true}));
