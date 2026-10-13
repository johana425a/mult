'use client';

// Course model configuration renders the generation pipeline as station cards and SVG rails.
// Each station shows its actual model. LLM stations follow the main selection in the settings store
// (providerId/modelId) unless overridden by user-level stage routes (llmStageRoutes),
// sent through x-model-routes and ranked below operator MODEL_ROUTES. Media stations
// read and write the actual modality switches and provider/model fields.

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CornerDownRight,
  Eye,
  FileStack,
  Images,
  Info,
  ListTree,
  MessageSquareText,
  MessagesSquare,
  Presentation,
  Search,
  Users,
  Volume2,
  X,
} from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { toast } from 'sonner';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { useI18n } from '@/lib/hooks/use-i18n';
import { useSettingsStore } from '@/lib/store/settings';
import { findModelById } from '@/lib/ai/model-aliases';
import { getThinkingConfigKey } from '@/lib/ai/thinking-config';
import type { ProviderId } from '@/lib/ai/providers';
import type { ThinkingConfig } from '@/lib/types/provider';
import { PDF_PROVIDERS, selectablePdfProviders } from '@/lib/pdf/constants';
import type { PDFProviderId } from '@/lib/pdf/types';
import { ASR_PROVIDERS, TTS_PROVIDERS } from '@/lib/audio/constants';
import type {
  ASRProviderId,
  BuiltInASRProviderId,
  BuiltInTTSProviderId,
  TTSProviderId,
} from '@/lib/audio/types';
import { IMAGE_PROVIDERS } from '@/lib/media/image-providers';
import { VIDEO_PROVIDERS } from '@/lib/media/video-providers';
import {
  IMAGE_PROVIDER_NAMES,
  VIDEO_PROVIDER_NAMES,
} from '@/components/settings/media-provider-names';
import {
  WEB_SEARCH_PROVIDERS,
  getWebSearchProviderDisplayName,
  isWebSearchProviderConfigured,
} from '@/lib/web-search/constants';
import type { WebSearchProviderId } from '@/lib/web-search/types';
import { ModelPicker, type ModelPickerGroup } from './model-picker';
import { useLLMPickerGroups } from './use-llm-picker-groups';
import { STATION_STAGE_KEYS } from '@/lib/config/station-stage-keys';

// ── Design coordinate system: fixed serpentine layout scaled to the container ──────────────
const DESIGN_W = 835;
const DESIGN_H = 398;
const CARD_W = 190;
const CARD_MIN_H = 72;
const CANVAS_PAD = 28;

const STATION_POS: Record<string, { x: number; y: number }> = {
  'doc-parse': { x: 215, y: 0 },
  'web-research': { x: 430, y: 0 },
  outline: { x: 645, y: 0 },
  agents: { x: 645, y: 150 },
  'scene-content': { x: 430, y: 150 },
  'scene-actions': { x: 215, y: 150 },
  tts: { x: 0, y: 150 },
  interaction: { x: 0, y: 300 },
  media: { x: 215, y: 300 },
};

const RAILS: Array<{ pts: Array<[number, number]>; dashed?: boolean }> = [
  // First row: document parsing → web research → outline planning
  {
    pts: [
      [405, 36],
      [430, 36],
    ],
  },
  {
    pts: [
      [620, 36],
      [645, 36],
    ],
  },
  // Outline planning to agent generation; the second row runs right to left
  {
    pts: [
      [740, 72],
      [740, 150],
    ],
  },
  // Second row: agent generation, scene content, scene actions, and speech synthesis
  {
    pts: [
      [645, 186],
      [620, 186],
    ],
  },
  {
    pts: [
      [430, 186],
      [405, 186],
    ],
  },
  {
    pts: [
      [215, 186],
      [190, 186],
    ],
  },
  // Speech synthesis to classroom interaction
  {
    pts: [
      [95, 222],
      [95, 300],
    ],
  },
  // Scene content to media generation, parallel dashed rail
  {
    pts: [
      [525, 222],
      [525, 260],
      [310, 260],
      [310, 300],
    ],
    dashed: true,
  },
  // Media generation to classroom interaction
  {
    pts: [
      [215, 336],
      [190, 336],
    ],
  },
];

/** Built-in TTS/ASR registries exclude custom IDs; access them safely. */
function ttsBuiltIn(id: string) {
  return TTS_PROVIDERS[id as BuiltInTTSProviderId];
}
function asrBuiltIn(id: string) {
  return ASR_PROVIDERS[id as BuiltInASRProviderId];
}

/** Rounded polyline path: quadratic curves soften intermediate corners. */
function roundedPath(pts: Array<[number, number]>, r = 16): string {
  if (pts.length < 2) return '';
  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [px, py] = pts[i - 1];
    const [cx, cy] = pts[i];
    const [nx, ny] = pts[i + 1];
    const d1 = Math.hypot(cx - px, cy - py) || 1;
    const d2 = Math.hypot(nx - cx, ny - cy) || 1;
    const r1 = Math.min(r, d1 / 2);
    const r2 = Math.min(r, d2 / 2);
    const p1: [number, number] = [cx - ((cx - px) / d1) * r1, cy - ((cy - py) / d1) * r1];
    const p2: [number, number] = [cx + ((nx - cx) / d2) * r2, cy + ((ny - cy) / d2) * r2];
    d += ` L ${p1[0]} ${p1[1]} Q ${cx} ${cy} ${p2[0]} ${p2[1]}`;
  }
  const last = pts[pts.length - 1];
  d += ` L ${last[0]} ${last[1]}`;
  return d;
}

