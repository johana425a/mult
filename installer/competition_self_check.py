"""Read-only checks for the installed competition candidate on another Windows PC.

Uses only bundled Python/Node. This checks files and libraries, not native UI,
account login, provider availability or complete learning flows.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
from accept_installed_candidate import verify_payload


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--report',required=True)
    args=parser.parse_args();app=Path(args.app).resolve(strict=True);out=Path(args.report).absolute()
    if out.exists():raise ValueError('Choose a new report filename; existing evidence is preserved')
    if out.is_relative_to(app):raise ValueError('Save the report outside the program directory')
    started=time.monotonic();rows=[]
    def check(name,operation):
        before=time.monotonic()
        try:
            details=operation();row={'case':name,'status':'passed','details':details}
        except Exception as error:
            row={'case':name,'status':'failed','error':str(error)[:1200]}
        row['seconds']=round(time.monotonic()-before,3);rows.append(row)
        print(name+': '+row['status'],flush=True)
    def payload():
        manifest=json.loads((app/'installer/payload-manifest.json').read_text('utf-8-sig'))
        links=json.loads((app/'installer/junctions.json').read_text('utf-8-sig'))
        return {'files':verify_payload(app,manifest,links),'junctions':len(links),'version':manifest['version']}
    check('all_installed_payload_files',payload)
    def libraries():
        code="import json,sys;import docx,openpyxl,pptx,reportlab,fitz;print(json.dumps({'python':sys.version.split()[0],'libraries':['docx','openpyxl','pptx','reportlab','fitz']}))"
        result=subprocess.run([str(app/'runtime/python/python.exe'),'-I','-B','-c',code],
            capture_output=True,text=True,encoding='utf-8',timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise ValueError(result.stderr[-1200:])
        return json.loads(result.stdout)
    check('bundled_document_libraries',libraries)
    def node():
        result=subprocess.run([str(app/'runtime/node/node.exe'),'--version'],capture_output=True,text=True,
            timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True)
        return {'node':result.stdout.strip(),'external_runtime_used':False}
    check('bundled_node',node)
    def maintenance():
        expected=('DeepSteam.exe','Uninstall-DeepSteam.exe','.deepsteam-installed','.deepsteam-uninstall-id')
        missing=[name for name in expected if not (app/name).is_file() or not (app/name).stat().st_size]
        if missing:raise ValueError('Missing installed maintenance files: '+', '.join(missing))
        return {'present':list(expected),'uninstall_executed':False}
    check('installation_maintenance_files',maintenance)
    report={'schema':1,'evidence_class':'second-pc-read-only-self-check','passed':all(r['status']=='passed' for r in rows),
        'machine_id':hashlib.sha256(('DeepSteam competition|'+platform.node()).encode()).hexdigest(),
        'os':platform.platform(),'architecture':platform.machine(),'rows':rows,
        'seconds':round(time.monotonic()-started,3),'native_ui_tested':False,'models_tested':False,
        'installation_lifecycle_tested':False,'credentials_collected':False}
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    print('Report saved. Login, UI flows and uninstall/reinstall still require separate observations.',flush=True)
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
