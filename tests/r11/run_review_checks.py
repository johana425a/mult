"""Record deterministic fixtures separately from installed real-model acceptance."""
from pathlib import Path
import json
import os
import subprocess
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'runtime/review-checks-final';OUT.mkdir(parents=True,exist_ok=True)
PYTHON=os.environ.get('DEEPSTEAM_TEST_PYTHON') or sys.executable
NODE=os.environ.get('DEEPSTEAM_TEST_NODE') or shutil.which('node')
if not NODE:raise RuntimeError('Set DEEPSTEAM_TEST_NODE to the staged Node executable')
env=dict(os.environ,DEEPSTEAM_HARNESS_TEST_PYTHON=PYTHON,DEEPSTEAM_HARNESS_TEST_ROOT=str(ROOT/'runtime/review-tests'),PYTHONUTF8='1')
cases=[(name,[PYTHON,str(ROOT/'tests/r11'/name)],ROOT) for name in (
    'test_repair_transactions.py','test_upgrade_transactions.py','test_reading_pagination.py','test_delivery_gate.py',
    'test_execution_client.py','test_harness_result_contract.py','test_learning_record_archive.py')]
cases += [('harness-real-os',[NODE,'--test',str(ROOT/'integration/harness/test/execution_tasks.test.mjs'),
    str(ROOT/'integration/harness/test/review_durability.test.mjs'),str(ROOT/'integration/harness/test/workspaces.test.mjs')],ROOT),
    ('openmaic-adapter',[NODE,str(ROOT/'upstream/OpenMAIC/node_modules/vitest/vitest.mjs'),'run','--config','vitest.review.config.ts'],ROOT/'upstream/OpenMAIC'),
    ('installer-hard-death',[str(ROOT/'runtime/review-build/InstallerReviewTests.exe')],ROOT)]
results=[]
if sys.argv[1:]:
    results=json.loads((OUT/'results.json').read_text('utf-8'))['cases']
    cases=[case for case in cases if case[0] in sys.argv[1:]]
    if not cases:raise ValueError('No selected regression case')
for name,command,cwd in cases:
    started=time.monotonic()
    with (OUT/(name+'.log')).open('w',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    record={'case':name,'exit_code':result.returncode,'seconds':round(time.monotonic()-started,3),'log':str(OUT/(name+'.log'))}
    results=[row for row in results if row['case']!=name]
    results.append(record);print(json.dumps(record),flush=True)
    (OUT/'results.json').write_text(json.dumps({'method':'deterministic fixtures with real files/processes; no cloud model calls',
        'passed':all(row['exit_code']==0 for row in results),'cases':results},indent=2),encoding='utf-8')
raise SystemExit(0 if all(row['exit_code']==0 for row in results) else 1)
