'use client';

/**
 * Video-export dialog — a centered modal for configuring and running a
 * classroom → video export.
 *
 * Replaces the cramped dropdown section (`video-export-menu.tsx`): parameters
 * (resolution / fps / quality / subtitles) get room to group, and the modal has
 * a stable lifecycle so a multi-minute render's progress, ETA, and result stay
 * visible instead of vanishing when a dropdown loses focus.
 *
 * Two render paths share one project ZIP:
 * - **Render MP4** (when the render service is configured) — uploads the ZIP,
 *   polls the async job, downloads the MP4. Exposes fps / quality + live progress.
 * - **Download ZIP** — the always-available degrade path (local CLI rendering).
 *
 * Subtitles are burned in only when toggled on (default off, #867 item 2); the
 * "Download subtitles" button always yields an SRT the user can add in an editor.
 */
import { useEffect, useState } from 'react';
import { Film, Loader2, Download } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Progress } from '@/components/ui/progress';
import { Switch } from '@/components/ui/switch';
import { useI18n } from '@/lib/hooks/use-i18n';
import { cn } from '@/lib/utils';
import { useExportVideo } from '@/lib/video-export-app/use-export-video';
import { useRenderVideo } from '@/lib/video-export-app/use-render-video';
import { useDownloadSubtitles } from '@/lib/video-export-app/use-download-subtitles';
import { useStageStore } from '@/lib/store/stage';
import {
  VIDEO_FPS,
  VIDEO_QUALITIES,
  VIDEO_RESOLUTIONS,
  type VideoResolution,
} from '@/lib/video-export-app/export-options';

const RESOLUTIONS = Object.keys(VIDEO_RESOLUTIONS) as VideoResolution[];

/** Format an ETA (ms) as a short localized "about X min Y sec" / "about Y sec". */
function formatRemaining(
  ms: number,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const totalSec = Math.max(1, Math.ceil(ms / 1000));
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return min > 0 ? t('export.videoEtaMinSec', { min, sec }) : t('export.videoEtaSec', { sec });
}

/** A row of mutually-exclusive small pill buttons. */
function OptionRow<T extends string | number>({
  label,
  options,
  value,
  onChange,
  format,
  disabled,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  format?: (v: T) => string;
  disabled?: boolean;
}) {
  return (
    <div>
      <div className="text-[11px] text-gray-400 dark:text-gray-500 mb-1">{label}</div>
      <div className="flex gap-1.5">
        {options.map((opt) => (
          <button
            key={String(opt)}
            onClick={() => onChange(opt)}
            disabled={disabled}
            className={cn(
              'flex-1 px-2 py-1.5 text-xs rounded-md border transition-colors disabled:opacity-50',
              opt === value
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-gray-200 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-700',
            )}
          >
            {format ? format(opt) : String(opt)}
          </button>
        ))}
      </div>
    </div>
  );
}

