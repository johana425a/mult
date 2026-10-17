'use client';

/**
 * Global store for the one-click MP4 render (issue #866).
 *
 * The render is async and long (a 10-minute classroom takes ~10 minutes), so
 * its progress must outlive the export menu: the user can close the menu, switch
 * scenes, and reopen the menu, and still see live progress. Keeping the state in
 * a component (as the first cut did) meant it died with the menu, and the
 * re-mounted menu reset its "already rendering" ref — letting the user submit a
 * duplicate render. Hoisting the whole lifecycle here fixes both.
 *
 * The store owns the submit → poll → download loop. Progress is a percentage
 * plus an estimated time remaining (extrapolated from elapsed time and smoothed
 * with an EMA); no producer stage strings are surfaced. i18n stays out of the
 * store: callers pass `t`, and toasts use sonner's global singleton so they
 * still fire if the calling component has unmounted.
 */
import { create } from 'zustand';
import { saveAs } from 'file-saver';
import { toast } from 'sonner';
import { createLogger } from '@/lib/logger';
import { runPolledTask } from '@/lib/media/polled-task';
import {
  NoScenesError,
  sanitizeFilename,
  type VideoFps,
  type VideoQuality,
  type VideoResolution,
} from '@/lib/video-export-app/export-options';
import type { Locale } from '@/lib/i18n';
import { useStageStore } from '@/lib/store/stage';
import { observeExportChanges } from '@/lib/video-export-app/observe-export-changes';
import { resolveExportStageName } from '@/lib/video-export-app/resolve-stage-name';

type BuildExportZipResult = import('@/lib/video-export-app/build-export-zip').BuildExportZipResult;

const log = createLogger('VideoRenderStore');

const POLL_INTERVAL_MS = 3000;
const MAX_POLL_ATTEMPTS = Math.ceil((60 * 60 * 1000) / POLL_INTERVAL_MS);

export type VideoRenderStatus = 'idle' | 'compiling' | 'rendering' | 'cancelling' | 'cancelled' | 'succeeded' | 'failed';

/** Minimal i18n surface the store needs, injected by callers. */
type Translate = (key: string, options?: Record<string, unknown>) => string;

export interface RenderOptions {
  resolution?: VideoResolution;
  fps?: VideoFps;
  quality?: VideoQuality;
  /** Burn subtitles into the MP4. Default false (sidecar SRT/VTT only). */
  burnInSubtitles?: boolean;
}

/** Fully-resolved render options (the store always holds concrete values). */
type ResolvedOptions = Required<RenderOptions>;
export type RenderSelection = {stageId:string; sceneIds:string[] | null};

const DEFAULT_OPTIONS: ResolvedOptions = {
  resolution: '1080p',
  fps: 30,
  quality: 'standard',
  burnInSubtitles: false,
};

interface JobStatusResponse {
  jobId: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  progress?: number;
  currentStage?: string;
  error?: string;
  done?: boolean;
  framesRendered?: number;
  totalFrames?: number;
}

interface VideoRenderState {
  status: VideoRenderStatus;
  /** 0..100. */
  percent: number;
  /** Estimated milliseconds remaining, or null while unknown. */
  etaMs: number | null;
  filename: string | null;
  selection: RenderSelection | null;
  jobId: string | null;
  frameCount: string | null;
  error: string | null;
  /**
   * The user's selected render options. Held in the store (not the menu
   * component) so they survive the menu unmounting on scene switches and, while
   * a render runs, reflect the options that render is actually using.
   */
  options: ResolvedOptions;
  setOptions: (patch: Partial<ResolvedOptions>) => void;
  /** True while a render is in flight (compiling or rendering). */
  isActive: () => boolean;
  /** `locale` is the export's, not the store's: it is baked into the emitted card chrome. */
  startRender: (t: Translate, locale: Locale, sceneIds?: readonly string[]) => Promise<void>;
  cancelRender: () => void;
  restoreRender: (t: Translate) => Promise<void>;
  reset: () => void;
}

/** Whether a status means a render is still in flight. */
function inFlight(status: VideoRenderStatus): boolean {
  return status === 'compiling' || status === 'rendering' || status === 'cancelling';
}

