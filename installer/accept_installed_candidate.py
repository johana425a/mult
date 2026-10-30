"""Cold-install one frozen candidate without launching its UI, then hash payload.

Only a new directory owned by this acceptance run is used. Existing installations
are never upgraded, stopped or overwritten. The disposable install is retained
for live-model and native acceptance, including its per-user uninstall entry.
"""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import release_gate as gate


def safe_member(root,name):
    rel=PurePosixPath(name)
    if rel.is_absolute() or '..' in rel.parts or ':' in name or '\\' in name:
        raise ValueError('Unsafe payload member: '+name)
    p=Path(root)/rel
    p.resolve().relative_to(Path(root).resolve())
    return p


def verify_payload(root,manifest,links):
    names=[r['path'] for r in manifest['files']]
    if not names or len(names)!=len(set(n.casefold() for n in names)):
        raise ValueError('Payload has zero files or duplicate identities')
    for row in manifest['files']:
        path=safe_member(root,row['path'])
        gate.checked({**row,'path':str(path)})
    for row in links:
        link=safe_member(root,row['path']);target=safe_member(root,row['target'])
        if not link.exists() or link.resolve()!=target.resolve():
            raise ValueError('Installed junction mismatch: '+row['path'])
    return len(names)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True)
    args=p.parse_args();run=Path(args.run).resolve(strict=True)
    context=json.loads((run/'context.json').read_text('utf-8'));gate.validate_context(context)
    if (run/'installed-package.json').exists():raise ValueError('Acceptance already recorded; use a new run to retry')
    exes=[gate.checked(r) for r in context['artifacts'] if r['path'].lower().endswith('.exe')]
    payloads=[gate.checked(r) for r in context['artifacts'] if r['path'].lower().endswith('.payload.dat')]
    if len(exes)!=1 or len(payloads)>1:raise ValueError('Expected exactly one EXE and at most one payload')
    exe=exes[0];archive=payloads[0] if payloads else exe
    with zipfile.ZipFile(archive) as package:
        manifest=json.loads(package.read('installer/payload-manifest.json'))
        links=json.loads(package.read('installer/junctions.json'))
        source=json.loads(package.read('installer/release-source.json'))
    if source['source']!=context['source'] or manifest['version']!=context['version']:
        raise ValueError('Package source/version is not this acceptance candidate')
    root=run/'isolated-install'
    if root.exists():raise ValueError('Cold acceptance requires a new empty installation path')
    if len(str(root))>100:raise ValueError('Choose a shorter candidate path (installer limit is 100 characters)')
    started=time.monotonic();flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    self_report=run/'installer-self-test.txt'
    self_result=subprocess.run([str(exe),'--self-test',str(self_report)],timeout=3600,creationflags=flags)
    self_pass=self_result.returncode==0 and self_report.read_text('utf-8-sig').startswith('PASS')
    if not self_pass:raise ValueError('Installer self-test failed')
    with (run/'cold-install.log').open('x',encoding='utf-8') as log:
        result=subprocess.run([str(exe),'--install-to',str(root),'--no-launch'],stdin=subprocess.DEVNULL,
            stdout=log,stderr=subprocess.STDOUT,timeout=3600,creationflags=flags)
    if result.returncode!=0 or not (root/'.deepsteam-installed').read_text('utf-8-sig').startswith('DeepSteam '+context['version']):
        raise ValueError('Cold installation failed; partial target retained for diagnostics')
    count=verify_payload(root,manifest,links)
    if json.loads((root/'installer/release-source.json').read_text('utf-8'))!=source:
        raise ValueError('Installed source binding differs from payload')
    gate.runtime_binding(context['source']['root'],root)
    gate.validate_context(context)
    detail={'passed':True,'installed_root':str(root),'files_verified':count,'junctions_verified':len(links),
        'seconds':round(time.monotonic()-started,3),'self_test':gate.descriptor(self_report),
        'install_log':gate.descriptor(run/'cold-install.log'),'original_app_restarted':False,'launched':False}
    gate.save_new(run/'installed-package-details.json',detail)
    gate.save_new(run/'installed-package.json',gate.receipt(context,'installed-package',passed=True,
        self_test_passed=True,all_payload_hashes_passed=True,source_binding_passed=True,isolated_install=True,
        files_verified=count,report=gate.descriptor(run/'installed-package-details.json')))
    print(json.dumps(detail,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('INSTALL ACCEPTANCE FAILED: '+str(exc),file=sys.stderr);raise SystemExit(1)
