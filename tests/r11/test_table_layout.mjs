import assert from 'node:assert/strict';
import {layoutGeneratedSlidePages} from './generation-runtime.mjs';
const cell = (id, text, extra={}) => ({id,text,colspan:1,rowspan:1,...extra});
const title = {id:'title',type:'text',left:50,top:50,width:900,height:50,rotate:0,
  content:'<p style="font-size:28px">Competitive inhibition</p>',defaultFontName:'Arial',defaultColor:'#000'};
const table = {id:'test-table',type:'table',left:50,top:150,width:900,height:160,rotate:0,
  outline:{width:1,color:'#333',style:'solid'},cellMinHeight:32,colWidths:[1,1,1],data:[
    [cell('h1','[S]'),cell('h2','Calculation'),cell('h3','v')],
    [cell('a','1'),cell('b','100 / 3'),cell('c','33.33')],
    [cell('d','2'),cell('e','200 / 4'),cell('f','50.00')],
    [cell('g','4'),cell('h','400 / 6'),cell('i','66.67')]]};
const before=JSON.stringify(table);
const pages=layoutGeneratedSlidePages({type:'slide',elements:[title,table]});
const result=pages.flatMap(p=>p.elements).filter(e=>e.type==='table');
assert.equal(result.length,1);
assert.equal(JSON.stringify(table),before,'Input content must remain intact');
assert.equal(result[0].data.flat().length,12);
for(const c of table.data.flat()) assert(result[0].data.flat().find(x=>x.id===c.id).text.includes(c.text));
assert(result[0].data.flat().every(c=>parseFloat(c.style.fontsize)>=24));
assert(result[0].top+result[0].height<=512.5);
assert(result[0].height<=224,'Single-line cells must not count the separate text element inset a second time');
const merged={...table,id:'merged',colWidths:[1,1],data:[
  [cell('m1','A',{rowspan:2}),cell('m2','B')],[cell('m3','C')]]};
const m=layoutGeneratedSlidePages({type:'slide',elements:[merged]})[0].elements[0];
assert.equal(m.data[0][0].rowspan,2); assert.equal(m.data.flat().length,3);
assert.throws(()=>layoutGeneratedSlidePages({type:'slide',elements:[{...table,colWidths:[1,0,1]}]}),/positive column/);
assert.throws(()=>layoutGeneratedSlidePages({type:'slide',elements:[{...table,data:[[cell('bad','x',{colspan:9})]]}]}),/invalid span/);
assert.throws(()=>layoutGeneratedSlidePages({type:'slide',elements:[{...table,cellMinHeight:500}]}),/SLIDE_LAYOUT_OVERFLOW/);
const numeric = {...table, data:[[cell('n','12.5',{padding:8,style:{fontsize:24}})]] ,colWidths:[1]};
const normalized=layoutGeneratedSlidePages({type:'slide',elements:[numeric]})[0].elements[0];
assert.equal(normalized.data[0][0].style.fontsize,'24px');
assert.equal(normalized.data[0][0].padding,'8px 8px 8px 8px');
for(const bad of [{padding:{}},{style:{fontsize:{}}},{padding:-4}]){
  assert.throws(()=>layoutGeneratedSlidePages({type:'slide',elements:[{...numeric,data:[[cell('bad','value',bad)]]}]}),/SLIDE_LAYOUT_UNSUPPORTED/);
}
console.log('PASS: real generated table, unchanged content, readable cells, merged spans, invalid geometry, overflow');
