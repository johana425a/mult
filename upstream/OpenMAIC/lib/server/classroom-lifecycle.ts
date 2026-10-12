/** DeepSteam: permanent content deletion. Control markers contain IDs only, never backups. */
import { AsyncLocalStorage } from 'node:async_hooks';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { resolveDataDir } from './data-directory';

interface LifecycleState {
  scope: AsyncLocalStorage<{ jobId: string; signal: AbortSignal; assertAttempt?: () => Promise<void> }>;
  queues: Map<string, Promise<void>>;
  stoppedJobs: Set<string>;
  stoppedStages: Set<string>;
  runners: Map<string, { controller: AbortController; completion: Promise<void> }>;
  stageOperations: Map<string, Set<{ controller: AbortController; completion: Promise<unknown> }>>;
}
// Next route bundles must share both the execution scope and its write lock.
// Separate data roots do not share IDs or deletion state (also used by tests).
const lifecycleGlobal = globalThis as typeof globalThis & { __deepsteamClassroomLifecycle?: Map<string, LifecycleState> };
const lifecycleStates = lifecycleGlobal.__deepsteamClassroomLifecycle ??= new Map();
const lifecycleRoot = path.resolve(resolveDataDir());
let lifecycle = lifecycleStates.get(lifecycleRoot);
if (!lifecycle) {
  lifecycle = { scope: new AsyncLocalStorage(), queues: new Map(), stoppedJobs: new Set(),
    stoppedStages: new Set(), runners: new Map(), stageOperations: new Map() };
  lifecycleStates.set(lifecycleRoot, lifecycle);
}
const { scope, queues, stoppedJobs, stoppedStages, runners, stageOperations } = lifecycle;
const controls = () => path.join(resolveDataDir(), 'classroom-deletions');
const jobsRoot = () => path.join(resolveDataDir(), 'classroom-jobs');
const valid = (id: string) => {
  if (!/^[a-zA-Z0-9_-]{1,100}$/.test(id)) throw new Error('Invalid content identifier');
  return id;
};
const marker = (kind: string, id: string) => path.join(controls(), `${kind}-${valid(id)}.json`);
async function exists(file: string) { try { await fs.access(file); return true; } catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false; throw error; } }
function aborted(): never { throw new DOMException('Content deletion requested', 'AbortError'); }

async function locked<T>(key: string, work: () => Promise<T>): Promise<T> {
  const before = queues.get(key) ?? Promise.resolve();
  let release!: () => void;
  const next = new Promise<void>(resolve => { release = resolve; });
  queues.set(key, next);
  await before;
  try { return await work(); } finally { release(); if (queues.get(key) === next) queues.delete(key); }
}

export async function assertClassroomJobWritable(jobId: string): Promise<void> {
  if (stoppedJobs.has(jobId) || await exists(marker('job', jobId))) aborted();
  scope.getStore()?.signal.throwIfAborted();
  await scope.getStore()?.assertAttempt?.();
}

export function withClassroomJob<T>(jobId: string, signal: AbortSignal, work: () => Promise<T>, assertAttempt?: () => Promise<void>): Promise<T> {
  return scope.run({ jobId, signal, assertAttempt }, async () => { await assertClassroomJobWritable(jobId); return work(); });
}
export function registerClassroomRunner(jobId: string, controller: AbortController, completion: Promise<void>) {
  runners.set(jobId, { controller, completion });
  void completion.finally(() => { if (runners.get(jobId)?.completion === completion) runners.delete(jobId); }).catch(() => {});
}
export function withClassroomJobWrite<T>(jobId: string, work: () => Promise<T>): Promise<T> {
  return locked(`job:${valid(jobId)}`, async () => { await assertClassroomJobWritable(jobId); return work(); });
}

/** Export narration can outlive its HTTP request; deletion owns its stop signal. */
export function withClassroomOperation<T>(stageId: string, signal: AbortSignal | undefined, work: (signal: AbortSignal) => Promise<T>): Promise<T> {
  valid(stageId);
  const controller = new AbortController();
  const stop = () => controller.abort();
  if (signal?.aborted) stop();
  signal?.addEventListener('abort', stop, { once: true });
  const completion = (async () => {
    if (stoppedStages.has(stageId) || await exists(marker('stage', stageId))) aborted();
    controller.signal.throwIfAborted();
    return work(controller.signal);
  })();
  const operation = { controller, completion };
  const operations = stageOperations.get(stageId) ?? new Set();
  operations.add(operation);
  stageOperations.set(stageId, operations);
  void completion.finally(() => {
    signal?.removeEventListener('abort', stop);
    operations.delete(operation);
    if (!operations.size) stageOperations.delete(stageId);
  }).catch(() => {});
  return completion;
}

