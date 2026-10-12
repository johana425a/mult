import i18n, { type Resource } from "i18next";
import { initReactI18next } from "react-i18next";

import enApp from "@/locales/en/app.json";
import { brandAppCatalog } from "@/lib/product-brand";
import { normalizeLanguage, type AppLanguage } from "./languages";

export { APP_LANGUAGES, isAppLanguage, normalizeLanguage } from "./languages";
export type { AppLanguage } from "./languages";

let _initialized = false;

export function initI18n(language?: unknown) {
  if (_initialized) return i18n;

  const resources: Resource = {
    en: { app: brandAppCatalog(enApp) },
  };

  i18n.use(initReactI18next).init({
    resources,
    lng: normalizeLanguage(language),
    fallbackLng: "en",
    // Use a single default namespace to keep lookups simple.
    // We intentionally keep keySeparator disabled so keys like "Generating..." remain valid.
    defaultNS: "app",
    ns: ["app"],
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
  if (i18n.hasResourceBundle(normalized, "app")) return;
  i18n.addResourceBundle(normalized, "app", brandAppCatalog(enApp), true, true);
}
