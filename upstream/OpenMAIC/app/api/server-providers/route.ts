import {
  getServerProviders,
  getServerTTSProviders,
  getServerASRProviders,
  getServerPDFProviders,
  getServerImageProviders,
  getServerVideoProviders,
  getServerWebSearchProviders,
  getParallelSceneConcurrency,
} from '@/lib/server/provider-config';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { createLogger } from '@/lib/logger';
import { DEEPSTEAM_SHARED_PROVIDER } from '@/lib/config/deepsteam-connection';
import { getDeepSteamExecution, publicDeepSteamConnection } from '@/lib/server/deepsteam-connection';

const log = createLogger('ServerProviders');

export async function GET() {
  try {
    let deepsteam: Record<string, unknown>;
    try {
      deepsteam = publicDeepSteamConnection(await getDeepSteamExecution());
    } catch {
      deepsteam = { error: 'The active DeepSteam connection is unavailable. Revalidate it in Connect model.' };
    }
    const connection = deepsteam.connection as { model?: string } | undefined;
    return apiSuccess({
      providers: {
        ...getServerProviders(),
        // Stable public selection even when disconnected: resolution fails
        // accurately instead of switching silently to a different model.
        [DEEPSTEAM_SHARED_PROVIDER]: { models: [connection?.model || 'current'] },
      },
      deepsteam,
      tts: getServerTTSProviders(),
      asr: getServerASRProviders(),
      pdf: getServerPDFProviders(),
      image: getServerImageProviders(),
      video: getServerVideoProviders(),
      webSearch: getServerWebSearchProviders(),
      generation: {
        parallelSceneConcurrency: getParallelSceneConcurrency(),
      },
    });
  } catch (error) {
    log.error('Error fetching server providers:', error);
    return apiError(
      'INTERNAL_ERROR',
      500,
      error instanceof Error ? error.message : 'Unknown error',
    );
  }
}
