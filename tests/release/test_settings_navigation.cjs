const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '../..'), web = path.join(root,'upstream/DeepTutor/web');
const req = createRequire(process.env.DEEPSTEAM_WEB_TEST_DEPENDENCIES || path.join(web,'package.json'));
const ts = req('typescript');
function load(name, imports={}) {
  const exports={};
  const code=ts.transpileModule(fs.readFileSync(path.join(web,name),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2021}}).outputText;
  vm.runInNewContext(code,{exports,require:id=>imports[id]||{},process:{env:{}}});
  return exports;
}
const nav=load('features/settings/navigation/settings-nav.ts',{'@/lib/product-brand':{PRODUCT_NAME:'DeepSteam'}});
const pages=load('features/settings/navigation/settings-pages.ts',{'./settings-nav':nav});
const visible=pages.visibleSettingsPages({hideAdminOnly:false,showLearnerOnly:true,showGuardianOnly:true});
for(const key of ['general','workspace','appearance','connections','llm','task-models','embedding','search','voice','multimodal','starters','attachments','video-learning','memory','usage']) {
  const row=visible.find(page=>page.key===key);
  assert.ok(row,key+' is visible');
  assert.match(pages.settingsPageLabel(key,row.label).zh,/[\u3400-\u9fff]/,key+' Chinese navigation');
  assert.ok(row.label.en.length>0);
}
assert.ok(pages.SETTINGS_PAGE_GROUPS.every(group=>/[\u3400-\u9fff]/.test(group.label.zh)));
assert.ok(!visible.some(row=>row.key==='about'));
assert.ok(!pages.SETTINGS_PAGE_GROUPS.some(group=>group.keys.includes('about')));
for (const name of ['DeepTutor-LICENSE.txt','DeepTutor-THIRD_PARTY_NOTICES.md','harness-MIT.txt']) {
  assert.ok(fs.statSync(path.join(root,'licenses',name)).size > 0, 'retained license: '+name);
}
console.log(JSON.stringify({passed:true,translatedNavigation:15,removedRequestedSection:true,licenseRetained:true}));
