import assert from 'node:assert/strict';
import {layoutGeneratedSlidePages} from './generation-runtime.mjs';
const text = (id,left,top,width,content) => ({id,type:'text',left,top,width,height:90,rotate:0,
  content:`<p style="font-size:24px">${content}</p>`,defaultFontName:'Arial',defaultColor:'#000'});
const title = {...text('title',50,50,900,'Mechanism'),content:'<p style="font-size:32px">Mechanism</p>'};
const columns = [title,
  text('a',50,150,430,'First explanation'),text('b',50,235,430,'Second explanation'),
  text('c',520,160,430,'First calculation'),text('d',520,245,430,'Second calculation'),
  text('e',50,330,430,'Third explanation'),text('f',520,340,430,'Third calculation')];
const compact = layoutGeneratedSlidePages({type:'slide',elements:columns});
assert.equal(compact.length,1,'A legible authored two-column layout must not become three pages');
assert.deepEqual(compact[0].elements.map(e=>e.id).sort(),columns.map(e=>e.id).sort());
const shape = {id:'enzyme',type:'shape',left:350,top:330,width:80,height:80,rotate:0,
  viewBox:[80,80],path:'M0 0 H80 V80 H0 Z',fill:'#ccc'};
const label = text('label',440,335,190,'Inhibitor');
const grouped = layoutGeneratedSlidePages({type:'slide',elements:[title,
  text('intro',50,150,900,'Condition '.repeat(35)),shape,label]});
assert(grouped.find(page=>page.elements.some(e=>e.id==='enzyme')).elements.some(e=>e.id==='label'));
assert.equal(grouped.flatMap(p=>p.elements).filter(e=>e.id==='label').length,1);
const narrow = layoutGeneratedSlidePages({type:'slide',elements:[title,text('narrow',50,150,35,'Longer paragraph')]});
assert(narrow.flatMap(p=>p.elements).some(e=>e.id==='narrow'&&e.width===900));
console.log(JSON.stringify({result:'PASS',readableTwoColumnsPages:compact.length,labelsStayWithDiagram:true,narrowBoxReflow:true}));
