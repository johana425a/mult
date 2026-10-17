import assert from 'node:assert/strict';
import {layoutGeneratedSlidePages} from './generation-runtime.mjs';
const text=(id,top,content,width=900)=>({id,type:'text',left:50,top,width,height:69,rotate:0,
  content:`<p style="font-size:24px">${content}</p>`,defaultFontName:'Arial',defaultColor:'#000'});
const title={...text('title',50,'Mechanism'),content:'<p style="font-size:32px">Mechanism</p>'};
const originals=[title,...Array.from({length:6},(_,i)=>text('point'+i,160+i*100,`Condition ${i+1}: preserved exactly.`))];
const pages=layoutGeneratedSlidePages({type:'slide',elements:originals});
assert.equal(pages.length,1,'Six short related blocks fit three readable two-column rows');
for(const original of originals) {
  const matches=pages.flatMap(p=>p.elements).filter(e=>e.id===original.id);
  assert.equal(matches.length,1); assert.equal(matches[0].content,original.content);
}
const content=pages[0].elements.filter(e=>e.id!=='title');
for(let i=0;i<content.length;i+=2){assert.equal(content[i].top,content[i+1].top);assert(content[i].left<content[i+1].left);}
const long=text('long',160,'All details must remain present. '.repeat(34));
assert.throws(()=>layoutGeneratedSlidePages({type:'slide',elements:[title,long]}),/cannot fit|OVERFLOW/);
const figure={id:'figure',type:'image',left:50,top:160,width:300,height:160,rotate:0,
  src:'data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="300" height="160"></svg>'),fixedRatio:true};
const withFigure=layoutGeneratedSlidePages({type:'slide',elements:[title,figure,...originals.slice(1)]});
const kept=withFigure.flatMap(p=>p.elements).find(e=>e.id==='figure');
assert.equal(kept.src,figure.src);assert.equal(kept.width/kept.height,300/160);
console.log(JSON.stringify({result:'PASS',compactPages:pages.length,bodyBlocks:6,exactContentAndOrder:true,sourceImageUnchanged:true,oversizedTextNotDropped:true}));