// One in-memory retry slot; the active request and the slot share the same Blob.
let cachedZip: {
  stageId: string;
  resolution: VideoResolution;
  burnInSubtitles: boolean;
  locale: Locale;
  sceneKey: string;
  result: BuildExportZipResult;
} | null = null;
let exportRevision = 0;
let activeRenders = 0;
let stopObserving: (() => void) | undefined;
let renderController: AbortController | null = null;
const RENDER_RECEIPT_KEY = 'deepsteam-video-render-v1';
type RenderReceipt = {jobId: string; filename: string; status: 'rendering' | 'succeeded'; options: ResolvedOptions; selection?:RenderSelection};
function saveReceipt(receipt: RenderReceipt | null) {
  try {
    if (receipt) localStorage.setItem(RENDER_RECEIPT_KEY, JSON.stringify(receipt));
    else localStorage.removeItem(RENDER_RECEIPT_KEY);
  } catch { /* Rendering still works if browser storage is unavailable. */ }
}
function readReceipt(): RenderReceipt | null {
  try {
    const value = JSON.parse(localStorage.getItem(RENDER_RECEIPT_KEY) || 'null');
    return value && typeof value.filename === 'string' && typeof value.jobId === 'string' &&
      /^[a-zA-Z0-9_-]{1,128}$/.test(value.jobId) && ['rendering', 'succeeded'].includes(value.status) ? value : null;
  } catch { return null; }
}

/** Poll an accepted job without cancelling it merely because the page disconnected. */
function renderPoll(signal: AbortSignal, update: (patch: Partial<VideoRenderState>) => void) {
  let networkFailures = 0;
  return async (jobId: string) => {
    signal.throwIfAborted();
    let res: Response;
    try {
      res = await fetch(`/api/export-video/render/${jobId}`, {signal});
      if (res.status >= 500) throw new Error(`HTTP ${res.status}`);
      networkFailures = 0;
    } catch (error) {
      signal.throwIfAborted();
      if (++networkFailures <= 6) return {status: 'pending' as const};
      throw error;
    }
    const data = await res.json() as JobStatusResponse;
    if (!res.ok) return {status: 'failed' as const, message: data.error || `HTTP ${res.status}`};
    update({percent: Math.round((data.progress ?? 0) * 100), etaMs: null,
      frameCount: data.totalFrames ? `${data.framesRendered ?? 0} / ${data.totalFrames}` : null});
    if (data.status === 'succeeded') {
      const dl = await fetch(`/api/export-video/render/${jobId}/download`, {signal});
      if (!dl.ok) return {status:'failed' as const,message:`download HTTP ${dl.status}`};
      return {status:'done' as const,result:await dl.blob()};
    }
    if (data.status === 'failed' || data.status === 'cancelled') {
      saveReceipt(null);
      return {status:'failed' as const,message:data.error || data.status};
    }
    return {status:'pending' as const,detail:data.currentStage};
  };
}

function releaseIdleObservers() {
  if (activeRenders === 0 && !cachedZip) {
    stopObserving?.();
    stopObserving = undefined;
  }
}

function invalidateCachedZip() {
  exportRevision += 1;
  cachedZip = null;
  releaseIdleObservers();
}

function rejectionMessageKey(status: number | null, reason?: string): string | undefined {
  if (status === 413) return 'export.videoTooLarge';
  if (status !== 429) return undefined;
  if (reason === 'queue_full') return 'export.videoQueueFull';
  if (reason === 'per_identity_limit') return 'export.videoRenderInProgress';
  return undefined;
}

