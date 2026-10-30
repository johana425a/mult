"use client";

import { useEffect, useRef, useState } from "react";
import { LoaderCircle, PackageX } from "lucide-react";
import { useTranslation } from "react-i18next";
import { canOpenUninstaller, openUninstaller } from "@/lib/deepsteam-desktop";

export default function DesktopUninstallCard() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const [desktop, setDesktop] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null);
  const opening = useRef(false);
  useEffect(() => setDesktop(canOpenUninstaller()), []);

  const launch = async () => {
    if (opening.current) return;
    opening.current = true;
    setPending(true);
    setNotice(null);
    try {
      const result = await openUninstaller();
      const success = result.status === "opened" || result.status === "already-open";
      const message = success
        ? result.status === "already-open"
          ? zh ? "卸载窗口已经打开，请在该窗口中继续或取消。" : "The uninstall window is already open. Continue or cancel there."
          : zh ? "卸载窗口已打开。确认之前不会删除任何内容，你可以取消。" : "The uninstall window is open. Nothing is removed until you confirm; you can cancel."
        : result.status === "unavailable"
          ? zh ? "未找到可用的卸载程序。请在 Windows 设置 → 应用 → 已安装的应用中查找 DeepSteam，或修复安装。" : "The uninstaller is unavailable. Find DeepSteam in Windows Settings → Apps → Installed apps, or repair the installation."
          : zh ? "无法打开卸载窗口。请重试，或在 Windows 设置 → 应用 → 已安装的应用中卸载 DeepSteam。" : "Could not open the uninstall window. Retry, or uninstall DeepSteam from Windows Settings → Apps → Installed apps.";
      setNotice({ text: message, error: !success });
    } catch {
      setNotice({ text: zh ? "无法打开卸载窗口。请重试，或在 Windows 已安装的应用中查找 DeepSteam。" : "Could not open the uninstall window. Retry, or find DeepSteam in Windows Installed apps.", error: true });
    } finally {
      opening.current = false;
      setPending(false);
    }
  };

  return (
    <section aria-labelledby="desktop-uninstall-title" className="mb-8 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <PackageX aria-hidden="true" size={21} className="mt-0.5 shrink-0 text-[var(--muted-foreground)]" />
          <div>
            <h2 id="desktop-uninstall-title" className="text-[15px] font-semibold">{zh ? "卸载 DeepSteam" : "Uninstall DeepSteam"}</h2>
            <p className="mt-1 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
              {zh ? "默认只移除程序，保留学习记录和设置。如需清理数据，请在卸载窗口中选择。" : "By default, only the program is removed; learning records and settings are kept. Choose any data cleanup in the uninstall window."}
            </p>
          </div>
        </div>
        <button type="button" onClick={() => void launch()} disabled={!desktop || pending} className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-[var(--border)] px-4 py-2.5 text-sm font-medium transition-colors hover:bg-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ring)]">
          {pending && <LoaderCircle aria-hidden="true" size={16} className="animate-spin" />}
          {pending ? zh ? "正在打开…" : "Opening…" : zh ? "卸载 DeepSteam…" : "Uninstall DeepSteam…"}
        </button>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-[var(--muted-foreground)]">
        {desktop === false
          ? zh ? "请在 DeepSteam 桌面应用中使用此入口，或打开 Windows 设置 → 应用 → 已安装的应用，搜索 DeepSteam。" : "Use this entry in the DeepSteam desktop app, or open Windows Settings → Apps → Installed apps and search for DeepSteam."
          : zh ? "点击后先打开确认窗口，不会立即卸载。确认移除前，请保存尚未发送的内容。" : "Clicking opens a confirmation window without uninstalling. Save unsent work before confirming removal."}
      </p>
      {notice && <p role={notice.error ? "alert" : "status"} className={`mt-3 text-sm leading-relaxed ${notice.error ? "text-red-600 dark:text-red-400" : "text-[var(--muted-foreground)]"}`}>{notice.text}</p>}
    </section>
  );
}
