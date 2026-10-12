'use client';

import { useEffect } from 'react';
import { useSettingsStore } from '@/lib/store/settings';

/**
 * Fetches server-configured providers on mount and merges into settings store,
 * then reconciles token-plan model seeds: enabled plans whose preset data
 * changed since they were applied get the new model defaults re-seeded
 * (credentials untouched). Renders nothing — purely a side-effect component.
 */
export function ServerProvidersInit() {
  const fetchServerProviders = useSettingsStore((state) => state.fetchServerProviders);
  const reconcileTokenPlanSeeds = useSettingsStore((state) => state.reconcileTokenPlanSeeds);
  const applyCatalogThinkingMetadata = useSettingsStore(
    (state) => state.applyCatalogThinkingMetadata,
  );

  useEffect(() => {
    const persist = useSettingsStore.persist;
    const run = () => {
      fetchServerProviders();
      reconcileTokenPlanSeeds();
      applyCatalogThinkingMetadata();
    };
    // The KV storage hydrates asynchronously (a network round-trip on
    // server-backed deployments). Running the reconcile before hydration
    // finishes would read the default state — a silent no-op — and the
    // thinking backfill's writes would be refused by the unhydrated store
    // and discarded when the persisted value lands. Gate on real hydration.
    let done = persist.hasHydrated();
    if (done) {
      run();
    }
    const unsubscribe = persist.onFinishHydration(() => {
      if (done) return;
      done = true;
      run();
    });
    const refresh = () => {
      if (persist.hasHydrated() && document.visibilityState === 'visible') fetchServerProviders();
    };
    // A connection may change in the desktop's connection page while this
    // native classroom iframe remains mounted. Refresh metadata, not secrets.
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', refresh);
    const timer = window.setInterval(refresh, 15000);
    return () => {
      done = true;
      unsubscribe();
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', refresh);
      window.clearInterval(timer);
    };
  }, [fetchServerProviders, reconcileTokenPlanSeeds, applyCatalogThinkingMetadata]);

  return null;
}