// ── Pipeline station definitions ────────────────────────────────────────────
interface StationDef {
  id: keyof typeof STATION_POS & string;
  labelKey: string;
  kind: 'llm' | 'media';
  /**
   * Runtime stage keys controlled by this station; see lib/config/station-stage-keys.ts.
   * For multi-key stations, write overrides and clear inherited routes as a group; display and reads
   * use the first key as the primary key.
   */
  stages?: readonly string[];
  subSlots?: Array<{ key: string; labelKey: string }>;
  vision?: boolean;
  tag?: 'loop' | 'parallel';
}

const STATIONS: StationDef[] = [
  {
    id: 'doc-parse',
    labelKey: 'settings.courseModels.stations.docParse',
    kind: 'media',
  },
  {
    id: 'web-research',
    labelKey: 'settings.courseModels.stations.webResearch',
    kind: 'llm',
    stages: STATION_STAGE_KEYS['web-research'],
  },
  {
    id: 'outline',
    labelKey: 'settings.courseModels.stations.outline',
    kind: 'llm',
    stages: STATION_STAGE_KEYS.outline,
    vision: true,
  },
  {
    id: 'agents',
    labelKey: 'settings.courseModels.stations.agents',
    kind: 'llm',
    stages: STATION_STAGE_KEYS.agents,
  },
  {
    id: 'scene-content',
    labelKey: 'settings.courseModels.stations.sceneContent',
    kind: 'llm',
    stages: STATION_STAGE_KEYS['scene-content'],
    vision: true,
    tag: 'loop',
    subSlots: [
      { key: 'scene-content:slide', labelKey: 'settings.courseModels.subStages.slide' },
      { key: 'scene-content:quiz', labelKey: 'settings.courseModels.subStages.quiz' },
      { key: 'scene-content:interactive', labelKey: 'settings.courseModels.subStages.interactive' },
      { key: 'scene-content:pbl', labelKey: 'settings.courseModels.subStages.pbl' },
    ],
  },
  {
    id: 'scene-actions',
    labelKey: 'settings.courseModels.stations.sceneActions',
    kind: 'llm',
    stages: STATION_STAGE_KEYS['scene-actions'],
    tag: 'loop',
  },
  {
    id: 'tts',
    labelKey: 'settings.courseModels.stations.tts',
    kind: 'media',
    tag: 'loop',
  },
  {
    id: 'media',
    labelKey: 'settings.courseModels.stations.media',
    kind: 'media',
    tag: 'parallel',
  },
  {
    id: 'interaction',
    labelKey: 'settings.courseModels.stations.interaction',
    kind: 'llm',
    // One control covers chat, quiz grading, and the PBL runtime, including parent fallback
    // for compound subkeys. They share this station model configuration.
    stages: STATION_STAGE_KEYS.interaction,
  },
];

const STATION_ICONS: Record<string, typeof FileStack> = {
  'doc-parse': FileStack,
  'web-research': Search,
  outline: ListTree,
  agents: Users,
  'scene-content': Presentation,
  'scene-actions': MessageSquareText,
  tts: Volume2,
  media: Images,
  interaction: MessagesSquare,
};

// ── Station cards ────────────────────────────────────────────────
function Station({
  def,
  label,
  following,
  overrideName,
  resolvedName,
  mediaLines,
  allOff,
  selected,
  onSelect,
  t,
}: {
  def: StationDef;
  label: string;
  following: boolean;
  overrideName?: string;
  resolvedName?: string;
  mediaLines: string[];
  allOff: boolean;
  selected: boolean;
  onSelect: () => void;
  t: (key: string) => string;
}) {
  const Icon = STATION_ICONS[def.id];
  const pos = STATION_POS[def.id];
  const lit = def.kind === 'llm' ? true : mediaLines.length > 0;
  const dim = def.kind === 'media' && allOff;

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
      aria-pressed={selected}
      className={cn(
        'absolute cursor-pointer rounded-xl border bg-card px-3 py-2.5 text-left shadow-xs transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
        lit &&
          !dim &&
          'border-violet-200/70 bg-violet-50/40 dark:border-violet-800/50 dark:bg-violet-950/20',
        !lit && !dim && 'border-border/70 hover:border-primary/40',
        dim && 'border-dashed border-border/60 opacity-60',
        selected && 'border-primary/50 ring-2 ring-primary/60 ring-offset-2 ring-offset-background',
      )}
      style={{ left: pos.x, top: pos.y, width: CARD_W, minHeight: CARD_MIN_H }}
    >
      <div className="flex items-center gap-2">
        <span
          className={cn(
            'flex size-7 shrink-0 items-center justify-center rounded-lg transition-colors duration-200',
            lit && !dim ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground/50',
          )}
        >
          <Icon className="size-3.5" />
        </span>
        <span className="min-w-0 flex-1 truncate text-xs font-medium leading-none">{label}</span>
        {def.vision && (
          <Eye
            className="size-3 shrink-0 text-muted-foreground/45"
            aria-label={t('settings.courseModels.visionSupported')}
          />
        )}
        {def.tag && (
          <span className="shrink-0 rounded-full border border-border/70 px-1.5 py-px text-[9px] leading-tight text-muted-foreground">
            {def.tag === 'loop'
              ? t('settings.courseModels.loop')
              : t('settings.courseModels.parallel')}
          </span>
        )}
      </div>

      {/* Model row: inherited/overridden LLM rows may coexist with service rows */}
      <div className="mt-1.5 flex min-h-4 flex-col gap-0.5">
        {dim ? (
          <span className="text-[10px] leading-none text-muted-foreground">
            {t('settings.courseModels.stopped')}
          </span>
        ) : (
          <>
            {def.stages &&
              (following ? (
                <span className="flex items-center gap-1 text-[10px] leading-none">
                  <CornerDownRight className="size-3 shrink-0 text-primary" />
                  <span className="shrink-0 text-muted-foreground">
                    {t('settings.courseModels.followMainline')}:
                  </span>
                  <span className="truncate font-mono text-foreground/80" title={resolvedName}>
                    {resolvedName}
                  </span>
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-[10px] leading-none">
                  <span className="size-1.5 shrink-0 rounded-full bg-violet-500" />
                  <span
                    className="truncate font-mono font-medium text-violet-600 dark:text-violet-300"
                    title={overrideName}
                  >
                    {overrideName}
                  </span>
                </span>
              ))}
            {mediaLines.map((line) => (
              <span
                key={line}
                className="max-w-full truncate font-mono text-[10px] leading-none text-foreground/75"
                title={line}
              >
                {line}
              </span>
            ))}
          </>
        )}
      </div>
    </button>
  );
}