/** Every producer funnels its mkdir/write through here, including late provider results. */
export async function withClassroomWrite<T>(stageId: string, work: () => Promise<T>, claimAfterSuccess = false): Promise<T> {
  valid(stageId);
  const current = scope.getStore();
  const recordOwnership = async () => {
    if (!current) return;
    const file = path.join(jobsRoot(), `${valid(current.jobId)}.resources.json`);
    let stages: string[] = [];
    try { stages = JSON.parse(await fs.readFile(file, 'utf8')).stages ?? []; } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
    if (!stages.includes(stageId)) {
      await fs.mkdir(jobsRoot(), { recursive: true });
      const temporary = `${file}.tmp`;
      await fs.writeFile(temporary, JSON.stringify({ stages: [...stages, stageId] }));
      await fs.rename(temporary, file);
    }
  };
  const write = () => locked(`stage:${stageId}`, async () => {
    if (stoppedStages.has(stageId) || await exists(marker('stage', stageId))) aborted();
    if (current) await assertClassroomJobWritable(current.jobId);
    if (current && !claimAfterSuccess) await recordOwnership();
    const result = await work();
    if (claimAfterSuccess) await recordOwnership();
    return result;
  });
  // A collided exclusive reservation belongs to somebody else. Keep the job
  // lock across successful reservation and ownership registration so deletion
  // cannot miss the newly owned ID between these two writes.
  // Retry fencing and the actual write share the job lock. A late provider
  // result cannot pass its attempt check and write after a retry takes ownership.
  if (current) return withClassroomJobWrite(current.jobId, write);
  return write();
}

async function begin(kind: 'job' | 'stage', id: string) {
  (kind === 'job' ? stoppedJobs : stoppedStages).add(valid(id));
  await fs.mkdir(controls(), { recursive: true });
  await fs.writeFile(marker(kind, id), JSON.stringify({ id, kind }));
}

function mediaReferences(value: unknown, result = new Map<string, Set<string>>()) {
  if (typeof value === 'string') {
    const expression = /\/api\/classroom-media\/([a-zA-Z0-9_-]{1,100})\/(audio|media)\/([^\s"'<>?#/\\]+)/g;
    for (const match of value.matchAll(expression)) {
      let name: string;
      try { name = decodeURIComponent(match[3]); } catch { continue; }
      if (!/^[a-zA-Z0-9_.-]+$/.test(name) || name.includes('..')) continue;
      const files = result.get(match[1]) ?? new Set<string>();
      files.add(`${match[2]}/${name}`); result.set(match[1], files);
    }
  } else if (Array.isArray(value)) {
    for (const item of value) mediaReferences(item, result);
  } else if (value && typeof value === 'object') {
    for (const item of Object.values(value)) mediaReferences(item, result);
  }
  return result;
}

async function referencedMedia(root: string, stageId: string): Promise<Set<string>> {
  const retained = new Set<string>();
  let names: string[];
  try { names = await fs.readdir(root); } catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return retained; throw error; }
  for (const name of names) {
    if (!/^[a-zA-Z0-9_-]+\.json$/.test(name) || name === `${stageId}.json`) continue;
    try {
      const saved = JSON.parse(await fs.readFile(path.join(root, name), 'utf8'));
      for (const file of mediaReferences(saved).get(stageId) ?? []) retained.add(file);
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
  }
  return retained;
}

async function removeExclusiveFiles(directory: string, retained: Set<string>, relative = ''): Promise<void> {
  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    const name = relative ? `${relative}/${entry.name}` : entry.name;
    if (entry.isSymbolicLink()) throw new Error('Generated classroom path is not owned');
    if (entry.isDirectory()) await removeExclusiveFiles(target, retained, name);
    else if (!retained.has(name)) await fs.rm(target, { force: true });
  }
  if (!(await fs.readdir(directory)).length) await fs.rmdir(directory);
}

async function removeGeneratedJson(file: string): Promise<void> {
  await fs.rm(file, { force: true });
  const directory = path.dirname(file);
  const prefix = `${path.basename(file)}.`;
  let names: string[];
  try { names = await fs.readdir(directory); } catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return; throw error; }
  for (const name of names) {
    if (name.startsWith(prefix) && /^\d+\.\d+(?:\.[a-zA-Z0-9_-]{6})?\.tmp$/.test(name.slice(prefix.length))) {
      await fs.rm(path.join(directory, name), { force: true });
    }
  }
}

