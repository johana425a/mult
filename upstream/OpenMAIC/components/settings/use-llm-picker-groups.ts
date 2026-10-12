'use client';

// Shared LLM groups: the course configuration and home toolbar model pickers use the same
// available-provider filtering, plan group priority, and in-group model recommendations. Priority
// has one source: active plans follow TOKEN_PLAN_PRESETS declaration order (activeTokenPlansIn
// PriorityOrder); consumers must not sort independently.

import { useMemo } from 'react';
import { useSettingsStore } from '@/lib/store/settings';
import { isLLMProviderConfigured } from '@/lib/store/settings-validation';
import { modelIdsMatch } from '@/lib/ai/model-aliases';
import type { ProviderId } from '@/lib/ai/providers';
import type { ModelInfo } from '@/lib/types/provider';
import { TOKEN_PLAN_PRESETS } from '@/lib/config/token-plan-presets';
import { activeTokenPlansInPriorityOrder } from '@/lib/config/apply-token-plan';
import type { ModelPickerGroup } from './model-picker';

/**
 * Map plan-seeded LLM providers to defaultModels, the plan's official
 * recommendation order. Keep that order even when /models discovery or old seeds reorder the catalog
 * so, for example, the cogevol series stays first.
 *
 * This helper sorts models within a group. Group priority depends on which
 * plans are active; see planRank in useLLMPickerGroups.
 */
const TOKEN_PLAN_LLM_PRESETS: ReadonlyMap<string, readonly string[]> = new Map(
  TOKEN_PLAN_PRESETS.flatMap((preset) => {
    const llm = preset.modalities.llm;
    return llm?.defaultModels?.length ? [[llm.providerId, llm.defaultModels] as const] : [];
  }),
);

export interface LLMProviderEntry {
  id: ProviderId;
  name: string;
  models: ModelInfo[];
}

/**
 * Selectable LLM providers and groups. providers is the available source list used for names and
 * other lookups; groups is the picker view with plan priority and recommendation order.
 */
export function useLLMPickerGroups(): {
  groups: ModelPickerGroup[];
  providers: LLMProviderEntry[];
} {
  const providersConfig = useSettingsStore((s) => s.providersConfig);
  const tokenPlanEnrollments = useSettingsStore((s) => s.tokenPlanEnrollments);
  const tokenPlanDisabled = useSettingsStore((s) => s.tokenPlanDisabled);

  // ── Available LLM catalog entries with reasoning capabilities for the picker. ──
  const providers = useMemo(
    () =>
      Object.entries(providersConfig ?? {})
        .filter(
          ([, config]) =>
            config.enabled !== false && // Hide providers disabled by authorization.
            isLLMProviderConfigured(config),
        )
        .map(([id, config]) => ({
          id: id as ProviderId,
          name: config.name || id,
          models:
            config.isServerConfigured && !config.apiKey && config.serverModels?.length
              ? config.models.filter((model) =>
                  config.serverModels?.some((serverModelId) =>
                    modelIdsMatch(id, model.id, serverModelId),
                  ),
                )
              : config.models,
        })),
    [providersConfig],
  );

  // Map active-plan providers to priority ranks, where zero is highest. Order comes from
  // TOKEN_PLAN_PRESETS and matches the visible Token Plan list;
  // disabled or disconnected plans are excluded, so their providers return to
  // ordinary provider positions.
  const planRank = useMemo(() => {
    const rank = new Map<string, number>();
    activeTokenPlansInPriorityOrder({
      tokenPlanEnrollments,
      providersConfig: providersConfig ?? {},
      tokenPlanDisabled,
    }).forEach((preset, index) => {
      const pid = preset.modalities.llm?.providerId;
      // When plans share a provider, the first plan claims it and later plans cannot override it.
      if (pid && !rank.has(pid)) rank.set(pid, index);
    });
    return rank;
  }, [tokenPlanEnrollments, providersConfig, tokenPlanDisabled]);

  // Pin plan provider groups in plan-list order;
  // sort models by plan recommendation, preserving the relative order of other catalog entries
  // after the recommended entries.
  const groups = useMemo<ModelPickerGroup[]>(
    () =>
      providers
        .map((p) => {
          const recommended = TOKEN_PLAN_LLM_PRESETS.get(p.id);
          const rank = recommended
            ? new Map(recommended.map((id, index) => [id, index] as const))
            : null;
          return {
            id: p.id,
            name: p.name,
            // Group status follows active enrollment, not the presence of a provider in
            // a plan definition. Disabled plans must not retain pinned positions.
            isTokenPlan: planRank.has(p.id),
            planRank: planRank.get(p.id) ?? Number.MAX_SAFE_INTEGER,
            models: p.models
              .map((m) => ({
                id: m.id,
                name: m.name,
                thinking: m.capabilities?.thinking,
              }))
              .sort(
                (a, b) =>
                  (rank?.get(a.id) ?? Number.MAX_SAFE_INTEGER) -
                  (rank?.get(b.id) ?? Number.MAX_SAFE_INTEGER),
              ),
          };
        })
        // Stable sort: plan groups first in plan-list order, then other providers in their original order.
        .sort((a, b) => a.planRank - b.planRank),
    [providers, planRank],
  );

  return { groups, providers };
}
