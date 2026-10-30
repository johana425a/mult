import i18n, { type Resource } from "i18next";
import { initReactI18next } from "react-i18next";

import enApp from "@/locales/en/app.json";
import zhApp from "@/locales/zh/app.json";
import enStandalone from "@/locales/en/standalone.json";
import zhStandalone from "@/locales/zh/standalone.json";
import { brandAppCatalog } from "@/lib/product-brand";
import { normalizeLanguage, type AppLanguage } from "./languages";

export { APP_LANGUAGES, isAppLanguage, normalizeLanguage } from "./languages";
export type { AppLanguage } from "./languages";

let _initialized = false;

export function initI18n(language?: unknown) {
  if (_initialized) return i18n;

  const resources: Resource = {
    en: { app: brandAppCatalog(enApp), deepsteam: enStandalone },
    zh: { app: brandAppCatalog(zhApp), deepsteam: zhStandalone },
  };

  i18n.use(initReactI18next).init({
    resources,
    lng: normalizeLanguage(language),
    fallbackLng: "en",
    // Use a single default namespace to keep lookups simple.
    // We intentionally keep keySeparator disabled so keys like "Generating..." remain valid.
    defaultNS: "app",
    ns: ["app", "deepsteam"],
    keySeparator: false,
    interpolation: {
      escapeValue: false,
    },
    returnEmptyString: false,
    returnNull: false,
  });

  _initialized = true;
  return i18n;
}

export async function ensureLanguage(language: AppLanguage) {
  const normalized = normalizeLanguage(language);
  if (i18n.hasResourceBundle(normalized, "app") && i18n.hasResourceBundle(normalized, "deepsteam")) return;
  i18n.addResourceBundle(normalized, "app", brandAppCatalog(normalized === "zh" ? zhApp : enApp), true, true);
  i18n.addResourceBundle(normalized, "deepsteam", normalized === "zh" ? zhStandalone : enStandalone, true, true);
}
