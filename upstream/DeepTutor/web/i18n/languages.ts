/** Public builds default to English; the standalone release explicitly selects Chinese. */
export const DEFAULT_APP_LANGUAGE: "en" | "zh" =
  process.env.NEXT_PUBLIC_DEEPSTEAM_DEFAULT_LANGUAGE === "zh" ? "zh" : "en";

export const APP_LANGUAGES = [
  { code: "en", labelKey: "language.english" },
  { code: "zh", labelKey: "language.chinese" },
] as const;

/** Legacy wire values remain type-compatible when older settings are imported. */
export type AppLanguage = "en" | "zh" | "fr" | "de" | "uk" | "pl";

const SUPPORTED_CODES: ReadonlySet<string> = new Set(
  APP_LANGUAGES.map(({ code }) => code),
);

export function isAppLanguage(value: unknown): value is AppLanguage {
  return typeof value === "string" && SUPPORTED_CODES.has(value);
}

export function normalizeLanguage(value: unknown): AppLanguage {
  if (typeof value !== "string") return DEFAULT_APP_LANGUAGE;
  const code = value.trim().toLowerCase().replaceAll("_", "-");
  if (code === "chinese" || code === "cn" || code === "zh" || code.startsWith("zh-")) return "zh";
  if (code === "english" || code === "en" || code.startsWith("en-")) return "en";
  return DEFAULT_APP_LANGUAGE;
}
