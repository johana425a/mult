"""Compile this checkout's generation sources in a fresh test directory.

Installed dependency packages may be reused explicitly, but a pre-existing
generation dist is never accepted as proof that the current source passes.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import release_gate as gate


def prepare(source,out,node,dependencies):
    source=Path(source).resolve(strict=True);out=Path(out).resolve()
    package=source/'upstream/OpenMAIC/packages/@openmaic/generation'
    dependencies=Path(dependencies).resolve(strict=True)
    modules=dependencies/'node_modules'
    compiler=modules/'typescript/lib/tsc.js'
    if not compiler.is_file():
        raise ValueError('Generation dependency package must expose node_modules/typescript/lib/tsc.js')
    type_roots=next((p/'node_modules/@types' for p in (dependencies,*dependencies.parents)
        if (p/'node_modules/@types/node/package.json').is_file()),None)
    if type_roots is None:raise ValueError('Pinned Node type declarations are required to compile generation')
    if out.exists():raise ValueError('Generation build must use a fresh directory')
    out.mkdir(parents=True)
    for name in ('src','templates','snippets','prompts-pbl'):
        if (package/name).is_dir():shutil.copytree(package/name,out/name)
    for name in ('package.json','tsconfig.json'):
        shutil.copy2(package/name,out/name)
    target=out/'node_modules'
    if os.name=='nt':
        env=dict(os.environ,DS_RELEASE_BUILD_LINK=str(target),DS_RELEASE_BUILD_TARGET=str(modules))
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
            "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:DS_RELEASE_BUILD_LINK -Target $env:DS_RELEASE_BUILD_TARGET | Out-Null"],
            env=env,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    else:target.symlink_to(modules,target_is_directory=True)
    with (out/'compile.log').open('x',encoding='utf-8') as log:
        result=subprocess.run([node,str(compiler),'-p',str(out/'tsconfig.json'),'--typeRoots',str(type_roots),'--types','node'],cwd=out,
            stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode!=0:raise ValueError('Current generation source failed to compile; see '+str(out/'compile.log'))
    files=[gate.descriptor(p) for p in sorted((out/'dist').rglob('*')) if p.is_file()]
    if not files or not (out/'dist/index.js').is_file():raise ValueError('Generation build produced no entrypoint')
    report={'passed':True,'source_files':[{'path':p.relative_to(package).as_posix(),'sha256':gate.digest(p)}
        for folder in ('src','templates','snippets','prompts-pbl') for p in sorted((package/folder).rglob('*')) if p.is_file()],
        'dependency_package':str(dependencies),'compiler':gate.descriptor(compiler),
        'node_types':gate.descriptor(type_roots/'node/package.json'),
        'files':files,'log':gate.descriptor(out/'compile.log')}
    gate.save_new(out/'build.json',report)
    return out/'dist',gate.descriptor(out/'build.json')
