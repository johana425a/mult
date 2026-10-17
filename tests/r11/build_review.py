"""Build the isolated OpenMAIC source; retain logs and timing, no UI control."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import time

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'runtime/review-build'
OUT.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,NEXT_TELEMETRY_DISABLED='1',NODE_OPTIONS='--max-old-space-size=8192',
    ALLOWED_FRAME_ANCESTORS='deepsteam://portal deepsteam://app http://127.0.0.1:3791 http://127.0.0.1:3792',NEXT_PUBLIC_ENABLE_VIDEO_EXPORT='true')
node=os.environ.get('DEEPSTEAM_TEST_NODE') or shutil.which('node')
if not node:raise RuntimeError('Set DEEPSTEAM_TEST_NODE to the staged Node executable')
started=time.monotonic()
with (OUT/'openmaic-build.log').open('w',encoding='utf-8') as output:
    result=subprocess.run([node,str(ROOT/'upstream/OpenMAIC/node_modules/next/dist/bin/next'),'build','--webpack'],
        cwd=ROOT/'upstream/OpenMAIC',env=env,stdout=output,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
record={'exit_code':result.returncode,'seconds':round(time.monotonic()-started,3),'source':str(ROOT/'upstream/OpenMAIC')}
build=ROOT/'upstream/OpenMAIC/.next/BUILD_ID'
if result.returncode==0:record['build_id']=build.read_text().strip()
(OUT/'openmaic-build.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record));raise SystemExit(result.returncode)