// ── Main panel ──────────────────────────────────────────────────
export function CourseModelConfigPanel({}) {
  const { t } = useI18n();

  // ── Main model and LLM routes ──
  const providerId = useSettingsStore((s) => s.providerId);
  const modelId = useSettingsStore((s) => s.modelId);
  const providersConfig = useSettingsStore((s) => s.providersConfig);
  const setModel = useSettingsStore((s) => s.setModel);
  const thinkingConfigs = useSettingsStore((s) => s.thinkingConfigs);
  const setThinkingConfig = useSettingsStore((s) => s.setThinkingConfig);
  const llmStageRoutes = useSettingsStore((s) => s.llmStageRoutes);
  const setStageRoute = useSettingsStore((s) => s.setStageRoute);

  // ── Media modalities ──
  const webSearchEnabled = useSettingsStore((s) => s.webSearchEnabled);
  const setWebSearchEnabled = useSettingsStore((s) => s.setWebSearchEnabled);
  const webSearchProviderId = useSettingsStore((s) => s.webSearchProviderId);
  const webSearchProvidersConfig = useSettingsStore((s) => s.webSearchProvidersConfig);
  const setWebSearchProvider = useSettingsStore((s) => s.setWebSearchProvider);

  const ttsEnabled = useSettingsStore((s) => s.ttsEnabled);
  const setTTSEnabled = useSettingsStore((s) => s.setTTSEnabled);
  const ttsProviderId = useSettingsStore((s) => s.ttsProviderId);
  const ttsProvidersConfig = useSettingsStore((s) => s.ttsProvidersConfig);
  const setTTSProvider = useSettingsStore((s) => s.setTTSProvider);
  const setTTSProviderConfig = useSettingsStore((s) => s.setTTSProviderConfig);

  const asrEnabled = useSettingsStore((s) => s.asrEnabled);
  const setASREnabled = useSettingsStore((s) => s.setASREnabled);
  const asrProviderId = useSettingsStore((s) => s.asrProviderId);
  const asrProvidersConfig = useSettingsStore((s) => s.asrProvidersConfig);
  const setASRProvider = useSettingsStore((s) => s.setASRProvider);
  const setASRProviderConfig = useSettingsStore((s) => s.setASRProviderConfig);

  const pdfProviderId = useSettingsStore((s) => s.pdfProviderId);
  const pdfProvidersConfig = useSettingsStore((s) => s.pdfProvidersConfig);
  const setPDFProvider = useSettingsStore((s) => s.setPDFProvider);

  const imageGenerationEnabled = useSettingsStore((s) => s.imageGenerationEnabled);
  const setImageGenerationEnabled = useSettingsStore((s) => s.setImageGenerationEnabled);
  const imageProviderId = useSettingsStore((s) => s.imageProviderId);
  const imageModelId = useSettingsStore((s) => s.imageModelId);
  const imageProvidersConfig = useSettingsStore((s) => s.imageProvidersConfig);
  const setImageProvider = useSettingsStore((s) => s.setImageProvider);
  const setImageModelId = useSettingsStore((s) => s.setImageModelId);

  const videoGenerationEnabled = useSettingsStore((s) => s.videoGenerationEnabled);
  const setVideoGenerationEnabled = useSettingsStore((s) => s.setVideoGenerationEnabled);
  const videoProviderId = useSettingsStore((s) => s.videoProviderId);
  const videoModelId = useSettingsStore((s) => s.videoModelId);
  const videoProvidersConfig = useSettingsStore((s) => s.videoProvidersConfig);
  const setVideoProvider = useSettingsStore((s) => s.setVideoProvider);
  const setVideoModelId = useSettingsStore((s) => s.setVideoModelId);

  const [selected, setSelected] = useState<string | null>(null);
  const selectedDef = STATIONS.find((s) => s.id === selected) ?? null;

  // ── Available LLM choices and model groups share filtering, plan priority, and recommendation order with the home toolbar ──
  const { groups: llmPickerGroups, providers: llmProviders } = useLLMPickerGroups();

  const mainThinkingConfig = thinkingConfigs[getThinkingConfigKey(providerId, modelId)];

  const mainModelName = useMemo(() => {
    const provider = llmProviders.find((p) => p.id === providerId);
    const resolved = findModelById(
      providerId,
      provider?.models ?? providersConfig?.[providerId]?.models,
      modelId,
    )?.name;
    // Show a placeholder when no main model is available instead of an empty inherited selection.
    if (!resolved && !modelId) return t('settings.courseModels.mainlineUnset');
    return resolved ?? modelId;
  }, [llmProviders, providersConfig, providerId, modelId, t]);

  const stageOverrideName = (stage: string) => {
    const route = llmStageRoutes[stage];
    if (!route) return undefined;
    const provider = providersConfig?.[route.providerId];
    return findModelById(route.providerId, provider?.models, route.modelId)?.name ?? route.modelId;
  };

  // ── Media display helpers ──
  const pdfProvider = PDF_PROVIDERS[pdfProviderId];
  const webSearchDisplayName = webSearchProviderId
    ? getWebSearchProviderDisplayName(webSearchProviderId, t)
    : '';

  const ttsModels = useMemo(() => {
    const config = ttsProvidersConfig[ttsProviderId];
    const builtIn = ttsBuiltIn(ttsProviderId);
    const custom = config?.customModels ?? [];
    return builtIn ? [...builtIn.models, ...custom] : custom;
  }, [ttsProvidersConfig, ttsProviderId]);
  const ttsModelName = useMemo(() => {
    const config = ttsProvidersConfig[ttsProviderId];
    const id = config?.modelId || ttsBuiltIn(ttsProviderId)?.defaultModelId || '';
    return ttsModels.find((m) => m.id === id)?.name ?? id;
  }, [ttsProvidersConfig, ttsProviderId, ttsModels]);

  const asrModelName = useMemo(() => {
    const config = asrProvidersConfig[asrProviderId];
    const builtIn = asrBuiltIn(asrProviderId);
    const models = builtIn
      ? [...builtIn.models, ...(config?.customModels ?? [])]
      : (config?.customModels ?? []);
    const id = config?.modelId || builtIn?.defaultModelId || '';
    return models.find((m) => m.id === id)?.name ?? id;
  }, [asrProvidersConfig, asrProviderId]);

  const imageModelName = useMemo(() => {
    const builtIn = IMAGE_PROVIDERS[imageProviderId];
    const config = imageProvidersConfig[imageProviderId];
    const models = config?.replaceBuiltInModels
      ? (config.customModels ?? [])
      : [...(builtIn?.models ?? []), ...(config?.customModels ?? [])];
    return models.find((m) => m.id === imageModelId)?.name ?? imageModelId;
  }, [imageProvidersConfig, imageProviderId, imageModelId]);

  // Use the same activation guard as the store: API key/server configuration and authorization; Token Plan
  // seeding also uses apiKey. Explain missing setup before enabling image/video generation.
  const hasUsableImageProvider = Object.values(imageProvidersConfig ?? {}).some(
    (c) => (c.isServerConfigured || c.apiKey) && c.enabled !== false,
  );
  const hasUsableVideoProvider = Object.values(videoProvidersConfig ?? {}).some(
    (c) => (c.isServerConfigured || c.apiKey) && c.enabled !== false,
  );

  const videoModelName = useMemo(() => {
    const builtIn = VIDEO_PROVIDERS[videoProviderId];
    const config = videoProvidersConfig[videoProviderId];
    const models = config?.replaceBuiltInModels
      ? (config.customModels ?? [])
      : [...(builtIn?.models ?? []), ...(config?.customModels ?? [])];
    return models.find((m) => m.id === videoModelId)?.name ?? videoModelId;
  }, [videoProvidersConfig, videoProviderId, videoModelId]);

  // ── Station status ──
  const stationState = (def: StationDef) => {
    switch (def.id) {
      case 'doc-parse':
        return {
          following: true,
          mediaLines: [pdfProvider?.name ?? pdfProviderId, asrEnabled ? asrModelName : null].filter(
            (v): v is string => !!v,
          ),
          allOff: false,
        };
      case 'web-research':
        return {
          following: !llmStageRoutes['web-search-query-rewrite'],
          mediaLines: webSearchEnabled ? [webSearchDisplayName] : [],
          allOff: !webSearchEnabled,
        };
      case 'tts':
        return {
          following: true,
          mediaLines: ttsEnabled ? [ttsModelName] : [],
          allOff: !ttsEnabled,
        };
      case 'media': {
        const lines = [
          imageGenerationEnabled ? imageModelName : null,
          videoGenerationEnabled ? videoModelName : null,
        ].filter((v): v is string => !!v);
        return { following: true, mediaLines: lines, allOff: lines.length === 0 };
      }
      default: {
        // Write all keys of an interaction station together; read the primary key to determine inherited/overridden state.
        const stage = def.stages?.[0];
        const route = stage ? llmStageRoutes[stage] : undefined;
        return { following: !route, mediaLines: [], allOff: false };
      }
    }
  };

  // ── Canvas scaling ──
  const wrapRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () =>
      setScale(
        Math.max(
          0.3,
          Math.min(
            1.15,
            (el.clientWidth - CANVAS_PAD * 2) / DESIGN_W,
            (el.clientHeight - CANVAS_PAD * 2) / DESIGN_H,
          ),
        ),
      );
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const cm = 'settings.courseModels';

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      {/* Main model bar */}
      <div className="flex shrink-0 items-center gap-3 px-1">
        <span className="shrink-0 text-xs font-medium">{t(`${cm}.mainModel`)}</span>
        <div className="w-56 shrink-0">
          {llmProviders.length > 0 ? (
            <ModelPicker
              groups={llmPickerGroups}
              value={{ providerId, modelId }}
              onSelect={(pid, mid) => setModel(pid as ProviderId, mid)}
              thinkingConfig={mainThinkingConfig}
              onThinkingChange={(config) => setThinkingConfig(providerId, modelId, config)}
              placeholder={t(`${cm}.noProviderHint`)}
              size="md"
              t={t}
            />
          ) : (
            <span className="text-[11px] text-muted-foreground">{t(`${cm}.noProviderHint`)}</span>
          )}
        </div>
        <p className="hidden min-w-0 flex-1 text-[11px] leading-snug text-muted-foreground lg:block">
          {t(`${cm}.mainModelHint`)}
        </p>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              aria-label={t(`${cm}.mainModel`)}
              className="ml-auto shrink-0 rounded-full p-1 text-muted-foreground/60 transition-colors hover:bg-muted hover:text-foreground"
            >
              <Info className="size-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-64 text-xs leading-relaxed">
            {t(`${cm}.mainModelTooltip`)}
          </TooltipContent>
        </Tooltip>
      </div>

      {/* Pipeline diagram and inspector */}
      <div
        className="relative min-h-0 flex-1 overflow-hidden rounded-xl border border-border/50 bg-card"
        style={{
          backgroundImage:
            'radial-gradient(circle, color-mix(in oklab, var(--foreground) 7%, transparent) 1px, transparent 1px)',
          backgroundSize: '20px 20px',
        }}
        onClick={() => setSelected(null)}
      >
        <div
          ref={wrapRef}
          className="flex h-full w-full items-center justify-center overflow-hidden"
        >
          <div
            className="relative shrink-0"
            style={{ width: DESIGN_W * scale, height: DESIGN_H * scale }}
          >
            <div
              className="absolute left-0 top-0"
              style={{
                width: DESIGN_W,
                height: DESIGN_H,
                transform: `scale(${scale})`,
                transformOrigin: 'top left',
              }}
            >
              <svg
                width={DESIGN_W}
                height={DESIGN_H}
                className="pointer-events-none absolute inset-0 overflow-visible"
              >
                <defs>
                  <marker
                    id="course-arrow"
                    viewBox="0 0 8 8"
                    refX="6.5"
                    refY="4"
                    markerWidth="7"
                    markerHeight="7"
                    orient="auto-start-reverse"
                  >
                    <path d="M0.5,0.8 L7,4 L0.5,7.2 Z" fill="currentColor" />
                  </marker>
                </defs>
                {RAILS.map((r, i) => (
                  <path
                    key={i}
                    d={roundedPath(r.pts)}
                    className="fill-none text-foreground/35 stroke-foreground/[0.18]"
                    strokeWidth={1.5}
                    strokeLinecap="round"
                    strokeDasharray={r.dashed ? '0.5 6' : undefined}
                    markerEnd="url(#course-arrow)"
                  />
                ))}
              </svg>

              <span
                className="absolute rounded-full border border-border/60 bg-card px-1.5 py-px text-[9px] text-muted-foreground"
                style={{ left: 385, top: 249 }}
              >
                {t(`${cm}.parallel`)}
              </span>

              {STATIONS.map((def) => {
                const state = stationState(def);
                return (
                  <Station
                    key={def.id}
                    def={def}
                    label={t(def.labelKey)}
                    following={state.following}
                    overrideName={
                      state.following ? undefined : stageOverrideName(def.stages?.[0] ?? '')
                    }
                    resolvedName={mainModelName}
                    mediaLines={state.mediaLines}
                    allOff={state.allOff}
                    selected={selected === def.id}
                    onSelect={() => setSelected(def.id)}
                    t={t}
                  />
                );
              })}
            </div>
          </div>
        </div>

        {selectedDef && (
          <Inspector
            def={selectedDef}
            t={t}
            llmPickerGroups={llmPickerGroups}
            mainModelName={mainModelName}
            llmStageRoutes={llmStageRoutes}
            setStageRoute={setStageRoute}
            onClose={() => setSelected(null)}
            // Actual media modality connections
            webSearch={{
              enabled: webSearchEnabled,
              setEnabled: setWebSearchEnabled,
              providerId: webSearchProviderId,
              setProvider: (id) => setWebSearchProvider(id as WebSearchProviderId),
              providersConfig: webSearchProvidersConfig,
            }}
            tts={{
              enabled: ttsEnabled,
              setEnabled: setTTSEnabled,
              providerId: ttsProviderId,
              setProvider: (id) => setTTSProvider(id as TTSProviderId),
              setProviderConfig: (id, config) => setTTSProviderConfig(id as TTSProviderId, config),
              providersConfig: ttsProvidersConfig,
            }}
            asr={{
              enabled: asrEnabled,
              setEnabled: setASREnabled,
              providerId: asrProviderId,
              setProvider: (id) => setASRProvider(id as ASRProviderId),
              setProviderConfig: (id, config) => setASRProviderConfig(id as ASRProviderId, config),
              providersConfig: asrProvidersConfig,
            }}
            pdf={{
              providerId: pdfProviderId,
              setProvider: setPDFProvider,
              providersConfig: pdfProvidersConfig,
            }}
            image={{
              enabled: imageGenerationEnabled,
              setEnabled: setImageGenerationEnabled,
              hasUsableProvider: hasUsableImageProvider,
              providerId: imageProviderId,
              modelId: imageModelId,
              setProvider: (id) => setImageProvider(id as typeof imageProviderId),
              setModelId: setImageModelId,
              providersConfig: imageProvidersConfig,
            }}
            video={{
              enabled: videoGenerationEnabled,
              setEnabled: setVideoGenerationEnabled,
              hasUsableProvider: hasUsableVideoProvider,
              providerId: videoProviderId,
              modelId: videoModelId,
              setProvider: (id) => setVideoProvider(id as typeof videoProviderId),
              setModelId: setVideoModelId,
              providersConfig: videoProvidersConfig,
            }}
          />
        )}
      </div>
    </div>
  );
}

