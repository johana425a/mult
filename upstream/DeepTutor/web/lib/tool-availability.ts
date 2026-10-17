import type { AppLanguage } from "@/i18n/languages";

export type ToolAvailabilityLanguage = AppLanguage;

export type ToolAvailabilityCopy = {
  badge: string;
  detail: string;
  href?: string;
};

export function toolEffectiveEnabled(
  savedEnabled: boolean,
  available: boolean,
  comingSoon: boolean,
): boolean {
  return savedEnabled && available && !comingSoon;
}

export function toolAvailabilityCopy(
  reason: string | null | undefined,
  language: ToolAvailabilityLanguage,
): ToolAvailabilityCopy {
  if (reason === "search_provider_not_configured") {
    return language === "zh"
      ? {
          badge: "Not configured",
          detail:
            "Choose a provider in Search settings first. DuckDuckGo needs no API key.",
          href: "/settings#search",
        }
      : {
          badge: "Not configured",
          detail:
            "Choose a provider in Search settings first. DuckDuckGo needs no API key.",
          href: "/settings#search",
        };
  }
  if (reason === "search_credentials_missing") {
    return language === "zh"
      ? {
          badge: "Credentials missing",
          detail:
            "The selected search provider needs credentials. Check Search settings.",
          href: "/settings#search",
        }
      : {
          badge: "Credentials missing",
          detail:
            "The selected search provider needs credentials. Check Search settings.",
          href: "/settings#search",
        };
  }
  return language === "zh"
    ? {
        badge: "Unavailable",
        detail: "This tool's runtime service is unavailable.",
      }
    : {
        badge: "Unavailable",
        detail: "This tool's runtime service is unavailable.",
      };
}
