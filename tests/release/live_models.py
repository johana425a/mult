"""Isolated real account inference through the installed adapters and Harness.

No original app start/restart; no native UI. Account grants stay local. Run this
using the candidate installation's bundled Python. The only test records are
written under --out, not into the user's learning database.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--runtime-root',required=True);p.add_argument('--account-root',required=True)
p.add_argument('--source-root',default=str(Path(__file__).resolve().parents[2]))
p.add_argument('--out',required=True);p.add_argument('--run')
args=p.parse_args()
ROOT=Path(args.runtime_root).resolve(strict=True);ACCOUNT=Path(args.account_root).resolve(strict=True)
SOURCE=Path(args.source_root).resolve(strict=True);WORK=Path(args.out).resolve()
if WORK==ACCOUNT or ACCOUNT in WORK.parents or WORK==ROOT or ROOT in WORK.parents:
    raise ValueError('Test output must be outside both installations')
WORK.mkdir(parents=True,exist_ok=True)
if (WORK/'live-models.json').exists():raise ValueError('Use a fresh output directory')
sys.path[:0]=[str(SOURCE/'installer'),str(ROOT),str(ROOT/'runtime/deeptutor-packages'),str(ACCOUNT/'scripts')]
import release_gate as gate
context=json.loads((Path(args.run)/'context.json').read_text('utf-8')) if args.run else None
if context:
    gate.validate_context(context)
    if Path(args.run).resolve()!=WORK:raise ValueError('--out must equal --run for bound evidence')
    installed=json.loads((ROOT/'installer/release-source.json').read_text('utf-8'))
    if installed['source']!=context['source']:raise ValueError('Candidate source binding differs')
    cold=gate.load_receipt(WORK,context,'installed-package')
    cold_detail=json.loads(gate.checked(cold['report']).read_text('utf-8'))
    if Path(cold_detail['installed_root']).resolve()!=ROOT:raise ValueError('Live calls must use the cold-installed candidate')
before=gate.runtime_binding(SOURCE,ROOT)
# Resolve the existing local account location without initializing or launching
# the application. No credentials or cookies are copied into the test profile.
from storage_paths import select_storage
storage=select_storage(ACCOUNT)
for name in list(os.environ):
    if name.startswith(('DEEPTUTOR_','AUTH_','LLM_','EMBEDDING_')) or name.endswith('_API_KEY'):
        os.environ.pop(name,None)
os.environ.update(storage.child_environment())
os.environ.update(DEEPTUTOR_HOME=str(storage.deeptutor_home),DEEPTUTOR_AUTH_ENABLED='false',
    AUTH_ENABLED='false',NEXT_PUBLIC_AUTH_ENABLED='false',DEEPSTEAM_HARNESS_CORE='1',
    PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
credential_path=storage.process_root/'harness-state/profile/credentials.dpapi'
if not credential_path.is_file():raise ValueError('DeepSeek account is not connected on the selected account installation')
catalog=json.loads((storage.deeptutor_home/'data/user/settings/model_catalog.json').read_text('utf-8'))
choices=[{'profile_id':a['id'],'model_id':m['id'],'reasoning_effort':'high'}
    for a in catalog['services']['llm']['profiles'] for m in a.get('models',[]) if m['model']=='gpt-6.1-sol']
if len(choices)!=1:raise ValueError('Exactly one configured gpt-6.1-sol connection is required; no silent model replacement')
from fastapi import FastAPI,Request,HTTPException
from integration.unified_model_runtime import UnifiedModelRuntime,ExecutionLease
from deeptutor.services.llm.config import LLMConfig
from deeptutor.multi_user.context import get_current_user
import uvicorn

listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
python_port=listener.getsockname()[1]
with socket.socket() as reserve:
    reserve.bind(('127.0.0.1',0));node_port=reserve.getsockname()[1]
guard=secrets.token_urlsafe(48);runtime=UnifiedModelRuntime();app=FastAPI()
from deeptutor.services.llm.provider_core.base import LLMResponse
from deeptutor.services.llm.provider_factory import get_runtime_provider
attempts=0
class FailingTransport:
    async def chat_stream_with_retry(self,**kwargs):
        global attempts
        attempts+=1
        return LLMResponse(content='Codex connection failed [ConnectError].',finish_reason='error')
runtime.provider_factory=lambda cfg:FailingTransport() if cfg.model=='synthetic-transport-failure' else get_runtime_provider(cfg)


@app.post('/freeze/{model}')
async def freeze(model:str,request:Request):
    if request.headers.get('authorization')!='Bearer '+guard:raise HTTPException(401)
    if model=='gpt-6.1-sol':
        execution=runtime.freeze(choices[0]);key=execution['execution_id'];lease=runtime.lease(key)
    elif model=='synthetic-connection-failure':
        key='dsexec_'+secrets.token_hex(16)
        cfg=LLMConfig(model='synthetic-transport-failure',binding='openai',provider_name='openai',
            api_key='synthetic-test-only',base_url=f'http://127.0.0.1:{python_port}',reasoning_effort='high',capabilities={'tools':True})
        lease=ExecutionLease(cfg,{}, {'model':model,'provider':'synthetic','reasoning_effort':'high','capabilities':{'tools':True}},
            get_current_user(),secrets.token_urlsafe(48),time.monotonic());runtime.leases[key]=lease
    elif model in gate.LIVE_MODELS[1:]:
        key='dsexec_'+secrets.token_hex(16)
        cfg=LLMConfig(model=model,api_key=guard,base_url=f'http://127.0.0.1:{node_port}/v1',
            binding='openai',provider_name='openai',api_format='openai_chat',reasoning_effort='high',
            display_model=model,max_output_tokens=256000,capabilities={'tools':True,'reasoning':True})
        lease=ExecutionLease(cfg,{}, {'model':model,'provider':'deepseek-account','reasoning_effort':'high',
            'capabilities':{'tools':True}},get_current_user(),secrets.token_urlsafe(48),time.monotonic())
        runtime.leases[key]=lease
    else:raise HTTPException(400,'Unsupported test selection')
    return {'provider':'deepsteam-custom','route_id':key,'model':key,
        'base_url':f'http://127.0.0.1:{python_port}/v1','api_key':lease.guard,
        'vision_supported':False,'vision_verified':False,'context_window':65536,'max_output_tokens':4096,
        'resolved_model':{'model':model,'provider':lease.snapshot['provider'],'reasoning_effort':'high'}}


@app.post('/v1/chat/completions')
async def complete(request:Request):
    return await runtime.completion(await request.json(),request.headers.get('authorization'))


@app.get('/counts')
async def counts(request:Request):
    if request.headers.get('authorization')!='Bearer '+guard:raise HTTPException(401)
    return {'attempts':attempts}


server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=python_port,log_level='error',access_log=False))
thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True)
thread.start();started=time.monotonic();exit_code=1
try:
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    if not server.started:raise RuntimeError('Isolated test server did not start')
    env=dict(os.environ,DS_TEST_PACKAGE=str(ROOT),DS_TEST_WORK=str(WORK),DS_TEST_GUARD=guard,
        DS_TEST_CREDENTIAL_PATH=str(credential_path),DS_TEST_MODEL_PORT=str(python_port),DS_TEST_HOST_PORT=str(node_port))
    with (WORK/'live-models.log').open('x',encoding='utf-8') as log:
        result=subprocess.run([str(ROOT/'runtime/node/node.exe'),str(Path(__file__).with_suffix('.mjs'))],
            env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=900)
    exit_code=result.returncode
finally:
    server.should_exit=True;thread.join(10);listener.close()
rows=json.loads((WORK/'live-model-transcript.json').read_text('utf-8')) if (WORK/'live-model-transcript.json').exists() else []
models=[]
for model in gate.LIVE_MODELS:
    text=next((r for r in rows if r['model']==model and r['case']=='text'),{})
    tool=next((r for r in rows if r['model']==model and r['case']=='tool'),{})
    models.append({'model':model,'text_passed':text.get('passed') is True,'tool_passed':tool.get('passed') is True,
        'tool_result_verified':tool.get('tool_result_verified') is True,
        'tool_names':tool.get('tool_names',[]),'frozen_selection':text.get('frozen_selection') is True and tool.get('frozen_selection') is True,
        'reasoning_effort':'high','text_seconds':text.get('seconds'),'tool_seconds':tool.get('seconds')})
recovery=next((r for r in rows if r['case']=='fault'),{})
passed=exit_code==0 and len(rows)==7 and all(x.get('passed') is True for x in rows)
passed=passed and gate.runtime_binding(SOURCE,ROOT)==before
fields={'passed':passed,'evidence_class':'live-provider','models':models,'synthetic_recovery':recovery,'seconds':round(time.monotonic()-started,3),
    'transcript':gate.descriptor(WORK/'live-model-transcript.json') if rows else gate.descriptor(WORK/'live-models.log'),
    'runtime_binding':before,'original_app_restarted':False,'native_ui_operations':0,'accounts_copied':False}
report=gate.receipt(context,'live-models',**fields) if context else fields
gate.save_new(WORK/'live-models.json',report)
print(json.dumps({'passed':passed,'models':models,'seconds':fields['seconds']},indent=2))
raise SystemExit(0 if passed else 1)