export const useVideoRenderStore = create<VideoRenderState>()((set, get) => ({
  status: 'idle',
  percent: 0,
  etaMs: null,
  filename: null,
  selection: null,
  jobId: null,
  frameCount: null,
  error: null,
  options: DEFAULT_OPTIONS,

  setOptions: (patch) => {
    const previous = get().options;
    const options = { ...previous, ...patch };
    if (
      options.resolution !== previous.resolution ||
      options.burnInSubtitles !== previous.burnInSubtitles
    )
      invalidateCachedZip();
    set({ options });
  },

  isActive: () => inFlight(get().status),
  cancelRender: () => {
    if (!renderController || !inFlight(get().status)) return;
    set({status:'cancelling'});
    renderController.abort();
  },
  restoreRender: async (t) => {
    if (inFlight(get().status) || get().status === 'succeeded') return;
    const receipt = readReceipt();
    if (!receipt) return;
    set({jobId:receipt.jobId,filename:receipt.filename,selection:receipt.selection ?? null,
      options:{...DEFAULT_OPTIONS,...receipt.options},error:null});
    if (receipt.status === 'succeeded') { set({status:'succeeded',percent:100}); return; }
    set({status:'rendering',etaMs:null});
    const controller = new AbortController();
    renderController = controller;
    const toastId = toast.loading(t('export.videoResuming'));
    try {
      const mp4 = await runPolledTask<Blob>({label:'resume-video',intervalMs:POLL_INTERVAL_MS,
        maxAttempts:MAX_POLL_ATTEMPTS,signal:controller.signal,
        submit:async()=>({status:'submitted',taskId:receipt.jobId}),poll:renderPoll(controller.signal,set)});
      saveAs(mp4,receipt.filename);
      saveReceipt({...receipt,status:'succeeded'});
      set({status:'succeeded',percent:100,etaMs:0});
      toast.success(t('export.videoMp4Success'),{id:toastId});
    } catch (error) {
      if (controller.signal.aborted) {
        try {
          const cancelled = await fetch(`/api/export-video/render/${receipt.jobId}`,{method:'DELETE'});
          if (!cancelled.ok) throw new Error(`HTTP ${cancelled.status}`);
          saveReceipt(null); set({status:'cancelled',error:null});
          toast.info(t('export.videoCancelled'),{id:toastId});
        } catch { set({status:'failed',error:t('export.videoCancelFailed')}); toast.error(t('export.videoCancelFailed'),{id:toastId}); }
      } else {
        set({status:'failed',error:error instanceof Error ? error.message : String(error)});
        toast.error(t('export.videoFailed'),{id:toastId});
      }
    } finally { if (renderController === controller) renderController = null; }
  },

  reset: () => {
    if (inFlight(get().status)) return;
    invalidateCachedZip();
    set({ status: 'idle', percent: 0, etaMs: null, filename: null, selection:null, jobId:null, frameCount:null, error: null });
  },

  startRender: async (t, locale, sceneIds) => {
    // Guard against a duplicate submit — the whole reason state lives here.
    if (inFlight(get().status)) return;
    if (readReceipt()?.status === 'rendering') { await get().restoreRender(t); return; }
    const controller = new AbortController();
    renderController = controller;
    const sceneKey = JSON.stringify(sceneIds ?? null);

    activeRenders += 1;
    stopObserving ??= observeExportChanges(invalidateCachedZip);
    const { resolution, fps, quality, burnInSubtitles } = get().options;
    const { stage } = useStageStore.getState();
    const stageId = stage?.id;
    const selection: RenderSelection | undefined = stageId ? {stageId,sceneIds:sceneIds ? [...sceneIds] : null} : undefined;
    if (
      cachedZip &&
      (cachedZip.stageId !== stageId ||
        cachedZip.resolution !== resolution ||
        cachedZip.burnInSubtitles !== burnInSubtitles ||
        cachedZip.locale !== locale || cachedZip.sceneKey !== sceneKey)
    )
      invalidateCachedZip();
    const cached = cachedZip?.result;

    set({
      status: cached ? 'rendering' : 'compiling',
      percent: 0,
      etaMs: null,
      filename: null,
      selection: selection ?? null,
      jobId:null,
      frameCount:null,
      error: null,
    });
    const toastId = toast.loading(t(cached ? 'export.videoRendering' : 'export.videoCompiling'));

    let zipBlob: Blob;
    let stageName: string;
    let missingCount = 0;
    let errorCount = 0;
    try {
      let built = cached;
      if (built && stage && !sceneIds) {
        const currentName = await resolveExportStageName(stage);
        // The async name read can overlap an edit/reset. Never reuse a slot
        // that was released while reading, even when the name still matches.
        if (cachedZip?.result !== built || currentName !== built.stageName) {
          invalidateCachedZip();
          built = undefined;
          set({ status: 'compiling' });
          toast.loading(t('export.videoCompiling'), { id: toastId });
        }
      }
      if (!built) {
        const revision = exportRevision;
        const compileStageId = useStageStore.getState().stage?.id;
        const { buildExportZip } = await import('@/lib/video-export-app/build-export-zip');
        built = await buildExportZip({ resolution, burnInSubtitles, locale, sceneIds, signal:controller.signal });
        // Changes during compilation (including reset or switching away and
        // back) cannot repopulate the retry slot with an obsolete snapshot.
        if (compileStageId && revision === exportRevision) {
          cachedZip = {
            stageId: compileStageId,
            resolution,
            burnInSubtitles,
            locale,
            sceneKey,
            result: built,
          };
        }
      }
      ({ zipBlob, stageName, missingCount, errorCount } = built);
      controller.signal.throwIfAborted();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      set({ status: controller.signal.aborted ? 'cancelled' : 'failed', error: controller.signal.aborted ? null : message });
      if (controller.signal.aborted) toast.info(t('export.videoCancelled'), {id:toastId});
      else if (error instanceof NoScenesError) {
        toast.error(t('export.videoNoScenes'), { id: toastId });
      } else {
        log.error('Video render (compile) failed:', error);
        toast.error(t('export.videoFailed'), { id: toastId });
      }
      activeRenders -= 1;
      releaseIdleObservers();
      if (renderController === controller) renderController = null;
      return;
    }

    const filename = `${sanitizeFilename(stageName)}.mp4`;
    set({ status: 'rendering', filename });

    // Set once the service accepts the job. Lets the catch below distinguish a
    // *submit* failure (nothing started) from a failure after the render began
    // (hard error, and cancel the server job to free its slot).
    let submittedJobId: string | null = null;
    // HTTP status of a failed submit, so the catch can tell "service genuinely
    // unavailable" (degrade to ZIP) from a real rejection like 429/413/5xx
    // (surface the error instead of an unsolicited download). null = fetch threw.
    let submitStatus: number | null = null;
    let submitReason: string | undefined;

    try {
      const form = new FormData();
      form.append('project', zipBlob, 'project.zip');
      form.append('fps', String(fps));
      form.append('quality', quality);
      form.append('format', 'mp4');

      toast.loading(t('export.videoRendering'), { id: toastId });

      const mp4 = await runPolledTask<Blob>({
        label: 'render-video',
        signal: controller.signal,
        intervalMs: POLL_INTERVAL_MS,
        maxAttempts: MAX_POLL_ATTEMPTS,
        submit: async () => {
          const res = await fetch('/api/export-video/render', { method: 'POST', body: form });
          const data = (await res.json().catch(() => ({}))) as {
            jobId?: string;
            error?: string;
            details?: string;
            reason?: string;
          };
          if (!res.ok || !data.jobId) {
            submitStatus = res.status;
            submitReason = data.reason;
            const detail = [data.error, data.details].filter(Boolean).join(': ');
            return { status: 'failed', message: detail || `HTTP ${res.status}` };
          }
          submittedJobId = data.jobId;
          set({jobId:data.jobId});
          saveReceipt({jobId:data.jobId,filename,status:'rendering',options:get().options,selection});
          return { status: 'submitted', taskId: data.jobId };
        },
        poll: renderPoll(controller.signal,set),
      });

      saveAs(mp4, filename);
      invalidateCachedZip();
      set({ status: 'succeeded', percent: 100, etaMs: 0 });
      if (submittedJobId) saveReceipt({jobId:submittedJobId,filename,status:'succeeded',options:get().options,selection});
      toast.success(t('export.videoMp4Success'), { id: toastId });
      if (missingCount > 0 || errorCount > 0) {
        toast.warning(t('export.videoWarnings', { assets: missingCount, diagnostics: errorCount }));
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (controller.signal.aborted) {
        try {
          if (submittedJobId) {
            const cancelled = await fetch(`/api/export-video/render/${submittedJobId}`,{method:'DELETE'});
            if (!cancelled.ok) throw new Error(`HTTP ${cancelled.status}`);
          }
          saveReceipt(null);
          set({status:'cancelled',error:null,etaMs:null});
          toast.info(t('export.videoCancelled'),{id:toastId});
        } catch {
          set({status:'failed',error:t('export.videoCancelFailed')});
          toast.error(t('export.videoCancelFailed'),{id:toastId});
        }
      } else if (submittedJobId == null) {
        // The submit never succeeded. Only degrade to the ZIP when the service
        // is genuinely unavailable — not configured (501) or unreachable (fetch
        // threw, submitStatus null). For real rejections (429 busy, 413 too
        // large, 5xx) surface the actual reason instead of silently downloading
        // a ZIP the user didn't ask for, so the failure is honest and retryable.
        const unavailable = submitStatus == null || submitStatus === 501;
        if (unavailable) {
          saveAs(zipBlob, `${sanitizeFilename(stageName)}-video.zip`);
          invalidateCachedZip();
          set({ status: 'idle', percent: 0, etaMs: null });
          toast.info(t('export.videoServiceUnavailable'), { id: toastId });
        } else {
          if (submitStatus === 400 || submitStatus === 413) invalidateCachedZip();
          set({ status: 'failed', error: message });
          const key = rejectionMessageKey(submitStatus, submitReason);
          toast.error(t(key ?? 'export.videoFailed'), { id: toastId });
        }
      } else {
        // Keep the accepted job receipt across a network failure. Reopening the
        // export dialog resumes polling instead of submitting duplicate work.
        log.error('Video render failed:', error);
        set({ status: 'failed', error: message });
        toast.error(t('export.videoFailed'), { id: toastId });
      }
    } finally {
      activeRenders -= 1;
      releaseIdleObservers();
      if (renderController === controller) renderController = null;
    }
  },
}));
