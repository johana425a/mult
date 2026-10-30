const assert=require('node:assert/strict'),path=require('node:path'),{spawnSync}=require('node:child_process');
const web=path.resolve(__dirname,'../../upstream/DeepTutor/web');
const {createRequire}=require('node:module');
const req=createRequire(process.env.DEEPSTEAM_WEB_TEST_DEPENDENCIES||path.join(web,'package.json'));
const binary=path.join(path.dirname(req.resolve('vitest/package.json')),'vitest.mjs');
const result=spawnSync(process.execPath,[binary,'run','tests/co-writer-scope.spec.tsx','tests/co-writer-lazy-notebook.spec.tsx','tests/co-writer-editor-state.test.ts','tests/notebook-workspace-scope.spec.tsx','tests/notebook-sidebar-rename.spec.tsx','tests/notebook-record-edit-discoverability.spec.tsx','tests/notebook-summary-language.spec.tsx','tests/imported-chat-visible.spec.tsx','tests/competition-partner-entry.spec.tsx','--reporter=json','--maxWorkers=1'],{cwd:web,encoding:'utf8',env:process.env,timeout:120000,windowsHide:true});
if(result.status!==0){process.stderr.write(result.stdout+result.stderr);throw Error('Co-Writer scope or persistence regression failed');}
const report=JSON.parse(result.stdout);assert.ok(report.success&&report.numPassedTests>=3);assert.equal(report.numPendingTests,0);assert.equal(report.numFailedTests,0);
console.log('DEEPSTEAM_ASSERTIONS='+report.numPassedTests);
