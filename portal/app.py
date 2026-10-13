"""Original integration API for DeepTutor and OpenMAIC; loopback deployment only."""
from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse, urlencode

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.cors import CORSMiddleware

from portal.storage import Store, identifier, now
from portal import material_sources
from integration.harness_bridge import HarnessBridge, HarnessError, GUIDE
from integration.workspace_management import WorkspaceManager

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('EDUAGENT_DATA', str(ROOT / 'data')))
store = Store(DATA)
UPLOADS = DATA / 'materials'
UPLOADS.mkdir(parents=True, exist_ok=True)
TASKS: set[asyncio.Task] = set()
CONTENT_TASKS: dict[str, asyncio.Task] = {}
DELETION_LOCKS: dict[str, asyncio.Lock] = {}
MATERIAL_LOCKS: dict[str, asyncio.Lock] = {}
ACTIVE_LESSONS: set[str] = set()
ALLOWED_ORIGINS = {'http://127.0.0.1:3791', 'http://localhost:3791', 'http://127.0.0.1:3792', 'http://testserver'}
DT_URL = 'http://127.0.0.1:8011'
OM_URL = 'http://127.0.0.1:3793'
EXECUTION_TIMEOUT = 300
HARNESS_BRIDGES = {}
WORKSPACE_MANAGERS = {}


def harness_bridge():
    # Tests replace Store; a bridge must never accidentally retain the old DB.
    key = str(store.path)
    if key not in HARNESS_BRIDGES:
        HARNESS_BRIDGES[key] = HarnessBridge(store, ROOT)
    return HARNESS_BRIDGES[key]


def workspace_manager():
    bridge = harness_bridge()
    key = str(store.path)
    if key not in WORKSPACE_MANAGERS or WORKSPACE_MANAGERS[key].transport is not bridge.transport:
        WORKSPACE_MANAGERS[key] = WorkspaceManager(bridge.transport)
    return WORKSPACE_MANAGERS[key]


async def configured_provider(settings):
    return await harness_bridge().selected_provider(settings)


def launch(coro, content_id=None):
    task = asyncio.create_task(coro)
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    if content_id:
        CONTENT_TASKS[content_id] = task
        def discard(done):
            if CONTENT_TASKS.get(content_id) is done:
                CONTENT_TASKS.pop(content_id, None)
        task.add_done_callback(discard)
    return task


def lesson_deleting(lesson_id):
    item = store.get('lessons', lesson_id)
    return item is None or item['status'] == 'deleting'


