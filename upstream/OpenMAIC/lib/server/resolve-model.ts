/**
 * Shared model resolution utilities for API routes.
 *
 * Extracts the repeated parseModelString → resolveApiKey → resolveBaseUrl →
 * resolveProxy → getModel boilerplate into a single call.
 */

import type { NextRequest } from 'next/server';
import { getModel, getProvider, parseModelString, type ModelWithInfo } from '@/lib/ai/providers';
import type { ProviderType, ThinkingConfig } from '@/lib/types/provider';
import {
  isServerConfiguredProvider,
  resolveApiKey,
  resolveBaseUrl,
  resolveProxy,
} from '@/lib/server/provider-config';
import { validateClientBaseUrl, validateUrlForSSRF } from '@/lib/server/ssrf-guard';
import { fetchWithRedirectValidation } from '@/lib/server/fetch-with-redirect-validation';
import { clientBaseUrlLlmFetch } from '@/lib/server/llm-provider-fetch';
import {
  getStageRoute,
  getUserStageRoute,
  parseUserStageRoutes,
  type LlmStage,
  type UserStageRoute,
} from '@/lib/server/model-routes';
import { DEEPSTEAM_SHARED_PROVIDER, parseDeepSteamSelection, isRetiredBundledSelection, type DeepSteamModelSelection, type DeepSteamModelSnapshot, type DeepSteamResolvedModel } from '@/lib/config/deepsteam-connection';
import { getDeepSteamExecution, privateDeepSteamModelFetch, type DeepSteamExecution } from '@/lib/server/deepsteam-connection';
import { getDefaultThinkingConfig } from '@/lib/ai/thinking-config';

export interface ResolvedModel extends ModelWithInfo {
  resolvedModel?: DeepSteamResolvedModel;
  modelSnapshot?: DeepSteamModelSnapshot;
  /** Original model string (e.g. "openai/gpt-4o-mini") */
  modelString: string;
  /** Resolved provider ID (e.g. "openai", "ollama") */
  providerId: string;
  /** Resolved model ID (e.g. "gpt-4o-mini") */
  modelId: string;
  /** Effective API key after server-side fallback resolution */
  apiKey: string;
  /** Effective base URL after server/client resolution */
  baseUrl?: string;
  /** Optional per-request thinking configuration from the client. */
  thinkingConfig?: ThinkingConfig;
}

/**
 * Resolve a language model from explicit parameters.
 *
 * Use this when model config comes from the request body.
 */
