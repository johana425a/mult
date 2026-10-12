import type { ProviderId } from '@/lib/types/provider';
import type { ImageProviderId, VideoProviderId } from '@/lib/media/types';
import type { TTSProviderId } from '@/lib/audio/types';
import type { WebSearchProviderId } from '@/lib/web-search/types';
import { MODALITY_ORDER, TOKEN_PLAN_PRESETS, tokenPlanSeedFingerprint } from './token-plan-presets';
import type {
  TokenPlanModality,
  TokenPlanModalityTarget,
  TokenPlanPreset,
} from './token-plan-presets';
import { getCatalogThinkingCapability } from '@/lib/ai/model-metadata';
import { PROVIDERS } from '@/lib/ai/providers';
import { findModelById } from '@/lib/ai/model-aliases';
import type { ModelInfo } from '@/lib/types/provider';

/**
 * The subset of settings-store setters needed to fill a token plan across
 * modalities. Injected so the orchestration is a pure, testable function.
 * Signatures mirror the store actions so they can be passed verbatim.
 */
export interface TokenPlanActions {
  setProviderConfig: (id: ProviderId, config: Record<string, unknown>) => void;
  setImageProviderConfig: (
    id: ImageProviderId,
    config: Partial<{
      apiKey: string;
      baseUrl: string;
      enabled: boolean;
      customModels: Array<{ id: string; name: string }>;
      replaceBuiltInModels: boolean;
    }>,
  ) => void;
  setVideoProviderConfig: (
    id: VideoProviderId,
    config: Partial<{
      apiKey: string;
      baseUrl: string;
      enabled: boolean;
      customModels: Array<{ id: string; name: string }>;
      replaceBuiltInModels: boolean;
    }>,
  ) => void;
  setTTSProviderConfig: (
    id: TTSProviderId,
    config: Partial<{
      apiKey: string;
      baseUrl: string;
      enabled: boolean;
      modelId: string;
      customModels: Array<{ id: string; name: string }>;
    }>,
  ) => void;
  setWebSearchProviderConfig: (
    id: WebSearchProviderId,
    config: Partial<{ apiKey: string; baseUrl: string; enabled: boolean }>,
  ) => void;
  /**
   * Optional model-selection setters. When provided, applying an image/video
   * modality that declares `defaultModels` also makes that provider+model the
   * active selection, so the plan's model is used out of the box. Optional so
   * `applyTokenPlan` stays usable in tests/headless callers without them.
   */
  setImageProvider?: (id: ImageProviderId) => void;
  setImageModelId?: (modelId: string) => void;
  setVideoProvider?: (id: VideoProviderId) => void;
  setVideoModelId?: (modelId: string) => void;
  /**
   * Optional main-model + stage-route setters. LLM apply makes the plan's
   * `defaultModelId` (or first catalogue model) the mainline selection and
   * writes the preset's recommended per-stage routes (e.g. courseware /
   * interactive page models).
   */
  setModel?: (providerId: ProviderId, modelId: string) => void;
  setStageRoute?: (
    stage: string,
    route: { providerId: ProviderId; modelId: string } | null,
  ) => void;
  /** Optional active-selection switches for TTS / web search. */
  setTTSProvider?: (id: TTSProviderId) => void;
  setWebSearchProvider?: (id: WebSearchProviderId) => void;
  /** Current stage routes — used by removal to drop routes onto this plan. */
  getStageRoutes?: () => Record<string, { providerId: string }>;
  /**
   * Explicit enrollment bookkeeping. Plan apply can only be told apart from a
   * personal key on the same provider (minimax / tokendance / doubao are both
   * plan endpoints and ordinary direct providers) by recording that THIS plan
   * wrote the credentials. `null` un-enrolls (disconnect).
   */
  setTokenPlanEnrolled?: (presetId: string, llmProviderId: string | null) => void;
  /**
   * Authorization bookkeeping. Connecting (apply) clears stale disabled flags; reconnecting
   * reauthorizes the plan. Removing a connection also clears them so flags do not leak across
   * connection lifetimes and create a contradictory Connected (off) state.
   */
  setTokenPlanEnabled?: (presetId: string, enabled: boolean) => void;
  /**
   * Seed-fingerprint bookkeeping. Only recorded after a successful seed so a
   * failed seed is retried by the next startup reconciliation. `null` clears.
   */
  setTokenPlanSeedVersion?: (presetId: string, fingerprint: string | null) => void;
  /** Currently enrolled plans (presetId → llm providerId); removal uses this
   *  to skip clearing providers another enrolled plan still owns. */
  getTokenPlanEnrollments?: () => Record<string, string>;
  /**
   * State snapshot for seeding priority: enrollments, providersConfig, and authorization switches.
   * When provided, exclusive slots defer to active plans earlier in the list. Without it, retain
   * the previous last-write-wins behavior.
   */
  getTokenPlanPriorityState?: () => TokenPlanEnrollmentState;
}

