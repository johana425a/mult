"""Run every release regression in fresh child processes; no original app launch."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_gate as gate
from prepare_release_generation import prepare


def execute_case(command, cwd, log, env, timeout=180):
    started = time.monotonic()
    try:
        with Path(log).open('x', encoding='utf-8') as stream:
            result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, timeout=timeout,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        code = result.returncode
    except subprocess.TimeoutExpired:
        code = 124
    except OSError as exc:
        Path(log).write_text(str(exc), encoding='utf-8'); code = 127
    output = Path(log).read_text('utf-8', errors='replace')
    counts = re.findall(r'(?:Ran (\d+) tests? in|DEEPSTEAM_ASSERTIONS=(\d+))', output)
    count = sum(int(a or b) for a,b in counts)
    skipped = bool(re.search(r'skipped[= :]+[1-9]\d*|\b[1-9]\d* skipped\b|\bSKIP\b', output, re.I))
    status = 'passed' if code == 0 and count > 0 and not skipped else 'failed'
    return {'status': status, 'exit_code': code, 'assertions': count, 'skipped': skipped,
            'seconds': round(time.monotonic()-started,3), 'log': gate.descriptor(log)}


def run(root, out, python, node, context=None):
    root = Path(root).resolve(strict=True); out = Path(out).resolve()
    if out == root or root in out.parents:
        raise ValueError('Use an evidence directory outside the source checkout')
    out.mkdir(parents=True, exist_ok=True)
    source = gate.source_identity(root)
    if context:
        gate.validate_context(context)
        if source != context['source']: raise ValueError('Wrong source checkout')
    env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    dependency_package = env.get('DEEPSTEAM_GENERATION_DEPENDENCIES',str(root/'upstream/OpenMAIC/packages/@openmaic/generation'))
    built,build_receipt = prepare(root,out/'generation-build',node,dependency_package)
    env['DEEPSTEAM_GENERATION_DIST']=str(built)
    rows = []
    for name in gate.REQUIRED_CASES:
        file = root / 'tests' / (name if name.startswith('r11/') else 'release/'+name)
        command = ([python, '-B', str(root/'tests/release/run_python_case.py'), str(file)]
                   if file.suffix == '.py' else
                   [node, '--require', str(root/'tests/release/count_assertions.cjs'), str(file)])
        row = {'case': name, 'evidence_class': 'deterministic',
               **execute_case(command, root, out/(name.replace('/','_')+'.log'), env)}
        rows.append(row)
        print(json.dumps({k:row[k] for k in ('case','status','assertions','seconds')}), flush=True)
    after = gate.source_identity(root)
    passed = all(x['status']=='passed' for x in rows) and after==source
    fields = {'passed':passed,'cases':rows,'source_before':source,'source_after':after,
              'model_calls':0,'native_ui_operations':0,'generation_build':build_receipt,
              'dependency_reuse':{k:env[k] for k in ('DEEPSTEAM_PYTHON_DEPENDENCIES','DEEPSTEAM_WEB_TEST_DEPENDENCIES','DEEPSTEAM_GENERATION_DIST') if k in env}}
    report = gate.receipt(context, 'regressions', **fields) if context else fields
    gate.save_new(out/'regressions.json', report)
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', default=str(Path(__file__).resolve().parents[1]))
    p.add_argument('--out', required=True); p.add_argument('--run')
    p.add_argument('--python', default=sys.executable)
    p.add_argument('--node', default=os.environ.get('DEEPSTEAM_TEST_NODE') or shutil.which('node'))
    args=p.parse_args()
    if not args.node: p.error('Node.js is required; set --node')
    ctx=json.loads((Path(args.run)/'context.json').read_text('utf-8')) if args.run else None
    if ctx and Path(args.out).resolve()!=Path(args.run).resolve(): p.error('--out must equal --run for bound acceptance')
    result=run(args.source,args.out,args.python,args.node,ctx)
    raise SystemExit(0 if result['passed'] else 1)
