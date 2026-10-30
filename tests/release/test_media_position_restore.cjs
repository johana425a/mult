'use strict';
// Delayed saved-position responses and transcript hydration against the actual
// React component. External players are deterministic stubs in this test.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {createRequire}=require('node:module');
const root=path.resolve(__dirname,'../..'),web=path.join(root,'upstream/DeepTutor/web');
const req=createRequire(process.env.DEEPSTEAM_WEB_TEST_DEPENDENCIES||path.join(web,'package.json'));
const {JSDOM}=req('jsdom'),ts=req('typescript');
const dom=new JSDOM('<body></body>',{url:'http://localhost/'});
Object.assign(global,{window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement});
Object.defineProperty(global,'navigator',{value:dom.window.navigator,configurable:true});
global.IS_REACT_ACT_ENVIRONMENT=true;
const React=req('react'),{render,act,cleanup,fireEvent}=req('@testing-library/react');
const noop=()=>{},t=x=>x,pending=[],seeks=[],starts=[],calls=[];
const controller={seek:s=>seeks.push(s),currentTime:()=>0,duration:()=>656,tracksPosition:true};
function Player(p){starts.push(p.startSeconds);React.useEffect(()=>{p.onController(controller);return()=>p.onController(null);},[p.onController]);return null;}
const time=s=>{const match=/[?#&]t=(\d+(?:\.\d+)?)/.exec(s||'');return match?Number(match[1]):null;};
const imports={react:React,'react/jsx-runtime':req('react/jsx-runtime'),'react-i18next':{useTranslation:()=>({t})},
 'lucide-react':new Proxy({},{get:()=>()=>null}),
 '@/context/ReadingContext':{useReading:()=>({annotations:[],saveMark:noop,removeMark:noop})},
 '@/lib/reading-api':{getReadingPosition:id=>{calls.push(id);return new Promise(resolve=>pending.push(resolve));},saveReadingPosition:async()=>{},rawMaterialUrl:()=>''},
 '@/lib/reading-media-controller':{html5ReadingController:()=>controller},
 '@/lib/reading-media-citations':{mediaTimeFromHref:()=>null},
 '@/lib/reading-reader-action':{READER_ACTION_EVENT:'reader-action',READER_TURN_END_EVENT:'reader-turn-end'},
 '@/lib/reading-turn-state':{setReadingViewport:noop},
 '@/shared/ui/Tooltip':{default:({children})=>children},
 '@/lib/reading-video-sources':{bilibiliOfficialUrl:()=>'',parseBilibiliSource:()=>({bvid:'test',page:1,startSeconds:0}),youtubeEntryTime:()=>0,youtubeVideoId:()=>''},
 '@/lib/transcript-search':{stepTranscriptMatch:noop,transcriptMatchIndexes:()=>[]},
 '@/lib/transcript-follow-dom.cjs':{observeTranscriptFollow:noop},
 './YouTubeReadingPlayer':{YouTubeReadingPlayer:Player},'./BilibiliReadingPlayer':{BilibiliReadingPlayer:Player},
 './BilibiliSubtitleControls':{BilibiliSubtitleControls:()=>null},
 '@/lib/reading-media-time':{formatMediaTime:String,timeFromSourceHref:time},
};
const exportsObject={};
const code=ts.transpileModule(fs.readFileSync(path.join(web,'components/reading/workspace/MediaReadingStage.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2021,jsx:ts.JsxEmit.ReactJSX}}).outputText;
vm.runInNewContext(code,{exports:exportsObject,require:n=>{if(!(n in imports))throw Error(n);return imports[n];},window,document,console,setTimeout,clearTimeout});
const rows=[{locator:1,text:'first',sourceHref:'#t=0'},{locator:2,text:'target',sourceHref:'#t=243.24'}];
const refs=rows.map(r=>({locator:r.locator,title:r.text,source_href:r.sourceHref}));
function Wrapper({materialId='video1',references=[]}){const [locator,setLocator]=React.useState(1);return React.createElement(exportsObject.MediaReadingStage,{material:{material_id:materialId,source_kind:'bilibili',source_url:'https://www.bilibili.com/video/test',duration_seconds:656},title:'Test',refs:references,transcript:rows,activeLocator:locator,onLocatorChange:setLocator,transcriptUnavailable:false,chaptersOnly:false});}
(async()=>{
 const view=render(React.createElement(Wrapper));await act(async()=>{});
 assert.equal(calls.length,1);assert.deepEqual(seeks,[]);
 view.rerender(React.createElement(Wrapper,{references:refs}));await act(async()=>{});
 assert.equal(calls.length,1);assert.deepEqual(seeks,[]);
 act(()=>fireEvent.click(view.container.querySelector('[data-transcript-cue="1"]')));
 assert.equal(seeks.at(-1),243.24);const before=seeks.length;
 await act(async()=>pending.shift()({source_anchor:'#t=37',locator:1}));
 assert.equal(seeks.length,before);assert.equal(starts.at(-1),0);
 view.unmount();seeks.length=0;
 const reopen=render(React.createElement(Wrapper,{references:refs}));await act(async()=>{});
 assert.equal(calls.length,2);
 await act(async()=>pending.shift()({source_anchor:'#t=37',locator:1}));
 assert.equal(seeks.at(-1),37);assert.equal(starts.at(-1),37);const restoredCount=seeks.length;
 reopen.rerender(React.createElement(Wrapper,{references:refs.map(r=>({...r}))}));await act(async()=>{});
 assert.equal(calls.length,2);assert.equal(seeks.length,restoredCount);
 reopen.rerender(React.createElement(Wrapper,{materialId:'video2',references:refs}));await act(async()=>{});
 assert.equal(calls.at(-1),'video2');
 act(()=>fireEvent.click(reopen.getByRole('button',{name:'Next',exact:true})));
 const afterNext=seeks.length;
 await act(async()=>pending.shift()({source_anchor:'#t=10',locator:1}));
 assert.equal(seeks.length,afterNext);assert.equal(seeks.at(-1),243.24);
 console.log('DEEPSTEAM_ASSERTIONS=15');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>{cleanup();dom.window.close();});