/** The slices of settings state the enrollment predicates read. */
export interface TokenPlanEnrollmentState {
  tokenPlanEnrollments: Record<string, string>;
  providersConfig: Record<string, { apiKey?: string }>;
  /** Authorization switch: explicitly disabled plans; absent means enabled. */
  tokenPlanDisabled?: Record<string, boolean>;
}

/**
 * Whether a plan is genuinely connected: it was enrolled through the Token
 * Plan UI (explicit marker — never inferred from a provider merely having a
 * key, which would hijack personal keys on shared providers) and its LLM
 * credentials are still present. Presets without an LLM modality never count
 * as enrolled (all shipped presets anchor on LLM).
 *
 * Note: this is the "connection" predicate and ignores the authorization
 * toggle — the Token Plan page must be able to show a connected-but-disabled
 * plan. Consumers should use isTokenPlanUsable.
 */
export function isTokenPlanActive(
  preset: TokenPlanPreset,
  state: TokenPlanEnrollmentState,
): boolean {
  const llm = preset.modalities.llm;
  if (!llm) return false;
  if (state.tokenPlanEnrollments[preset.id] !== llm.providerId) return false;
  return !!state.providersConfig[llm.providerId]?.apiKey;
}

/**
 * Authorization means connected and not disabled. Course model candidates,
 * ordering, and overrides use this rule, matching provider enabled !== false
 * in Model services.
 */
export function isTokenPlanUsable(
  preset: TokenPlanPreset,
  state: TokenPlanEnrollmentState,
): boolean {
  if (state.tokenPlanDisabled?.[preset.id]) return false;
  return isTokenPlanActive(preset, state);
}

/**
 * Return active plans in TOKEN_PLAN_PRESETS declaration order, the only application-wide
 * plan-priority source. Earlier active plans have higher priority for
 * stage-route/main-model ownership and for ordering plan groups
 * in model pickers.
 */
export function activeTokenPlansInPriorityOrder(
  state: TokenPlanEnrollmentState,
): TokenPlanPreset[] {
  return TOKEN_PLAN_PRESETS.filter((preset) => isTokenPlanUsable(preset, state));
}

/**
 * Authorization-toggle cascade: translate "enable this plan" into the `enabled`
 * flag of each of its modality providers. Course Model Config candidates,
 * stage-route pruning, media guards, and the x-model-routes header then reuse
 * the existing authorization layer without needing to understand the plan
 * concept — matching the effect of a provider toggle in Model Services.
 *
 * Shared providers (tokendance and volcengine-ark both ride seedream, etc.) are
 * skipped while another still-usable plan owns them: that credential belongs to
 * the other plan right now and must not be carried away by this toggle.
 */
export function setTokenPlanAuthorization(
  preset: TokenPlanPreset,
  enabled: boolean,
  actions: TokenPlanActions,
  state: TokenPlanEnrollmentState,
): void {
  const ownedByOtherUsablePlan = (providerId: string): boolean =>
    TOKEN_PLAN_PRESETS.some((other) => {
      if (other.id === preset.id) return false;
      if (!isTokenPlanUsable(other, state)) return false;
      return MODALITY_ORDER.some((m) => other.modalities[m]?.providerId === providerId);
    });

  for (const modality of MODALITY_ORDER) {
    const target = preset.modalities[modality];
    if (!target) continue;
    // Only disabling requires deference. Enabling a shared provider is also desired by another
    // active plan that uses it.
    if (!enabled && ownedByOtherUsablePlan(target.providerId)) continue;

    try {
      switch (modality) {
        case 'llm':
          actions.setProviderConfig(target.providerId as ProviderId, { enabled });
          break;
        case 'image':
          actions.setImageProviderConfig(target.providerId as ImageProviderId, { enabled });
          break;
        case 'video':
          actions.setVideoProviderConfig(target.providerId as VideoProviderId, { enabled });
          break;
        case 'tts':
          actions.setTTSProviderConfig(target.providerId as TTSProviderId, { enabled });
          break;
        case 'webSearch':
          actions.setWebSearchProviderConfig(target.providerId as WebSearchProviderId, { enabled });
          break;
      }
    } catch {
      // A failed modality write must not block other modalities, consistent with apply/remove isolation.
    }
  }
}