def safe_error(exc):
    # Provider errors must never expose keys back to the browser or records.
    text = str(exc)
    try:
        for key in ('api_key', 'tts_api_key'):
            value = store.settings(secret=True).get(key)
            if value:
                text = text.replace(value, '[key hidden]')
    except Exception:
        pass
    text = re.sub(r'(?i)(bearer\s+)[^\s"\']+', r'\1[hidden]', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[hidden]', text)
    # Present the failing service without surfacing application-owned endpoints.
    # Keep custom provider URLs and useful status codes intact.
    text = re.sub(r'(?i)https?://(?:127\.0\.0\.1|localhost):(?:379[1-6]|8011)(?=[/\s\"\'?#]|$)[^\s\"\'<>]*', 'DeepSteam internal service', text)
    return text[:1500]


def dt_bridge():
    from integration.deeptutor_bridge import DeepTutorBridge
    return DeepTutorBridge(base_url=DT_URL, timeout=EXECUTION_TIMEOUT)


def om_bridge():
    from integration.openmaic_bridge import OpenMAICBridge
    return OpenMAICBridge(base_url=OM_URL)


@asynccontextmanager
async def lifespan(app):
    try:
        await harness_bridge().restore_routes()
    except HarnessError:
        # Starting without a model host must not prevent access to old records.
        pass
    for lesson in store.list('lessons'):
        if lesson['status'] == 'deleting':
            launch(_delete_lesson(lesson['id']))
            continue
        if lesson['status'] in ('queued', 'generating', 'awaiting_reconnect'):
            if lesson['job_id']:
                launch(generate_lesson(lesson['id'], resume=True), lesson['id'])
            else:
                store.update('lessons', lesson['id'], status='interrupted', error='The service restarted before a generation job ID was received. Materials were preserved. Generate again.', updated_at=now())
    for attempt in store.list('attempts'):
        if attempt['status'] in ('queued', 'grading'):
            store.update('attempts', attempt['id'], status='saved', error='The service restarted. Your original answer was preserved, but model feedback was not confirmed.', updated_at=now())
    yield
    for task in list(TASKS):
        task.cancel()
    if TASKS:
        await asyncio.gather(*TASKS, return_exceptions=True)


app = FastAPI(title='DeepSteam', lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:3792'],
                   allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
                   allow_headers=['Content-Type'], allow_credentials=False)


@app.middleware('http')
async def local_origin(request: Request, call_next):
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin not in ALLOWED_ORIGINS:
        return JSONResponse({'detail': 'Changes are accepted only from the local workbench.'}, status_code=403)
    workspace_request = any(request.url.path.startswith('/api/harness/' + prefix)
                            for prefix in ('workspaces', 'workspace-management', 'sessions', 'approvals'))
    if (request.url.path.startswith('/api/harness/') and '/internal/' not in request.url.path
            and (request.method not in ('GET', 'HEAD', 'OPTIONS') or workspace_request)
            and request.method != 'OPTIONS' and origin not in ALLOWED_ORIGINS):
        return JSONResponse({'detail': 'Use the local model connection page for this operation.', 'code': 'origin_required'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


async def healthy(url):
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
            response = await client.get(url)
            return response.status_code == 200
    except httpx.HTTPError:
        return False


@app.get('/api/status')
async def status():
    dt, om = await asyncio.gather(healthy(DT_URL + '/api/auth/status'), healthy(OM_URL + '/api/health'))
    return {'services': {'deeptutor': {'ok': dt, 'entry': 'learning'}, 'openmaic': {'ok': om, 'entry': 'classroom'}}, 'counts': {table: len(store.list(table)) for table in ('materials', 'lessons', 'attempts')}}


def material_public(item, full=False):
    value = {k: v for k, v in item.items() if k not in ('path', 'text', 'source_snapshot')}
    value['text_preview'] = item['text'][:24000 if full else 400]
    value['preview_truncated'] = bool(item['preview_truncated'] or (full and len(item['text']) > 24000))
    snapshot = material_sources.decode(item.get('source_snapshot'), {})
    value['source_status'] = snapshot.get('status')
    value['source_locators'] = [unit.get('locator') for unit in snapshot.get('units', [])]
    value['warnings'] = snapshot.get('warnings', [])
    value['next_cursor'] = snapshot.get('next_cursor')
    return value


@app.get('/api/materials')
async def materials(workspace_id: str | None = None):
    return {'items': [material_public(m) for m in store.list('materials')
                      if workspace_id is None or (m.get('workspace_id') or '') == workspace_id]}


@app.get('/api/material-config')
async def material_config():
    return {'max_bytes': material_sources.MAX_DOCUMENT_BYTES, 'extensions': sorted(material_sources.SUPPORTED_SUFFIXES)}


class DocumentReadInput(BaseModel):
    path: str = ''
    cursor: str | None = None
    document_sha256: str | None = None
    max_units: int = Field(default=10, ge=1, le=10)
    asset_id: str | None = None
    query: str | None = None
    limit: int = Field(default=200, ge=1, le=500)
    refresh: bool = False
    coverage_cursor: str | None = None
    engine: str = Field(default='auto', pattern='^(auto|builtin|mineru)$')
    tier: str = Field(default='basic', pattern='^(basic|standard)$')
    job_id: str | None = None


@app.post('/api/workspaces/{workspace_id}/documents/{action}')
async def workspace_document(workspace_id: str, action: str, value: DocumentReadInput):
    if action not in {'list', 'search', 'inventory', 'coverage', 'read', 'asset', 'status', 'cancel'}:
        raise HTTPException(404, 'Material operation not found.')
    try:
        payload = {'path': value.path, 'cursor': value.cursor, 'document_sha256': value.document_sha256}
        if action == 'read':
            payload['max_chars'] = material_sources.READ_OPTIONS['max_chars']
            payload['max_units'] = value.max_units
            payload['engine'] = value.engine
            payload['tier'] = value.tier
            if value.job_id:
                payload['job_id'] = value.job_id
        elif action == 'asset':
            payload.pop('cursor')
            payload['asset_id'] = value.asset_id
        elif action in {'status', 'cancel'}:
            payload = {'path': value.path, 'job_id': value.job_id}
        elif action == 'coverage':
            payload = {'path': value.path, 'coverage_cursor': value.coverage_cursor,
                       'limit': min(value.limit, 200), 'document_sha256': value.document_sha256}
        else:
            payload = {'path': value.path or '.', 'limit': value.limit}
            if action == 'search':
                payload['query'] = value.query or ''
            elif action == 'inventory':
                payload.update(cursor=value.cursor, refresh=value.refresh, limit=min(value.limit, 200))
        return await material_sources.workspace_request(workspace_id, action, **payload)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, safe_error(exc)) from None


class WorkspaceMaterialInput(DocumentReadInput):
    workspace_id: str = Field(min_length=1, max_length=100)


@app.post('/api/materials/from-workspace', status_code=201)
async def workspace_material(value: WorkspaceMaterialInput):
    try:
        result = await material_sources.workspace_request(value.workspace_id, 'read',
            path=value.path, cursor=value.cursor, document_sha256=value.document_sha256,
            max_units=value.max_units, max_chars=material_sources.READ_OPTIONS['max_chars'])
        fields = material_sources.window_fields(result, value.cursor)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, safe_error(exc)) from None
    filename = Path(value.path.replace('\\', '/')).name
    existing = next((item for item in store.list('materials')
                     if item.get('source_kind') == 'workspace' and item.get('workspace_id') == value.workspace_id
                     and item.get('relative_path') == value.path and item.get('source_cursor') == value.cursor
                     and int(item.get('source_max_units') or 10) == value.max_units
                     and item.get('document_sha256') == fields['document_sha256']
                     and material_sources.same_window(item.get('source_snapshot'), result)), None)
    if existing:
        return material_public(existing, full=True)
    item = {'id': identifier('material'), 'title': Path(filename).stem, 'filename': filename,
            'path': '', 'source_kind': 'workspace', 'workspace_id': value.workspace_id,
            'relative_path': value.path, 'source_max_units': value.max_units,
            'created_at': now(), 'dt_material_id': None, 'sync_error': None, **fields}
    store.insert('materials', item)
    return material_public(item, full=True)


class MaterialDeleteInput(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)


@app.post('/api/materials/delete')
async def delete_materials(value: MaterialDeleteInput):
    ids = list(dict.fromkeys(value.ids))
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', key) for key in ids):
        raise HTTPException(422, 'Invalid material ID.')
    results = []
    deadline = asyncio.get_running_loop().time() + 90
    for key in ids:
        lock = MATERIAL_LOCKS.setdefault(key, asyncio.Lock())
        try:
            await asyncio.wait_for(lock.acquire(), timeout=max(0.01, min(8, deadline - asyncio.get_running_loop().time())))
        except TimeoutError:
            results.append({'id': key, 'deleted': False, 'code': 'material_busy',
                            'error': 'The material is still synchronizing and has not been deleted. Try again shortly.'})
            continue
        try:
            results.append(store.delete_material_copy(key, UPLOADS))
        except OSError:
            results.append({'id': key, 'deleted': False, 'code': 'file_busy',
                            'error': 'The imported copy could not be deleted. Its record was preserved. Close programs using the file, then retry.'})
        except Exception:
            results.append({'id': key, 'deleted': False, 'code': 'delete_failed',
                            'error': 'Deletion has not been confirmed. The material record was preserved. Try again.'})
        finally:
            lock.release()
    return {'items': results, 'deleted_count': sum(bool(item['deleted']) for item in results)}


@app.get('/api/materials/{material_id}')
async def material(material_id: str):
    result = store.get('materials', material_id)
    if not result:
        raise HTTPException(404, 'Material not found.')
    return material_public(result, full=True)


@app.get('/api/materials/{material_id}/file')
async def material_file(material_id: str):
    result = store.get('materials', material_id)
    if not result:
        raise HTTPException(404, 'Material not found.')
    if result.get('source_kind') == 'workspace':
        raise HTTPException(409, 'The original remains in the workspace. Open it there; no duplicate file was created here.')
    return FileResponse(result['path'], filename=result['filename'])


@app.post('/api/materials/{material_id}/read')
async def read_material_window(material_id: str, value: DocumentReadInput):
    source = store.get('materials', material_id)
    if not source:
        raise HTTPException(404, 'Material not found.')
    try:
        return await material_sources.read_source({**source, 'source_max_units': value.max_units}, UPLOADS, cursor=value.cursor)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, safe_error(exc)) from None


@app.post('/api/materials/{material_id}/select-range', status_code=201)
async def select_material_window(material_id: str, value: DocumentReadInput):
    async with MATERIAL_LOCKS.setdefault(material_id, asyncio.Lock()):
        source = store.get('materials', material_id)
        if not source:
            raise HTTPException(404, 'Material not found.')
        try:
            result = await material_sources.read_source({**source, 'source_max_units': value.max_units}, UPLOADS, cursor=value.cursor)
            fields = material_sources.window_fields(result, value.cursor)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, safe_error(exc)) from None
        if (source.get('source_cursor') == value.cursor
                and int(source.get('source_max_units') or 10) == value.max_units
                and source.get('document_sha256') == fields['document_sha256']
                and material_sources.same_window(source.get('source_snapshot'), result)):
            return material_public(source, full=True)
        # A selected range may already be used by a classroom; never mutate it.
        item = {**source, **fields, 'source_max_units': value.max_units,
                'id': identifier('material'), 'created_at': now(), 'dt_material_id': None}
        if source.get('source_kind') != 'workspace':
            # The original upload keeps ownership. A range is a reference to it,
            # and deletion of either row preserves any still-referenced copy.
            item['source_kind'] = 'upload_range'
        store.insert('materials', item)
        return material_public(item, full=True)


async def sync_material(material_id):
    async with MATERIAL_LOCKS.setdefault(material_id, asyncio.Lock()):
        return await _sync_material(material_id)


async def _sync_material(material_id):
    source = store.get('materials', material_id)
    if source is None:
        return None
    if source['dt_material_id']:
        return source['dt_material_id']
    try:
        if source.get('source_snapshot'):
            # Native feedback receives the selected extracted window, never a
            # second upload of the original PDF or Office document.
            import tempfile
            with tempfile.TemporaryDirectory(prefix='selected-source-', dir=UPLOADS) as directory:
                selected = Path(directory) / 'selected-source.md'
                selected_snapshot = material_sources.decode(source.get('source_snapshot'), {})
                selected_locators = json.dumps([unit.get('locator') for unit in selected_snapshot.get('units', [])], ensure_ascii=False)
                selected.write_text('Material: ' + source['filename'] + '\nVersion: ' + (source.get('document_sha256') or '')
                                    + '\nSelected scope: ' + selected_locators + '\nThis is a local parsing snapshot of the selected scope, not the entire source document.\n\n' + source['text'], encoding='utf-8')
                result = await dt_bridge().import_material(selected, title=source['title'])
        else:
            result = await dt_bridge().import_material(Path(source['path']), title=source['title'])
        mid = result.get('material_id') or result.get('id')
        if not mid:
            raise ValueError('DeepSteam did not return a material ID.')
        store.update('materials', material_id, dt_material_id=mid, sync_error=None)
        return mid
    except Exception as exc:
        store.update('materials', material_id, sync_error=safe_error(exc))
        return None


