/** DeepSteam integration. Installation-owned credentials stay in the server process.
 * A browser selects a stable shared provider; it never receives the gateway guard,
 * account token, private API endpoint, or internal route model id. */
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import {
  type DeepSteamConnection,
  type DeepSteamNarration,
  type DeepSteamModelSelection, type DeepSteamModelSnapshot, type DeepSteamResolvedModel,
} from '@/lib/config/deepsteam-connection';

interface ExecutionProvider {
  base_url: string;
  model: string;
  api_key: string;
  provider_type: string;
  context_window?: number;
  context_window_source?: string;
  max_output_tokens?: number;
}
export interface DeepSteamExecution {
  provider: ExecutionProvider;
  connection: DeepSteamConnection;
  narration: DeepSteamNarration & { base_url?: string; api_key?: string };
  execution_id?: string;
  model_snapshot?: DeepSteamModelSnapshot;
  resolved_model?: DeepSteamResolvedModel;
}

export class DeepSteamConnectionError extends Error {
  constructor(readonly code: 'connection_unavailable' | 'connection_service_unavailable') {
    super(code === 'connection_unavailable'
      ? 'The active DeepSteam model connection is unavailable. Revalidate or select a model in Connect model.'
      : 'The DeepSteam connection service is temporarily unavailable. Check that desktop services are running and retry.');
    this.name = 'DeepSteamConnectionError';
  }
}

/** Preserve actual HTTP status/reason while preventing provider error replies
 * from reflecting the private key or internal route back into UI/logs. Successful
 * streams are passed through without buffering or changing model output. */
export function privateDeepSteamModelFetch(execution: DeepSteamExecution, transport: typeof fetch): typeof fetch {
  const redact = (text: string): string => {
    for (const secret of [execution.provider.api_key, execution.provider.base_url]) {
      if (secret) text = text.split(secret).join('[Active model connection]');
    }
    if (execution.provider.model !== execution.connection.model) {
      text = text.split(execution.provider.model).join(execution.connection.model);
    }
    return text;
  };
  return async (input, init) => {
    let response: Response;
    const send = () => {
      if (!execution.execution_id || typeof init?.body !== 'string') return transport(input, init);
      const body = JSON.parse(init.body);
      const headers = new Headers(init.headers);
      headers.set('authorization', `Bearer ${execution.provider.api_key}`);
      body.model = execution.provider.model;
      return transport(input, { ...init, headers, body: JSON.stringify(body) });
    };
    try {
      response = await send();
      if (response.status === 409 && execution.model_snapshot) {
        const failure = await response.clone().json().catch(() => null);
        if (failure?.detail?.code === 'model_execution_expired') {
          const renewed = await getDeepSteamExecution({ modelSnapshot: execution.model_snapshot });
          Object.assign(execution, renewed);
          response = await send();
        }
      }
    }
    catch (error) {
      if (error instanceof Error && error.name === 'AbortError') throw error;
      throw new Error(redact(error instanceof Error ? error.message : 'The model network connection failed. Please retry.'));
    }
    if (response.ok) return response;
    const text = redact(await response.text());
    const headers = new Headers(response.headers);
    for (const key of ['authorization', 'api-key', 'x-api-key', 'x-goog-api-key', 'content-length']) headers.delete(key);
    return new Response(text, { status: response.status, statusText: response.statusText, headers });
  };
}

const safeString = (value: unknown): string => typeof value === 'string' ? value : '';
const positiveInteger = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : undefined;

/** Construct a strict public whitelist rather than forwarding the portal payload. */
export function publicDeepSteamConnection(value: DeepSteamExecution): {
  connection: DeepSteamConnection;
  narration: DeepSteamNarration;
} {
  const c = value.connection;
  const n = value.narration;
  return {
    connection: {
      selection: safeString(c.selection), provider: safeString(c.provider),
      provider_label: safeString(c.provider_label), model: safeString(c.model),
      route: safeString(c.route), managed: c.managed === true,
      context_window: positiveInteger(c.context_window),
      max_output_tokens: positiveInteger(c.max_output_tokens),
      context_window_source: safeString(c.context_window_source) || undefined,
      text: { verified: c.text?.verified === true }, vision: {
        verified: c.vision?.verified === true, configured: c.vision?.configured === true,
      },
      targets: { learning: safeString(c.targets?.learning), classroom: safeString(c.targets?.classroom) },
    },
    narration: {
      enabled: n?.enabled === true, mode: safeString(n?.mode), provider: safeString(n?.provider),
      model: safeString(n?.model), voice: safeString(n?.voice),
    },
  };
}

export async function getDeepSteamExecution(options: {
  llmSelection?: DeepSteamModelSelection | null; modelSnapshot?: DeepSteamModelSnapshot; executionId?: string;
} = {}): Promise<DeepSteamExecution> {
  const tokenPath = process.env.DEEPSTEAM_HARNESS_TOKEN_FILE ||
    (process.env.DEEPSTEAM_STATE_ROOT
      ? path.join(process.env.DEEPSTEAM_STATE_ROOT, 'runtime', 'harness-state', 'control-token')
      : undefined);
  if (!tokenPath) throw new DeepSteamConnectionError('connection_service_unavailable');
  try {
    const token = (await readFile(tokenPath, 'utf8')).trim();
    if (!token || token.length > 8192 || /[\r\n]/.test(token)) {
      throw new DeepSteamConnectionError('connection_service_unavailable');
    }
    // The address is an installation-owned service, never chosen by browser input.
    const res = await fetch('http://localhost:3791/api/harness/internal/provider', {
      method: 'POST',
      headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
      body: JSON.stringify({
        ...(options.llmSelection !== undefined ? { llm_selection: options.llmSelection } : {}),
        ...(options.modelSnapshot ? { model_snapshot: options.modelSnapshot } : {}),
        ...(options.executionId ? { execution_id: options.executionId } : {}),
      }),
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) throw new DeepSteamConnectionError(res.status === 409
      ? 'connection_unavailable' : 'connection_service_unavailable');
    const body = await res.json() as DeepSteamExecution;
    if (!body.provider || !safeString(body.provider.model) || !safeString(body.provider.base_url)
      || typeof body.provider.api_key !== 'string' || !body.connection || !safeString(body.connection.model)) {
      throw new DeepSteamConnectionError('connection_unavailable');
    }
    // Validate protocol while permitting user-configured remote or local providers.
    const url = new URL(body.provider.base_url);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
      throw new DeepSteamConnectionError('connection_unavailable');
    }
    return body;
  } catch (error) {
    if (error instanceof DeepSteamConnectionError) throw error;
    // Never expose raw transport errors, response bodies, or credential paths.
    throw new DeepSteamConnectionError('connection_service_unavailable');
  }
}