/**
 * Current shared-provider owner: when multiple plans declare the provider for a modality,
 * return the earliest active plan excluding excludedPresetId, or undefined.
 */
function sharedModalityOwner(
  modality: TokenPlanModality,
  providerId: string,
  state: TokenPlanEnrollmentState | undefined,
  excludedPresetId?: string,
): TokenPlanPreset | undefined {
  if (!state) return undefined;
  return TOKEN_PLAN_PRESETS.find(
    (p) =>
      p.id !== excludedPresetId &&
      isTokenPlanUsable(p, state) &&
      p.modalities[modality]?.providerId === providerId,
  );
}

/** Credential deference on apply: a higher-priority active plan owns this modality/provider. */
function sharedOwnerYields(
  preset: TokenPlanPreset,
  modality: TokenPlanModality,
  state: TokenPlanEnrollmentState | undefined,
): boolean {
  const providerId = preset.modalities[modality]?.providerId;
  if (!providerId || !state) return false;
  const owner = sharedModalityOwner(modality, providerId, state, preset.id);
  if (!owner) return false;
  return TOKEN_PLAN_PRESETS.indexOf(owner) < TOKEN_PLAN_PRESETS.indexOf(preset);
}

/**
 * Re-resolve shared credentials after any authorization change (review P0-03):
 * the highest-priority active plan owns the slot; rewrite credentials, baseUrl, and catalog together
 * using the owner gateway key saved in its LLM provider slot during enrollment.
 *
 * excludeConcerned semantics, preserving regression #2:
 * - Disable/remove (true): exclude this plan and hand slots to the remaining active plans;
 * - Re-enable (false): include this plan when resolving ownership; otherwise a newly enabled
 *   higher-priority plan would exclude itself and leave its slots with a lower-priority plan.
 * Do not write without an owner: disabling cascades authorization to the provider; removing
 * uses usability checks and removeModality cleanup.
 */
export function restoreSharedProviderCredentials(
  concernedPresetId: string,
  actions: TokenPlanActions,
  state: TokenPlanEnrollmentState,
  opts?: { excludeConcerned?: boolean },
): void {
  const concerned = TOKEN_PLAN_PRESETS.find((p) => p.id === concernedPresetId);
  if (!concerned) return;
  const excludeConcerned = opts?.excludeConcerned !== false;
  const excludedId = excludeConcerned ? concernedPresetId : undefined;

  for (const modality of MODALITY_ORDER) {
    const target = concerned.modalities[modality];
    if (!target) continue;
    // Only shared slots need re-resolution; exclusive slots use removeModality/authorization cascades.
    const owner = sharedModalityOwner(modality, target.providerId, state, excludedId);
    if (!owner) continue;
    const ownerTarget = owner.modalities[modality];
    if (!ownerTarget) continue;
    // The owner gateway key resides in its LLM provider slot, an enrollment invariant.
    const ownerKey = state.providersConfig[owner.modalities.llm?.providerId ?? '']?.apiKey;
    if (!ownerKey) continue;

    try {
      applyModality(modality, ownerTarget, owner, ownerKey, actions);
      seedPlanModels(owner, actions, { modalities: [modality], priorityState: state });
    } catch {
      // As in apply/remove, one failed modality does not block other rewrites.
    }
  }
}

export interface ApplyResult {
  modality: TokenPlanModality;
  // 'pending' is a UI-only state the settings page sets while a live probe is in
  // flight; applyTokenPlan itself only ever returns 'lit' or 'failed'.
  status: 'pending' | 'lit' | 'failed';
  providerId: string;
  detail?: string;
}

/**
 * Fills the API key into every modality the preset declares and enables it.
 * Each modality is isolated: a thrown setter doesn't abort the others.
 *
 * Note: this fills config synchronously. For LLM, the caller may additionally
 * trigger model probing (via /api/provider/probe-models) to populate the model
 * list — that's async and lives in the UI, not here.
 */
