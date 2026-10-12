/** DeepSteam integration: public metadata only; never include connection secrets. */
export const DEEPSTEAM_SHARED_PROVIDER = 'custom-deepsteam-shared' as const;
export const DEEPSTEAM_CURRENT_MODEL = 'current';

/** Recognize the former product-owned tuple, not another model a user added
 * to the old profile or a manually configured local server. */
export function isRetiredBundledSelection(providerId: string, modelId: string, baseUrl?: string): boolean {
  if (providerId !== 'custom-deepsteam-local' || modelId !== 'qwen3.5-4b-local') return false;
  if (!baseUrl) return true;
  try {
    const url = new URL(baseUrl);
    return url.protocol === 'http:' && ['localhost', '[::1]'].includes(url.hostname)
      && url.port === '3795' && url.pathname.replace(/\/+$/, '') === '/v1'
      && !url.username && !url.password && !url.search && !url.hash;
  } catch { return false; }
}

export interface DeepSteamModelSelection { profile_id: string; model_id: string; reasoning_effort?: string }
export interface DeepSteamResolvedModel {
  provider: string; provider_label: string; model: string; model_name: string;
  selection_source: 'default' | 'override'; reasoning_effort?: string | null;
  configuration_revision?: string; context_window?: number; context_window_source?: string;
  capabilities?: { tools?: boolean; vision?: boolean; json_output?: boolean };
}
export interface DeepSteamModelSnapshot { selection: DeepSteamModelSelection; resolved_model: DeepSteamResolvedModel }

export function parseDeepSteamSelection(raw: string | null): DeepSteamModelSelection | null | undefined {
  if (raw === null) return undefined;
  if (raw.length > 2048) throw new Error('Invalid model selection');
  const value = JSON.parse(raw);
  if (value === null) return null;
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).some(key => !['profile_id', 'model_id', 'reasoning_effort'].includes(key))
    || typeof value.profile_id !== 'string' || !value.profile_id
    || typeof value.model_id !== 'string' || !value.model_id
    || (value.reasoning_effort !== undefined && typeof value.reasoning_effort !== 'string')) throw new Error('Invalid model selection');
  return value;
}

export interface DeepSteamConnection {
  selection: string;
  provider: string;
  provider_label: string;
  model: string;
  route: string;
  managed: boolean;
  resolved_model?: DeepSteamResolvedModel;
  context_window?: number;
  context_window_source?: string;
  max_output_tokens?: number;
  text: { verified: boolean };
  vision: { verified: boolean; configured?: boolean };
  targets?: { learning?: string; classroom?: string };
}

export interface DeepSteamNarration {
  enabled: boolean;
  mode: string;
  provider: string;
  model: string;
  voice: string;
}

/** Only a shared selection follows the default. A retired bundled model must
 * remain unavailable until the user explicitly chooses a replacement. */
export function followsDeepSteamConnection(providerId: string): boolean {
  return !providerId || providerId === DEEPSTEAM_SHARED_PROVIDER;
}

export function deepsteamConnectionLabel(connection: DeepSteamConnection): string {
  const route = connection.route === 'account' ? 'Account login' : connection.route === 'apikey' ? 'API connection' : 'Active connection';
  return `${connection.provider_label} · ${connection.model} · ${route}`;
}
