/** Competition integration addition: explicit request-scoped BYOK settings.
 * These values are never added to job input, classroom data or global env.
 */
import type { NextRequest } from 'next/server';
import type { TTSModelConfig } from '@/lib/audio/types';
import { validateClientBaseUrl } from '@/lib/server/ssrf-guard';
import { DEEPSTEAM_SHARED_PROVIDER, parseDeepSteamSelection, type DeepSteamModelSelection, type DeepSteamModelSnapshot } from '@/lib/config/deepsteam-connection';
import { getDeepSteamExecution, type DeepSteamExecution } from '@/lib/server/deepsteam-connection';

export interface ContestProviderOptions {
  modelConfig?: {
    modelString: string;
    apiKey?: string;
    baseUrl?: string;
    providerType?: string;
    llmSelection?: DeepSteamModelSelection | null;
    modelSnapshot?: DeepSteamModelSnapshot;
    deepsteamExecution?: DeepSteamExecution;
  };
  ttsConfig?: Pick<TTSModelConfig, 'providerId' | 'modelId' | 'apiKey' | 'baseUrl' | 'voice'>;
}

export async function contestProviderFromHeaders(
  req: NextRequest,
): Promise<ContestProviderOptions> {
  const read = (name: string) => {
    const value = req.headers.get(name) || undefined;
    if (value && (value.length > 8192 || /[\r\n]/.test(value))) {
      throw new Error('Invalid provider configuration');
    }
    return value;
  };
  const modelString = read('x-model');
  let modelConfig: ContestProviderOptions['modelConfig'] = modelString
    ? {
        modelString,
        apiKey: read('x-api-key'),
        baseUrl: read('x-base-url'),
        providerType: read('x-provider-type'),
      }
    : undefined;
  const ttsProvider = read('x-contest-tts-provider');
  let ttsConfig: ContestProviderOptions['ttsConfig'];
  // One-shot generation follows the same shared resolver as native scene
  // generation and feedback. Keep narration independent of the language model.
  if (modelString?.startsWith(`${DEEPSTEAM_SHARED_PROVIDER}:`) ||
      (!modelString && process.env.DEFAULT_MODEL?.startsWith(`${DEEPSTEAM_SHARED_PROVIDER}:`))) {
    const llmSelection = parseDeepSteamSelection(req.headers.get('x-deepsteam-model-selection'));
    const rawSnapshot = read('x-deepsteam-model-snapshot');
    const modelSnapshot: DeepSteamModelSnapshot | undefined = rawSnapshot ? JSON.parse(rawSnapshot) : undefined;
    if (modelSnapshot && (!modelSnapshot.selection || !modelSnapshot.resolved_model)) {
      throw new Error('Invalid saved model snapshot');
    }
    const execution = await getDeepSteamExecution({ llmSelection, modelSnapshot,
      executionId: read('x-deepsteam-execution-id') });
    modelConfig = { ...modelConfig, modelString: modelString || `${DEEPSTEAM_SHARED_PROVIDER}:current`,
      llmSelection, modelSnapshot: execution.model_snapshot, deepsteamExecution: execution };
    const { narration } = execution;
    if (!ttsProvider && narration?.enabled && ['windows-system-tts', 'openai-tts'].includes(narration.provider)) {
      ttsConfig = {
        providerId: narration.provider as 'windows-system-tts' | 'openai-tts',
        modelId: narration.model, voice: narration.voice,
        ...(narration.provider === 'openai-tts' ? { apiKey: narration.api_key, baseUrl: narration.base_url } : {}),
      };
    }
  }
  if (ttsProvider) {
    if (ttsProvider !== 'openai-tts' && ttsProvider !== 'windows-system-tts')
      throw new Error('Unsupported portal TTS provider');
    if (ttsProvider === 'windows-system-tts') {
      // Native adapter accepts a voice choice, never a caller executable,
      // endpoint, credential, or hidden cloud fallback.
      ttsConfig = {
        providerId: 'windows-system-tts',
        modelId: 'system-speech',
        voice: read('x-contest-tts-voice') || 'auto-en',
      };
      return { modelConfig, ttsConfig };
    }
    const baseUrl = read('x-contest-tts-base-url');
    if (baseUrl) {
      const error = await validateClientBaseUrl(baseUrl);
      if (error) throw new Error(error);
    }
    ttsConfig = {
      providerId: 'openai-tts',
      modelId: read('x-contest-tts-model') || 'tts-1',
      voice: read('x-contest-tts-voice') || 'alloy',
      apiKey: read('x-contest-tts-api-key'),
      baseUrl,
    };
  }
  return { modelConfig, ttsConfig };
}

export function redactContestSecrets(value: string, options: ContestProviderOptions): string {
  let result = value;
  for (const secret of [options.modelConfig?.apiKey, options.ttsConfig?.apiKey]) {
    if (secret) result = result.split(secret).join('[REDACTED]');
  }
  return result;
}