export function applyTokenPlan(
  preset: TokenPlanPreset,
  apiKey: string,
  actions: TokenPlanActions,
): ApplyResult[] {
  const results: ApplyResult[] = [];
  // Priority snapshot read before enrollment, naturally excluding this plan.
  const priorityState = actions.getTokenPlanPriorityState?.();

  for (const modality of MODALITY_ORDER) {
    const target = preset.modalities[modality];
    if (!target) continue;

    // Shared-provider credentials (review P0-03): when a higher-priority active plan owns
    // the same modality/provider, do not override credentials or catalog regardless of connection order;
    // the earliest active plan owns the slot. Still mark the shared slot lit (connection
    // succeeded); ownership remains with the owner and selection follows seed priority.
    const ownerYields = sharedOwnerYields(preset, modality, priorityState);
    if (ownerYields) {
      results.push({ modality, status: 'lit', providerId: target.providerId });
      continue;
    }

    try {
      applyModality(modality, target, preset, apiKey, actions);
      results.push({ modality, status: 'lit', providerId: target.providerId });
    } catch (err) {
      results.push({
        modality,
        status: 'failed',
        providerId: target.providerId,
        detail: err instanceof Error ? err.message : String(err),
      });
    }
  }

  const lit = results.filter((r) => r.status === 'lit').map((r) => r.modality);

  // Enrollment FIRST: with credentials in, the plan counts as connected even
  // if seeding below throws — reconciliation retries the seed on next load.
  if (lit.length > 0) {
    actions.setTokenPlanEnrolled?.(
      preset.id,
      preset.modalities.llm?.providerId ?? results[0].providerId,
    );
    // Reconnecting reauthorizes the plan and clears stale disabled flags.
    actions.setTokenPlanEnabled?.(preset.id, true);
  }

  // Seed only the modalities that actually got credentials — seeding a failed
  // modality would switch its active selection onto a keyless provider. The
  // fingerprint is recorded only on seed success, so a failed seed is retried.
  try {
    // Exclusive slots (main model, stage route, modality selection) defer to higher-priority
    // active plans; connecting a later plan must not take slots owned by an earlier plan.
    seedPlanModels(preset, actions, {
      modalities: lit,
      priorityState: actions.getTokenPlanPriorityState?.(),
    });
    actions.setTokenPlanSeedVersion?.(preset.id, tokenPlanSeedFingerprint(preset));
  } catch {
    // Credentials stand; the startup reconciliation retries on next load
    // (the fingerprint above was deliberately not recorded).
  }

  return results;
}

function catalogModelFor(target: TokenPlanModalityTarget, id: string): ModelInfo | undefined {
  const direct = findModelById(
    target.providerId,
    PROVIDERS[target.providerId as ProviderId]?.models,
    id,
  );
  if (direct) return direct;

  const allModels = Object.values(PROVIDERS).flatMap((provider) => provider.models);
  return (
    allModels.find((m) => m.id === id) ??
    allModels.find((m) => m.id.toLowerCase() === id.toLowerCase())
  );
}

function tokenPlanModelInfo(target: TokenPlanModalityTarget, id: string): ModelInfo {
  const catalog = catalogModelFor(target, id);
  const thinking = getCatalogThinkingCapability(target.providerId, id);
  if (catalog) {
    return {
      ...catalog,
      id,
      name: catalog.name || id,
      capabilities: {
        ...catalog.capabilities,
        ...(thinking ? { thinking } : {}),
      },
    };
  }
  return {
    id,
    name: id,
    capabilities: {
      streaming: true,
      tools: true,
      vision: false,
      ...(thinking ? { thinking } : {}),
    },
  };
}

/**
 * Seed a plan's model defaults — catalogues, main model, stage routes and the
 * per-modality active selections. Credentials (apiKey/baseUrl) are NOT touched:
 * `applyTokenPlan` writes those first, and the startup reconciliation reuses
 * this to refresh an already-enabled plan whose preset data changed, keeping
 * the user's saved key untouched.
 */
