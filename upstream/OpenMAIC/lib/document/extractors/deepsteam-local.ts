/** DeepSteam: fixed, isolated, offline document reader shared with the workspace. */
import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { resolveDataDir } from '@/lib/server/data-directory';
import { MAX_EXTRACT_DOCUMENT_FILE_SIZE_BYTES } from '@/lib/constants/generation';
import { validClassroomImageSources } from '@/lib/server/classroom-image-sources';
import { getDocumentExtractorManifestEntry } from './manifest';
import type { DocumentArtifact, DocumentExtractorInput, DocumentExtractorProvider } from '../types';
import type { ClassroomImageSource, SourceDocumentLocator } from '@/lib/types/generation';

const MAX_OUTPUT_BYTES = 128 * 1024 * 1024;
const WAITER_TIMEOUT_MS = 35_000;
const MAX_RECONNECT_ATTEMPTS = 3;
const extensions: Record<string, string> = {
  'application/pdf': '.pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
  'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp',
  'image/gif': '.gif', 'image/bmp': '.bmp',
};

interface SharedUnit {
  text: string; locator: SourceDocumentLocator; kind?: string;
  table?: { rows?: string[][] }; equations?: Array<{ format?: string; text?: string; status?: string }>;
  status?: string; coverage?: Record<string, unknown>;
}
interface SharedResult {
  ok: true;
  recovery: DocumentExtractionRecovery;
  document: { sha256: string; unit_count: number };
  units: SharedUnit[];
  images: Array<{ base64: string; mime_type: string; source_asset_id: string; unit_index: number; locator: SourceDocumentLocator }>;
  warnings: string[]; status: string; coverage: Record<string, unknown>;
  requires_image_reading?: boolean; visual_pending?: boolean; vision_pending?: unknown[];
  image_reading?: string; next_tool?: string;
}

export interface DocumentExtractionRecovery {
  ingestion_id: string;
  source_ref: string;
  document_sha256: string;
  job_id?: string;
}

interface PendingResult {
  ok: false;
  status: 'queued' | 'running';
  retry_after_ms?: number;
  recovery: DocumentExtractionRecovery;
}

interface CancelledResult {
  ok: false;
  status: 'cancelled';
  error?: string;
  recovery: DocumentExtractionRecovery;
}

type SharedResponse = SharedResult | PendingResult | CancelledResult;

export class DocumentExtractionError extends Error {
  constructor(message: string, readonly recovery?: DocumentExtractionRecovery) {
    super(message);
    this.name = 'DocumentExtractionError';
  }
}

class WaiterError extends DocumentExtractionError {
  constructor(message: string, readonly retryable: boolean, recovery?: DocumentExtractionRecovery) {
    super(message, recovery);
  }
}

/** Only server-owned installation configuration can locate executables. */
async function installation() {
  const configured = process.env.DEEPSTEAM_APP_ROOT;
  if (!configured || !path.isAbsolute(configured)) throw new Error('The local document reader was not located. Start the application through DeepSteam; no parsing API is required.');
  const root = await fs.realpath(configured).catch(() => { throw new Error('The local document reader is incomplete. Repair the installation.'); });
  const helper = path.join(root, 'scripts', 'openmaic_document_extract.py');
  const portable = path.join(root, 'runtime', 'python', 'python.exe');
  const development = path.join(root, 'runtime', 'deeptutor-venv', 'Scripts', 'python.exe');
  const python = await fs.stat(portable).then(info => info.isFile() ? portable : development, () => development);
  for (const target of [helper, python]) {
    const resolved = await fs.realpath(target).catch(() => '');
    if (!resolved.startsWith(root + path.sep) || !(await fs.stat(resolved)).isFile()) {
      throw new Error('The local document reader is incomplete. Repair the installation; no parsing API is required.');
    }
  }
  return { python, helper };
}

