"""Rebuild the source-only byte inventory from this Git checkout."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
EXCLUDED={'LOCAL-BUILD-INFO.json','PACKAGE-MANIFEST.json','PUBLIC-SOURCE-MANIFEST.json'}
PRIVATE={'node_modules','.git','.next','.next-github','__pycache__','.pytest_cache','.venv',
    'browser-profile','userData','harness-state','.cache','.turbo','dist'}

def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=True,indent=2)+'\n',encoding='utf-8',newline='\n')

def main():
    raw=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT)
    names=sorted(set(raw.decode('utf-8').split('\0'))-{''}-EXCLUDED)
    attributes=subprocess.check_output(['git','check-attr','-z','--stdin','eol'],
        input=('\0'.join(names)+'\0').encode('utf-8'),cwd=ROOT).decode('utf-8').split('\0')
    checkout_eol={attributes[i]:attributes[i+2] for i in range(0,len(attributes)-1,3)}
    rows=[]
    for name in names:
        path=Path(name);target=ROOT/path
        if not target.exists():continue
        if path.parts[0] in {'runtime','data','cache'} or PRIVATE.intersection(path.parts):
            raise ValueError('Generated/private member cannot enter source inventory: '+name)
        if not name.isascii() or path.is_absolute() or '..' in path.parts or target.is_symlink() or target.is_junction():
            raise ValueError('Unexpected source path: '+name)
        data=target.read_bytes()
        if checkout_eol.get(name)=='crlf':
            if path.suffix.lower()!='.cmd':raise ValueError('Unexpected CRLF source attribute: '+name)
            data=data.replace(b'\r\n',b'\n')
        row={'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'git_blob_sha':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}
        if checkout_eol.get(name)=='crlf':row['checkout_eol']='crlf'
        rows.append(row)
    identity=json.loads((ROOT/'RELEASE-IDENTITY.json').read_text('utf-8'))
    manifest=json.loads((ROOT/'PUBLIC-SOURCE-MANIFEST.json').read_text('utf-8'))
    manifest.update(version=identity['version'],source_base_commit=identity['source_base_commit'],
        earlier_recovery_checkout=identity.get('earlier_recovery_checkout'),file_count=len(rows),files=rows)
    save(ROOT/'PUBLIC-SOURCE-MANIFEST.json',manifest)
    digest=hashlib.sha256((ROOT/'PUBLIC-SOURCE-MANIFEST.json').read_bytes()).hexdigest()
    for name in ['LOCAL-BUILD-INFO.json','PACKAGE-MANIFEST.json']:
        value=json.loads((ROOT/name).read_text('utf-8'));value['source_manifest_sha256']=digest
        if name=='PACKAGE-MANIFEST.json':value['source_files_hashed']=len(rows)
        save(ROOT/name,value)
    print(json.dumps({'files':len(rows),'manifest_sha256':digest}))

if __name__=='__main__':main()