/** Only an application's generated ID directory is eligible; never follow a directory link. */
export async function deleteOwnedClassroom(stageId: string): Promise<void> {
  await begin('stage', stageId);
  const operations = [...(stageOperations.get(stageId) ?? [])];
  for (const operation of operations) operation.controller.abort();
  if (operations.length) {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const settled = await Promise.race([
      Promise.allSettled(operations.map(operation => operation.completion)).then(() => true),
      new Promise<boolean>(resolve => { timer = setTimeout(() => resolve(false), 15000); }),
    ]);
    clearTimeout(timer);
    if (!settled) throw new Error('Classroom export is stopping. Retry deletion after it settles.');
  }
  const orphanSources = new Set<string>();
  await locked(`stage:${stageId}`, async () => {
    const { CLASSROOMS_DIR, resolveClassroomFilePath } = await import('./classroom-storage');
    const root = path.resolve(CLASSROOMS_DIR);
    const retained = await referencedMedia(root, stageId);
    try {
      const saved = JSON.parse(await fs.readFile(resolveClassroomFilePath(stageId), 'utf8'));
      for (const id of mediaReferences(saved).keys()) {
        if (id !== stageId && !await exists(resolveClassroomFilePath(id))) orphanSources.add(id);
      }
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
    for (const parent of [root, path.join(path.dirname(root), 'generation-failures')]) {
      const directory = path.join(parent, valid(stageId));
      try {
        const info = await fs.lstat(directory);
        if (info.isSymbolicLink() || !(await fs.realpath(directory)).startsWith(`${await fs.realpath(parent)}${path.sep}`)) throw new Error('Generated classroom path is not owned');
        if (parent === root && retained.size) await removeExclusiveFiles(directory, retained);
        else await fs.rm(directory, { recursive: true, force: true });
      } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
    }
    await removeGeneratedJson(resolveClassroomFilePath(stageId));
    await fs.rm(marker('stage', stageId), { force: true });
  });
  // Media kept for another saved classroom becomes exclusive only when the
  // last reference disappears. No material/upload/source directory is visited.
  for (const id of orphanSources) await deleteOwnedClassroom(id);
}

export async function deleteClassroomGenerationJob(jobId: string, timeoutMs = 15000, preserveClassroomIds: string[] = []): Promise<void> {
  const protectedIds = new Set(preserveClassroomIds.map(valid));
  await begin('job', jobId);
  const run = runners.get(jobId);
  if (run) {
    run.controller.abort();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const settled = await Promise.race([
      run.completion.then(() => true, () => true),
      new Promise<boolean>(resolve => { timer = setTimeout(() => resolve(false), timeoutMs); }),
    ]);
    clearTimeout(timer);
    if (!settled) throw new Error('Generation is stopping. Retry deletion after the current request settles.');
  }
  await locked(`job:${jobId}`, async () => {
    const file = path.join(jobsRoot(), `${valid(jobId)}.json`);
    const resources = path.join(jobsRoot(), `${jobId}.resources.json`);
    const ids = new Set<string>();
    for (const candidate of [file, resources]) {
      try {
        const item = JSON.parse(await fs.readFile(candidate, 'utf8'));
        for (const id of item.stages ?? []) ids.add(valid(id));
        if (item.result?.classroomId) ids.add(valid(item.result.classroomId));
      } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
    }
    for (const id of ids) if (!protectedIds.has(id)) await deleteOwnedClassroom(id);
    await removeGeneratedJson(file);
    for (const owned of [resources, `${resources}.tmp`]) await fs.rm(owned, { force: true });
    await fs.rm(marker('job', jobId), { force: true });
  });
}