export async function resolveModel(params: {
  llmSelection?: DeepSteamModelSelection | null;
  modelSnapshot?: DeepSteamModelSnapshot;
  deepsteamExecution?: DeepSteamExecution;
  modelString?: string;
  /**
   * Optional generation stage (a `callLLM` source label, e.g. 'scene-content').
   * When set and a route is configured via `MODEL_ROUTES`, the route wins for
   * this call — even over a client-sent `modelString` (x-model). Unrouted
   * stages fall back to `modelString` then `DEFAULT_MODEL`. See
   * lib/server/model-routes.ts.
   */
  stage?: LlmStage;
  /**
   * User-level per-stage routes (parsed from the `x-model-routes` header by
   * resolveModelFromHeaders/FromRequest). Precedence: operator MODEL_ROUTES >
   * these user routes > x-model > DEFAULT_MODEL. A user route carries its own
   * connection params (apiKey/baseUrl/providerType) for the routed provider;
   * server-managed providers still resolve credentials authoritatively.
   */
  userRoutes?: Record<string, UserStageRoute>;
  apiKey?: string;
  baseUrl?: string;
  providerType?: string;
  thinkingConfig?: ThinkingConfig;
}): Promise<ResolvedModel> {
  // Resolution order: env stage route > user stage route > x-model > DEFAULT_MODEL.
  // A configured stage route is the operator's deliberate per-stage choice and
  // wins even over a client-sent x-model (otherwise the browser UI, which always
  // sends its saved model, would shadow every route). User routes (the
  // user-facing Course model configuration per-stage selection) sit just below operator
  // routes and above the client's main-model x-model. Unrouted stages fall back
  // to the client x-model, then DEFAULT_MODEL. There is intentionally no hardcoded
  // model fallback — if nothing resolves we fail loud rather than silently pick a
  // vendor default.
  const envRoute = getStageRoute(params.stage);
  const userRoute = envRoute ? undefined : getUserStageRoute(params.userRoutes ?? {}, params.stage);
  const stageRoute: UserStageRoute | undefined = envRoute ?? userRoute;
  const stageModel = stageRoute?.model;
  const modelString = stageModel || params.modelString || process.env.DEFAULT_MODEL;
  if (!modelString) {
    throw new Error(
      'No model could be resolved. Configure DEFAULT_MODEL (and/or a MODEL_ROUTES entry for this stage), or send a model via x-model.',
    );
  }
  const { providerId, modelId } = parseModelString(modelString);

  if (isRetiredBundledSelection(providerId, modelId, stageRoute?.baseUrl ?? params.baseUrl)) {
    throw new Error('BUNDLED_MODEL_REMOVED: The bundled chat model has been removed. Select a classroom model to continue. Existing classrooms and original materials are retained.');
  }

  if (providerId === DEEPSTEAM_SHARED_PROVIDER) {
    // This branch covers classroom generation, scene calls, Pi/legacy chat,
    // feedback and all other users of this resolver. Client keys/URLs/types are
    // ignored; an expired login must fail instead of silently falling back to Qwen.
    const execution = params.deepsteamExecution ?? await getDeepSteamExecution({
      llmSelection: params.llmSelection, modelSnapshot: params.modelSnapshot });
    const connection = execution.connection;
    // Capacity belongs to the selected provider, never the opaque gateway ID
    // or the previous bundled model. The maximum output is a capability, not
    // the reserve requested for each ordinary classroom response.
    const positiveInteger = (value: unknown): number | undefined =>
      typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : undefined;
    const contextWindow = positiveInteger(execution.provider.context_window)
      ?? positiveInteger(connection.context_window);
    const outputCap = positiveInteger(execution.provider.max_output_tokens)
      ?? positiveInteger(connection.max_output_tokens);
    const result = getModel({
      providerId: 'custom-deepsteam-execution',
      modelId: execution.provider.model,
      apiKey: execution.provider.api_key || 'no-key',
      baseUrl: execution.provider.base_url,
      providerType: execution.provider.provider_type as ProviderType,
      fetchImpl: privateDeepSteamModelFetch(execution, fetchWithRedirectValidation),
    });
    return {
      ...result,
      resolvedModel: execution.resolved_model,
      modelSnapshot: execution.model_snapshot,
      modelInfo: {
        ...(result.modelInfo ?? {}),
        id: connection.model, name: connection.model,
        contextWindow,
        outputWindow: outputCap,
        capabilities: {
          ...result.modelInfo?.capabilities,
          // Catalog support is not proof that this connection accepts pixels.
          // This state belongs to the exact frozen provider configuration.
          vision: connection.vision?.verified === true,
        },
      },
      modelString: `${DEEPSTEAM_SHARED_PROVIDER}:${connection.model}`,
      providerId: DEEPSTEAM_SHARED_PROVIDER,
      modelId: connection.model,
      apiKey: execution.provider.api_key || 'no-key',
      baseUrl: execution.provider.base_url,
      thinkingConfig: stageModel ? stageRoute?.thinking : params.thinkingConfig,
    };
  }

  // When a stage route overrides the client's model, the client-sent connection
  // params (apiKey/baseUrl/providerType) belong to the client's *other* model
  // and must not bleed onto the routed provider — otherwise e.g. a routed
  // Anthropic model would be built with the client's OpenAI providerType/key.
  // A routed model resolves purely from server config, as if no x-model was sent
  // — except a *user* route, which supplies its own connection for the routed
  // provider (server-managed providers ignore it regardless).
  const routed = Boolean(stageModel);
  const clientApiKey = routed ? userRoute?.apiKey : params.apiKey;
  const clientProviderType = routed ? userRoute?.providerType : params.providerType;
  const clientBaseUrlParam = routed ? userRoute?.baseUrl : params.baseUrl;

  // Server-managed providers are admin-owned: the operator's key and base URL
  // are authoritative and any client-sent override is ignored. Origin URL
  // validation therefore applies only to unmanaged providers, where the base
  // URL really is client-supplied. (Server-configured URLs are trusted by the
  // operator.) Every provider fetch still runs through a transport that
  // re-validates redirect hops: no upstream can be assumed to redirect only to
  // public targets, so the hop target is checked regardless of who chose the
  // origin.
  const managed = isServerConfiguredProvider('providers', providerId);
  const registeredProviderType = getProvider(providerId)?.type;
  if (
    clientProviderType &&
    registeredProviderType &&
    clientProviderType !== registeredProviderType
  ) {
    throw new Error(
      `Provider type mismatch for ${providerId}: expected ${registeredProviderType}, received ${clientProviderType}.`,
    );
  }
  const effectiveProviderType = (clientProviderType || registeredProviderType) as
    | ProviderType
    | undefined;
  if (effectiveProviderType === 'bedrock' && (providerId !== 'bedrock' || !managed)) {
    throw new Error('Amazon Bedrock must be enabled by the server operator before it can be used.');
  }
  const clientBaseUrl = managed ? undefined : clientBaseUrlParam || undefined;
  // An unmanaged provider's endpoint is the caller's choice whenever the caller
  // picked the model (x-model or a user route) or sent a base URL: either the
  // client-supplied URL or the provider's catalog default (e.g. a localhost
  // Ollama). Only a model the operator selected (MODEL_ROUTES or
  // DEFAULT_MODEL) with no client base URL resolves purely from server config.
  const operatorSelected = Boolean(envRoute) || (!userRoute && !params.modelString);
  const clientEndpoint = !managed && (Boolean(clientBaseUrl) || !operatorSelected);
  const endpointUrl = clientBaseUrl ?? getProvider(providerId)?.defaultBaseUrl;
  if (clientEndpoint && endpointUrl) {
    const ssrfError = clientBaseUrl
      ? await validateClientBaseUrl(clientBaseUrl)
      : await validateUrlForSSRF(endpointUrl);
    if (ssrfError) {
      throw new Error(ssrfError);
    }
  }

  const apiKey = resolveApiKey(providerId, clientApiKey || '');
  const baseUrl = resolveBaseUrl(providerId, clientBaseUrl);
  const proxy = resolveProxy(providerId);
  const { model, modelInfo } = getModel({
    providerId,
    modelId,
    apiKey,
    baseUrl,
    proxy,
    providerType: clientProviderType as ProviderType | undefined,
    // A caller-chosen endpoint is pinned and refuses redirects (see
    // lib/server/llm-provider-fetch.ts). Operator-configured endpoints keep the
    // transport that re-validates every redirect hop.
    fetchImpl: clientEndpoint ? clientBaseUrlLlmFetch : fetchWithRedirectValidation,
  });

  // Thinking arbitration mirrors model routing — the route carries a full
  // ThinkingConfig (mode/effort/level/enabled/budgetTokens/…) which callLLM
  // normalizes against the model's capability:
  //  - routed + thinking set → the route's thinking wins (over client thinking).
  //  - routed + no thinking  → routed model uses its own default; client thinking
  //    is dropped (it belonged to the client's other model).
  //  - unrouted              → honor the client's thinking config.
  const requestedThinking: ThinkingConfig | undefined = routed
    ? stageRoute?.thinking
    : params.thinkingConfig;
  let defaultThinking = process.env.LLM_THINKING_DISABLED === 'true'
    ? undefined : getDefaultThinkingConfig(modelInfo?.capabilities?.thinking);
  if (defaultThinking?.budgetTokens && defaultThinking.budgetTokens > 0 && modelInfo?.outputWindow) {
    // Manual reasoning budgets share the model's actual output allowance.
    // The API requires space after thinking; preserve every explicit budget.
    const budget = Math.min(defaultThinking.budgetTokens, modelInfo.outputWindow - 1);
    const minimum = modelInfo.capabilities?.thinking?.budgetRange?.min ?? 0;
    if (budget < minimum) throw new Error('SOURCE_CONTEXT_LIMIT: the configured model output ceiling cannot support its minimum reasoning budget. Correct the model output limit or explicitly choose a supported reasoning setting.');
    defaultThinking = { ...defaultThinking, budgetTokens: budget };
  }
  const thinkingConfig = requestedThinking ?? defaultThinking;

  return {
    model,
    modelInfo,
    modelString,
    providerId,
    modelId,
    apiKey,
    baseUrl,
    thinkingConfig,
  };
}

