/**
 * Promoted provider links with regional destinations.
 *
 * Used by provider lists and configuration panels: promoted providers include an
 * API key acquisition link. A locale selects the regional destination;
 * both destinations remain directly accessible in the panel.
 */
export interface RegionalLinks {
  domestic: string;
  international: string;
}

export const PROVIDER_SIGNUP_LINKS: Partial<Record<string, RegionalLinks>> = {
  kimi: {
    domestic: 'https://platform.kimi.com?aff=openmaic',
    international: 'https://platform.kimi.ai?aff=openmaic',
  },
};

/** The single list link follows locale routing; the panel displays both links. */
export function pickRegionalLink(links: RegionalLinks, locale: string): string {
  return locale.toLowerCase().startsWith('zh') ? links.domestic : links.international;
}

/** The promoted Model services provider is pinned first. */
export const PINNED_PROVIDER_ID = 'kimi';
