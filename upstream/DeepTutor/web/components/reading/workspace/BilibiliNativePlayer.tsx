"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ReadingMediaController } from "@/lib/reading-media-controller";
import { bilibiliOfficialUrl, type BilibiliSource } from "@/lib/reading-video-sources";

type Playback = { status: string; time?: number; duration?: number; rate?: number; paused?: boolean };
type Command = { action: string; url: string; instance: string; seconds?: number; rate?: number;
  bounds?: { x: number; y: number; width: number; height: number; visible: boolean } };
type Bridge = (command: Command) => Promise<Playback>;

/** Restore the already shipped, account-aware official player bridge. */
export function BilibiliNativePlayer({ source, startSeconds, duration, title, onController, onTime, onError }: {
  source: BilibiliSource; startSeconds: number; duration: number; title: string;
  onController(controller: ReadingMediaController | null): void;
  onTime(seconds: number, duration: number): void;
  onError(error: string): void;
}) {
  const { t } = useTranslation();
  const host = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onController, onTime, onError });
  callbacks.current = { onController, onTime, onError };
  const initialTime = useRef(startSeconds); initialTime.current = startSeconds;
  const [status, setStatus] = useState("loading");
  const state = useRef({ time: startSeconds, duration, rate: 1 });
  const url = bilibiliOfficialUrl(source, 0);
  const instance = useMemo(() => "bili_" + crypto.randomUUID().replaceAll("-", ""), [url]);
  const bridge = (window as unknown as { deepsteamDesktop: { domesticVideo: Bridge } }).deepsteamDesktop.domesticVideo;
  const commandEpoch = useRef(0);
  const queued = useRef<{ seek?: number; rate?: number; playback?: "play" | "pause" }>({});
  const controller = useMemo<ReadingMediaController>(() => {
    const send = (action: string, value?: number) => {
      commandEpoch.current += 1;
      // Captions can load before the official player. Keep the last user
      // command until media metadata exists; an early seek must also win over
      // the saved reading position applied at initial playback.
      if (action === "seek") queued.current.seek = value;
      else if (action === "rate") queued.current.rate = value;
      else if (action === "play" || action === "pause") queued.current.playback = action;
    };
    return { currentTime: () => state.current.time, duration: () => state.current.duration,
      playbackRate: () => state.current.rate, tracksPosition: false,
      seek: seconds => send("seek", Math.max(0, Math.min(state.current.duration || Infinity, seconds))),
      setPlaybackRate: rate => send("rate", rate), play: () => send("play"), pause: () => send("pause"), destroy: () => undefined };
  }, [bridge, instance, url, t]);

  useEffect(() => {
    let stopped = false, pending = false, positioned = false;
    callbacks.current.onController(controller);
    const call = (action: string, extra: Partial<Command> = {}) => bridge({ action, url, instance, ...extra });
    const bounds = () => {
      const r = host.current?.getBoundingClientRect();
      if (!r) return { x: 0, y: 0, width: 0, height: 0, visible: false };
      const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      return { x: r.x, y: r.y, width: r.width, height: r.height,
        visible: !!hit && !!host.current?.contains(hit) && r.top >= 0 && r.left >= 0 && r.bottom <= innerHeight && r.right <= innerWidth };
    };
    const layout = () => { void call("bounds", { bounds: bounds() }).catch(() => undefined); };
    const poll = async () => {
      layout(); if (stopped || pending) return;
      pending = true; const epoch = commandEpoch.current;
      try {
        const value = await call("state");
        if (stopped || epoch !== commandEpoch.current) return;
        setStatus(value.status);
        if (value.status === "ready" && Number.isFinite(value.time) && Number.isFinite(value.duration)) {
          if (!positioned) {
            positioned = true;
            if (queued.current.seek === undefined && initialTime.current > 0) queued.current.seek = initialTime.current;
          }
          const commands = queued.current;
          if (commands.seek !== undefined || commands.rate !== undefined || commands.playback) {
            queued.current = {};
            if (commands.seek !== undefined) await call("seek", { seconds: commands.seek });
            if (commands.rate !== undefined) await call("rate", { rate: commands.rate });
            if (commands.playback) await call(commands.playback);
            return; // Never publish the pre-command time over the user's seek.
          }
          state.current = { time: value.time!, duration: value.duration!, rate: value.rate || 1 };
          if (!controller.tracksPosition) { controller.tracksPosition = true; callbacks.current.onController(controller); }
          callbacks.current.onError(""); callbacks.current.onTime(state.current.time, state.current.duration);
        } else if (["network_error", "load_timeout", "request_failed", "removed", "region_restricted"].includes(value.status)) {
          if (controller.tracksPosition) { controller.tracksPosition = false; callbacks.current.onController(controller); }
          callbacks.current.onError(t("The video could not be loaded. Reopen this material to retry."));
        }
      } catch { if (!stopped) { setStatus("request_failed"); callbacks.current.onError(t("The player did not respond. Reopen this material to retry.")); } }
      finally { pending = false; }
    };
    void call("mount", { bounds: bounds() }).then(() => { if (!stopped) void poll(); }).catch(() => {
      if (!stopped) callbacks.current.onError(t("The video could not be loaded. Reopen this material to retry."));
    });
    const observer = new ResizeObserver(layout); if (host.current) observer.observe(host.current);
    window.addEventListener("scroll", layout, true); window.addEventListener("resize", layout);
    const timer = window.setInterval(() => void poll(), 250);
    return () => {
      stopped = true; window.clearInterval(timer); observer.disconnect();
      window.removeEventListener("scroll", layout, true); window.removeEventListener("resize", layout);
      callbacks.current.onController(null); void call("unmount").catch(() => undefined);
    };
  }, [bridge, controller, instance, t, url]);

  return <div ref={host} data-testid="bilibili-native-player" data-player-status={status}
    className="h-full w-full bg-black" aria-label={title} />;
}
