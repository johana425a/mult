/** Installation-owned document reader. No shell, downloads, or ambient credentials. */
import { spawn } from 'node:child_process';
import { opendir, lstat } from 'node:fs/promises';
import { isAbsolute, join, relative, extname, dirname } from 'node:path';

const failure = (code, message) => ({ ok: false, status: 'error', error: { code, message } });
const omitted = new Set(['.git', 'node_modules', '.deeptutor', '__pycache__', '.dsh', '.codex', '.ssh']);
const readableFormats = new Set(['.pdf', '.docx', '.pptx', '.xlsx', '.md', '.markdown', '.txt', '.csv', '.tsv', '.json', '.rst', '.log', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff']);
function environment() {
  const allowed = new Set(['SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'TEMP', 'TMP']);
  return { ...Object.fromEntries(Object.entries(process.env).filter(([key]) => allowed.has(key.toUpperCase()))),
    PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1', PYTHONNOUSERSITE: '1',
    EDUAGENT_DOCUMENT_MAX_BYTES: String(Math.min(512 * 1024 * 1024, Math.max(1024 * 1024, Number(process.env.EDUAGENT_DOCUMENT_MAX_BYTES) || 200 * 1024 * 1024))) };
}

export function runReaderProcess(python, argv, payload, signal, timeoutMs = 90000) {
  if (!isAbsolute(python ?? '')) return Promise.resolve(failure('document_runtime_unavailable', 'The packaged document reader is unavailable.'));
  if (signal?.aborted) return Promise.resolve(failure('document_cancelled', 'Document was not read.'));
  return new Promise(resolveResult => {
    let settled = false; const chunks = []; let bytes = 0; let timer; let child; let stopped;
    const finish = value => { if (settled) return; settled = true; clearTimeout(timer); signal?.removeEventListener('abort', abort); resolveResult(value); };
    const stop = (code, message) => { if (stopped) return; stopped = failure(code, message); child.kill(); };
    const abort = () => stop('document_cancelled', 'Document reading was cancelled.');
    try { child = spawn(python, ['-I', '-B', ...argv], { windowsHide: true, env: environment(), stdio: ['pipe', 'pipe', 'pipe'] }); }
    catch { finish(failure('document_runtime_unavailable', 'The packaged document reader is unavailable.')); return; }
    timer = setTimeout(() => stop('document_timeout', 'Document reading timed out; request fewer pages.'), timeoutMs);
    signal?.addEventListener('abort', abort, { once: true });
    child.stderr.resume();
    child.stdout.on('data', data => {
      bytes += data.length;
      if (bytes > 24 * 1024 * 1024) return stop('document_result_limit', 'Document result exceeded its limit.');
      chunks.push(data);
    });
    child.on('error', () => { finish(failure('document_runtime_unavailable', 'The packaged document reader is unavailable; repair the installation.')); });
    child.on('close', code => {
      if (settled) return;
      if (stopped) return finish(stopped);
      if (code !== 0) return finish(failure('document_reader_failed', 'Document was not read. The local reader did not complete.'));
      try { const value = JSON.parse(Buffer.concat(chunks).toString('utf8')); if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(); finish(value); }
      catch { finish(failure('document_reader_failed', 'Document was not read. The packaged reader did not return a valid result.')); }
    });
    child.stdin.on('error', () => {});
    child.stdin.end(payload === undefined ? '' : JSON.stringify(payload));
    if (signal?.aborted) abort();
  });
}

export function readDocument(python, helper, root, action, input, signal) {
  if (!isAbsolute(helper ?? '')) return Promise.resolve(failure('document_runtime_unavailable', 'The packaged document reader is unavailable.'));
  const allowed = ['path', 'cursor', 'start_unit', 'ocr', 'max_chars', 'max_units', 'asset_id', 'document_sha256', 'max_dimension', 'engine', 'job_id', 'tier', 'limit', 'refresh', 'coverage_cursor', 'paths', 'cancel', 'wait_seconds'];
  const request = Object.fromEntries(Object.entries(input).filter(([key]) => allowed.includes(key)));
  // This short-lived process is only a waiter. The durable Python dispatcher
  // owns the read and parse lanes and outlives HTTP disconnects/aborted waiters.
  const argv = [join(dirname(helper), 'document_job_worker.py')];
  if (process.env.DEEPSTEAM_HARNESS_TEST_ROOT) argv.push('--test-root', process.env.DEEPSTEAM_HARNESS_TEST_ROOT);
  const waitMs = action === 'read' ? Math.min(50, Math.max(0, Number(request.wait_seconds ?? 20) || 0)) * 1000 : 0;
  // prepare hashes up to 50 documents to bind each plan to its exact version.
  const timeoutMs = action === 'prepare' ? 120000 : Math.max(35000, waitMs + 15000);
  return runReaderProcess(python, argv, { ...request, action, root }, signal, timeoutMs);
}

/** True while a read job is still queued, reading, or waiting on local MinerU. */
export const documentPending = value => Boolean(value?.ok && ['queued', 'running'].includes(value.status) && value.job_id && !Array.isArray(value.units));

/**
 * Model-facing view of a read result. The full result stays in the session log
 * and task ledger; this view removes the duplicated top-level text and repeats
 * the navigation block at both ends, so the official result pruner (which keeps
 * a head and a tail of long tool output) can never cut away the next position.
 */
export function documentModelView(value) {
  if (documentPending(value)) {
    // Not an error: local work continues while the model does something else.
    const { retry_after_ms: _retry, status: _status, ...rest } = value;
    return { status: 'pending', ...rest, how_to_continue: `${value.message ?? 'The document is still being read on this computer.'} `
      + `To continue, call read_document again with the same arguments (it resumes job ${value.job_id}); document_queue shows progress.` };
  }
  if (!value || typeof value !== 'object' || !Array.isArray(value.units)) return value;
  const { text: _duplicate, units, navigation, ...rest } = value;
  const nav = navigation ?? { next_cursor: value.next_cursor ?? null, next_start_unit: value.next_start_unit ?? null, done: !value.truncated };
  const next = nav.done ? (value.visual_pending || value.vision_pending?.length
    ? 'Text-layer extraction is complete, but visual content remains unread. Call read_document_image for each vision_pending asset using the selected, image-verified model; do not mark the document fully read.'
    : 'Requested document data has been delivered. Delivery is not proof of semantic comprehension.')
    : `Continue with cursor="${nav.next_cursor}" or, equivalently, start_unit=${nav.next_start_unit}.`;
  return { navigation: { ...nav, how_to_continue: next }, ...rest,
    units: units.map(({ unit_text_sha256: _hash, ...unit }) => unit), navigation_end: { ...nav, how_to_continue: next } };
}

/** Local MinerU readiness: model, llama.cpp backend, default tier. No network. */
export function documentEngineStatus(python, helper, verify, signal) {
  if (!isAbsolute(helper ?? '')) return Promise.resolve(failure('document_runtime_unavailable', 'The packaged document reader is unavailable.'));
  return runReaderProcess(python, [join(dirname(helper), 'document_job_worker.py')],
    { action: 'engine_status', ...(verify ? { refresh: true } : {}) }, signal, verify ? 260000 : 100000);
}

export async function workspaceFileCatalog(root, input, checkPath, signal) {
  // Browsing a directory must not flatten descendants into the current level.
  // Callers performing a bounded recursive search choose depth explicitly.
  const maxDepth = Math.max(1, Math.min(Number(input.depth) || 1, 5));
  const limit = Math.max(1, Math.min(Number(input.limit) || 60, 200));
  const query = String(input.query ?? '').toLocaleLowerCase();
  const entries = []; let visited = 0; let truncated = false;
  const base = await checkPath(input.path || '.');
  async function walk(directory, depth) {
    const children = [];
    for await (const child of await opendir(directory)) {
      if (children.length >= 1000) { truncated = true; break; }
      children.push(child);
    }
    children.sort((a, b) => Number(b.isDirectory()) - Number(a.isDirectory()) || a.name.localeCompare(b.name));
    for (const [index, child] of children.entries()) {
      if (signal?.aborted) throw Object.assign(new Error('Document reading cancelled'), { code: 'document_cancelled' });
      if (++visited > 1000 || entries.length >= limit) { truncated = true; return; }
      if (omitted.has(child.name) || child.isSymbolicLink()) continue;
      const candidate = join(directory, child.name); let safe;
      try { safe = await checkPath(relative(root, candidate)); } catch { continue; }
      const info = await lstat(safe);
      if (info.isSymbolicLink() || (!info.isFile() && !info.isDirectory())) continue;
      const path = relative(root, safe).replaceAll('\\', '/');
      const matched = !query || path.toLocaleLowerCase().includes(query);
      if (matched) entries.push({ path, name: child.name, is_dir: info.isDirectory(), size_bytes: info.isFile() ? info.size : null,
        supported: info.isFile() && readableFormats.has(extname(path).toLowerCase()) });
      if (info.isDirectory() && depth < maxDepth) await walk(safe, depth + 1);
      if (visited > 1000 || entries.length >= limit) {
        if (index < children.length - 1) truncated = true;
        return;
      }
    }
  }
  await walk(base, 1);
  return { ok: true, status: 'ready', path: input.path || '.', entries, matches: entries, truncated,
    ...(query ? { search_scope: 'filenames only; use document read for safely bounded content extraction' } : {}) };
}

export async function packagedDependencies(python, signal) {
  const code = 'import sys,json,importlib.metadata as m; names=["PyMuPDF","pypdf","pdfplumber","python-docx","python-pptx","openpyxl","Pillow","rapidocr-onnxruntime","rapidocr","onnxruntime","opencv-python-headless","shapely","pypdfium2"]; rows=[]\nfor n in names:\n try: rows.append({"name":n,"version":m.version(n),"available":True})\n except m.PackageNotFoundError: rows.append({"name":n,"available":False})\nprint(json.dumps({"ok":True,"python":{"executable":sys.executable,"version":sys.version.split()[0]},"libraries":rows}))';
  const result = await runReaderProcess(python, ['-c', code], undefined, signal, 15000);
  return result.ok ? { ...result, node: { executable: process.execPath, version: process.versions.node },
    note: 'Use these installed runtimes. Document read tools require no package installation. In authorized-task mode, execution follows the user-authorized task scope; legacy exact-action mode still requires approval for each exact action.' } : result;
}
