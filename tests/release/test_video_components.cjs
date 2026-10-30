'use strict';
// Render the shipped source, using deterministic bridge responses. Real external
// playback and login are separately verified in the background desktop fixture.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {createRequire}=require('node:module');
const root=path.resolve(__dirname,'../..'),web=path.join(root,'upstream/DeepTutor/web');
const req=createRequire(process.env.DEEPSTEAM_WEB_TEST_DEPENDENCIES||path.join(web,'package.json'));
const {JSDOM}=req('jsdom'),ts=req('typescript');
const dom=new JSDOM('<!doctype html><body></body>',{url:'http://localhost/'});
Object.assign(global,{window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement,MutationObserver:dom.window.MutationObserver});
Object.defineProperty(global,'navigator',{value:dom.window.navigator,configurable:true});
document.elementFromPoint=()=>document.querySelector('[data-testid="bilibili-native-player"]');
global.IS_REACT_ACT_ENVIRONMENT=true;
const React=req('react'),{render,act,cleanup,fireEvent}=req('@testing-library/react');
const t=value=>value,cache=new Map(),folder='components/reading/workspace/';
class ResizeObserver {observe(){} disconnect(){}}
function load(relative){
 if(cache.has(relative))return cache.get(relative);
 const exports={};cache.set(relative,exports);
 const code=ts.transpileModule(fs.readFileSync(path.join(web,relative),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2021,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const imports={react:React,'react/jsx-runtime':req('react/jsx-runtime'),'react-i18next':{useTranslation:()=>({t,i18n:{language:'en'}})},'@/lib/workspace-scope':{activeWorkspaceId:()=> 'ws_test'}};
 vm.runInNewContext(code,{exports,window,document,globalThis:window,crypto:window.crypto,ResizeObserver,
  innerWidth:1440,innerHeight:1100,setTimeout,clearTimeout,setInterval,clearInterval,URL,URLSearchParams,console,
  require:name=>imports[name]||(name==='@/lib/reading-video-sources'?load('lib/reading-video-sources.ts'):
    name.startsWith('./')?load(folder+name.slice(2)+'.tsx'):req(name))});
 return exports;
}
const player=load(folder+'BilibiliReadingPlayer.tsx').BilibiliReadingPlayer;
const account=load(folder+'BilibiliSubtitleControls.tsx').BilibiliSubtitleControls;
const wait=ms=>act(()=>new Promise(resolve=>setTimeout(resolve,ms)));
(async()=>{
 let received=[],current,calls=[],time=12,rate=1;
 window.deepsteamDesktop={domesticVideo:async o=>{calls.push(o);if(o.action==='seek')time=o.seconds;if(o.action==='rate')rate=o.rate;
  return o.action==='state'?{status:'ready',time,duration:656,rate,paused:true}:{status:'mounted'};}};
 const props={source:{bvid:'BV1SmpD6QEuX',page:1,startSeconds:0},startSeconds:0,duration:656,title:'test video',
  onController:c=>{current=c;},onTime:(...values)=>received.push(values),onError:()=>{}};
 const view=render(React.createElement(player,props));await wait(350);
 assert(view.getByTestId('bilibili-native-player'));assert(current.tracksPosition);
 assert.deepEqual(received.at(-1),[12,656]);assert(calls.some(c=>c.action==='mount'));
 act(()=>{current.seek(300);current.setPlaybackRate(1.5);});await wait(650);
 assert.equal(current.currentTime(),300);assert.equal(current.playbackRate(),1.5);
 view.unmount();await wait(10);assert(calls.some(c=>c.action==='unmount'));assert.equal(current,null);
 const before=received.length;await wait(300);assert.equal(received.length,before);
 let ready=false;calls=[];time=0;rate=1;
 window.deepsteamDesktop={domesticVideo:async o=>{calls.push(o);if(ready&&o.action==='seek')time=o.seconds;if(ready&&o.action==='rate')rate=o.rate;
  return o.action==='state'?{status:ready?'ready':'loading',time,duration:656,rate,paused:true}:{status:'mounted'};}};
 const early=render(React.createElement(player,{...props,startSeconds:37}));await wait(30);
 act(()=>{current.seek(243.24);current.setPlaybackRate(2);current.pause();});await wait(300);
 assert.equal(calls.filter(c=>['seek','rate','pause'].includes(c.action)).length,0);
 ready=true;await wait(650);
 assert.equal(time,243.24);assert.equal(rate,2);
 assert.deepEqual(calls.filter(c=>c.action==='seek').map(c=>c.seconds),[243.24]);
 assert(calls.some(c=>c.action==='pause'));assert.equal(current.currentTime(),243.24);
 early.unmount();await wait(10);
 delete window.deepsteamDesktop;
 const fallback=render(React.createElement(player,props));assert(fallback.container.querySelector('iframe[src^="https://player.bilibili.com"]'));fallback.unmount();
 window.deepsteamDesktop={bilibiliSessionStatus:async()=>({status:'signed_in',profile:{displayName:'Fixture user',avatarUrl:'https://i0.hdslb.com/fixture.png'}}),
  onBilibiliSessionChanged:()=>()=>{},signOutBilibili:async()=>({status:'signed_out'})};
 const signed=render(React.createElement(account,{materialId:'0123456789abcdef'}));await wait(10);
 assert(signed.getByTestId('bilibili-avatar'));assert(signed.getByTestId('bilibili-signout'));assert.equal(signed.queryByTestId('bilibili-signin'),null);
 await act(async()=>{fireEvent.click(signed.getByTestId('bilibili-signout'));});await wait(10);
 assert(signed.getByTestId('bilibili-signin'));assert.equal(signed.queryByTestId('bilibili-signout'),null);signed.unmount();
 const stage=fs.readFileSync(path.join(web,folder+'MediaReadingStage.tsx'),'utf8');
 assert.match(stage,/<BilibiliSubtitleControls materialId=/);assert.match(stage,/import \{ BilibiliReadingPlayer \}/);
 assert.doesNotMatch(stage,/line-clamp-1 min-w-0|line-clamp-2 min-w-0 leading/);
 console.log('DEEPSTEAM_ASSERTIONS=26');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>{cleanup();dom.window.close();});
