/** The public interface uses English independently of the operating system language. */
export const APP_LANGUAGES = [
  { code: "en", labelKey: "language.english" },
] as const;

/** Legacy wire values remain type-compatible when older settings are imported. */
export type AppLanguage = "en" | "zh" | "fr" | "de" | "uk" | "pl";

const SUPPORTED_CODES: ReadonlySet<string> = new Set(
  APP_LANGUAGES.map(({ code }) => code),
);

export function isAppLanguage(value: unknown): value is AppLanguage {
  return typeof value === "string" && SUPPORTED_CODES.has(value);
}

export function normalizeLanguage(_value: unknown): AppLanguage {
  return "en";
}
