"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { activeWorkspaceId } from "@/lib/workspace-scope";

async function bounded<T>(promise: Promise<T>, milliseconds: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  try {
    return await Promise.race([promise, new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error("REQUEST_TIMEOUT")), milliseconds);
    })]);
  } finally { clearTimeout(timer!); }
}

export function BilibiliSubtitleControls({ materialId }: { materialId: string }) {
  const { t, i18n } = useTranslation();
  const zh = i18n.language.startsWith("zh");
  const desktop = () => (window as any).deepsteamDesktop;
  const [busy, setBusy] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [status, setStatus] = useState("");
  const [account, setAccount] = useState("checking");
  const [profile, setProfile] = useState<{displayName?: string; avatarUrl?: string}>({});
  const revision = useRef(0), busyRef = useRef(false), checking = useRef(false);
  const recheck = useRef(false), awaitingLogin = useRef(false), loginStarted = useRef(0);

  const refresh = useCallback(async () => {
    const importer = desktop()?.importBilibiliSubtitles;
    if (!importer) { setStatus("unavailable"); return; }
    if (busyRef.current) return;
    const attempt = revision.current;
    busyRef.current = true; setBusy(true); setStatus("");
    try {
      const result: any = await bounded(importer({ materialId, workspaceId: activeWorkspaceId() }), 75000);
      if (attempt !== revision.current) return;
      setStatus(result.status);
      if (result.status === "login_required") { setAccount("signed_out"); setProfile({}); }
      if (result.status === "ready") window.location.reload();
    } catch { if (attempt === revision.current) setStatus("request_failed"); }
    finally { if (attempt === revision.current) { busyRef.current = false; setBusy(false); } }
  }, [materialId]);

  const checkSession: () => Promise<void> = useCallback(async () => {
    const check = desktop()?.bilibiliSessionStatus;
    if (!check) { setAccount("unavailable"); return; }
    if (checking.current) { recheck.current = true; return; }
    checking.current = true;
    const attempt = revision.current;
    try {
      const result: any = await bounded(check(), 20000);
      if (attempt !== revision.current) return;
      if (result.status === "signing_out") return;
      setAccount(result.status);
      setProfile(result.status === "signed_in" ? (result.profile || {}) : {});
      if (result.status === "signed_in" && awaitingLogin.current) {
        awaitingLogin.current = false; setStatus("");
        await refresh();
      }
    } catch { if (attempt === revision.current) setAccount("request_failed"); }
    finally { if (attempt === revision.current) {
      checking.current = false;
      if (recheck.current) { recheck.current = false; void checkSession(); }
    } }
  }, [refresh]);

  useEffect(() => {
    revision.current += 1;
    busyRef.current = false; checking.current = false; recheck.current = false; awaitingLogin.current = false;
    setBusy(false); setLeaving(false); setStatus(""); setAccount("checking"); setProfile({});
    const changed = () => { void checkSession(); };
    const unsubscribe = desktop()?.onBilibiliSessionChanged?.(changed);
    window.addEventListener("focus", changed);
    const poll = setInterval(() => {
      if (!awaitingLogin.current) return;
      if (Date.now() - loginStarted.current > 300000) {
        awaitingLogin.current = false; setStatus("login_timeout"); return;
      }
      void checkSession();
    }, 2500);
    void checkSession();
    return () => { revision.current += 1; clearInterval(poll); unsubscribe?.(); window.removeEventListener("focus", changed); };
  }, [checkSession]);

  const login = async () => {
    const open = desktop()?.openBilibiliLogin;
    if (!open) { setStatus("unavailable"); return; }
    const attempt = revision.current;
    awaitingLogin.current = true; loginStarted.current = Date.now(); setStatus("");
    try {
      const result: any = await bounded(open(), 10000);
      if (attempt !== revision.current) return;
      if (result.status !== "opened") { awaitingLogin.current = false; setStatus(result.status); }
      else if (awaitingLogin.current) { setStatus("login_opened"); await checkSession(); }
    } catch { if (attempt === revision.current) { awaitingLogin.current = false; setStatus("request_failed"); } }
  };

  const logout = async () => {
    if (leaving) return;
    const leave = desktop()?.signOutBilibili;
    if (!leave) { setStatus("unavailable"); return; }
    revision.current += 1; const attempt = revision.current;
    awaitingLogin.current = false; checking.current = false; recheck.current = false;
    busyRef.current = false; setBusy(false); setLeaving(true); setStatus("");
    try {
      const result: any = await bounded(leave(), 20000);
      if (attempt !== revision.current) return;
      if (result.status === "signed_out") { setAccount("signed_out"); setProfile({}); setStatus("signed_out"); }
      else setStatus("request_failed");
    } catch { if (attempt === revision.current) setStatus("request_failed"); }
    finally { if (attempt === revision.current) setLeaving(false); }
  };

  const messages: Record<string, [string,string]> = {
    login_required: ["请在软件弹出的 B站窗口完成登录，再刷新字幕。", "Sign in in the Bilibili window, then refresh subtitles."],
    login_opened: ["完成 B站登录后，将自动确认账号并刷新字幕。", "Subtitles refresh automatically after sign-in is confirmed."],
    session_mismatch: ["账号已登录，字幕服务暂未接受当前登录状态，请重试字幕。", "Signed in; the subtitle service has not accepted this session. Retry subtitles."],
    no_track: ["本视频未提供可提取的字幕轨道。", "This video has no extractable caption track."],
    unavailable: ["请重新启动 DeepSteam 以连接字幕功能。", "Restart DeepSteam to reconnect subtitle controls."],
    denied: ["请重新打开当前阅读页面。", "Reopen this reading page."],
    request_failed: ["连接未完成，请重试；这不代表账号已退出。", "The request did not complete. Retry; this does not mean you signed out."],
    login_timeout: ["登录确认已超时，请重新打开登录窗口。", "Sign-in confirmation timed out. Reopen the sign-in window."],
    signed_out: ["已退出 DeepSteam 中的 B站账号。", "Signed out of Bilibili in DeepSteam."],
  };
  const hint = messages[status]?.[zh ? 0 : 1] || "";
  return <div data-testid="bilibili-account-controls" className="flex flex-wrap items-center gap-2 text-[10px]" aria-live="polite">
    {account === "signed_in" ? <>
      <span className="inline-flex items-center gap-2" data-testid="bilibili-signed-in">
        {profile.avatarUrl ? <img data-testid="bilibili-avatar" src={profile.avatarUrl} alt={zh ? "B站头像" : "Bilibili avatar"} width={28} height={28} referrerPolicy="no-referrer" className="rounded-full" style={{width:28,height:28,objectFit:"cover"}} /> : null}
        <span>{profile.displayName || (zh ? "B站已登录" : "Bilibili signed in")}</span>
      </span>
      <button data-testid="bilibili-signout" type="button" className="text-[var(--primary)]" disabled={leaving} onClick={() => void logout()}>{leaving ? (zh ? "正在退出…" : "Signing out…") : (zh ? "退出登录" : "Sign out")}</button>
    </> : <>
      <button data-testid="bilibili-signin" type="button" className="shrink-0 whitespace-nowrap text-[var(--primary)]" disabled={busy || leaving} onClick={() => void login()}>{t("Sign in to Bilibili")}</button>
      {account === "checking" && <span>{zh ? "正在确认 B站登录状态…" : "Checking Bilibili sign-in…"}</span>}
      {account === "request_failed" && <button type="button" className="text-[var(--primary)]" onClick={() => void checkSession()}>{zh ? "登录状态确认失败，点击重试" : "Could not check sign-in. Retry"}</button>}
    </>}
    <button data-testid="bilibili-refresh" type="button" className="shrink-0 whitespace-nowrap text-[var(--primary)]" disabled={busy || leaving} onClick={() => void refresh()}>{busy ? t("Refreshing subtitles…") : t("Refresh Bilibili subtitles")}</button>
    {hint && <span>{hint}</span>}
  </div>;
}
