const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {createRequire}=require('node:module');
const root=path.resolve(__dirname,'../..');
const req=createRequire(process.env.DEEPSTEAM_WEB_TEST_DEPENDENCIES||path.join(root,'upstream/DeepTutor/web/package.json'));
const ts=req('typescript');
function load(relative,language,imports={}){
 const filename=path.join(root,relative),exports={};
 const js=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2021,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 vm.runInNewContext(js,{exports,process:{env:{NEXT_PUBLIC_DEEPSTEAM_DEFAULT_LANGUAGE:language}},require:id=>imports[id]||{}});
 return exports;
}
let checks=0;
for(const [flag,expected] of [[undefined,'en'],['zh','zh']]){
 const module=load('upstream/DeepTutor/web/i18n/languages.ts',flag);
 assert.equal(module.DEFAULT_APP_LANGUAGE,expected);checks++;
 for(const input of [null,undefined,'', 'not-a-language']){assert.equal(module.normalizeLanguage(input),expected);checks++;}
 for(const input of ['zh','zh-CN','zh_TW','chinese']){assert.equal(module.normalizeLanguage(input),'zh');checks++;}
 for(const input of ['en','en-US','english']){assert.equal(module.normalizeLanguage(input),'en');checks++;}
 assert(module.isAppLanguage('zh'));checks++;
 const store=load('upstream/DeepTutor/web/context/app-shell-storage.ts',flag,{'@/i18n/languages':module});
 assert.equal(store.readStoredLanguage(),expected);assert.equal(store.resolveResponseLanguage(null),expected);checks+=2;
 assert.equal(store.readStoredResponseLanguage(),expected);checks++;
 assert.equal(store.resolveResponseLanguage('zh-tw'),'zh-tw');assert.equal(store.resolveResponseLanguage('en','zh'),'en');checks+=2;
 const om=load('upstream/OpenMAIC/lib/i18n/types.ts',flag);
 assert.equal(om.defaultLocale,expected==='zh'?'zh-CN':'en-US');checks++;
 const hook=load('upstream/OpenMAIC/lib/hooks/use-i18n.tsx',flag,{
  react:{createContext:()=>({})},
  '@/lib/i18n':{...om,supportedLocales:[{code:'en-US'},{code:'zh-CN'},{code:'zh-TW'}]},
 });
 assert.equal(hook.resolveInitialLocale(null,'en-US'),expected==='zh'?'zh-CN':'en-US');checks++;
 assert.equal(hook.resolveInitialLocale('en-US','zh-CN'),'en-US');checks++;
 assert.equal(hook.resolveInitialLocale('zh-TW','en-US'),'zh-TW');checks++;
}
const en=JSON.parse(fs.readFileSync(path.join(root,'upstream/DeepTutor/web/locales/en/app.json'),'utf8'));
const zh=JSON.parse(fs.readFileSync(path.join(root,'upstream/DeepTutor/web/locales/zh/app.json'),'utf8'));
assert.deepEqual(Object.keys(en).filter(k=>!Object.hasOwn(zh,k)),[]);checks++;
for(const key of ['Immersive Reading','Personalized Learning','Task Board','Settings','Retry saving']){assert(/[\u3400-\u9fff]/.test(zh[key]),key);checks++;}
const standaloneEn=JSON.parse(fs.readFileSync(path.join(root,'upstream/DeepTutor/web/locales/en/standalone.json'),'utf8'));
const standaloneZh=JSON.parse(fs.readFileSync(path.join(root,'upstream/DeepTutor/web/locales/zh/standalone.json'),'utf8'));
assert.deepEqual(Object.keys(standaloneEn).sort(),Object.keys(standaloneZh).sort());checks++;
const instance=req('i18next').createInstance();
instance.init({lng:'en',fallbackLng:'en',initImmediate:false,keySeparator:false,resources:{en:{deepsteam:standaloneEn},zh:{deepsteam:standaloneZh}}});
const copy=load('upstream/DeepTutor/web/i18n/standalone.ts','zh',{'i18next':{default:instance},'react-i18next':{useTranslation:()=>{}}});
for(const key of ['Connect a model','Interactive classroom','Workspace agent','Ready to learn','Sign in to DeepSeek','Allow full access','Learning:','Classroom:']){
 assert.equal(copy.standaloneCopy(key),standaloneEn[key]);checks++;
}
instance.changeLanguage('zh');
for(const key of ['Connect a model','Interactive classroom','Workspace agent','Ready to learn','Sign in to DeepSeek','Allow full access','Learning:','Classroom:']){
 assert.equal(copy.standaloneCopy(key),standaloneZh[key]);assert(/[\u3400-\u9fff]/.test(copy.standaloneCopy(key)));checks+=2;
}
for(const asset of ['deepsteam-mark.svg','deepsteam-wordmark.svg','deepsteam-wordmark-light.svg']){
 const content=fs.readFileSync(path.join(root,'upstream/DeepTutor/web/public',asset),'utf8');
 assert((content.match(/<circle /g)||[]).length>80,'Approved gold dotted swirl: '+asset);checks++;
 assert.equal(content,fs.readFileSync(path.join(root,'upstream/OpenMAIC/public',asset),'utf8'));checks++;
}
const approvedTheme=fs.readFileSync(path.join(root,'patches/20261015-ui-refresh/theme.css'),'utf8').replace(/\r\n/g,'\n').trim();
const builtTheme=fs.readFileSync(path.join(root,'upstream/DeepTutor/web/app/deepsteam-theme.css'),'utf8').replace(/\r\n/g,'\n').trim();
assert.equal(builtTheme,approvedTheme,'Retain the existing approved theme without redesign');checks++;
const layout=fs.readFileSync(path.join(root,'upstream/DeepTutor/web/app/layout.tsx'),'utf8');
assert(layout.indexOf('import "./deepsteam-theme.css";')>layout.indexOf('import "./globals.css";'),'Theme must be included after base styles');checks++;
for(const file of ['components/space/SpaceDashboard.tsx','components/agents/ConnectedAgents.tsx']){
 const content=fs.readFileSync(path.join(root,'upstream/DeepTutor/web',file),'utf8');
 const chinese=[...content.matchAll(/zh: "([^"]+)"/g)].map(m=>m[1]);
 assert(chinese.length>10);assert(chinese.filter(value=>/[\u3400-\u9fff]/.test(value)).length>=chinese.length-1);
 checks+=2;
}
console.log(JSON.stringify({passed:true,assertions:checks,publicDefault:'en',standaloneDefault:'zh',savedLanguagePreserved:true,chineseCatalogComplete:true,approvedThemePreserved:true}));