export interface SeedPlanModelsOptions {
  /** Restrict seeding to these modalities (e.g. only those whose credentials
   *  were just written). Omit to seed every declared modality. */
  modalities?: TokenPlanModality[];
  /**
   * When multiple plans are active, exclusive main-model and stage-route slots
   * belong to earlier plans in TOKEN_PLAN_PRESETS and the Token Plan list.
   * With current state, seeding skips slots owned by higher-priority plans so
   * results do not depend on seeding order, whether connecting a lower-priority plan or
   * reconciling plans at startup in any order.
   */
  priorityState?: TokenPlanEnrollmentState;
}

/** Currently active plans with higher priority than the preset. */
function higherPriorityPlans(
  preset: TokenPlanPreset,
  state: TokenPlanEnrollmentState,
): TokenPlanPreset[] {
  const order = TOKEN_PLAN_PRESETS.findIndex((p) => p.id === preset.id);
  if (order < 0) return [];
  return TOKEN_PLAN_PRESETS.slice(0, order).filter((p) => isTokenPlanUsable(p, state));
}

export function seedPlanModels(
  preset: TokenPlanPreset,
  actions: TokenPlanActions,
  opts?: SeedPlanModelsOptions,
): void {
  const m = preset.modalities;
  const allowed = (modality: TokenPlanModality) =>
    !opts?.modalities || opts.modalities.includes(modality);

  // Exclusive-slot deference. Without priorityState, as in stateless calls or tests,
  // preserve existing behavior without deference.
  const rivals = opts?.priorityState ? higherPriorityPlans(preset, opts.priorityState) : [];
  const mainModelTaken = rivals.some((p) => {
    const llm = p.modalities.llm;
    return !!(llm?.defaultModelId ?? llm?.defaultModels?.[0]);
  });
  const stageTaken = (stage: string) =>
    rivals.some((p) => p.modalities.llm?.stageRoutes?.[stage] !== undefined);

  if (m.llm && allowed('llm')) {
    const target = m.llm;
    // Only overwrite the catalogue when the preset curates one — an LLM-only
    // plan without defaultModels keeps the provider's existing model list.
    // Catalogs are per-provider rather than exclusive slots and do not defer.
    if (target.defaultModels?.length) {
      actions.setProviderConfig(target.providerId as ProviderId, {
        models: target.defaultModels.map((id) => tokenPlanModelInfo(target, id)),
      });
    }
    const mainModel = target.defaultModelId ?? target.defaultModels?.[0];
    if (mainModel && !mainModelTaken) {
      actions.setModel?.(target.providerId as ProviderId, mainModel);
    }
    for (const [stage, modelId] of Object.entries(target.stageRoutes ?? {})) {
      if (stageTaken(stage)) continue;
      actions.setStageRoute?.(stage, {
        providerId: target.providerId as ProviderId,
        modelId,
      });
    }
  }

  // A modality selected provider is also exclusive; if a higher-priority plan claims it,
  // write only this plan catalog/credentials without taking the selection.
  const selectionTaken = (modality: TokenPlanModality) =>
    rivals.some((p) => !!p.modalities[modality]);

  // Shared-provider deference (review P0-03): when a higher-priority active plan owns
  // the provider, do not write the catalog either; customModels would overwrite the owner
  // catalog. Both apply and startup reconciliation use this path.
  const providerYields = (modality: TokenPlanModality) =>
    sharedOwnerYields(preset, modality, opts?.priorityState);

  if (m.image && allowed('image') && !providerYields('image')) {
    const customModels = (m.image.defaultModels ?? []).map((id) => ({ id, name: id }));
    if (customModels.length) {
      actions.setImageProviderConfig(m.image.providerId as ImageProviderId, {
        customModels,
        replaceBuiltInModels: true,
      });
      if (!selectionTaken('image')) {
        actions.setImageProvider?.(m.image.providerId as ImageProviderId);
        actions.setImageModelId?.(customModels[0].id);
      }
    }
  }

  if (m.video && allowed('video') && !providerYields('video')) {
    const customModels = (m.video.defaultModels ?? []).map((id) => ({ id, name: id }));
    if (customModels.length) {
      actions.setVideoProviderConfig(m.video.providerId as VideoProviderId, {
        customModels,
        replaceBuiltInModels: true,
      });
      if (!selectionTaken('video')) {
        actions.setVideoProvider?.(m.video.providerId as VideoProviderId);
        actions.setVideoModelId?.(customModels[0].id);
      }
    }
  }

  if (m.tts && allowed('tts') && !providerYields('tts')) {
    const ttsModels = (m.tts.defaultModels ?? []).map((id) => ({ id, name: id }));
    actions.setTTSProviderConfig(m.tts.providerId as TTSProviderId, {
      ...(m.tts.defaultModelId ? { modelId: m.tts.defaultModelId } : {}),
      ...(ttsModels.length ? { customModels: ttsModels } : {}),
    });
    if (!selectionTaken('tts')) {
      actions.setTTSProvider?.(m.tts.providerId as TTSProviderId);
    }
  }

  if (m.webSearch && allowed('webSearch') && !selectionTaken('webSearch')) {
    actions.setWebSearchProvider?.(m.webSearch.providerId as WebSearchProviderId);
  }
}