// ── Inspector ──────────────────────────────────────────────────
interface MediaSlotPropsBase {
  providerId: string;
}

function Inspector(props: {
  def: StationDef;
  t: (key: string) => string;
  llmPickerGroups: ModelPickerGroup[];
  mainModelName: string;
  llmStageRoutes: Record<
    string,
    { providerId: ProviderId; modelId: string; thinking?: ThinkingConfig }
  >;
  setStageRoute: (
    stage: string,
    route: { providerId: ProviderId; modelId: string; thinking?: ThinkingConfig } | null,
  ) => void;
  onClose: () => void;
  webSearch: MediaSlotPropsBase & {
    enabled: boolean;
    setEnabled: (v: boolean) => void;
    setProvider: (id: string) => void;
    providersConfig: Record<
      string,
      {
        apiKey?: string;
        baseUrl?: string;
        enabled?: boolean;
        isServerConfigured?: boolean;
        serverDisabled?: boolean;
      }
    >;
  };
  tts: MediaSlotPropsBase & {
    enabled: boolean;
    setEnabled: (v: boolean) => void;
    setProvider: (id: string) => void;
    setProviderConfig: (id: string, config: { modelId?: string }) => void;
    providersConfig: Record<
      string,
      {
        modelId?: string;
        customModels?: Array<{ id: string; name: string }>;
        isServerConfigured?: boolean;
      }
    >;
  };
  asr: MediaSlotPropsBase & {
    enabled: boolean;
    setEnabled: (v: boolean) => void;
    setProvider: (id: string) => void;
    setProviderConfig: (id: string, config: { modelId?: string }) => void;
    providersConfig: Record<
      string,
      {
        modelId?: string;
        customModels?: Array<{ id: string; name: string }>;
        isServerConfigured?: boolean;
      }
    >;
  };
  pdf: MediaSlotPropsBase & {
    setProvider: (id: PDFProviderId) => void;
    providersConfig: Record<
      string,
      {
        apiKey?: string;
        accessKeyId?: string;
        accessKeySecret?: string;
        enabled?: boolean;
        isServerConfigured?: boolean;
      }
    >;
  };
  image: MediaSlotPropsBase & {
    enabled: boolean;
    setEnabled: (v: boolean) => void;
    /** Explain and reject activation when no API key or server configuration is available. */
    hasUsableProvider: boolean;
    modelId: string;
    providerId: string;
    setProvider: (id: string) => void;
    setModelId: (id: string) => void;
    providersConfig: Record<
      string,
      {
        customModels?: Array<{ id: string; name: string }>;
        replaceBuiltInModels?: boolean;
        enabled?: boolean;
        isServerConfigured?: boolean;
      }
    >;
  };
  video: MediaSlotPropsBase & {
    enabled: boolean;
    setEnabled: (v: boolean) => void;
    hasUsableProvider: boolean;
    modelId: string;
    setProvider: (id: string) => void;
    setModelId: (id: string) => void;
    providersConfig: Record<
      string,
      {
        customModels?: Array<{ id: string; name: string }>;
        replaceBuiltInModels?: boolean;
        enabled?: boolean;
        isServerConfigured?: boolean;
      }
    >;
  };
}) {
  const { t, def, llmPickerGroups, mainModelName, llmStageRoutes, setStageRoute } = props;
  const cm = 'settings.courseModels';

  // Stage picker: station-level calls pass the whole key group, writing/clearing multi-key routes together;
  // see lib/config/station-stage-keys.ts. Individual substages still pass a single key.
  const stageRouteSelect = (
    stageKeys: string | readonly string[],
    followLabel: string,
    followNote: string,
  ) => {
    const keys = typeof stageKeys === 'string' ? [stageKeys] : stageKeys;
    const primary = keys[0];
    const route = primary ? (llmStageRoutes[primary] ?? null) : null;
    const writeAll = (
      routeValue: { providerId: ProviderId; modelId: string; thinking?: ThinkingConfig } | null,
    ) => {
      for (const key of keys) setStageRoute(key, routeValue);
    };
    return (
      <div className="space-y-1">
        <ModelPicker
          groups={llmPickerGroups}
          value={route ? { providerId: route.providerId, modelId: route.modelId } : null}
          followLabel={followLabel}
          followNote={followNote}
          onFollow={() => writeAll(null)}
          onSelect={(pid, mid) => writeAll({ providerId: pid as ProviderId, modelId: mid })}
          thinkingConfig={route?.thinking}
          onThinkingChange={
            route
              ? (config) =>
                  writeAll({
                    providerId: route.providerId,
                    modelId: route.modelId,
                    thinking: config,
                  })
              : undefined
          }
          t={t}
        />
        {route && (
          <button
            onClick={() => writeAll(null)}
            className="text-[11px] text-primary transition-colors hover:underline"
          >
            {t(`${cm}.restoreFollow`)}
          </button>
        )}
      </div>
    );
  };

  return (
    <aside
      onClick={(e) => e.stopPropagation()}
      className="absolute inset-y-0 right-0 z-10 flex w-80 flex-col overflow-hidden border-l border-border/60 bg-card/95 backdrop-blur"
    >
      <div className="flex items-start justify-between gap-2 border-b border-border/60 px-4 py-3">
        <div className="min-w-0">
          <p className="text-sm font-medium leading-tight">{t(def.labelKey)}</p>
          {def.stages ? (
            <p className="mt-1 truncate rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
              {def.stages.join(' · ')}
            </p>
          ) : (
            def.kind === 'media' && (
              <p className="mt-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {t(`${cm}.servicesAndModels`)}
              </p>
            )
          )}
        </div>
        <button
          onClick={props.onClose}
          aria-label={t('settings.close')}
          className="shrink-0 rounded-md p-1 text-muted-foreground/60 transition-colors hover:bg-muted hover:text-foreground"
        >
          <X className="size-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 pb-5">
        <p className="text-xs leading-relaxed text-muted-foreground">
          {t(`${cm}.stations.desc.${def.id}`)}
        </p>

        {def.stages && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium">{t(`${cm}.modelSource`)}</p>
            {llmPickerGroups.length > 0 ? (
              stageRouteSelect(def.stages, t(`${cm}.followMainline`), mainModelName)
            ) : (
              <p className="text-[11px] text-muted-foreground">{t(`${cm}.noProviderHint`)}</p>
            )}
          </div>
        )}

        {def.subSlots && def.subSlots.length > 0 && llmPickerGroups.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium">{t(`${cm}.subStagesTitle`)}</p>
            {def.subSlots.map((sub) => (
              <div key={sub.key} className="space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px]">{t(sub.labelKey)}</span>
                  <span className="truncate font-mono text-[9px] text-muted-foreground/70">
                    {sub.key.split(':').pop()}
                  </span>
                </div>
                {stageRouteSelect(sub.key, t(`${cm}.followParent`), mainModelName)}
              </div>
            ))}
          </div>
        )}

        {/* Web research: search provider */}
        {def.id === 'web-research' && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-medium">{t(`${cm}.searchService`)}</span>
              <Switch
                checked={props.webSearch.enabled}
                onCheckedChange={props.webSearch.setEnabled}
                aria-label={t(`${cm}.searchService`)}
                className="scale-90"
              />
            </div>
            <Select
              value={props.webSearch.providerId}
              onValueChange={(v) => props.webSearch.setProvider(v)}
            >
              <SelectTrigger size="sm" className="h-7 w-full text-[11px]">
                <SelectValue placeholder={t(`${cm}.pickProvider`)} />
              </SelectTrigger>
              <SelectContent align="start">
                {Object.values(WEB_SEARCH_PROVIDERS)
                  .filter((provider) => {
                    const cfg = props.webSearch.providersConfig[provider.id];
                    const usable =
                      isWebSearchProviderConfigured(provider, cfg) && cfg?.enabled !== false;
                    return (
                      usable ||
                      // Keep unavailable selections as a muted row so SelectValue is not blank.
                      provider.id === props.webSearch.providerId
                    );
                  })
                  .map((provider) => {
                    const cfg = props.webSearch.providersConfig[provider.id];
                    const usable =
                      isWebSearchProviderConfigured(provider, cfg) && cfg?.enabled !== false;
                    return (
                      <SelectItem
                        key={provider.id}
                        value={provider.id}
                        disabled={!usable}
                        className="text-[11px]"
                      >
                        {usable
                          ? getWebSearchProviderDisplayName(provider.id, t)
                          : `${getWebSearchProviderDisplayName(provider.id, t)} · ${t(`${cm}.optionInvalid`)}`}
                      </SelectItem>
                    );
                  })}
              </SelectContent>
            </Select>
          </div>
        )}

        {/* Speech synthesis */}
        {def.id === 'tts' && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-medium">{t('settings.ttsSettings')}</span>
              <Switch
                checked={props.tts.enabled}
                onCheckedChange={props.tts.setEnabled}
                aria-label={t('settings.enableTTS')}
                className="scale-90"
              />
            </div>
            <ModelPicker
              groups={[
                {
                  id: props.tts.providerId,
                  name: ttsBuiltIn(props.tts.providerId)?.name ?? props.tts.providerId,
                  models: (() => {
                    const builtIn = ttsBuiltIn(props.tts.providerId);
                    const config = props.tts.providersConfig[props.tts.providerId];
                    return builtIn
                      ? [...builtIn.models, ...(config?.customModels ?? [])]
                      : (config?.customModels ?? []);
                  })(),
                },
              ]}
              value={{
                providerId: props.tts.providerId,
                modelId:
                  props.tts.providersConfig[props.tts.providerId]?.modelId ||
                  ttsBuiltIn(props.tts.providerId)?.defaultModelId ||
                  '',
              }}
              onSelect={(_, mid) =>
                props.tts.setProviderConfig(props.tts.providerId, { modelId: mid })
              }
              disabled={!props.tts.enabled}
              t={t}
            />
          </div>
        )}

        {/* Document parsing: parser and speech transcription */}
        {def.id === 'doc-parse' && (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <span className="text-[11px] font-medium">{t(`${cm}.parseService`)}</span>
              <Select
                value={props.pdf.providerId}
                onValueChange={(v) => props.pdf.setProvider(v as PDFProviderId)}
              >
                <SelectTrigger size="sm" className="h-7 w-full text-[11px]">
                  <SelectValue placeholder={t(`${cm}.pickProvider`)} />
                </SelectTrigger>
                <SelectContent align="start">
                  {selectablePdfProviders()
                    .filter((provider) => {
                      const cfg = props.pdf.providersConfig[provider.id];
                      const hasCredentials =
                        !!cfg?.apiKey || (!!cfg?.accessKeyId && !!cfg?.accessKeySecret);
                      const available =
                        !provider.requiresApiKey || hasCredentials || !!cfg?.isServerConfigured;
                      const usable = available && cfg?.enabled !== false;
                      return (
                        usable ||
                        // Keep unavailable selections as a muted row so SelectValue is not blank.
                        provider.id === props.pdf.providerId
                      );
                    })
                    .map((provider) => {
                      const cfg = props.pdf.providersConfig[provider.id];
                      const hasCredentials =
                        !!cfg?.apiKey || (!!cfg?.accessKeyId && !!cfg?.accessKeySecret);
                      const available =
                        !provider.requiresApiKey || hasCredentials || !!cfg?.isServerConfigured;
                      const usable = available && cfg?.enabled !== false;
                      return (
                        <SelectItem
                          key={provider.id}
                          value={provider.id}
                          disabled={!usable}
                          className="text-[11px]"
                        >
                          {usable
                            ? provider.name
                            : `${provider.name} · ${t(`${cm}.optionInvalid`)}`}
                        </SelectItem>
                      );
                    })}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-medium">{t(`${cm}.asrTranscribe`)}</span>
                <Switch
                  checked={props.asr.enabled}
                  onCheckedChange={props.asr.setEnabled}
                  aria-label={t('settings.enableASR')}
                  className="scale-90"
                />
              </div>
              <ModelPicker
                groups={[
                  {
                    id: props.asr.providerId,
                    name: asrBuiltIn(props.asr.providerId)?.name ?? props.asr.providerId,
                    models: (() => {
                      const builtIn = asrBuiltIn(props.asr.providerId);
                      const config = props.asr.providersConfig[props.asr.providerId];
                      return builtIn
                        ? [...builtIn.models, ...(config?.customModels ?? [])]
                        : (config?.customModels ?? []);
                    })(),
                  },
                ]}
                value={{
                  providerId: props.asr.providerId,
                  modelId:
                    props.asr.providersConfig[props.asr.providerId]?.modelId ||
                    asrBuiltIn(props.asr.providerId)?.defaultModelId ||
                    '',
                }}
                onSelect={(_, mid) =>
                  props.asr.setProviderConfig(props.asr.providerId, { modelId: mid })
                }
                disabled={!props.asr.enabled}
                t={t}
              />
            </div>
          </div>
        )}

        {/* Media generation: images and video */}
        {def.id === 'media' &&
          [
            {
              key: 'image' as const,
              label: t(`${cm}.aiIllustration`),
              enabled: props.image.enabled,
              setEnabled: props.image.setEnabled,
              hasUsableProvider: props.image.hasUsableProvider,
              providerId: props.image.providerId,
              modelId: props.image.modelId,
              registry: IMAGE_PROVIDERS as Record<
                string,
                { name?: string; models: Array<{ id: string; name: string }> }
              >,
              config: props.image.providersConfig,
              setProvider: props.image.setProvider,
              setModelId: props.image.setModelId,
              aria: t('settings.enableImageGeneration'),
            },
            {
              key: 'video' as const,
              label: t(`${cm}.aiVideo`),
              enabled: props.video.enabled,
              setEnabled: props.video.setEnabled,
              hasUsableProvider: props.video.hasUsableProvider,
              providerId: props.video.providerId,
              modelId: props.video.modelId,
              registry: VIDEO_PROVIDERS as Record<
                string,
                { name?: string; models: Array<{ id: string; name: string }> }
              >,
              config: props.video.providersConfig,
              setProvider: props.video.setProvider,
              setModelId: props.video.setModelId,
              aria: t('settings.enableVideoGeneration'),
            },
          ].map((slot) => {
            const nameKeys =
              slot.key === 'image'
                ? (IMAGE_PROVIDER_NAMES as Record<string, string>)
                : (VIDEO_PROVIDER_NAMES as Record<string, string>);
            // Groups contain authorized providers with credentials, consistent with search and document parsing.
            const groupIds = Object.keys(slot.registry).filter((pid) => {
              const cfg = slot.config[pid] as
                | { apiKey?: string; isServerConfigured?: boolean; enabled?: boolean }
                | undefined;
              return cfg?.enabled !== false && !!(cfg?.apiKey || cfg?.isServerConfigured);
            });
            // Pass null when the selected provider is disabled, removed, or unset,
            // so the trigger shows a placeholder rather than an empty pill.
            const selectionValid =
              !!slot.providerId && groupIds.includes(slot.providerId) && !!slot.modelId;
            return (
              <div key={slot.key} className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-medium">{slot.label}</span>
                  <Switch
                    checked={slot.enabled}
                    onCheckedChange={(checked) => {
                      // The store guard rejects activation without credentials; explain it here first,
                      // so users understand why the switch cannot be enabled.
                      if (checked && !slot.hasUsableProvider) {
                        toast.error(t(`${cm}.mediaEnableNeedsSetup`));
                        return;
                      }
                      slot.setEnabled(checked);
                    }}
                    aria-label={slot.aria}
                    className="scale-90"
                  />
                </div>
                <ModelPicker
                  groups={groupIds.map((pid) => {
                    const cfg = slot.config[pid];
                    const provider = slot.registry[pid];
                    const list = cfg?.replaceBuiltInModels
                      ? (cfg.customModels ?? [])
                      : [...(provider?.models ?? []), ...(cfg?.customModels ?? [])];
                    return {
                      id: pid,
                      name: t(`settings.${nameKeys[pid]}`) || provider?.name || pid,
                      models: list,
                    };
                  })}
                  value={
                    selectionValid ? { providerId: slot.providerId, modelId: slot.modelId } : null
                  }
                  placeholder={t(`${cm}.pickModel`)}
                  onSelect={(pid, mid) => {
                    // Switch the provider first, which resets its model selection, then select the model explicitly.
                    if (pid !== slot.providerId) slot.setProvider(pid);
                    slot.setModelId(mid);
                  }}
                  disabled={!slot.enabled}
                  t={t}
                />
              </div>
            );
          })}
      </div>
    </aside>
  );
}