def material_filename(filename):
    filename = Path(filename.replace('\\', '/')).name
    filename = re.sub(r'[\x00-\x1f]', '', filename)[:160]
    suffix = Path(filename).suffix.lower()
    if suffix not in material_sources.SUPPORTED_SUFFIXES:
        raise HTTPException(415, 'Supported formats: PDF, DOCX, PPTX, Markdown, TXT, and XLSX. Convert legacy DOC/PPT files to DOCX/PPTX first.')
    return filename, suffix


async def finish_material_upload(mid, path, filename, workspace_id):
    try:
        result = await material_sources.managed_request(UPLOADS, path.name, **material_sources.READ_OPTIONS)
        fields = material_sources.window_fields(result)
        item = {'id': mid, 'title': Path(filename).stem, 'filename': filename, 'path': str(path),
                'source_kind': 'upload', 'workspace_id': workspace_id, **fields,
                'dt_material_id': None, 'sync_error': None, 'created_at': now()}
        store.insert('materials', item)
        return material_public(item, full=True)
    except BaseException as exc:
        path.unlink(missing_ok=True)
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
        raise HTTPException(400, 'Material parsing failed: ' + safe_error(exc)) from exc


async def save_material(filename, content, workspace_id=''):
    filename, suffix = material_filename(filename)
    if not content or len(content) > material_sources.MAX_DOCUMENT_BYTES:
        raise HTTPException(413, f'Materials must be nonempty and no larger than {material_sources.MAX_DOCUMENT_BYTES // 1024 // 1024} MB.')
    if suffix == '.pdf' and not content.startswith(b'%PDF-'):
        raise HTTPException(400, 'The file content is not a valid PDF.')
    mid = identifier('material')
    path = UPLOADS / (mid + suffix)
    path.write_bytes(content)
    return await finish_material_upload(mid, path, filename, workspace_id)


@app.post('/api/materials', status_code=201)
async def upload(file: UploadFile = File(...), workspace_id: str = ''):
    filename, suffix = material_filename(file.filename or 'material.txt')
    mid = identifier('material')
    path = UPLOADS / (mid + suffix)
    size = 0
    try:
        with path.open('xb') as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > material_sources.MAX_DOCUMENT_BYTES:
                    raise HTTPException(413, f'Materials cannot exceed {material_sources.MAX_DOCUMENT_BYTES // 1024 // 1024} MB.')
                stream.write(chunk)
        if not size:
            raise HTTPException(413, 'Materials cannot be empty.')
        return await finish_material_upload(mid, path, filename, workspace_id)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


@app.post('/api/demo-material', status_code=201)
async def demo_material():
    path = ROOT / 'demo' / 'conditional-probability.md'
    return await save_material(path.name, path.read_bytes())


@app.get('/api/demo-video')
async def demo_video():
    path = ROOT / 'reports' / 'demo-lesson-video.mp4'
    if not path.is_file():
        raise HTTPException(404, 'The demo video has not been generated yet.')
    return FileResponse(path, media_type='video/mp4', headers={'Content-Disposition': 'inline; filename="demo-lesson-video.mp4"'})


@app.get('/api/settings')
async def settings():
    return store.settings()


@app.exception_handler(HarnessError)
async def harness_failure(request, exc):
    return JSONResponse({'detail': exc.message, 'code': exc.code}, status_code=exc.status)


class HarnessOperationInput(BaseModel):
    operation_id: str | None = Field(default=None, max_length=100)
    revision: int | None = Field(default=None, ge=1)


class HarnessProbeInput(HarnessOperationInput):
    operation_id: str = Field(max_length=100)
    revision: int = Field(ge=1)
    model: str = Field(min_length=1, max_length=150)


class HarnessApplyInput(HarnessOperationInput):
    operation_id: str = Field(max_length=100)
    revision: int = Field(ge=1)
    confirm: bool = Field(default=False, strict=True)
    targets: list[str] = Field(default_factory=lambda: ['learning', 'classroom'], max_length=2)


@app.get('/api/harness/status')
async def harness_status(refresh_account: bool = False):
    return await harness_bridge().status(refresh_account=refresh_account)


@app.get('/api/models/connection')
async def model_connection():
    return await harness_bridge().connection_status()


def authenticate_service(request):
    # Browser code never gets this application's control token. Service-only
    # provider responses cannot be requested by a renderer even if it presents
    # an accidentally exposed token.
    if request.headers.get('origin'):
        raise HarnessError('service_only', 'This endpoint is available only to local services.', 403)
    if not harness_bridge().authenticate_internal(request.headers.get('authorization')):
        raise HarnessError('unauthorized', 'Internal endpoint authentication failed.', 401)


@app.get('/api/harness/internal/provider')
@app.post('/api/harness/internal/provider')
async def internal_execution_provider(request: Request, require_managed: bool = False):
    authenticate_service(request)
    if request.method == 'POST':
        body = await workspace_input(request, {'llm_selection', 'execution_id', 'model_snapshot'})
        return await harness_bridge().execution_config(require_managed=require_managed, **body)
    return await harness_bridge().execution_config(require_managed=require_managed)


@app.post('/api/harness/internal/workspace-provider')
async def internal_workspace_provider(request: Request):
    authenticate_service(request)
    body = await workspace_input(request, {'llm_selection'})
    return await harness_bridge().workspace_provider(**body)


async def execution_workspace_binding(owner, native_workspace_id):
    owner = workspace_identifier(owner)
    identity = workspace_identifier(native_workspace_id)
    # The service token establishes the caller, while Native validates the
    # owner and the owner's registered filesystem scope. No browser path or
    # default administrator context may stand in for that authorization.
    native = await harness_bridge().transport.native_service('POST', 'workspace-binding',
        {'owner': owner, 'native_workspace_id': identity})
    if (native.get('owner') != owner or native.get('native_workspace_id') != identity
            or native.get('kind') != 'workspace' or not native.get('ready')
            or native.get('archived') or not isinstance(native.get('path'), str)):
        raise HarnessError('workspace_binding_invalid', 'Choose a workspace accessible to the current account.', 403)
    result = await harness_bridge().transport.host('GET', '/workspaces')
    canonical = os.path.normcase(os.path.abspath(native['path']))
    item = next((row for row in result.get('workspaces', [])
                 if isinstance(row, dict) and isinstance(row.get('path'), str)
                 and os.path.normcase(os.path.abspath(row['path'])) == canonical
                 and not row.get('archived')), None)
    if item is None:
        registered = await harness_bridge().transport.host('POST', '/workspaces',
            {'path': native['path'], 'name': native.get('name') or 'Learning workspace'})
        item = registered.get('workspace', registered)
    if not isinstance(item, dict) or not isinstance(item.get('id'), str):
        raise HarnessError('workspace_binding_invalid', 'The workspace connection is unfinished. Select it again.', 409)
    return workspace_identifier(item['id'])


