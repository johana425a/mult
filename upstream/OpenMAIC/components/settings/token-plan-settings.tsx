'use client';

// The "Token Plan" section: a two-column panel with a service tablist on the
// left (logo, display-name mapping, status row, keyboard navigation) and a
// one-line header on the right (status / update key / manage-account link / ⋯
// menu disconnect). Saving the key connects the plan by applying or removing a
// local settings-store preset — there is no server-side connection, OAuth, or
// quota consent. The "capabilities offered" block below stays a segmented tab
// list of models.

import { useState, useCallback, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Eye,
  EyeOff,
  Check,
  ChevronDown,
  ExternalLink,
  MoreHorizontal,
  Unlink,
  MessageSquare,
  Image as ImageIcon,
  Video,
  Volume2,
  Search,
  type LucideIcon,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useI18n } from '@/lib/hooks/use-i18n';
import { cn } from '@/lib/utils';
import { Switch } from '@/components/ui/switch';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useSettingsStore } from '@/lib/store/settings';
import {
  TOKEN_PLAN_PRESETS,
  MODALITY_ORDER,
  type TokenPlanPreset,
  type TokenPlanModality,
} from '@/lib/config/token-plan-presets';
import {
  applyTokenPlan,
  isTokenPlanActive,
  isTokenPlanUsable,
  removeTokenPlan,
  restoreSharedProviderCredentials,
  setTokenPlanAuthorization,
} from '@/lib/config/apply-token-plan';

const MODALITY_LABEL_KEYS: Record<TokenPlanModality, string> = {
  llm: 'settings.providers',
  image: 'settings.imageSettings',
  video: 'settings.videoSettings',
  tts: 'settings.ttsSettings',
  webSearch: 'settings.webSearchSettings',
};

const MODALITY_ICONS: Record<TokenPlanModality, LucideIcon> = {
  llm: MessageSquare,
  image: ImageIcon,
  video: Video,
  tts: Volume2,
  webSearch: Search,
};

/** Display-name mapping: the volcengine-ark preset is shown as "Seed". */
function presetDisplayName(preset: TokenPlanPreset): string {
  if (preset.id === 'minimax') return 'MiniMax';
  if (preset.id === 'volcengine-ark') return 'Seed';
  return preset.name;
}

/** Balance-management link: `{vendor site}/credits`, preserving the query. */
function portalCreditsUrl(base: string): string {
  try {
    const url = new URL(base);
    url.pathname = `${url.pathname.replace(/\/+$/, '')}/credits`;
    return url.toString();
  } catch {
    return base;
  }
}

/** Model plan row: capability/station to plan default model; omit modalities without model choices. */
interface ModelPlanItem {
  capability: TokenPlanModality;
  stageId?: string;
  model?: string;
}

const MODEL_PLAN_STAGE_LABEL_KEYS: Record<string, string> = {
  'scene-content:slide': 'settings.tokenPlan.stageSlide',
  'scene-content:interactive': 'settings.tokenPlan.stageInteractive',
};

const MODEL_PLAN_CAPABILITY_LABEL_KEYS: Record<TokenPlanModality, string> = {
  llm: 'settings.tokenPlan.capLlm',
  image: 'settings.tokenPlan.capImage',
  video: 'settings.tokenPlan.capVideo',
  tts: 'settings.tokenPlan.capTts',
  webSearch: 'settings.tokenPlan.capWebSearch',
};

function modelPlanItems(preset: TokenPlanPreset): ModelPlanItem[] {
  const items: ModelPlanItem[] = [];
  const llm = preset.modalities.llm;
  if (llm) {
    items.push({ capability: 'llm', model: llm.defaultModelId ?? llm.defaultModels?.[0] });
    for (const [stageId, model] of Object.entries(llm.stageRoutes ?? {})) {
      items.push({ capability: 'llm', stageId, model });
    }
  }
  for (const capability of ['image', 'video', 'tts'] as const) {
    const target = preset.modalities[capability];
    if (target) {
      items.push({
        capability,
        model: target.defaultModelId ?? target.defaultModels?.[0],
      });
    }
  }
  // Modalities with no model concept (e.g. web search) do not disclose a model.
  if (preset.modalities.webSearch) items.push({ capability: 'webSearch' });
  return items;
}

