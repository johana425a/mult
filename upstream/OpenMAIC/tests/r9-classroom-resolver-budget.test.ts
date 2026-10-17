/** Frozen-provider capacity and native defaults; all transports are mocked. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const fixture = vi.hoisted(() => ({
  output: 128_000,
  thinking: { control: 'effort', requestAdapter: 'openai', effortValues: ['low', 'high', 'xhigh', 'max'], defaultEffort: 'low' },
}));

vi.mock('@/lib/ai/providers', () => ({
  LLM_FETCH_TIMEOUT_MS: 1000,
  parseModelString: (value: string) => {
    const [providerId, modelId] = value.split(':');
    return { providerId, modelId };
  },
  getProvider: () => ({ type: 'openai' }),
  getModel: () => ({ model: { modelId: 'fixture-only' }, modelInfo: {
    id: 'fixture-only', name: 'Fixture only', contextWindow: 500_000,
    outputWindow: fixture.output, capabilities: { thinking: fixture.thinking },
  } }),
}));
vi.mock('@/lib/server/provider-config', () => ({
  isServerConfiguredProvider: () => true, resolveApiKey: () => '', resolveBaseUrl: () => undefined,
  resolveProxy: () => undefined,
}));
vi.mock('@/lib/server/model-routes', () => ({
  getStageRoute: () => undefined, getUserStageRoute: () => undefined, parseUserStageRoutes: () => ({}),
}));
vi.mock('@/lib/server/deepsteam-connection', () => ({
  getDeepSteamExecution: async () => ({
    provider: { model: 'fixture-only', base_url: 'http://localhost:9999/mock', api_key: '', provider_type: 'openai',
      context_window: 500_000, max_output_tokens: 128_000 },
    connection: { model: 'Frozen fixture', context_window: 500_000, max_output_tokens: 128_000,
      vision: { verified: false } },
    resolved_model: { provider: 'fixture-provider', model: 'Frozen fixture' },
  }),
  privateDeepSteamModelFetch: () => () => { throw new Error('No inference is allowed in this fixture'); },
}));

import { resolveModel } from '@/lib/server/resolve-model';

describe('r9 actual resolved output and default reasoning', () => {
  beforeEach(() => {
    fixture.output = 128_000;
    fixture.thinking = { control: 'effort', requestAdapter: 'openai', effortValues: ['low', 'high', 'xhigh', 'max'], defaultEffort: 'low' };
    delete process.env.LLM_THINKING_DISABLED;
  });

  it('preserves frozen 128k output capacity rather than wrapping it in a 4k cap', async () => {
    const result = await resolveModel({ modelString: 'custom-deepsteam-shared:current' });
    expect(result.modelInfo?.outputWindow).toBe(128_000);
    expect(result.modelInfo?.contextWindow).toBe(500_000);
    expect(result.modelId).toBe('Frozen fixture');
  });

  it('sets highest supported native effort only when it was unspecified', async () => {
    expect((await resolveModel({ modelString: 'openai:fixture-only' })).thinkingConfig?.effort).toBe('max');
    const requested = { mode: 'enabled' as const, effort: 'low' as const };
    expect((await resolveModel({ modelString: 'openai:fixture-only', thinkingConfig: requested })).thinkingConfig).toEqual(requested);
    process.env.LLM_THINKING_DISABLED = 'true';
    expect((await resolveModel({ modelString: 'openai:fixture-only' })).thinkingConfig).toBeUndefined();
  });

  it('constrains only default manual budgets to the actual output ceiling', async () => {
    fixture.output = 16_000;
    fixture.thinking = { control: 'toggle-budget', requestAdapter: 'anthropic', budgetRange: { min: 1024, max: 64000 },
      defaultBudgetTokens: 2048 } as unknown as typeof fixture.thinking;
    const resolved = await resolveModel({ modelString: 'anthropic:fixture-only' });
    expect(resolved.thinkingConfig?.budgetTokens).toBe(15_999);
    const requested = { mode: 'enabled' as const, budgetTokens: 4096 };
    expect((await resolveModel({ modelString: 'anthropic:fixture-only', thinkingConfig: requested })).thinkingConfig).toEqual(requested);
  });
});