@app.post('/api/harness/internal/execution-tasks')
async def internal_execution_task_create(request: Request):
    authenticate_service(request)
    body = await workspace_input(request, {'owner', 'native_workspace_id', 'source', 'task_key',
        'text', 'llm_selection', 'source_references', 'parent_task_id', 'continuation_task_id'})
    if (not isinstance(body.get('owner'), str) or not isinstance(body.get('native_workspace_id'), str)
            or not isinstance(body.get('text'), str) or not 1 <= len(body['text'].strip()) <= 24000
            or not isinstance(body.get('source'), str) or not 1 <= len(body['source']) <= 100
            or not isinstance(body.get('task_key'), str) or not 1 <= len(body['task_key']) <= 200
            or not isinstance(body.get('source_references', []), list)):
        raise HarnessError('workspace_input_invalid', 'Invalid task request. Start again.', 422)
    body['workspace_id'] = await execution_workspace_binding(body['owner'], body['native_workspace_id'])
    return await harness_bridge().transport.host('POST', '/execution-tasks', body)


@app.get('/api/harness/internal/execution-tasks')
async def internal_execution_tasks(request: Request, owner: str):
    authenticate_service(request)
    return await harness_bridge().transport.host('GET', '/execution-tasks?' + urlencode({'owner': workspace_identifier(owner)}))


@app.get('/api/harness/internal/execution-tasks/{task_id}')
async def internal_execution_task(request: Request, task_id: str, owner: str, after_seq: int = -1):
    authenticate_service(request)
    if not -1 <= after_seq <= 1000000000:
        raise HarnessError('event_cursor_invalid', 'Invalid task event cursor.', 422)
    query = urlencode({'owner': workspace_identifier(owner), 'after_seq': after_seq})
    return await harness_bridge().transport.host('GET', '/execution-tasks/' + workspace_identifier(task_id) + '?' + query)


@app.post('/api/harness/internal/execution-tasks/{task_id}/{action}')
async def internal_execution_task_action(request: Request, task_id: str, action: str):
    authenticate_service(request)
    if action not in {'cancel', 'resume'}:
        raise HarnessError('execution_action_invalid', 'Task operation not found.', 404)
    body = await workspace_input(request, {'owner'})
    if not isinstance(body.get('owner'), str):
        raise HarnessError('workspace_input_invalid', 'Invalid task account.', 422)
    body['owner'] = workspace_identifier(body['owner'])
    return await harness_bridge().transport.host('POST', '/execution-tasks/' + workspace_identifier(task_id) + '/' + action, body)


@app.post('/api/harness/internal/workspace-metadata')
async def internal_workspace_metadata(request: Request):
    authenticate_service(request)
    body = await workspace_input(request, {'path'})
    if not isinstance(body.get('path'), str) or not body['path'] or len(body['path']) > 4000 or re.search(r'[\0\r\n]', body['path']):
        raise HarnessError('workspace_input_invalid', 'Invalid workspace path.', 422)
    return await workspace_manager().metadata(body['path'])


@app.get('/api/harness/internal/workspaces/{workspace_id}')
async def internal_workspace_directory(workspace_id: str, request: Request, owner: str | None = None):
    authenticate_service(request)
    identity = workspace_identifier(workspace_id)
    if identity in {'general', 'system'}:
        raise HarnessError('workspace_protected', 'First choose a workspace connected to a material folder.', 403)
    if owner is not None:
        harness_id = await execution_workspace_binding(owner, identity)
        result = await harness_bridge().transport.host('GET', '/workspaces')
        item = next((row for row in result.get('workspaces', []) if row.get('id') == harness_id), None)
        if not item:
            raise HarnessError('workspace_missing', 'This workspace has not been registered.', 404)
        return {'workspace_id': identity, 'harness_workspace_id': harness_id, 'path': item['path']}
    result = await harness_bridge().transport.host('GET', '/workspaces')
    candidates = result.get('workspaces', []) if isinstance(result, dict) else []
    item = next((item for item in candidates if isinstance(item, dict) and item.get('id') == identity), None)
    if not item:
        # A native study workspace has a different durable ID. Resolve its
        # registered path through the native service, then require a matching
        # Harness registration; no caller-supplied filesystem path is accepted.
        native = await harness_bridge().transport.native_workspace(identity)
        native_path = native.get('path') if isinstance(native, dict) else None
        if (isinstance(native_path, str) and identity not in {'general', 'system'}
                and native.get('kind') not in {'general', 'system'} and not native.get('is_builtin')):
            item = next((row for row in candidates if isinstance(row, dict) and isinstance(row.get('path'), str)
                         and os.path.normcase(os.path.abspath(row['path'])) == os.path.normcase(os.path.abspath(native_path))), None)
            if not item and not native.get('archived'):
                # Native metadata is the authority; the Host applies the same
                # protected-root and canonical-directory checks as its picker.
                registration = await harness_bridge().transport.host('POST', '/workspaces',
                    {'path': native_path, 'name': native.get('name') or native.get('title') or 'Learning workspace'})
                item = registration.get('workspace', registration)
    if not item or not isinstance(item.get('path'), str):
        raise HarnessError('workspace_missing', 'This workspace has not been registered.', 404)
    try:
        directory = Path(item['path']).resolve(strict=True)
        if not directory.is_dir():
            raise ValueError('not directory')
    except (OSError, ValueError):
        raise HarnessError('workspace_directory_unavailable', 'The workspace folder is missing or inaccessible.', 409) from None
    return {'workspace_id': identity, 'harness_workspace_id': item['id'], 'path': str(directory)}


def workspace_identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise HarnessError('workspace_identity_invalid', 'Invalid workspace or session ID.', 422)
    return value


async def workspace_input(request, allowed):
    try:
        # Bounded manual parsing does not reflect accidentally pasted keys in
        # Pydantic's validation error JSON.
        raw = await request.body()
        if len(raw) > 100000:
            raise ValueError('too large')
        body = json.loads(raw or b'{}')
        if not isinstance(body, dict) or set(body) - set(allowed):
            raise ValueError('invalid fields')
        return body
    except (ValueError, TypeError):
        raise HarnessError('workspace_input_invalid', 'Invalid workspace request. Check the selected folder or input.', 422) from None


@app.get('/api/harness/workspace-access')
async def harness_workspace_access():
    return await harness_bridge().transport.host('GET', '/workspace-access')


@app.post('/api/harness/workspace-access')
async def harness_workspace_access_update(request: Request):
    body = await workspace_input(request, {'default_access'})
    if body.get('default_access') not in {'workspace', 'full'}:
        raise HarnessError('workspace_access_invalid', 'Choose Workspace only or Full computer access.', 422)
    return await harness_bridge().transport.host('POST', '/workspace-access', body)


@app.get('/api/harness/workspaces')
async def harness_workspaces():
    return await workspace_manager().harness_catalog()


@app.get('/api/harness/workspace-management/catalog')
async def harness_workspace_management_catalog():
    return await workspace_manager().catalog()


@app.patch('/api/harness/workspaces/{workspace_id}/manage')
async def harness_workspace_manage(workspace_id: str, request: Request):
    body = await workspace_input(request, {'name', 'archived'})
    return await workspace_manager().manage(workspace_identifier(workspace_id), body)


@app.post('/api/harness/workspaces')
async def harness_workspace_create(request: Request):
    body = await workspace_input(request, {'path', 'name'})
    if (not isinstance(body.get('path'), str) or not 1 <= len(body['path']) <= 4000
            or any(c in body['path'] for c in '\x00\r\n')
            or ('name' in body and (not isinstance(body['name'], str) or len(body['name']) > 200))):
        raise HarnessError('workspace_input_invalid', 'Choose an existing folder on this computer.', 422)
    return await workspace_manager().register(body)


@app.get('/api/harness/workspaces/{workspace_id}/sessions')
async def harness_workspace_sessions(workspace_id: str):
    return await harness_bridge().transport.host('GET', '/workspaces/' + workspace_identifier(workspace_id) + '/sessions')


