"""One-run deterministic acceptance; selected checks never certify a full suite."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]


def assess(records, expected, identity):
    names = [row['case'] for row in records]
    selected = bool(records) and len(names) == len(set(names)) and set(names).issubset(expected)
    selected = selected and all(row.get('exit_code') == 0 and row.get('status') == 'passed'
        and row.get('identity') == identity and row.get('command_sha256') for row in records)
    full = bool(selected and set(names) == set(expected))
    return {'selected_passed':bool(selected), 'full_suite_passed':full, 'passed':full,
        'status':'passed' if full else 'partial' if selected else 'failed',
        'missing_cases':sorted(set(expected)-set(names))}


def source_identity(root, node):
    def command(args):
        return subprocess.check_output(args, cwd=root, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    files = command(['git','ls-files','--cached','--others','--exclude-standard','-z']).split(b'\0')
    digest = hashlib.sha256()
    for raw in sorted(set(path for path in files if path)):
        path = root / raw.decode('utf-8')
        digest.update(raw + b'\0' + (hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b'missing'))
    return {'run_id':uuid.uuid4().hex, 'source_tree':digest.hexdigest(),
        'commit':command(['git','rev-parse','HEAD']).decode().strip(),
        'python':sys.version, 'node':command([node,'--version']).decode().strip()}


def main(argv):
    out = ROOT/'runtime/review-checks-final'
    python = os.environ.get('DEEPSTEAM_TEST_PYTHON') or sys.executable
    node = os.environ.get('DEEPSTEAM_TEST_NODE') or shutil.which('node')
    if not node:
        raise RuntimeError('Set DEEPSTEAM_TEST_NODE to the staged Node executable')
    cases=[(name,[python,str(ROOT/'tests/r11'/name)],ROOT) for name in (
        'test_repair_transactions.py','test_upgrade_transactions.py','test_reading_pagination.py','test_delivery_gate.py',
        'test_execution_client.py','test_harness_result_contract.py','test_learning_record_archive.py','test_review_runner.py')]
    cases += [('harness-real-os',[node,'--test',str(ROOT/'integration/harness/test/execution_tasks.test.mjs'),
        str(ROOT/'integration/harness/test/second_review.test.mjs'),str(ROOT/'integration/harness/test/review_durability.test.mjs'),
        str(ROOT/'integration/harness/test/workspaces.test.mjs')],ROOT),
        ('openmaic-adapter',[node,str(ROOT/'upstream/OpenMAIC/node_modules/vitest/vitest.mjs'),'run','--config','vitest.review.config.ts'],ROOT/'upstream/OpenMAIC'),
        ('installer-hard-death',[str(ROOT/'runtime/review-build/InstallerReviewTests.exe')],ROOT)]
    expected=[row[0] for row in cases]
    if argv and (len(argv)!=len(set(argv)) or not set(argv).issubset(expected)):
        raise ValueError('Unknown or duplicate selected regression case')
    selected=[case for case in cases if not argv or case[0] in argv]
    identity=source_identity(ROOT,node);run_dir=out/identity['run_id'];run_dir.mkdir(parents=True)
    env=dict(os.environ,DEEPSTEAM_HARNESS_TEST_PYTHON=python,DEEPSTEAM_HARNESS_TEST_ROOT=str(ROOT/'runtime/review-tests'),PYTHONUTF8='1')
    (ROOT/'runtime/review-tests').mkdir(parents=True,exist_ok=True)
    records=[]
    for name, command, cwd in selected:
        started=time.monotonic();log=run_dir/(name+'.log')
        try:
            with log.open('w',encoding='utf-8') as stream:
                result=subprocess.run(command,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            exit_code=result.returncode
        except OSError as error:
            log.write_text(str(error),encoding='utf-8');exit_code=-1
        output=log.read_text('utf-8',errors='replace')
        skipped=bool(re.search(r'skipped[= :]+[1-9]\d*|\b[1-9]\d* skipped\b',output,re.I))
        record={'case':name,'exit_code':exit_code,'status':'failed' if exit_code else 'skipped' if skipped else 'passed',
            'identity':identity,'seconds':round(time.monotonic()-started,3),'log':str(log),
            'command_sha256':hashlib.sha256(json.dumps(command).encode()).hexdigest()}
        records.append(record);print(json.dumps(record),flush=True)
        report={'method':'deterministic fixtures with real files/processes; no cloud model calls', 'identity':identity,
            'expected_cases':expected,**assess(records,expected,identity),'cases':records}
        payload=json.dumps(report,indent=2)
        (run_dir/'results.json').write_text(payload,encoding='utf-8');(out/'results.json').write_text(payload,encoding='utf-8')
    final_identity=source_identity(ROOT,node)
    if any(final_identity[key]!=identity[key] for key in ('source_tree','python','node')):
        report.update(passed=False,selected_passed=False,full_suite_passed=False,status='source_changed_during_run')
        payload=json.dumps(report,indent=2)
        (run_dir/'results.json').write_text(payload,encoding='utf-8');(out/'results.json').write_text(payload,encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('passed','selected_passed','full_suite_passed','status','missing_cases')}))
    return 0 if report['selected_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