/** Service logo container: TokenDance uses a filled black background, others white with size-6. */
function PresetLogo({ preset }: { preset: TokenPlanPreset }) {
  if (!preset.icon) return <span className="size-8 shrink-0 rounded-lg bg-muted" />;
  return (
    <span
      className={cn(
        'flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-lg',
        preset.id === 'tokendance' ? 'bg-black' : 'bg-background',
      )}
    >
      {}
      <img
        src={preset.icon}
        alt=""
        className={cn('object-contain', preset.id === 'tokendance' ? 'size-full' : 'size-6')}
      />
    </span>
  );
}

/** The models a preset declares for one modality (display-only, no probing). */
function modalityModels(preset: TokenPlanPreset, m: TokenPlanModality): string[] {
  const target = preset.modalities[m];
  if (!target) return [];
  if (target.defaultModels?.length) return target.defaultModels;
  if (target.defaultModelId) return [target.defaultModelId];
  return [target.providerId];
}

export function TokenPlanSettings() {
  const { t } = useI18n();
  const setProviderConfig = useSettingsStore((s) => s.setProviderConfig);
  const setImageProviderConfig = useSettingsStore((s) => s.setImageProviderConfig);
  const setVideoProviderConfig = useSettingsStore((s) => s.setVideoProviderConfig);
  const setTTSProviderConfig = useSettingsStore((s) => s.setTTSProviderConfig);
  const setWebSearchProviderConfig = useSettingsStore((s) => s.setWebSearchProviderConfig);
  const setImageProvider = useSettingsStore((s) => s.setImageProvider);
  const setImageModelId = useSettingsStore((s) => s.setImageModelId);
  const setVideoProvider = useSettingsStore((s) => s.setVideoProvider);
  const setVideoModelId = useSettingsStore((s) => s.setVideoModelId);
  const setModel = useSettingsStore((s) => s.setModel);
  const setStageRoute = useSettingsStore((s) => s.setStageRoute);
  const setTTSProvider = useSettingsStore((s) => s.setTTSProvider);
  const setWebSearchProvider = useSettingsStore((s) => s.setWebSearchProvider);
  // Read provider configs so the page can reflect already-persisted state
  // (other settings panels read the store directly; this page must too).
  const providersConfig = useSettingsStore((s) => s.providersConfig);
  const tokenPlanEnrollments = useSettingsStore((s) => s.tokenPlanEnrollments);
  const tokenPlanDisabled = useSettingsStore((s) => s.tokenPlanDisabled);

  const [selectedId, setSelectedId] = useState<string>(TOKEN_PLAN_PRESETS[0]?.id ?? '');
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [editingKey, setEditingKey] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<TokenPlanModality>('llm');
  const tabRefs = useRef(new Map<string, HTMLButtonElement>());

  const selected =
    TOKEN_PLAN_PRESETS.find((p) => p.id === selectedId) ?? TOKEN_PLAN_PRESETS[0] ?? null;

  // A plan is connected only when it was enrolled through the Token Plan UI
  // (explicit marker) and its LLM credentials are still present — never merely
  // because the provider has a key: minimax/tokendance/doubao double as
  // ordinary direct providers, and a personal key is not a plan connection.
  const isPresetEnabled = (preset: TokenPlanPreset): boolean =>
    isTokenPlanActive(preset, { tokenPlanEnrollments, providersConfig });

  // Authorization means connected and not disabled. The left status column and model configuration
  // share this rule so connection alone is not mistaken for active usage.
  const isPresetUsable = (preset: TokenPlanPreset): boolean =>
    isTokenPlanUsable(preset, { tokenPlanEnrollments, providersConfig, tokenPlanDisabled });

  // The modalities a preset declares, in display order — drives the tab bar.
  const presetModalities = (preset: TokenPlanPreset): TokenPlanModality[] =>
    MODALITY_ORDER.filter((m) => preset.modalities[m]);

  const selectPreset = (preset: TokenPlanPreset) => {
    setSelectedId(preset.id);
    setActiveTab(presetModalities(preset)[0] ?? 'llm');
    setApiKey('');
    setEditingKey(false);
    setDisconnectOpen(false);
  };

  const disablePreset = (preset: TokenPlanPreset) => {
    removeTokenPlan(preset, {
      setProviderConfig,
      setImageProviderConfig,
      setVideoProviderConfig,
      setTTSProviderConfig,
      setWebSearchProviderConfig,
      setStageRoute,
      getStageRoutes: () => useSettingsStore.getState().llmStageRoutes,
      setTokenPlanEnrolled: (presetId, llmProviderId) =>
        useSettingsStore.getState().setTokenPlanEnrolled(presetId, llmProviderId),
      setTokenPlanEnabled: (presetId, enabled) =>
        useSettingsStore.getState().setTokenPlanEnabled(presetId, enabled),
      setTokenPlanSeedVersion: (presetId, fingerprint) =>
        useSettingsStore.getState().setTokenPlanSeedVersion(presetId, fingerprint),
      getTokenPlanEnrollments: () => useSettingsStore.getState().tokenPlanEnrollments,
      // Restoring shared slots requires complete enrollment, provider configuration, and authorization state.
      getTokenPlanPriorityState: () => {
        const s = useSettingsStore.getState();
        return {
          tokenPlanEnrollments: s.tokenPlanEnrollments,
          providersConfig: s.providersConfig,
          tokenPlanDisabled: s.tokenPlanDisabled,
        };
      },
    });
  };

  const disconnect = (preset: TokenPlanPreset) => {
    disablePreset(preset);
    setDisconnectOpen(false);
    setApiKey('');
    setEditingKey(false);
    toast.success(t('settings.tokenPlan.saved'));
  };

  // Authorization toggle: record the flag and cascade it to each modality
  // provider's `enabled`, so Course Model Config candidates, stage-route
  // pruning, and media guards reuse the existing authorization layer.
  const toggleAuthorization = (preset: TokenPlanPreset, checked: boolean) => {
    const store = useSettingsStore.getState();
    store.setTokenPlanEnabled(preset.id, checked);
    // Cascade operations read state after writing the flag, so shared-provider priority
    // uses the actual active set after the switch.
    const next = useSettingsStore.getState();
    const nextState = {
      tokenPlanEnrollments: next.tokenPlanEnrollments,
      providersConfig: next.providersConfig,
      tokenPlanDisabled: next.tokenPlanDisabled,
    };
    const writeActions = {
      setProviderConfig,
      setImageProviderConfig,
      setVideoProviderConfig,
      setTTSProviderConfig,
      setWebSearchProviderConfig,
    };
    setTokenPlanAuthorization(preset, checked, writeActions, nextState);
    // Re-resolve shared slot ownership: disabling excludes this plan and hands slots to the remaining
    // active plans; enabling must include this plan as a possible highest-priority
    // owner, or the newly enabled plan cannot reclaim its slots.
    restoreSharedProviderCredentials(preset.id, writeActions, nextState, {
      excludeConcerned: !checked,
    });

    // Reseed on enabling: authorization clears stage routes while provider
    // enabled=false. Resetting the switch alone does not restore routes; clear the fingerprint so
    // reconciliation reseeds the slots allowed by priorityState.
    if (checked) {
      useSettingsStore.getState().setTokenPlanSeedVersion(preset.id, null);
      useSettingsStore.getState().reconcileTokenPlanSeeds();
    }
  };

  // Save = connect: seed every declared modality's config + the plan's model
  // defaults, then we're done. No probing — the models a plan offers are
  // listed as-is, and the user picks/toggles on the generation bar.
  const handleApply = useCallback(
    (key: string) => {
      const trimmedKey = key.trim();
      if (!selected || !trimmedKey) return;
      applyTokenPlan(selected, trimmedKey, {
        setProviderConfig,
        setImageProviderConfig,
        setVideoProviderConfig,
        setTTSProviderConfig,
        setWebSearchProviderConfig,
        setImageProvider,
        setImageModelId,
        setVideoProvider,
        setVideoModelId,
        setModel,
        setStageRoute,
        setTTSProvider,
        setWebSearchProvider,
        // Enrollment + seed-fingerprint bookkeeping happen inside applyTokenPlan
        // so they stay in lockstep with what actually got written.
        setTokenPlanEnrolled: (presetId, llmProviderId) =>
          useSettingsStore.getState().setTokenPlanEnrolled(presetId, llmProviderId),
        setTokenPlanEnabled: (presetId, enabled) =>
          useSettingsStore.getState().setTokenPlanEnabled(presetId, enabled),
        setTokenPlanSeedVersion: (presetId, fingerprint) =>
          useSettingsStore.getState().setTokenPlanSeedVersion(presetId, fingerprint),
        getTokenPlanEnrollments: () => useSettingsStore.getState().tokenPlanEnrollments,
        // Exclusive slots follow plan-list order. Connecting a lower-priority plan does not replace
        // main models, stage routes, or modality selections owned by higher-priority plans.
        getTokenPlanPriorityState: () => {
          const s = useSettingsStore.getState();
          return {
            tokenPlanEnrollments: s.tokenPlanEnrollments,
            providersConfig: s.providersConfig,
            tokenPlanDisabled: s.tokenPlanDisabled,
          };
        },
      });
      setApiKey('');
      setEditingKey(false);
      toast.success(t('settings.tokenPlan.saved'));
    },
    [
      selected,
      setProviderConfig,
      setImageProviderConfig,
      setVideoProviderConfig,
      setTTSProviderConfig,
      setWebSearchProviderConfig,
      setImageProvider,
      setImageModelId,
      setVideoProvider,
      setVideoModelId,
      setModel,
      setStageRoute,
      setTTSProvider,
      setWebSearchProvider,
      t,
    ],
  );

  const tp = 'settings.tokenPlan';

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <div>
        <h3 className="text-sm font-semibold mb-1">{t(`${tp}.title`)}</h3>
        <p className="text-xs text-muted-foreground">{t(`${tp}.desc`)}</p>
      </div>

      {/* Use a 1:2 split: the provider list is narrow and connection/capability details have more space. */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        {/* Left column: service tablist (collapses to a 3-column grid on small screens) */}
        <div
          className="grid grid-cols-3 content-start gap-1 rounded-xl bg-muted/40 p-1 sm:grid-cols-1 sm:gap-1 sm:bg-transparent sm:p-0"
          role="tablist"
          aria-label={t(`${tp}.selectPlan`)}
        >
          {TOKEN_PLAN_PRESETS.map((preset, index) => {
            const enabled = isPresetEnabled(preset);
            const usable = isPresetUsable(preset);
            const active = selected?.id === preset.id;
            return (
              <button
                type="button"
                role="tab"
                key={preset.id}
                aria-selected={active}
                tabIndex={active ? 0 : -1}
                ref={(node) => {
                  if (node) tabRefs.current.set(preset.id, node);
                  else tabRefs.current.delete(preset.id);
                }}
                onClick={() => selectPreset(preset)}
                onKeyDown={(event) => {
                  const delta =
                    event.key === 'ArrowRight' || event.key === 'ArrowDown'
                      ? 1
                      : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
                        ? -1
                        : 0;
                  if (!delta && event.key !== 'Home' && event.key !== 'End') return;
                  event.preventDefault();
                  const next =
                    TOKEN_PLAN_PRESETS[
                      event.key === 'Home'
                        ? 0
                        : event.key === 'End'
                          ? TOKEN_PLAN_PRESETS.length - 1
                          : (index + delta + TOKEN_PLAN_PRESETS.length) % TOKEN_PLAN_PRESETS.length
                    ];
                  selectPreset(next);
                  tabRefs.current.get(next.id)?.focus();
                }}
                className={cn(
                  'flex min-w-0 flex-col items-center gap-2 rounded-lg px-2 py-3 text-center outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 sm:flex-row sm:gap-3 sm:px-3 sm:py-2 sm:text-left',
                  active
                    ? 'bg-background text-foreground shadow-sm sm:bg-accent/70 sm:shadow-none'
                    : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground',
                )}
              >
                <PresetLogo preset={preset} />
                <span className="min-w-0">
                  <span className="block break-words text-sm font-medium leading-5">
                    {presetDisplayName(preset)}
                  </span>
                  <span className="flex items-center justify-center gap-1 text-xs leading-5 text-muted-foreground sm:justify-start">
                    {usable && <Check className="size-3 shrink-0" />}
                    {t(
                      !enabled
                        ? `${tp}.statusNotConnected`
                        : usable
                          ? `${tp}.statusConnected`
                          : `${tp}.statusDisabled`,
                    )}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        {/* Right column: service header, secure key form, and capabilities. */}
        {selected && (
          <div
            className="min-w-0 space-y-5 sm:border-l sm:border-border/60 sm:pl-6"
            role="tabpanel"
          >
            {(() => {
              const enabled = isPresetEnabled(selected);
              const usable = isPresetUsable(selected);
              return (
                <>
                  {/* Header row: identity, status, and service actions (update key, manage account, more). */}
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h4 className="break-words text-sm font-semibold leading-5">
                        {presetDisplayName(selected)}
                      </h4>
                      <div className="flex flex-wrap items-center gap-x-2 text-xs leading-5 text-muted-foreground">
                        <span>
                          {t(
                            !enabled
                              ? `${tp}.statusNotConnected`
                              : usable
                                ? `${tp}.statusConnected`
                                : `${tp}.statusDisabled`,
                          )}
                        </span>
                        {enabled && (
                          <button
                            type="button"
                            onClick={() => {
                              setEditingKey(!editingKey);
                              setApiKey('');
                            }}
                            className="rounded-sm underline-offset-2 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            {t(editingKey ? `${tp}.cancelKeyUpdate` : `${tp}.updateKey`)}
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="ml-auto flex shrink-0 items-center gap-2">
                      {/* Balance management lives on the TokenDance portal
                          (/credits); shown only when connected, styled like
                          "Manage account". */}
                      {selected.id === 'tokendance' && enabled && selected.websiteUrl && (
                        <a
                          href={portalCreditsUrl(selected.websiteUrl)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 rounded-sm text-xs leading-5 text-muted-foreground underline-offset-2 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {t(`${tp}.balanceManagement`)}
                          <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
                        </a>
                      )}
                      {/* For plans with subscription links, Manage account is a grouping label
                          and the regional links perform navigation. Plans without subscription links
                          retain a direct Manage account link. */}
                      {selected.subscribeUrls ? (
                        <span className="text-xs leading-5 text-muted-foreground">
                          {t(`${tp}.manageAccount`)}
                        </span>
                      ) : (
                        selected.websiteUrl && (
                          <a
                            href={selected.websiteUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 rounded-sm text-xs leading-5 text-muted-foreground underline-offset-2 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            {t(`${tp}.manageAccount`)}
                            <ExternalLink className="size-3 shrink-0" aria-hidden="true" />{' '}
                          </a>
                        )
                      )}
                      {/* Subscription links, such as Kimi Coding Plan, follow Manage account,
                          with regional destinations and the affiliate information from preset data. */}
                      {selected.subscribeUrls &&
                        (
                          [
                            ['domestic', selected.subscribeUrls.domestic],
                            ['international', selected.subscribeUrls.international],
                          ] as const
                        ).map(([region, url]) => (
                          <a
                            key={region}
                            href={url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 rounded-sm text-xs leading-5 text-muted-foreground underline-offset-2 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            {t(`settings.providerLinks.${region}`)}
                            <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
                          </a>
                        ))}
                      {/* Authorization switch: disabling removes the plan from course model choices
                          while retaining credentials and connection. Disconnected plans cannot be enabled. */}
                      <Tooltip>
                        {/* Wrap with a span: TooltipTrigger asChild merges its own
                            data-state into its child. Applying it directly to Switch overrides
                            checked/unchecked state and breaks selected colors. */}
                        <TooltipTrigger asChild>
                          <span className="inline-flex">
                            <Switch
                              checked={usable}
                              disabled={!enabled}
                              onCheckedChange={(checked) => toggleAuthorization(selected, checked)}
                              aria-label={t(`${tp}.enableThisPlan`)}
                            />
                          </span>
                        </TooltipTrigger>
                        <TooltipContent side="bottom" className="text-xs">
                          {t(`${tp}.enableThisPlanHint`)}
                        </TooltipContent>
                      </Tooltip>
                      {enabled && (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-8"
                              aria-label={t(`${tp}.disconnect`)}
                            >
                              <MoreHorizontal className="size-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onSelect={() => setDisconnectOpen(true)}>
                              <Unlink className="size-4" />
                              {t(`${tp}.disconnect`)}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </div>
                  </div>

                  {/* Show the secure key form before connection or while updating; saving connects. */}
                  {(!enabled || editingKey) && (
                    <form
                      className="space-y-2"
                      onSubmit={(event) => {
                        event.preventDefault();
                        handleApply(apiKey);
                      }}
                    >
                      {/* Field and its commit share one row; the button never owns a line. */}
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="relative min-w-0 flex-1 basis-40">
                          <Input
                            type={showKey ? 'text' : 'password'}
                            autoComplete="new-password"
                            spellCheck={false}
                            aria-label={t(`${tp}.apiKey`)}
                            placeholder={selected.apiKeyPlaceholder ?? 'sk-...'}
                            value={apiKey}
                            onChange={(e) => setApiKey(e.target.value)}
                            className="h-8 pr-8"
                          />
                          <button
                            type="button"
                            onClick={() => setShowKey(!showKey)}
                            aria-label={t(`${tp}.apiKey`)}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                          >
                            {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                          </button>
                        </div>
                        <Button
                          type="submit"
                          size="sm"
                          className="ml-auto shrink-0"
                          disabled={!apiKey.trim()}
                        >
                          {t(editingKey ? `${tp}.updateKey` : `${tp}.saveKey`)}
                        </Button>
                      </div>
                      <p className="text-xs leading-5 text-muted-foreground">
                        {t(`${tp}.keyStorage`)}
                      </p>
                    </form>
                  )}

                  {/* View model plan: a capability · stage → plan default model
                      table; modalities with no model concept show "not disclosed". */}
                  <details className="group border-t border-border/60 pt-4">
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-sm text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
                      {t(`${tp}.modelPlan`)}
                      <ChevronDown className="size-4 shrink-0 transition-transform motion-reduce:transition-none group-open:rotate-180" />
                    </summary>
                    <div className="mt-2 space-y-2 text-xs leading-5 text-muted-foreground">
                      <p>{t(`${tp}.planNoteEntitlement`)}</p>
                      <p>{t(`${tp}.planNoteEditable`)}</p>
                    </div>
                    <dl className="mt-2 space-y-2 text-xs leading-5">
                      {modelPlanItems(selected).map((item) => (
                        <div
                          key={`${item.capability}:${item.stageId ?? ''}`}
                          className="flex justify-between gap-4"
                        >
                          <dt className="text-muted-foreground">
                            {t(MODEL_PLAN_CAPABILITY_LABEL_KEYS[item.capability])}
                            {item.stageId
                              ? ` · ${
                                  MODEL_PLAN_STAGE_LABEL_KEYS[item.stageId]
                                    ? t(MODEL_PLAN_STAGE_LABEL_KEYS[item.stageId])
                                    : item.stageId
                                }`
                              : ''}
                          </dt>
                          <dd className="break-all text-right font-mono">
                            {item.model ?? t(`${tp}.planUnavailable`)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </details>

                  {/* Capabilities: a display-only tab list of the models the plan
                      offers per modality. No status, no probing — selection and
                      enable/disable happen on the generation bar. */}
                  <div className="space-y-3">
                    <div className="text-sm font-medium">{t(`${tp}.capabilities`)}</div>

                    {/* Tab bar (segmented control) */}
                    <div className="flex gap-0.5 rounded-lg bg-muted/60 p-0.5">
                      {presetModalities(selected).map((m) => {
                        const Icon = MODALITY_ICONS[m];
                        const isActive = activeTab === m;
                        return (
                          <button
                            key={m}
                            onClick={() => setActiveTab(m)}
                            className={cn(
                              'relative flex flex-1 items-center justify-center gap-1.5 rounded-md py-1.5 text-[11px] font-medium transition-all',
                              isActive
                                ? 'bg-background text-foreground shadow-sm'
                                : 'text-muted-foreground hover:text-foreground/80',
                            )}
                          >
                            <Icon className="size-3.5" />
                            <span className="hidden truncate sm:inline">
                              {t(MODALITY_LABEL_KEYS[m])}
                            </span>
                          </button>
                        );
                      })}
                    </div>

                    {/* Tab content: static model list for the active modality */}
                    {(() => {
                      const models = modalityModels(selected, activeTab);
                      return (
                        <div className="space-y-2 rounded-md border p-3">
                          <div className="flex items-center justify-between gap-3 text-xs">
                            <span className="font-medium">{t(MODALITY_LABEL_KEYS[activeTab])}</span>
                            <span className="text-muted-foreground">
                              {t(`${tp}.modelsCount`, { n: models.length })}
                            </span>
                          </div>
                          <ul className="space-y-1">
                            {models.map((id) => (
                              <li
                                key={id}
                                className="flex items-center gap-2 text-xs text-muted-foreground"
                              >
                                <span className="size-1 shrink-0 rounded-full bg-muted-foreground/40" />
                                <span className="truncate font-mono">{id}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      );
                    })()}

                    <p className="text-[11px] leading-relaxed text-muted-foreground">
                      {t(`${tp}.offeredNote`)}
                    </p>
                  </div>
                </>
              );
            })()}
          </div>
        )}
      </div>

      {/* Disconnect confirmation */}
      {selected && (
        <AlertDialog open={disconnectOpen} onOpenChange={setDisconnectOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t(`${tp}.disconnectTitle`)}</AlertDialogTitle>
              <AlertDialogDescription>{t(`${tp}.disconnectBody`)}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
              <AlertDialogAction onClick={() => disconnect(selected)}>
                {t(`${tp}.disconnect`)}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </div>
  );
}