@app.post('/api/harness/workspaces/{workspace_id}/sessions')
async def harness_workspace_session_create(workspace_id: str, request: Request):
    body = await workspace_input(request, {'title'})
    if 'title' in body and (not isinstance(body['title'], str) or len(body['title']) > 200):
        raise HarnessError('workspace_input_invalid', 'Invalid session name.', 422)
    return await harness_bridge().transport.host('POST', '/workspaces/' + workspace_identifier(workspace_id) + '/sessions', body)


@app.get('/api/harness/sessions/{session_id}/events')
async def harness_workspace_events(session_id: str, after_seq: int = -1):
    if not -1 <= after_seq <= 1000000000:
        raise HarnessError('event_cursor_invalid', 'Invalid session event cursor.', 422)
    query = urlencode({'after_seq': after_seq})
    return await harness_bridge().transport.host('GET', '/sessions/' + workspace_identifier(session_id) + '/events?' + query)


@app.post('/api/harness/sessions/{session_id}/turn')
async def harness_workspace_turn(session_id: str, request: Request):
    body = await workspace_input(request, {'text', 'llm_selection', 'access_level'})
    if not isinstance(body.get('text'), str) or not 1 <= len(body['text'].strip()) <= 24000:
        raise HarnessError('workspace_input_invalid', 'Enter the task to execute.', 422)
    if 'access_level' in body and body['access_level'] not in {'workspace', 'full'}:
        raise HarnessError('workspace_input_invalid', 'Choose Workspace only or Full computer access.', 422)
    return await harness_bridge().transport.host('POST', '/sessions/' + workspace_identifier(session_id) + '/turn', body)


@app.get('/api/harness/sessions/{session_id}/attachments/{attachment_id}')
async def harness_workspace_attachment(session_id: str, attachment_id: str):
    content, media_type = await harness_bridge().transport.host_attachment(
        workspace_identifier(session_id), workspace_identifier(attachment_id))
    return Response(content=content, media_type=media_type, headers={'Cache-Control': 'no-store'})


@app.post('/api/harness/sessions/{session_id}/cancel')
async def harness_workspace_cancel(session_id: str, request: Request):
    await workspace_input(request, set())
    return await harness_bridge().transport.host('POST', '/sessions/' + workspace_identifier(session_id) + '/cancel', {})


@app.post('/api/harness/approvals/{approval_id}')
async def harness_workspace_approve(approval_id: str, request: Request):
    body = await workspace_input(request, {'session_id', 'decision'})
    if not isinstance(body.get('session_id'), str) or body.get('decision') not in ('allow', 'deny'):
        raise HarnessError('approval_input_invalid', 'Confirm this specific operation or decline it.', 422)
    workspace_identifier(body['session_id'])
    return await harness_bridge().transport.host('POST', '/approvals/' + workspace_identifier(approval_id), body)


@app.get('/api/harness/guide')
async def harness_guide(provider: str = 'deepseek'):
    if provider != 'deepseek':
        raise HarnessError('provider_not_supported', 'The connection assistant currently supports DeepSeek. Other providers remain available in Settings.', 422)
    return GUIDE


@app.get('/api/harness/models')
async def harness_models():
    return await harness_bridge().models()


@app.post('/api/harness/account/start')
async def harness_account_start():
    return await harness_bridge().start()


@app.post('/api/harness/connect')
async def harness_reuse_connection(request: Request):
    body = await workspace_input(request, {'model'})
    return await harness_bridge().reuse_connection(body.get('model'))


@app.post('/api/harness/account/cancel')
async def harness_account_cancel(value: HarnessOperationInput):
    return await harness_bridge().cancel(value.operation_id, value.revision)


@app.post('/api/harness/account/signout')
async def harness_account_signout():
    return await harness_bridge().signout()


@app.post('/api/harness/credential')
async def harness_credential(request: Request):
    # Never let Pydantic's validation response reflect a credential input.
    try:
        if int(request.headers.get('content-length', '0')) > 12000:
            raise ValueError('oversize')
        body = await request.json()
        if not isinstance(body, dict) or set(body) - {'api_key', 'model', 'operation_id', 'revision'}:
            raise ValueError('invalid fields')
        if not isinstance(body.get('model', ''), str) or len(body.get('model', '')) > 150:
            raise ValueError('invalid model')
        if body.get('revision') is not None and type(body['revision']) is not int:
            raise ValueError('invalid revision')
        if body.get('operation_id') is not None and (not isinstance(body['operation_id'], str) or len(body['operation_id']) > 100):
            raise ValueError('invalid operation')
    except (ValueError, TypeError):
        raise HarnessError('credential_input_invalid', 'Invalid key input. Enter it again in the dedicated key field.', 422) from None
    return harness_bridge().credential(body.get('api_key'), body.get('model', ''), body.get('operation_id'), body.get('revision'))


@app.post('/api/harness/probe')
async def harness_probe(value: HarnessProbeInput):
    return await harness_bridge().probe(value.operation_id, value.revision, value.model)


@app.post('/api/harness/apply')
async def harness_apply(value: HarnessApplyInput):
    return await harness_bridge().apply(value.operation_id, value.revision, value.confirm, value.targets)


@app.post('/api/harness/rollback')
async def harness_rollback(value: HarnessApplyInput):
    return await harness_bridge().rollback(value.operation_id, value.revision, value.confirm)


@app.post('/api/harness/internal/secret')
async def harness_internal_secret(request: Request):
    if not harness_bridge().authenticate_internal(request.headers.get('authorization')):
        raise HarnessError('unauthorized', 'Internal endpoint authentication failed.', 401)
    body = await request.json()
    return {'api_key': harness_bridge().secret(str(body.get('secret_ref', '')), str(body.get('route_id', '')))}


@app.post('/api/harness/internal/tool')
async def harness_internal_tool(request: Request):
    if not harness_bridge().authenticate_internal(request.headers.get('authorization')):
        raise HarnessError('unauthorized', 'Internal endpoint authentication failed.', 401)
    body = await request.json()
    arguments = body.get('arguments', {})
    if not isinstance(arguments, dict) or len(json.dumps(arguments)) > 5000:
        raise HarnessError('tool_arguments_invalid', 'Invalid tool arguments.', 422)
    return await harness_bridge().tool(str(body.get('name', '')), arguments, body.get('operation_id'))


class SettingsInput(BaseModel):
    connection_mode: str | None = Field(default=None, pattern='^(current|custom|native|unconfigured)$')
    model_mode: str = Field(default='api', pattern='^api$')
    base_url: str = Field(default='', max_length=1500)
    model: str = Field(default='', max_length=200)
    api_key: str = Field(default='', max_length=8000)
    clear_api_key: bool = False
    tts_enabled: bool = True
    tts_mode: str = Field(default='local', pattern='^(local|api)$')
    tts_base_url: str = Field(default='', max_length=1500)
    tts_model: str = Field(default='', max_length=200)
    tts_voice: str = Field(default='', max_length=200)
    tts_api_key: str = Field(default='', max_length=8000)
    clear_tts_api_key: bool = False


@app.put('/api/settings')
async def save_settings(value: SettingsInput):
    # Partial writes leave saved provider URLs, models and DPAPI keys intact.
    payload = value.model_dump(exclude_unset=True)
    if 'connection_mode' not in payload and payload.get('model_mode') == 'api' and any(payload.get(key) for key in ('base_url', 'model', 'api_key')):
        payload['connection_mode'] = 'custom'
    for key in ('base_url', 'tts_base_url'):
        if key not in payload:
            continue
        url = payload[key].strip().rstrip('/')
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise HTTPException(422, 'The API address must use HTTP(S) and cannot contain credentials, query parameters, or a fragment.')
        payload[key] = url
    if 'model' in payload:
        payload['model'] = payload['model'].strip()
    try:
        return store.save_settings(payload)
    except ValueError:
        raise HarnessError('connection_selection_invalid', 'Choose the verified current connection or configure your own external model API.', 409) from None


