'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {createRequire}=require('node:module');
const root=path.resolve(__dirname,'../..'),web=path.join(root,'upstream/DeepTutor/web');
const req=createRequire(process.env.DEEPSTEAM_WEB_TEST_DEPENDENCIES||path.join(web,'package.json'));
const {JSDOM}=req('jsdom'),ts=req('typescript');
const dom=new JSDOM('<body></body>',{url:'http://localhost/'});
Object.assign(global,{window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement});
Object.defineProperty(global,'navigator',{value:dom.window.navigator,configurable:true});
global.IS_REACT_ACT_ENVIRONMENT=true;
const React=req('react'),{renderHook,act,cleanup}=req('@testing-library/react');
const noop=()=>{},t=x=>x,source=id=>({material_id:id,status:'ready',unit:'segment',revision:1,unit_refs:[{locator:id==='old'?189:51}]}),old=source('old'),next=source('next');
let reading={material:old,annotations:[{note:'old note'}],openMaterial:async()=>true,closeMaterial:noop,reportViewport:noop};
const workspace={workspace_id:'rw_test',active_material_id:'old',tabs:[{material:old},{material:next}]};
const pending=new Map(),requests=[];
const imports={
 react:React,'next/navigation':{useRouter:()=>({push:noop,replace:noop})},'react-i18next':{useTranslation:()=>({t})},
 '@/context/ReadingContext':{useReading:()=>reading},
 '@/features/chat/ChatStateAdapter':{useChatStateAdapter:()=>({state:{sessionId:null},configureSession:noop,loadSession:async()=>{},newSession:noop})},
 '@/lib/course-session-scope':{courseSessionConfiguration:x=>x},
 '@/lib/session-load':{SESSION_LOAD_TIMEOUT_MS:1000,sessionSubmissionBlocked:()=>false},
 '@/lib/reading-turn-state':{setReadingWorkspace:noop},
 '@/lib/workspace-mode':{READING_WORKSPACE_MODE:'immersive_reading'},
 '@/lib/reading-reader-action':{READER_ACTION_EVENT:'reader-action'},
 '@/lib/learning-routes':{readingCollectionRoute:x=>x,readingSessionRoute:x=>x},
 '@/lib/reading-api':{getReadingTranscript:id=>{requests.push(id);return new Promise(resolve=>pending.set(id,resolve));},listBookmarks:async()=>[]},
 '@/lib/reading-workspace-api':{getReadingWorkspace:async()=>({workspace}),listReadingConversations:async()=>[]},
};
const exportsObject={};
const code=ts.transpileModule(fs.readFileSync(path.join(web,'components/reading/workspace/useReadingWorkspace.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2021,jsx:ts.JsxEmit.ReactJSX}}).outputText;
vm.runInNewContext(code,{exports:exportsObject,require:n=>{if(!(n in imports))throw Error(n);return imports[n];},window,console,AbortController,setTimeout,clearTimeout});
(async()=>{
 const hook=renderHook(()=>exportsObject.useReadingWorkspace('rw_test',null));
 await act(async()=>{});
 assert.equal(hook.result.current.material.material_id,'old');
 assert.equal(requests.at(-1),'old');
 // Change selection while both the old detail and old transcript request exist.
 act(()=>hook.result.current.setWorkspace({...workspace,active_material_id:'next'}));
 assert.equal(hook.result.current.material,null);
 assert.equal(hook.result.current.annotations.length,0);
 assert.equal(hook.result.current.transcript.length,0);
 assert.equal(hook.result.current.submissionBlocked,true);
 reading={...reading,material:next,annotations:[]};
 act(()=>hook.rerender());await act(async()=>{});
 await act(async()=>pending.get('next')({segments:[{locator:51,text:'new transcript'}]}));
 assert.equal(hook.result.current.transcript[0].text,'new transcript');
 await act(async()=>pending.get('old')({segments:[{locator:189,text:'stale transcript'}]}));
 assert.equal(hook.result.current.transcript[0].text,'new transcript');
 assert.equal(hook.result.current.material.unit_refs[0].locator,51);
 assert.equal(hook.result.current.submissionBlocked,false);
 // An empty/unloaded tab cannot retain the last successful transcript.
 act(()=>hook.result.current.setWorkspace({...workspace,active_material_id:'old'}));
 assert.equal(hook.result.current.material,null);
 assert.equal(hook.result.current.transcript.length,0);
 console.log('DEEPSTEAM_ASSERTIONS=12');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>{cleanup();dom.window.close();});