function applyModality(
  modality: TokenPlanModality,
  target: TokenPlanModalityTarget,
  preset: TokenPlanPreset,
  apiKey: string,
  actions: TokenPlanActions,
): void {
  switch (modality) {
    case 'llm':
      actions.setProviderConfig(target.providerId as ProviderId, {
        apiKey,
        baseUrl: target.baseUrl,
        // Connecting a plan authorizes the provider: without this, a provider
        // whose enable toggle was previously off stays disabled while the seed
        // below force-selects it, leaving a contradictory state.
        enabled: true,
        type: target.apiFormat ?? 'openai',
        name: preset.name,
        icon: preset.icon,
        requiresApiKey: true,
        isBuiltIn: false,
        // Seed the model list from the preset's curated `defaultModels`.
        // Token-plan apply never probes individual models; unsupported tier
        // picks surface at generation time instead of being silently pruned.
        ...(target.modelsUrl ? { modelsUrl: target.modelsUrl } : {}),
      });
      break;
    case 'image':
      actions.setImageProviderConfig(target.providerId as ImageProviderId, {
        apiKey,
        baseUrl: target.baseUrl,
        enabled: true,
      });
      break;
    case 'video':
      actions.setVideoProviderConfig(target.providerId as VideoProviderId, {
        apiKey,
        baseUrl: target.baseUrl,
        enabled: true,
      });
      break;
    case 'tts':
      actions.setTTSProviderConfig(target.providerId as TTSProviderId, {
        apiKey,
        baseUrl: target.baseUrl,
        enabled: true,
      });
      break;
    case 'webSearch':
      actions.setWebSearchProviderConfig(target.providerId as WebSearchProviderId, {
        apiKey,
        baseUrl: target.baseUrl,
        enabled: true,
      });
      break;
  }
}

/**
 * Removes a token plan: clears the API key and disables every modality it
 * declared. For LLM, applying overwrote the shared built-in provider in place
 * (baseUrl, models, name, icon, isBuiltIn: false, …), so removal must restore
 * those built-in defaults — not just clear the key — or the provider stays
 * pointed at the plan endpoint with plan-specific model ids. For image/video,
 * the store switches the active selection away when the provider is disabled
 * (see setImageProviderConfig/setVideoProviderConfig). Each modality is isolated
 * — a thrown setter doesn't abort the rest.
 */