class LessonInput(BaseModel):
    material_id: str
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=6000)
    llm_selection: dict | None = None


@app.get('/api/lessons')
async def lessons(workspace_id: str | None = None):
    return {'items': [lesson_public(item) for item in store.list('lessons')
                      if workspace_id is None or (item.get('workspace_id') or '') == workspace_id]}


def lesson_public(item):
    item = dict(item)
    for field in ('llm_selection', 'resolved_model'):
        if isinstance(item.get(field), str):
            try:
                item[field] = json.loads(item[field])
            except ValueError:
                item[field] = None
    item.pop('model_snapshot', None)
    item.pop('source_snapshot', None)
    return item


@app.post('/api/demo-lesson', status_code=201)
async def demo_lesson():
    from portal.demo_classroom import payload
    for existing in store.list('lessons'):
        if existing['title'] == 'Conditional probability · Prepared demo' and existing['status'] == 'ready':
            try:
                await om_bridge().classroom(existing['classroom_id'])
                return existing
            except Exception:
                pass
    demo = ROOT / 'demo' / 'conditional-probability.md'
    content = demo.read_text('utf-8')
    matching = next((m for m in store.list('materials') if m['text'] == content), None)
    if not matching:
        saved = await save_material(demo.name, demo.read_bytes())
        matching = store.get('materials', saved['id'])
    stage, scenes = payload()
    try:
        result = await om_bridge().save_classroom(stage, scenes)
    except Exception as exc:
        raise HTTPException(503, 'The demo classroom could not open. Check that the classroom service is running.' + safe_error(exc)) from exc
    cid = result.get('id') or result.get('classroomId')
    if not cid:
        raise HTTPException(502, 'The classroom service did not return a demo classroom ID.')
    item = {'id': identifier('lesson'), 'title': stage['name'], 'material_id': matching['id'], 'goal': 'Understand the comparison group in conditional probability. Prepared demo; live AI generation requires a configured model.', 'status': 'ready', 'job_id': None, 'classroom_id': cid, 'classroom_url': OM_URL + '/classroom/' + cid, 'dt_course_id': None, 'error': None, 'progress': 'An open prepared example created with Codex assistance, including visuals and a quiz, to demonstrate the classroom player. Opening it does not call a model.', 'created_at': now(), 'updated_at': now()}
    mid = await sync_material(matching['id'])
    if mid:
        try:
            course = await dt_bridge().create_course(item['title'], [mid], instructions=item['goal'])
            item['dt_course_id'] = course.get('course_id') or course.get('id')
        except Exception:
            item['warning'] = 'The demo classroom is available; its learning-course link is unfinished.'
    store.insert('lessons', item)
    return item


@app.post('/api/lessons', status_code=202)
async def create_lesson(value: LessonInput):
    source = store.get('materials', value.material_id)
    if not source:
        raise HTTPException(404, 'Choose a material first.')
    snapshot = None
    if source.get('source_snapshot'):
        try:
            snapshot = await material_sources.classroom_snapshot(source, UPLOADS)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, 'The material scope is not ready: ' + safe_error(exc)) from None
    selection_args = {'llm_selection': value.llm_selection} if 'llm_selection' in value.model_fields_set else {}
    execution = await harness_bridge().execution_config(**selection_args)
    if (snapshot and snapshot.get('images')
            and ((execution.get('resolved_model') or {}).get('capabilities') or {}).get('vision') is False):
        raise HTTPException(409, 'The selected material contains images, but the current model does not support image input. Choose a vision-capable model before generating the classroom.')
    config = {**execution['provider'], 'execution_id': execution.get('execution_id'), 'model_snapshot': execution.get('model_snapshot')}
    if not config.get('model') or not config.get('base_url'):
        raise HTTPException(409, 'Enter the model name and API address in Settings. Saving does not call a model; selected materials are sent only when you generate.')
    item = {'id': identifier('lesson'), 'title': value.title.strip(), 'material_id': value.material_id, 'goal': value.goal.strip(), 'status': 'queued', 'job_id': None, 'classroom_id': None, 'classroom_url': None, 'dt_course_id': None, 'error': None, 'progress': 'Preparing selected materials', 'created_at': now(), 'updated_at': now()}
    item['workspace_id'] = source.get('workspace_id')
    item['source_snapshot'] = json.dumps(snapshot, ensure_ascii=False) if snapshot else None
    try:
        store.insert('lessons', item)
    except ValueError:
        raise HTTPException(409, 'The selected material was deleted. Choose another material.') from None
    store.update('lessons', item['id'], llm_selection=json.dumps(value.llm_selection, ensure_ascii=False), resolved_model=json.dumps(execution.get('resolved_model'), ensure_ascii=False))
    store.update('lessons', item['id'], model_snapshot=json.dumps(execution.get('model_snapshot'), ensure_ascii=False))
    item.update(llm_selection=value.llm_selection, resolved_model=execution.get('resolved_model'))
    launch(generate_lesson(item['id'], frozen_provider=config), item['id'])
    return lesson_public(item)


async def _delete_lesson(lesson_id):
    from portal.content_deletion import delete_lesson_content
    lock = DELETION_LOCKS.setdefault(lesson_id, asyncio.Lock())
    async with lock:
        try:
            await delete_lesson_content(store, lesson_id, CONTENT_TASKS, om_bridge(), dt_bridge())
        except Exception as error:
            store.update('lessons', lesson_id, error='Deletion is unfinished: ' + safe_error(error), updated_at=now())
            raise


@app.delete('/api/lessons/{lesson_id}')
async def delete_lesson(lesson_id: str):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', lesson_id):
        raise HTTPException(422, 'Invalid lesson ID.')
    try:
        await _delete_lesson(lesson_id)
    except Exception as error:
        raise HTTPException(409, 'Deletion is unfinished. Try again shortly.' + safe_error(error)) from None
    return {'deleted': True, 'lesson_id': lesson_id}


@app.get('/api/lessons/{lesson_id}')
async def lesson(lesson_id: str):
    item = store.get('lessons', lesson_id)
    if not item:
        raise HTTPException(404, 'Lesson not found.')
    return lesson_public(item)


