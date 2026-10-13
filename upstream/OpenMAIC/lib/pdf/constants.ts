/**
 * PDF Provider Constants
 * Separated from pdf-providers.ts to avoid importing sharp in client components
 */

import type { PDFProviderId, PDFProviderConfig } from './types';

export const MINERU_CLOUD_DEFAULT_BASE = 'https://mineru.net/api/v4';
export const ALIDOCMIND_DEFAULT_BASE = 'https://docmind-api.cn-hangzhou.aliyuncs.com';

/**
 * PDF Provider Registry
 */
export const PDF_PROVIDERS: Record<PDFProviderId, PDFProviderConfig> = {
  'deepsteam-local': {
    id: 'deepsteam-local', name: 'DeepSteam local reader (ready to use)', requiresApiKey: false,
    features: ['text', 'images', 'metadata', 'ocr'],
  },
  unpdf: {
    id: 'unpdf',
    name: 'unpdf',
    requiresApiKey: false,
    icon: '/logos/unpdf.svg',
    features: ['text', 'images', 'metadata'],
  },

  mineru: {
    id: 'mineru',
    name: 'MinerU',
    requiresApiKey: false,
    icon: '/logos/mineru.png',
    features: ['text', 'images', 'tables', 'formulas', 'layout-analysis'],
  },

  'mineru-cloud': {
    id: 'mineru-cloud',
    name: 'MinerU (Cloud)',
    requiresApiKey: true,
    icon: '/logos/mineru.png',
    features: ['text', 'images', 'tables', 'formulas', 'layout-analysis'],
  },

  alidocmind: {
    id: 'alidocmind',
    name: 'AliDocMind',
    requiresApiKey: true,
    icon: '/logos/aliyun.svg',
    features: ['text', 'images', 'tables', 'formulas', 'layout-analysis', 'ocr'],
  },
};

/**
 * DeepSteam parses documents on the user's computer with the bundled local
 * MinerU VLM. Hosted MinerU (mineru.net) and remote MinerU endpoints are not
 * offered, never auto-selected and rejected by the server routes.
 */
export const DISABLED_REMOTE_PDF_PROVIDERS: ReadonlySet<PDFProviderId> = new Set<PDFProviderId>([
  'mineru',
  'mineru-cloud',
]);

export function isDisabledRemotePdfProvider(providerId: string | undefined | null): boolean {
  return !!providerId && DISABLED_REMOTE_PDF_PROVIDERS.has(providerId as PDFProviderId);
}

/** PDF providers that may be shown and selected in DeepSteam. */
export function selectablePdfProviders(): PDFProviderConfig[] {
  return Object.values(PDF_PROVIDERS).filter((provider) => !isDisabledRemotePdfProvider(provider.id));
}

/**
 * Get all available PDF providers
 */
export function getAllPDFProviders(): PDFProviderConfig[] {
  return selectablePdfProviders();
}

/**
 * Get PDF provider by ID
 */
export function getPDFProvider(providerId: PDFProviderId): PDFProviderConfig | undefined {
  return PDF_PROVIDERS[providerId];
}
