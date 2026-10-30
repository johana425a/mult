const assert=require('node:assert/strict'),path=require('node:path'),{spawnSync}=require('node:child_process');
const web=path.resolve(__dirname,'../../upstream/DeepTutor/web');
const {createRequire}=require('node:module');
const req=createRequire(process.env.DEEPSTEAM_WEB_TEST_DEPENDENCIES||path.join(web,'package.json'));
const binary=path.join(path.dirname(req.resolve('vitest/package.json')),'vitest.mjs');
const result=spawnSync(process.execPath,[binary,'run','tests/composer-draft-restore-failure.spec.tsx','tests/chat/StandaloneComposer.smoke.spec.tsx','tests/chat-failed-submission-recovery.spec.tsx','tests/chat-streaming-status.spec.tsx','tests/ask-user-terminal-turn.spec.tsx','tests/ask-user-resume-cursor.spec.tsx','tests/ask-user-streaming-card.spec.tsx','--reporter=json','--maxWorkers=1'],
 {cwd:web,encoding:'utf8',env:process.env,timeout:120000,windowsHide:true});
if(result.status!==0){process.stderr.write(result.stdout+result.stderr);throw new Error('Composer recovery regression failed');}
const report=JSON.parse(result.stdout);
assert.ok(report.success&&report.numPassedTests>0);
assert.equal(report.numPendingTests,0);assert.equal(report.numFailedTests,0);
console.log('DEEPSTEAM_ASSERTIONS='+report.numPassedTests);