async def generate_lesson(lesson_id, resume=False, frozen_provider=None, retry_from=None):
    if lesson_deleting(lesson_id):
        return
    if lesson_id in ACTIVE_LESSONS:
        return
    ACTIVE_LESSONS.add(lesson_id)
    item = store.get('lessons', lesson_id)
    source = store.get('materials', item['material_id'])
    try:
        bridge = om_bridge()
        store.update('lessons', lesson_id, status='generating', updated_at=now())
        job_id = item['job_id']
        if retry_from:
            result = await bridge.retry(job_id, retry_from, frozen_provider)
            store.update('lessons', lesson_id, job_attempt_id=result.get('attemptId'),
                         retryable=0, error=None, recovery_message=None,
                         progress='The original materials were resubmitted. Generating the classroom from the beginning.', updated_at=now())
        if not resume:
            config = store.settings(secret=True)
            if frozen_provider:
                provider = frozen_provider
            elif item.get('model_snapshot'):
                snapshot = json.loads(item['model_snapshot'])
                execution = await harness_bridge().execution_config(model_snapshot=snapshot)
                provider = {**execution['provider'], 'execution_id': execution.get('execution_id'), 'model_snapshot': execution.get('model_snapshot')}
            else:
                provider = await configured_provider(config)
            mid = await sync_material(source['id'])
            if mid:
                try:
                    async def record_course(course_id, workspace_id):
                        ownership = {'dt_reading_workspace_id': workspace_id}
                        if course_id:
                            ownership['dt_course_id'] = course_id
                        store.update('lessons', lesson_id, **ownership)
                    course = await dt_bridge().create_course(item['title'], [mid], instructions=item['goal'], owner_callback=record_course)
                    store.update('lessons', lesson_id, dt_course_id=course.get('course_id') or course.get('id'))
                    store.update('lessons', lesson_id, dt_reading_workspace_id=course.get('reading_workspace_id'))
                except Exception as exc:
                    store.update('lessons', lesson_id, progress='Materials are ready; the learning-course link needs retry: ' + safe_error(exc))
            parsed = material_sources.decode(item.get('source_snapshot'))
            if not parsed:
                parsed = await material_sources.classroom_snapshot(source, UPLOADS)
                store.update('lessons', lesson_id, source_snapshot=json.dumps(parsed, ensure_ascii=False))
            if lesson_deleting(lesson_id):
                return
            if parsed.get('truncated') or parsed.get('warning'):
                store.update('lessons', lesson_id, warning=str(parsed.get('warning') or 'Parsing results were truncated. Complete source coverage has not been confirmed.'))
            text = parsed.get('text', '')
            if not text.strip() and not parsed.get('images'):
                raise ValueError('No usable text or original page images were extracted. Check the document reader and selected page range.')
            source_scope = json.dumps(parsed.get('locators', []), ensure_ascii=False)
            image_scope = json.dumps([{'image_index': entry['image_index'], 'locator': entry['locator']}
                                      for entry in parsed.get('image_sources', [])], ensure_ascii=False)
            requirement = f"Lesson title: {item['title']}\nLearning goal: {item['goal']}\nSelected material: {source['filename']}\nMaterial version: {parsed.get('document', {}).get('sha256', '')}\nReading scope: {source_scope}\nAttached image order and source mapping: {image_scope}\nCover only the attached selected scope; do not claim full-book coverage. Generate an English visual lesson from the attached materials and preserve relevant source images. Distinguish source content from supplementary explanation and never invent source references. End with questions that check understanding."
            if config.get('tts_mode', 'local') == 'local':
                tts = {'provider': 'windows-system-tts', 'model': 'system-speech', 'voice': 'auto-zh'}
            else:
                tts = {'provider': 'openai-tts', 'base_url': config.get('tts_base_url'), 'model': config.get('tts_model'), 'voice': config.get('tts_voice'), 'api_key': config.get('tts_api_key')}
            job_id = identifier('job')
            store.update('lessons', lesson_id, job_id=job_id, updated_at=now())
            result = await bridge.generate(requirement=requirement, source_text=text, image_urls=parsed.get('images', []),
                                           image_sources=parsed.get('image_sources'), provider=provider,
                                           enable_tts=config.get('tts_enabled', False), tts_provider=tts, job_id=job_id)
            job_id = result.get('jobId') or result.get('job_id')
            if not job_id:
                raise ValueError('The classroom service did not return a generation job ID.')
            store.update('lessons', lesson_id, job_id=job_id, job_attempt_id=result.get('attemptId'), progress='Generating classroom', updated_at=now())
        transport_errors = 0
        for _ in range(360):
            if lesson_deleting(lesson_id):
                return
            try:
                result = await bridge.poll(job_id)
                transport_errors = 0
            except Exception as exc:
                transport_errors += 1
                store.update('lessons', lesson_id, progress='Task progress is temporarily unavailable. The original generation may still be running; reconnecting.', error=safe_error(exc), updated_at=now())
                if transport_errors >= 6:
                    store.update('lessons', lesson_id, status='awaiting_reconnect', progress='The upstream task status cannot be confirmed. Continue checking queries the original job and does not create a new one.', updated_at=now())
                    return
                await asyncio.sleep(min(2 ** transport_errors, 30))
                continue
            state = str(result.get('status', '')).lower()
            message = str(result.get('message') or result.get('step') or state)
            recovery = str(result.get('recoveryMessage') or result.get('error') or message)
            store.update('lessons', lesson_id, progress=message[:1200],
                         **({'job_attempt_id': result['attemptId']} if result.get('attemptId') else {}),
                         retryable=int(result.get('retryable') is True), updated_at=now())
            if state == 'interrupted':
                recovery = ('The material scope and original task parameters were saved. Use Regenerate from original materials to retry from the beginning; this may use additional quota.'
                            if result.get('retryable') is True else
                            'This legacy task lacks complete recovery inputs. Select materials again to generate. Saved content remains preserved.')
                store.update('lessons', lesson_id, status='interrupted',
                             recovery_message=safe_error(recovery), error=None,
                             progress='The generation service restarted and the original execution was interrupted. Materials and progress were preserved; no model was automatically called again.', updated_at=now())
                return
            if state in {'failed', 'error', 'cancelled'}:
                retained = result.get('result') or {}
                cid = retained.get('classroomId') if isinstance(retained, dict) else None
                if (state == 'failed' and isinstance(retained, dict) and retained.get('reviewRequired') is True
                        and retained.get('sourceFidelity') == 'needs_review'
                        and isinstance(cid, str) and re.fullmatch(r'[a-zA-Z0-9_-]+', cid)):
                    try:
                        draft = await bridge.classroom(cid)
                        stage = draft.get('stage') or {}
                        fidelity = stage.get('sourceFidelity') or {}
                        if (draft.get('id') == cid and stage.get('id') == cid
                                and draft.get('reserved') is not True
                                and fidelity.get('status') == 'needs_review'
                                and isinstance(draft.get('scenes'), list) and draft['scenes']):
                            store.update('lessons', lesson_id, status='failed', classroom_id=cid,
                                         classroom_url=OM_URL + '/classroom/' + cid,
                                         review_required=1, source_fidelity='needs_review',
                                         error=safe_error(RuntimeError(str(result.get('error') or message))),
                                         progress='Classroom generation failed source verification. A review draft was preserved for inspection; narration and teaching video were not generated.',
                                         warning='A review draft is not a completed classroom. Check the source and explanation before using it for study.',
                                         tts_coverage=None, updated_at=now())
                            return
                    except Exception:
                        # A missing/unreadable draft must not create a review
                        # link or replace the original generation failure.
                        pass
                raise RuntimeError(str(result.get('error') or message))
            if state in {'completed', 'complete', 'succeeded', 'success', 'ready'}:
                cid = result.get('classroomId') or result.get('classroom_id')
                if not cid:
                    nested = result.get('result') or result.get('data') or {}
                    cid = nested.get('classroomId') or nested.get('classroom_id') or nested.get('id')
                if not cid:
                    raise ValueError('Generation ended without a classroom ID. Playback cannot be confirmed.')
                try:
                    await bridge.classroom(cid)
                except Exception as exc:
                    store.update('lessons', lesson_id, status='awaiting_reconnect', classroom_id=cid, error=safe_error(exc), progress='The upstream task completed, but the classroom is temporarily unavailable. Continue checking to verify again.', updated_at=now())
                    return
                native_result = result.get('result') or {}
                warning = result.get('warning') or native_result.get('warning')
                coverage = result.get('ttsCoverage') or native_result.get('ttsCoverage')
                previous_warning = store.get('lessons', lesson_id).get('warning')
                warning_text = '; '.join(str(w) for w in (previous_warning, warning) if w)
                progress = 'The classroom is ready to study. Create a video through its export menu.'
                if warning_text:
                    progress += ' Note: ' + warning_text
                store.update('lessons', lesson_id, status='ready', classroom_id=cid, classroom_url=OM_URL + '/classroom/' + cid, progress=progress, warning=warning_text or None, tts_coverage=json.dumps(coverage, ensure_ascii=False) if coverage is not None else None, review_required=0, source_fidelity=None, error=None, updated_at=now())
                return
            await asyncio.sleep(5)
        store.update('lessons', lesson_id, status='awaiting_reconnect', progress='This monitoring interval ended; failure has not been established. The job ID was preserved so the original task can be checked again.', updated_at=now())
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        store.update('lessons', lesson_id, status='failed', review_required=0, source_fidelity=None, error=safe_error(exc), updated_at=now())
    finally:
        ACTIVE_LESSONS.discard(lesson_id)


