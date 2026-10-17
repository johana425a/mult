'use client';

/**
 * `useRenderVideo` — thin React facade over the global {@link useVideoRenderStore}.
 *
 * The render lifecycle (build ZIP → upload → poll → download) and the selected
 * options both live in the store, so they survive the export menu unmounting
 * (scene switches, menu close) and can be observed from anywhere — e.g. the
 * persistent ring on the export button. This hook just binds `t` and re-exports
 * the reactive slice the menu needs.
 */
import { useCallback } from 'react';
import { useI18n } from '@/lib/hooks/use-i18n';
import { useVideoRenderStore } from '@/lib/store/video-render';

export function useRenderVideo() {
  const { t, locale } = useI18n();
  const status = useVideoRenderStore((s) => s.status);
  const percent = useVideoRenderStore((s) => s.percent);
  const etaMs = useVideoRenderStore((s) => s.etaMs);
  const options = useVideoRenderStore((s) => s.options);
  const setOptions = useVideoRenderStore((s) => s.setOptions);
  const startRender = useVideoRenderStore((s) => s.startRender);
  const error = useVideoRenderStore((s) => s.error);
  const jobId = useVideoRenderStore((s) => s.jobId);
  const frameCount = useVideoRenderStore((s) => s.frameCount);
  const filename = useVideoRenderStore((s) => s.filename);
  const selection = useVideoRenderStore((s) => s.selection);
  const cancelRender = useVideoRenderStore((s) => s.cancelRender);
  const restoreRender = useVideoRenderStore((s) => s.restoreRender);

  const renderVideo = useCallback((sceneIds?: readonly string[]) => startRender(t, locale, sceneIds), [startRender, t, locale]);
  const resumeRender = useCallback(() => restoreRender(t), [restoreRender,t]);

  return {
    rendering: status === 'compiling' || status === 'rendering' || status === 'cancelling',
    status, jobId, frameCount, filename, selection, cancelRender, resumeRender,
    percent,
    etaMs,
    options,
    setOptions,
    renderVideo,
    error,
  };
}