function getThinkingConfigFromBody(body: unknown): ThinkingConfig | undefined {
  if (!body || typeof body !== 'object') return undefined;
  const record = body as { thinkingConfig?: unknown; thinking?: unknown };
  const config = record.thinkingConfig ?? record.thinking;
  return config && typeof config === 'object' ? (config as ThinkingConfig) : undefined;
}

/**
 * Resolve a language model from standard request headers.
 *
 * Reads: x-model, x-api-key, x-base-url, x-provider-type, x-model-routes
 * Note: requiresApiKey is derived server-side from the provider registry,
 * never from client headers, to prevent auth bypass.
 */
export async function resolveModelFromHeaders(
  req: NextRequest,
  stage?: LlmStage,
  thinkingConfig?: ThinkingConfig,
): Promise<ResolvedModel> {
  return resolveModel({
    llmSelection: parseDeepSteamSelection(req.headers.get('x-deepsteam-model-selection')),
    modelString: req.headers.get('x-model') || undefined,
    stage,
    userRoutes: parseUserStageRoutes(req.headers.get('x-model-routes')),
    apiKey: req.headers.get('x-api-key') || undefined,
    baseUrl: req.headers.get('x-base-url') || undefined,
    providerType: req.headers.get('x-provider-type') || undefined,
    thinkingConfig,
  });
}

/**
 * Resolve a language model from standard request headers plus body fields.
 *
 * Reads model credentials from headers and per-request thinking config from
 * the JSON body field `thinkingConfig` (or legacy/eval field `thinking`).
 */
export async function resolveModelFromRequest(
  req: NextRequest,
  body: unknown,
  stage?: LlmStage,
): Promise<ResolvedModel> {
  // Pass the client's body thinking into resolveModel so the single arbiter
  // there decides (a routed stage may override or drop it). See resolveModel.
  return resolveModelFromHeaders(req, stage, getThinkingConfigFromBody(body));
}