export function removeTokenPlan(preset: TokenPlanPreset, actions: TokenPlanActions): ApplyResult[] {
  const results: ApplyResult[] = [];

  // Plans share media providers (e.g. tokendance and volcengine-ark both ride
  // `seedream`): only another USABLE (enrolled AND still enabled) plan holds
  // real claim to the slot — the removed plan's credentials must not survive
  // behind a merely-enrolled-but-disabled plan (review P0-03 regression #2:
  // disconnecting TD while Seed is disabled left TD's key usable on seedream).
  // Without a priority state (headless callers) fall back to enrollment.
  const priorityState = actions.getTokenPlanPriorityState?.();
  const ownedByOtherPlan = (providerId: string): boolean =>
    priorityState
      ? TOKEN_PLAN_PRESETS.some(
          (p) =>
            p.id !== preset.id &&
            isTokenPlanUsable(p, priorityState) &&
            MODALITY_ORDER.some((m) => p.modalities[m]?.providerId === providerId),
        )
      : (() => {
          const enrollments = actions.getTokenPlanEnrollments?.() ?? {};
          return Object.keys(enrollments).some((pid) => {
            if (pid === preset.id) return false;
            const other = TOKEN_PLAN_PRESETS.find((p) => p.id === pid);
            if (!other) return false;
            return MODALITY_ORDER.some((m) => other.modalities[m]?.providerId === providerId);
          });
        })();

  // Drop the user-level stage routes this plan seeded (courseware / interactive /
  // pro-agent picks), so removal doesn't leave dead routes onto a keyless
  // provider. Stage routes the user later re-pointed elsewhere stay untouched —
  // and so do routes another enrolled plan re-seeded onto the same provider.
  const llmProviderId = preset.modalities.llm?.providerId;
  if (llmProviderId && actions.getStageRoutes && actions.setStageRoute) {
    if (!ownedByOtherPlan(llmProviderId)) {
      for (const [stage, route] of Object.entries(actions.getStageRoutes())) {
        if (route.providerId === llmProviderId) actions.setStageRoute(stage, null);
      }
    }
  }

  for (const modality of MODALITY_ORDER) {
    const target = preset.modalities[modality];
    if (!target) continue;
    if (ownedByOtherPlan(target.providerId)) {
      results.push({ modality, status: 'lit', providerId: target.providerId });
      continue;
    }

    try {
      removeModality(modality, target, actions);
      results.push({ modality, status: 'lit', providerId: target.providerId });
    } catch (err) {
      results.push({
        modality,
        status: 'failed',
        providerId: target.providerId,
        detail: err instanceof Error ? err.message : String(err),
      });
    }
  }

  // Always close the book on this plan, whatever happened above. The disabled
  // marker goes too — it describes THIS connection's authorization and must
  // not leak into the next connect cycle.
  actions.setTokenPlanEnrolled?.(preset.id, null);
  actions.setTokenPlanEnabled?.(preset.id, true);
  actions.setTokenPlanSeedVersion?.(preset.id, null);

  // Restore shared slots (review P0-03): return credentials and catalogs previously used by
  // the removed plan to the highest-priority remaining active plan; retained slots may contain
  // the removed key. The pre-removal snapshot is equivalent because restore excludes its ID.
  if (priorityState) {
    restoreSharedProviderCredentials(preset.id, actions, priorityState);
  }

  return results;
}

function removeModality(
  modality: TokenPlanModality,
  target: TokenPlanModalityTarget,
  actions: TokenPlanActions,
): void {
  switch (modality) {
    case 'llm': {
      // Applying overwrote the built-in provider in place. Restore its built-in
      // defaults so it doesn't linger on the plan endpoint with plan model ids
      // and isBuiltIn:false. The store's LLM resolver then switches the active
      // selection away since the restored config has no key. Custom (non-built-
      // in) providers aren't in the registry — just clear the key for those.
      const builtIn = PROVIDERS[target.providerId as ProviderId];
      if (builtIn) {
        actions.setProviderConfig(target.providerId as ProviderId, {
          apiKey: '',
          baseUrl: '',
          models: builtIn.models,
          name: builtIn.name,
          type: builtIn.type,
          defaultBaseUrl: builtIn.defaultBaseUrl,
          icon: builtIn.icon,
          requiresApiKey: builtIn.requiresApiKey,
          isBuiltIn: true,
          modelsUrl: undefined,
          // applyModality forces enabled:true on connection; disconnecting restores it symmetrically
          // so disabling then disconnecting does not leave a built-in provider enabled:false
          // and require an extra switch after entering a personal API key.
          enabled: true,
        });
      } else {
        actions.setProviderConfig(target.providerId as ProviderId, { apiKey: '' });
      }
      break;
    }
    case 'image':
      actions.setImageProviderConfig(target.providerId as ImageProviderId, {
        apiKey: '',
        baseUrl: '',
        enabled: false,
        customModels: [],
        replaceBuiltInModels: false,
      });
      break;
    case 'video':
      actions.setVideoProviderConfig(target.providerId as VideoProviderId, {
        apiKey: '',
        baseUrl: '',
        enabled: false,
        customModels: [],
        replaceBuiltInModels: false,
      });
      break;
    case 'tts':
      actions.setTTSProviderConfig(target.providerId as TTSProviderId, {
        apiKey: '',
        baseUrl: '',
        enabled: false,
      });
      break;
    case 'webSearch':
      actions.setWebSearchProviderConfig(target.providerId as WebSearchProviderId, {
        apiKey: '',
        baseUrl: '',
        enabled: false,
      });
      break;
  }
}
