"use client";

import { useEffect, useState } from "react";
import i18n from "i18next";

import {
  ensureLanguage,
  initI18n,
  normalizeLanguage,
  type AppLanguage,
} from "./init";

// Initialize i18next at module load (before any React render) so that the
// `init()` call — which fires `initialized` / `languageChanged` events that
// trigger setState on subscribed components — never happens during another
// component's render phase. Calling `initI18n` from the render body would
// produce the React warning:
//   "Cannot update a component (`X`) while rendering a different component
//   (`I18nProvider`)."
initI18n();

export function I18nProvider({
  language,
  enabled = true,
  children,
}: {
  language: AppLanguage | string;
  enabled?: boolean;
  children: React.ReactNode;
}) {
  const nextLang = normalizeLanguage(language);
  const [readyLanguage, setReadyLanguage] = useState<AppLanguage | null>(() =>
    enabled &&
    i18n.language === nextLang &&
    i18n.hasResourceBundle(nextLang, "app")
      ? nextLang
      : null,
  );
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    if (!enabled) return () => undefined;
    setLoadFailed(false);
    void ensureLanguage(nextLang).then(async () => {
      if (cancelled) return;
      if (i18n.language !== nextLang) {
        await i18n.changeLanguage(nextLang);
      }
      if (cancelled) return;
      // Keep <html lang="..."> in sync for accessibility & Intl defaults.
      document.documentElement.lang = nextLang;
      setReadyLanguage(nextLang);
    }).catch(() => {
      if (!cancelled) setLoadFailed(true);
    });
    return () => {
      cancelled = true;
    };
  }, [enabled, nextLang, attempt]);

  // Keep an already mounted workspace alive while a different locale loads.
  // The old blank placeholder removed drafts, players and in-memory views.
  if (readyLanguage === null) {
    return (
      <div
        role={loadFailed ? "alert" : "status"}
        aria-busy={!loadFailed}
        className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-[var(--background)] text-[var(--foreground)]"
      >
        <span className="text-lg font-semibold">DeepSteam</span>
        <p>{nextLang === "zh"
          ? (loadFailed ? "界面加载失败，请重试。" : "正在加载工作区…")
          : (loadFailed ? "The interface could not load. Please retry." : "Loading your workspace...")}</p>
        {loadFailed && (
          <button type="button" className="rounded-lg border border-[var(--border)] px-4 py-2" onClick={() => setAttempt(value => value + 1)}>
            {nextLang === "zh" ? "重试" : "Retry"}
          </button>
        )}
      </div>
    );
  }
  return children;
}