@app.post('/api/lessons/{lesson_id}/resume', status_code=202)
async def resume_lesson(lesson_id: str):
    item = store.get('lessons', lesson_id)
    if not item:
        raise HTTPException(404, 'Lesson not found.')
    if item['status'] not in {'generating', 'awaiting_reconnect'} or not item.get('job_id'):
        raise HTTPException(409, 'This lesson has no generation job to continue checking.')
    if lesson_id not in ACTIVE_LESSONS:
        launch(generate_lesson(lesson_id, resume=True), lesson_id)
    return lesson_public(item)


class RetryLessonInput(BaseModel):
    attempt_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')


@app.post('/api/lessons/{lesson_id}/retry', status_code=202)
async def retry_lesson(lesson_id: str, value: RetryLessonInput):
    # One explicit click retries saved inputs; reconnect/poll never calls this.
    lock = DELETION_LOCKS.setdefault(lesson_id, asyncio.Lock())
    async with lock:
        item = store.get('lessons', lesson_id)
        if not item:
            raise HTTPException(404, 'Lesson not found.')
        if item['status'] == 'deleting':
            raise HTTPException(409, 'This classroom is being deleted and cannot be regenerated.')
        if lesson_id in ACTIVE_LESSONS:
            return lesson_public(item)
        if (item['status'] not in {'interrupted', 'failed'} or not item.get('retryable')
                or not item.get('job_id') or item.get('job_attempt_id') != value.attempt_id):
            raise HTTPException(409, 'The task state changed or recovery inputs are incomplete. Refresh; materials can be selected again for a legacy task.')
        if not item.get('model_snapshot'):
            raise HTTPException(409, 'The legacy task has no explicit saved model configuration. Select materials and a model again.')
        execution = await harness_bridge().execution_config(model_snapshot=json.loads(item['model_snapshot']))
        config = store.settings(secret=True)
        provider = {**execution['provider'], 'execution_id': execution.get('execution_id'),
                    'model_snapshot': execution.get('model_snapshot'),
                    'tts_enabled': config.get('tts_enabled', False)}
        if config.get('tts_mode', 'local') == 'local':
            provider.update(tts_provider='windows-system-tts', tts_model='system-speech', tts_voice='auto-zh')
        else:
            provider.update(tts_provider='openai-tts', **{key: config.get(key) for key in ('tts_base_url', 'tts_model', 'tts_voice', 'tts_api_key')})
        store.update('lessons', lesson_id, status='generating', progress='Resubmitting the original task...', updated_at=now())
        launch(generate_lesson(lesson_id, resume=True, frozen_provider=provider, retry_from=value.attempt_id), lesson_id)
        return lesson_public(store.get('lessons', lesson_id))


class AttemptInput(BaseModel):
    question: str = Field(min_length=1, max_length=12000)
    answer: str = Field(min_length=1, max_length=30000)


@app.post('/api/lessons/{lesson_id}/attempts', status_code=202)
async def submit_attempt(lesson_id: str, value: AttemptInput):
    item = store.get('lessons', lesson_id)
    if not item:
        raise HTTPException(404, 'Lesson not found.')
    if item['status'] == 'deleting':
        raise HTTPException(409, 'This classroom is being deleted and cannot accept another answer.')
    attempt = {'id': identifier('attempt'), 'lesson_id': lesson_id, 'question': value.question.strip(), 'answer': value.answer.strip(), 'feedback': None, 'status': 'queued', 'error': None, 'dt_session_id': None, 'dt_turn_id': None, 'created_at': now(), 'updated_at': now()}
    store.insert('attempts', attempt)
    launch(grade_attempt(attempt['id']), attempt['id'])
    return attempt


async def grade_attempt(attempt_id):
    attempt = store.get('attempts', attempt_id)
    lesson = store.get('lessons', attempt['lesson_id'])
    if lesson_deleting(attempt['lesson_id']):
        return
    async def recorded(session_id):
        store.update('attempts', attempt_id, dt_session_id=session_id, updated_at=now())
        if lesson_deleting(attempt['lesson_id']):
            raise asyncio.CancelledError()
    try:
        store.update('attempts', attempt_id, status='grading', updated_at=now())
        mid = await sync_material(lesson['material_id'])
        if not mid:
            raise RuntimeError('The learning service is unavailable. Your original answer was saved in the workbench.')
        config = store.settings(secret=True)
        if lesson_deleting(attempt['lesson_id']):
            return
        result = await dt_bridge().submit_answer(question=attempt['question'], answer=attempt['answer'], material_id=mid, course_id=lesson.get('dt_course_id'), provider_config=await configured_provider(config), submission_id=attempt_id, record_callback=recorded)
        store.update('attempts', attempt_id, dt_session_id=result.get('session_id'), dt_turn_id=result.get('turn_id'), updated_at=now())
        feedback = result.get('feedback') or result.get('text') or ''
        if result.get('status') != 'completed' or not feedback:
            store.update('attempts', attempt_id, feedback=feedback or None)
            raise ValueError(result.get('error') or 'Your answer was saved, but complete tutor feedback was not received.')
        store.update('attempts', attempt_id, status='completed', feedback=feedback, dt_session_id=result.get('session_id'), dt_turn_id=result.get('turn_id'), error=None, updated_at=now())
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        store.update('attempts', attempt_id, status='saved', error=safe_error(exc), updated_at=now())


@app.get('/api/attempts')
async def attempts(workspace_id: str | None = None):
    items = store.list('attempts')
    for item in items:
        lesson = store.get('lessons', item['lesson_id'])
        item['lesson_title'] = lesson['title'] if lesson else ''
        item['workspace_id'] = lesson.get('workspace_id') if lesson else ''
    return {'items': [item for item in items if workspace_id is None or (item.get('workspace_id') or '') == workspace_id]}


@app.get('/api/export-records')
async def export_records():
    return JSONResponse({'exported_at': now(), 'materials': [material_public(x, True) for x in store.list('materials')], 'lessons': store.list('lessons'), 'attempts': store.list('attempts')}, headers={'Content-Disposition': 'attachment; filename="learning-records.json"'})


@app.get('/')
async def index():
    return RedirectResponse('http://127.0.0.1:3792/chat', status_code=307)


@app.get('/open/{entry}')
async def application_entry(entry: str):
    # Browser development fallback only. The desktop rewrites these known
    # internal destinations to its application scheme, never an arbitrary URL.
    entries = {'learning': 'http://127.0.0.1:3792/chat',
               'settings': 'http://127.0.0.1:3792/settings',
               'classroom': OM_URL + '/'}
    if entry not in entries:
        raise HTTPException(404, 'Application entry not found.')
    return RedirectResponse(entries[entry], status_code=307)


@app.get('/legacy')
async def legacy_index():
    # Retained for rollback. The complete native DeepTutor UI is the main entry.
    return FileResponse(ROOT / 'portal' / 'static' / 'index.html')


app.mount('/static', StaticFiles(directory=str(ROOT / 'portal' / 'static'), check_dir=False), name='static')
