const assert=require('node:assert/strict');
const {createRequire}=require('node:module');
const path=require('node:path');
const req=createRequire(path.resolve(process.env.DEEPSTEAM_WEB_TEST_DEPENDENCIES || path.join(__dirname,'../../upstream/DeepTutor/web/package.json')));
const {JSDOM}=req('jsdom');
const dom=new JSDOM('<!doctype html><html><body></body></html>',{url:'http://localhost/?dt_workspace=A'});
global.window=dom.window;global.document=dom.window.document;
global.IS_REACT_ACT_ENVIRONMENT=true;
const React=req('react'),{createRoot}=req('react-dom/client');
const {act}=React;
const state=require('../../upstream/DeepTutor/web/lib/sidebar-view-state.cjs');
let update,rendered;
function View(){const [rows,setRows]=state.useRetained(React,'sessions',[]);update=setRows;rendered=rows;return React.createElement('p',{},rows.join(','));}
async function mount(){const element=document.createElement('div');document.body.append(element);const root=createRoot(element);await act(async()=>root.render(React.createElement(View)));return root;}
(async()=>{
  let root=await mount();assert.deepEqual(rendered,[]);await act(async()=>update(['same-workspace']));
  const oldUpdate=update;await act(async()=>root.unmount());root=await mount();
  assert.deepEqual(rendered,['same-workspace'],'Remount must retain its first paint');
  await act(async()=>oldUpdate(['late-unmounted']));assert.deepEqual(rendered,['same-workspace']);
  window.history.replaceState(null,'','/?dt_workspace=B');
  const staleScopeUpdate=update;await act(async()=>root.render(React.createElement(View)));
  assert.deepEqual(rendered,[]);await act(async()=>staleScopeUpdate(['foreign']));assert.deepEqual(rendered,[]);
  await act(async()=>update(['workspace-B']));assert.deepEqual(rendered,['workspace-B']);
  window.history.replaceState(null,'','/?workspace=A');await act(async()=>root.render(React.createElement(View)));
  assert.deepEqual(rendered,['same-workspace']);
  const staleAuthUpdate=update;await act(async()=>state.clear());assert.deepEqual(rendered,[]);
  await act(async()=>staleAuthUpdate(['old-account']));assert.deepEqual(rendered,[]);
  await act(async()=>update(['fresh-account']));assert.deepEqual(rendered,['fresh-account']);
  await act(async()=>update(previous=>[...previous,'second']));assert.equal(rendered.length,2);
  assert.equal(window.localStorage.length,0);await act(async()=>root.unmount());
  console.log(JSON.stringify({passed:8,retainedFirstPaint:true,scopeIsolation:true,authInvalidation:true,unmountedAndStaleResponsesIgnored:true,noDiskStorage:true}));
})().catch(error=>{console.error(error);process.exitCode=1;});