export function VideoExportDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const { exporting: isExportingVideo, exportVideo } = useExportVideo();
  const { rendering, percent, etaMs, options, setOptions, renderVideo, error,
    status, jobId, frameCount, filename, selection, cancelRender, resumeRender } = useRenderVideo();
  const currentSceneId = useStageStore(s => s.currentSceneId);
  const stageId = useStageStore(s => s.stage?.id);
  const scenes = useStageStore(s => s.scenes);
  const [sceneIds, setSceneIds] = useState<string[] | undefined>(undefined);
  // Persist the actual selection, not merely an "all/current" UI preference:
  // the user may move to another scene while the accepted job is rendering.
  useEffect(() => {
    if (jobId && selection && selection.stageId === stageId) setSceneIds(selection.sceneIds ?? undefined);
  }, [jobId,selection,stageId]);
  const scope = !sceneIds ? 'all' : sceneIds.length === 1 && sceneIds[0] === currentSceneId ? 'current' : 'saved';
  const selectedTitle = sceneIds?.map(id => scenes.find(scene => scene.id === id)?.title || id).join(', ');
  const { downloading, downloadSubtitles } = useDownloadSubtitles();
  const { resolution, fps, quality, burnInSubtitles } = options;
  // undefined = unknown (still probing); true/false = capability answer.
  const [serviceEnabled, setServiceEnabled] = useState<boolean | undefined>(undefined);
  const [accepting, setAccepting] = useState<boolean | undefined>(undefined);
  const [checking, setChecking] = useState(true);
  const [probeAttempt, setProbeAttempt] = useState(0);
  const [previousOpen, setPreviousOpen] = useState(open);
  useEffect(() => { if (open) void resumeRender(); }, [open,resumeRender]);
  // Reopening must not briefly enable MP4 using the last opening's answer.
  if (previousOpen !== open) {
    setPreviousOpen(open);
    if (open) setChecking(true);
  }

  useEffect(() => {
    if (!open) return;
    let active = true;
    const controller = new AbortController();
    fetch('/api/export-video/capability', { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error('Capability check failed');
        return r.json();
      })
      .then((d: { enabled?: boolean; accepting?: boolean }) => {
        if (!active) return;
        setServiceEnabled(Boolean(d.enabled));
        setAccepting(d.accepting);
      })
      .catch(() => {
        if (active) setServiceEnabled(false);
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [open, probeAttempt]);

  // Any in-flight export operation (ZIP build, in-app render, or subtitle
  // download) blocks the others — they share one compile/store critical section.
  const busy = isExportingVideo || rendering || downloading;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Film className="w-4 h-4 text-gray-400 shrink-0" />
            {t('export.video')}
          </DialogTitle>
          <DialogDescription>{t('export.videoDesc')}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          {/* Output settings */}
          {filename && <p className="text-xs break-words text-muted-foreground">{filename}</p>}
          {!(rendering && (!selection || selection.stageId !== stageId)) && <OptionRow label={t('export.videoScope')} options={['all','current'] as const}
            value={scope} onChange={value => setSceneIds(value === 'current' && currentSceneId ? [currentSceneId] : undefined)} disabled={busy}
            format={value=>t(value === 'all' ? 'export.videoAllScenes' : 'export.videoCurrentScene')} />
          }
          {sceneIds && <p className="text-xs text-muted-foreground">{selectedTitle}</p>}
          <OptionRow
            label={t('export.videoResolution')}
            options={RESOLUTIONS}
            value={resolution}
            onChange={(resolution) => setOptions({ resolution })}
            format={(r) => (r === '4k' ? '4K' : r)}
            disabled={busy}
          />
          {serviceEnabled && (
            <>
              <OptionRow
                label={t('export.videoFps')}
                options={VIDEO_FPS}
                value={fps}
                onChange={(fps) => setOptions({ fps })}
                disabled={busy}
              />
              <OptionRow
                label={t('export.videoQuality')}
                options={VIDEO_QUALITIES}
                value={quality}
                onChange={(quality) => setOptions({ quality })}
                format={(q) => t(`export.videoQuality_${q}`)}
                disabled={busy}
              />
            </>
          )}

          {/* Subtitles */}
          <div className="border-t border-gray-200 dark:border-gray-700 pt-3 flex flex-col gap-2">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm">{t('export.videoBurnSubtitles')}</div>
                <div className="text-[11px] text-gray-400 dark:text-gray-500">
                  {t('export.videoBurnSubtitlesDesc')}
                </div>
              </div>
              <Switch
                checked={burnInSubtitles}
                onCheckedChange={(burnInSubtitles) => setOptions({ burnInSubtitles })}
                disabled={busy}
              />
            </div>
            <button
              onClick={() => downloadSubtitles('srt',sceneIds)}
              disabled={busy || downloading}
              className="w-full px-2 py-1.5 text-xs rounded-md border border-gray-200 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5"
            >
              {downloading ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Download className="w-3 h-3" />
              )}
              {t('export.videoDownloadSubtitles')}
            </button>
          </div>

          {/* Progress */}
          {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          {status === 'cancelled' && <p role="status" className="text-sm text-muted-foreground">{t('export.videoCancelled')}</p>}
          {status === 'succeeded' && jobId && <div role="status" className="flex flex-col gap-2 text-sm">
            <span>{t('export.videoMp4Success')}</span>
            <video controls preload="metadata" className="w-full max-h-40 rounded" src={`/api/export-video/render/${jobId}/download`} />
            <a className="underline" href={`/api/export-video/render/${jobId}/download`} download={filename || 'classroom.mp4'}>{t('export.videoDownloadAgain')}</a>
          </div>}
          {rendering && (
            <div>
              <Progress value={percent} />
              <div className="mt-1 text-[11px] text-gray-400 dark:text-gray-500">
                {etaMs != null
                  ? t('export.videoProgressWithEta', {
                      percent,
                      remaining: formatRemaining(etaMs, t),
                    })
                  : t('export.videoProgress', { percent })}
              </div>
              {frameCount && <div className="text-xs text-muted-foreground">{t('export.videoFrameCount',{count:frameCount})}</div>}
              <button type="button" onClick={cancelRender} disabled={status === 'cancelling'}
                className="mt-2 w-full rounded border px-2 py-1.5 text-sm disabled:opacity-50">
                {t(status === 'cancelling' ? 'export.videoCancelling' : 'export.videoCancel')}
              </button>
            </div>
          )}

          {/* Actions */}
          <div className="border-t border-gray-200 dark:border-gray-700 pt-3 flex flex-col gap-1.5">
            {serviceEnabled && (
              <button
                onClick={() => renderVideo(sceneIds)}
                disabled={busy || checking || accepting === false}
                className="w-full px-2 py-2 text-sm rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center justify-center gap-1.5"
              >
                {rendering && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {t('export.videoRenderMp4')}
              </button>
            )}
            {serviceEnabled && accepting === false && (
              <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span role="status">{t('export.videoQueueBusy')}</span>
                <button
                  onClick={() => {
                    setChecking(true);
                    setProbeAttempt((attempt) => attempt + 1);
                  }}
                  disabled={checking || busy}
                  className="shrink-0 underline underline-offset-2 disabled:opacity-50"
                >
                  {checking ? t('export.videoCheckingQueue') : t('export.videoRecheckQueue')}
                </button>
              </div>
            )}
            <button
              onClick={() => exportVideo(resolution, burnInSubtitles, sceneIds)}
              disabled={busy}
              className="w-full px-2 py-2 text-sm rounded-md border border-gray-200 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5"
            >
              {isExportingVideo && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {t('export.videoDownloadZip')}
            </button>
            {serviceEnabled === false && (
              <div className="text-[11px] text-gray-400 dark:text-gray-500">
                {t('export.videoServiceHint')}
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
