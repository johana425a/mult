"""Bind every shipped application source and rebuilt UI to a candidate.

Dependency binaries remain pinned, reused dependencies, not a claimed rebuild.
Build receipts are engineering evidence, not signatures from an untrusted party.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import subprocess

COMPONENTS = {'frontend': 'upstream/DeepTutor/web/', 'classroom': 'upstream/OpenMAIC/'}
DIRECT_PREFIXES = ('integration/', 'scripts/', 'installer/', 'portal/')
NON_RUNTIME = {'.md', '.map'}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_names(root):
    raw = subprocess.check_output(['git','-C',str(root),'ls-files','--cached','--others','--exclude-standard','-z'],
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return sorted(set(v.decode('utf-8') for v in raw.split(b'\0') if v))


def member(root, name):
    value = PurePosixPath(name)
    if not name or value.is_absolute() or '..' in value.parts or ':' in name or '\\' in name:
        raise ValueError('Unsafe runtime member: '+name)
    path = root / name
    path.resolve().relative_to(root.resolve())
    return path


def component_identity(root, prefix, names=None):
    names = source_names(root) if names is None else names
    shared = {'upstream/DeepTutor/deeptutor/config/competition-features.json'} if prefix == COMPONENTS['frontend'] else set()
    selected = [n for n in names if (n.startswith(prefix) or n in shared) and (root/n).is_file()]
    if not selected: raise ValueError('Empty component: '+prefix)
    with ThreadPoolExecutor(max_workers=6) as pool:
        hashes = list(pool.map(lambda n: sha(root/n), selected))
    rows=[{'path':n,'sha256':h} for n,h in zip(selected,hashes)]
    value=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'prefix':prefix,'files':len(rows),'sha256':value}


def is_test(name):
    p=PurePosixPath(name)
    return ('tests' in p.parts or p.name.startswith('test_') or '.test.' in p.name or
            '.fixture.' in p.name or '-fixture.' in p.name or p.name.endswith('-acceptance.cjs'))


def direct_map(names):
    """Explicit application families; new files in a family cannot escape checks."""
    rows=[]
    for name in names:
        p=PurePosixPath(name)
        if is_test(name) or p.suffix in NON_RUNTIME: continue
        targets=[]
        if name.startswith(DIRECT_PREFIXES):
            targets.append(name)
            if name.startswith('integration/harness/') and p.suffix in {'.mjs','.cjs','.py','.json'}:
                targets.append('runtime/harness/'+name.removeprefix('integration/harness/'))
        elif name.startswith('upstream/DeepTutor/deeptutor/'):
            targets.append('runtime/deeptutor-packages/'+name.removeprefix('upstream/DeepTutor/'))
            targets.append('runtime/python/Lib/site-packages/'+name.removeprefix('upstream/DeepTutor/'))
        elif name.startswith('desktop/') and p.suffix in {'.cjs','.html','.json','.png'}:
            targets.append(name)
            if p.name != 'package-lock.json':targets.append('runtime/desktop/resources/app/'+p.name)
        elif name in {'DeepSteam.ico','Start-DeepSteam.cmd','Stop-DeepSteam.cmd','Setup-DeepSteam-Portable.ps1',
                      'RELEASE-IDENTITY.json','LOCAL-BUILD-INFO.json','PACKAGE-MANIFEST.json'}:
            targets.append(name)
        rows.extend({'source':name,'runtime':target} for target in targets)
    return rows


def read_asar(archive):
    """Read packed regular entries, so a matching source mirror alone is insufficient."""
    result={}
    with archive.open('rb') as stream:
        header=stream.read(16)
        if len(header)!=16:raise ValueError('Invalid desktop ASAR header')
        size_len,header_size,pickle_size,json_size=struct.unpack('<4I',header)
        if size_len!=4 or not 0<json_size<=header_size<=32*1024*1024:
            raise ValueError('Invalid desktop ASAR sizes')
        tree=json.loads(stream.read(json_size))
        base=8+header_size
        def walk(entries,prefix=''):
            for name,item in entries.items():
                key=prefix+name
                if 'files' in item:walk(item['files'],key+'/');continue
                if item.get('unpacked') or 'link' in item:raise ValueError('Unexpected unpacked desktop source')
                size=int(item['size']);offset=int(item['offset'])
                if min(size,offset)<0:raise ValueError('Invalid ASAR entry')
                stream.seek(base+offset);data=stream.read(size)
                if len(data)!=size:raise ValueError('Truncated desktop ASAR entry')
                result[key]=hashlib.sha256(data).hexdigest()
        walk(tree['files'])
    return result


def verify_direct(source, runtime, names=None):
    names=source_names(source) if names is None else names
    mapping=direct_map(names)
    if not mapping:raise ValueError('No application source mapped')
    rows=[];errors=[]
    for row in mapping:
        src=member(source,row['source']);dst=member(runtime,row['runtime'])
        if not src.is_file():
            # Removed tracked code must not remain executable in the package.
            if dst.exists():errors.append('Deleted source remains in runtime: '+row['runtime'])
            continue
        if not dst.is_file():errors.append('Missing application file: '+row['runtime']);continue
        expected=sha(src)
        if sha(dst)!=expected:
            label='Stale Python mirror: ' if row['runtime'].startswith('runtime/python/Lib/site-packages/') else 'Stale application file: '
            errors.append(label+row['runtime'])
        rows.append({**row,'sha256':expected})
    if errors:raise ValueError('\n'.join(errors[:60])+f'\nTotal source/runtime mismatches: {len(errors)}')
    return rows


def verify_compiled(source, runtime, names=None):
    names=source_names(source) if names is None else names
    file=runtime/'installer/compiled-source.json'
    receipt=json.loads(file.read_text('utf-8'))
    builds=receipt.get('components',[])
    release_file=source/'RELEASE-IDENTITY.json'
    release=json.loads(release_file.read_text('utf-8')) if release_file.is_file() else {}
    packaged_language=release.get('default_language') if release.get('edition','').startswith('windows-standalone') else None
    if len(builds)!=len(COMPONENTS) or {x.get('component') for x in builds}!=set(COMPONENTS):
        raise ValueError('Both frontend and classroom must have current build receipts')
    for build in builds:
        if packaged_language and build.get('default_language')!=packaged_language:
            raise ValueError('Compiled language differs from standalone edition: '+build['component'])
        identity=component_identity(source,COMPONENTS[build['component']],names)
        if build.get('source')!=identity or build.get('source_after')!=identity:
            raise ValueError('Compiled source changed: '+build['component'])
        if build.get('exit_code')!=0 or not build.get('build_id') or not build.get('outputs'):
            raise ValueError('Incomplete component build')
        rows=build['outputs']
        if len(rows)!=len({r['path'] for r in rows}):raise ValueError('Duplicate build output')
        required_prefix='runtime/native-frontends/' if build['component']=='frontend' else 'runtime/openmaic-standalone/'
        for row in rows:
            if not row['path'].startswith(required_prefix):raise ValueError('Unrelated build output')
            out=member(runtime,row['path'])
            if not out.is_file() or out.stat().st_size!=row['bytes'] or sha(out)!=row['sha256']:
                raise ValueError('Compiled output changed: '+row['path'])
        declared={r['path'] for r in rows}
        ids=[r for r in rows if r['path'].endswith('/BUILD_ID')]
        if len(ids)!=1 or member(runtime,ids[0]['path']).read_text('utf-8').strip()!=build['build_id']:
            raise ValueError('Build ID is not backed by compiled output')
        # Enumerate output directories as well: extra stale chunks must not pass.
        output_roots=build.get('output_roots',[])
        if not output_roots:raise ValueError('Missing complete output inventory roots')
        found=set()
        for prefix in output_roots:
            if not prefix.startswith(required_prefix):raise ValueError('Invalid output inventory root')
            root=member(runtime,prefix)
            for p in root.rglob('*'):
                if p.is_symlink() or p.is_junction():raise ValueError('Compiled assets must be plain files')
                if p.is_file():found.add(p.relative_to(runtime).as_posix())
        if not found or not found.issubset(declared):raise ValueError('Unrecorded compiled output')
    return {'receipt_sha256':sha(file),'components':builds}


def verify_runtime(source, runtime):
    import release_gate as gate
    names=source_names(source)
    rows=verify_direct(source,runtime,names)
    desktop={r['runtime'].removeprefix('runtime/desktop/resources/app/'):r['sha256']
        for r in rows if r['runtime'].startswith('runtime/desktop/resources/app/')}
    if desktop!=read_asar(runtime/'runtime/desktop/resources/app.asar'):
        raise ValueError('Actual Electron ASAR does not match the source mirror')
    compiled=verify_compiled(source,runtime,names)
    return {'schema':2,'source':gate.source_identity(source),'synchronized_files':rows,
        'compiled':compiled,'desktop_asar_sha256':sha(runtime/'runtime/desktop/resources/app.asar'),
        'dependencies_reused':True,'full_clean_dependency_build_claimed':False}
