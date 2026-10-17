import { expect, test, vi } from 'vitest';
import { useSettingsStore } from '../lib/store/settings';
import { buildUsableFallbackOrder } from '../lib/store/settings-validation';

test('real local provider metadata is accepted by the classroom store', async () => {
  const response = await fetch('http://127.0.0.1:3793/api/server-providers');
  expect(response.ok).toBe(true);
  const data = await response.json();
  vi.stubGlobal('fetch', async () => Response.json(data));
  try {
    await useSettingsStore.getState().fetchServerProviders();
    expect(useSettingsStore.getState().deepsteamConnectionError).toBeUndefined();
    expect(useSettingsStore.getState().deepsteamConnection?.model).toBe('gpt-6.1-sol');
    expect(useSettingsStore.getState().pdfProvidersConfig['deepsteam-local']).toBeDefined();
  } finally { vi.unstubAllGlobals(); }
});

test('a missing old provider entry does not hide valid or re-enable disabled providers', () => {
  const config = { missing: undefined, ready: { isServerConfigured: true },
    off: { isServerConfigured: true, serverDisabled: true },
    disabled: { apiKey: 'test', enabled: false } };
  expect(buildUsableFallbackOrder(config as any)).toEqual(['ready']);
});