function childEnvironment(temporary: string): NodeJS.ProcessEnv {
  const names = new Set(['SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'TEMP', 'TMP']);
  const environment: NodeJS.ProcessEnv = { NODE_ENV: process.env.NODE_ENV ?? 'production' };
  for (const [key, value] of Object.entries(process.env)) if (names.has(key.toUpperCase())) environment[key] = value;
  return { ...environment, PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1', PYTHONNOUSERSITE: '1',
    DEEPSTEAM_DOCUMENT_TEMP_ROOT: temporary };
}

function recoveryFrom(value: unknown, expectedDigest: string): DocumentExtractionRecovery | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const recovery = value as DocumentExtractionRecovery;
  if (!/^[a-f0-9]{32}$/.test(recovery.ingestion_id)
      || typeof recovery.source_ref !== 'string' || !recovery.source_ref.length || recovery.source_ref.length > 256
      || /[\u0000-\u001f\u007f]/.test(recovery.source_ref)
      || recovery.document_sha256 !== expectedDigest) return undefined;
  return { ingestion_id: recovery.ingestion_id, source_ref: recovery.source_ref,
    document_sha256: recovery.document_sha256,
    ...(typeof recovery.job_id === 'string' && /^[a-f0-9]{32}$/.test(recovery.job_id) ? { job_id: recovery.job_id } : {}) };
}

function sameIngestion(previous: DocumentExtractionRecovery, next: DocumentExtractionRecovery): boolean {
  return previous.ingestion_id === next.ingestion_id && previous.source_ref === next.source_ref
    && previous.document_sha256 === next.document_sha256;
}

function readShared(python: string, helper: string, request: Record<string, unknown>, temporary: string,
                    expectedDigest: string): Promise<SharedResponse> {
  return new Promise((resolve, reject) => {
    const child = spawn(python, ['-I', '-B', helper], {
      cwd: path.dirname(helper), env: childEnvironment(temporary), windowsHide: true,
      shell: false, stdio: ['pipe', 'pipe', 'ignore'],
    });
    const chunks: Buffer[] = [];
    let size = 0;
    let failure: WaiterError | undefined;
    const stop = (message: string, retryable: boolean) => {
      if (failure) return;
      failure = new WaiterError(message, retryable);
      // This process only waits for a durable ingestion. Its descendants may
      // own parsing for other clients: never kill a tree or use taskkill /T.
      child.kill();
    };
    const timer = setTimeout(() => stop('The reading connection timed out. The background job and original document are retained; reopen the material to continue.', true), WAITER_TIMEOUT_MS);
    child.on('error', () => { clearTimeout(timer); reject(new WaiterError('The local document connection is temporarily unavailable. Please retry.', true)); });
    child.stdin.on('error', () => {});
    child.stdout.on('data', (data: Buffer) => {
      size += data.length;
      if (size > MAX_OUTPUT_BYTES) stop('The document result exceeds the local limit. Split the document and retry.', false);
      else if (!failure) chunks.push(data);
    });
    child.on('close', code => {
      clearTimeout(timer);
      if (failure) return reject(failure);
      try {
        const result = JSON.parse(Buffer.concat(chunks).toString('utf8'));
        const recovery = recoveryFrom(result?.recovery, expectedDigest);
        if (code === 0 && result?.ok === false && ['queued', 'running'].includes(result.status)) {
          if (!recovery) throw new WaiterError('The pending document result does not contain valid recovery information.', false);
          return resolve({ ...result, recovery });
        }
        if (code === 0 && result?.status === 'cancelled') {
          if (!recovery) throw new WaiterError('The stopped reading result does not contain valid recovery information.', false);
          return resolve({ ...result, ok: false, recovery });
        }
        if (result?.ok === false) throw new WaiterError(
          typeof result.error === 'string' ? result.error : 'The local document has not been fully read. Reopen the material to retry.', false, recovery);
        if (code !== 0 || result?.ok !== true) throw new WaiterError('The local document connection was interrupted. Reopen the material to continue.', true, recovery);
        if (!recovery) throw new WaiterError('The document result does not contain valid recovery information.', false);
        resolve({ ...result, recovery } as SharedResult);
      } catch (error) { reject(error instanceof SyntaxError ? new WaiterError('The local document reader returned an invalid result.', true) : error); }
    });
    child.stdin.end(JSON.stringify(request));
  });
}

async function waitForShared(python: string, helper: string, source: string, temporary: string,
                             input: DocumentExtractorInput, action: 'read' | 'cancel' = 'read',
                             initialRecovery?: DocumentExtractionRecovery): Promise<SharedResult | CancelledResult> {
  const expectedDigest = createHash('sha256').update(input.buffer).digest('hex');
  let recovery = initialRecovery;
  let reconnects = 0;
  for (;;) {
    try {
      const result = await readShared(python, helper, {
        source, include_assets: input.config.textOnly !== true,
        owner_scope: input.serverContext!.ownerScope,
        ...(recovery ? { ingestion_id: recovery.ingestion_id } : {}),
        ...(action === 'cancel' ? { action } : {}),
      }, temporary, expectedDigest);
      reconnects = 0;
      if (recovery && !sameIngestion(recovery, result.recovery)) {
        throw new WaiterError('The recovery information does not match the current material task.', false, recovery);
      }
      if (result.ok === false && (result.status === 'queued' || result.status === 'running')) {
        recovery = result.recovery;
        const delay = Number.isFinite(result.retry_after_ms) ? Math.min(2000, Math.max(100, result.retry_after_ms!)) : 500;
        await new Promise(resolve => setTimeout(resolve, delay));
        continue;
      }
      return result as SharedResult | CancelledResult;
    } catch (error) {
      if (error instanceof DocumentExtractionError && error.recovery) {
        if (recovery && !sameIngestion(recovery, error.recovery)) {
          throw new DocumentExtractionError('The recovery information does not match the current material task.', recovery);
        }
        recovery = error.recovery;
      }
      if (!(error instanceof WaiterError) || !error.retryable || reconnects >= MAX_RECONNECT_ATTEMPTS) {
        throw new DocumentExtractionError(error instanceof Error ? error.message : 'Material reading has not finished.', recovery);
      }
      reconnects += 1;
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  }
}

function safeName(name?: string) {
  return (name?.split(/[\\/]/).pop() || 'document').replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 160) || 'document';
}

export function deepsteamDocumentArtifact(result: SharedResult, input: DocumentExtractorInput): DocumentArtifact {
  const digest = createHash('sha256').update(input.buffer).digest('hex');
  const imageReady = result.requires_image_reading === true && result.coverage?.source_units_enumerated === true
    && result.coverage?.text_layer_complete === true && result.images?.length > 0;
  if (result.document?.sha256 !== digest || !Array.isArray(result.units)
      || result.units.length !== result.document.unit_count || (result.coverage?.document_fully_read !== true && !imageReady)
      || !Array.isArray(result.images) || !Array.isArray(result.warnings)) throw new Error('The document result is missing completeness information.');
  const name = safeName(input.fileName);
  const sources: ClassroomImageSource[] = [];
  const assets = result.images.map((image, index) => {
    if (image.mime_type !== 'image/png' || !/^[A-Za-z0-9+/=]+$/.test(image.base64)
        || !Buffer.from(image.base64, 'base64').subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) {
      throw new Error('The document image result has an invalid format.');
    }
    const source: ClassroomImageSource = { image_index: index + 1, asset_id: image.source_asset_id,
      locator: image.locator, document_sha256: digest, source_document_name: name };
    sources.push(source);
    return { id: `img_${index + 1}`, type: 'image' as const, mimeType: image.mime_type,
      data: `data:${image.mime_type};base64,${image.base64}`, pageNumber: image.locator.page,
      description: `Source figure; original location: ${JSON.stringify(image.locator)}`,
      metadata: { imageSource: source } };
  });
  if (!validClassroomImageSources(sources, assets.length)) throw new Error('Document images are missing valid source locators.');
  const blocks: DocumentArtifact['blocks'] = result.units.map((unit, index) => ({
    id: `unit_${index + 1}`, type: 'text',
    text: `[Source location: ${JSON.stringify(unit.locator)}]\n${unit.text}`,
    pageNumber: unit.locator.page,
    metadata: { locator: unit.locator, coverage: unit.coverage, status: unit.status,
      table: unit.table, equations: unit.equations },
  }));
  // Structured Office content is preserved when supplied. PDF table/formula
  // semantics remain explicitly unguaranteed by the reader's coverage report.
  result.units.forEach((unit, index) => {
    if (unit.table?.rows) blocks.push({ id: `table_${index + 1}`, type: 'table', pageNumber: unit.locator.page,
      metadata: { data: unit.table.rows, locator: unit.locator } });
    for (const [equationIndex, equation] of (unit.equations ?? []).entries()) {
      if (equation.format === 'latex' && equation.text) blocks.push({ id: `formula_${index + 1}_${equationIndex + 1}`,
        type: 'formula', text: equation.text, pageNumber: unit.locator.page,
        metadata: { locator: unit.locator, status: equation.status } });
    }
  });
  if (result.warnings.length) blocks.push({ id: 'reading-notes', type: 'text',
    text: `[Document reading notes]\n${result.warnings.map(warning => `- ${warning}`).join('\n')}` });
  const pageCount = Math.max(0, ...result.units.map(unit => unit.locator.page ?? 0));
  return { metadata: { fileName: name, fileSize: input.buffer.length, mimeType: input.mimeType,
    pageCount, providerId: 'deepsteam-local' }, blocks, assets,
    diagnostics: result.warnings.map(message => ({ severity: 'warning', message, providerId: 'deepsteam-local' })),
    providerRaw: { text: '', images: [], image_sources: sources, metadata: { parser: 'deepsteam-local', pageCount,
      documentSha256: digest, documentUnitCount: result.document.unit_count,
      readingStatus: result.status, coverage: result.coverage, warnings: result.warnings,
      requiresImageReading: result.requires_image_reading === true,
      visualPending: result.visual_pending === true, visionPending: result.vision_pending,
      imageReading: result.image_reading, nextTool: result.next_tool } },
  };
}

async function executeShared(input: DocumentExtractorInput, action: 'read' | 'cancel' = 'read',
                             recovery?: DocumentExtractionRecovery): Promise<SharedResult | CancelledResult> {
  const extension = extensions[input.mimeType];
  if (!extension || !input.buffer.length || input.buffer.length > MAX_EXTRACT_DOCUMENT_FILE_SIZE_BYTES) throw new Error('The document format is unsupported or the file exceeds the 200 MiB limit.');
  const owner = input.serverContext?.ownerScope;
  if (typeof owner !== 'string' || !owner.length || owner.length > 256 || /[\u0000-\u001f\u007f]/.test(owner)) {
    throw new Error('Document reading is missing valid server ownership information. Reopen the material.');
  }
  let directory: string | undefined;
  try {
    const { python, helper } = await installation();
    const temporary = path.join(resolveDataDir(), 'document-extract-tmp');
    await fs.mkdir(temporary, { recursive: true });
    const root = await fs.realpath(temporary);
    directory = await fs.mkdtemp(path.join(root, 'extract-'));
    const source = path.join(directory, `source${extension}`);
    await fs.writeFile(source, input.buffer, { flag: 'wx' });
    return await waitForShared(python, helper, source, root, input, action, recovery);
  } finally {
    if (directory) await fs.rm(directory, { recursive: true, force: true });
  }
}

/** Explicit server action only. An HTTP disconnect must never call this. */
export async function cancelDeepsteamDocumentExtraction(input: DocumentExtractorInput,
                                                       recovery: DocumentExtractionRecovery): Promise<CancelledResult> {
  const expectedDigest = createHash('sha256').update(input.buffer).digest('hex');
  const verified = recoveryFrom(recovery, expectedDigest);
  if (!verified) throw new DocumentExtractionError('The recovery information for the material to stop could not be verified.');
  const result = await executeShared(input, 'cancel', verified);
  if (result.ok !== false || result.status !== 'cancelled') throw new DocumentExtractionError('The material has already finished reading and cannot be stopped.', verified);
  return result;
}

export const deepsteamLocalDocumentExtractor: DocumentExtractorProvider = {
  ...getDocumentExtractorManifestEntry('deepsteam-local')!,
  async extract(input) {
    const result = await executeShared(input);
    if (result.ok === false) throw new DocumentExtractionError(result.error || 'Reading was stopped; the original document is retained.', result.recovery);
    return deepsteamDocumentArtifact(result, input);
  },
};
