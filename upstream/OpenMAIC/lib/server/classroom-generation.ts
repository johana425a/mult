import { callLLM } from '@/lib/ai/llm';
import { focusedNarrationCall } from '@/lib/server/classroom-narration-focus.cjs';
import { compactAdjacentSlides } from '@/lib/server/classroom-compact-scenes.cjs';
import { resolveQuizSourceImages } from '@/lib/server/classroom-quiz-images.cjs';
import { retainOriginalSourceImages } from '@/lib/server/classroom-source-references.cjs';
import { SLIDE_LAYOUT_GUIDANCE, findOrnamentOnlyPages } from '@/lib/server/classroom-page-quality.cjs';
import { classroomPrefetchWindow, orderedPrefetch, createClassroomTimings } from '@/lib/server/classroom-performance';
import { createStageAPI } from '@/lib/api/stage-api';
import type { StageStore } from '@/lib/api/stage-api-types';
import {
  applyOutlineFallbacks,
  buildVisionUserContent,
  generateSceneOutlinesFromRequirements,
  generateSceneActions,
  generateSceneContent,
  expandGeneratedSlidePages,
  layoutGeneratedSlidePages,
  imageDimensionsFromDataUrl,
  isAbortError,
  PBLGenerationError,
  withGenerationRetry,
  type AICallFn,
  type AgentInfo,
  type PdfImage,
} from '@openmaic/generation';
import { createSceneWithActions } from '@/lib/server/scene-generation';
import { generatePBLV2Project } from '@/lib/pbl/v2/agents/planner';
import { getDefaultAgents } from '@/lib/orchestration/registry/store';
import { createLogger } from '@/lib/logger';
import type { ContestProviderOptions } from '@/lib/server/contest-provider';
import { isProviderKeyRequired } from '@/lib/ai/providers';
import { resolveClassroomWebSearchConfig } from '@/lib/server/web-search-config';
import { resolveModel } from '@/lib/server/resolve-model';
import { getStageModel, type LlmStage } from '@/lib/server/model-routes';
import type { LanguageModel } from 'ai';
import path from 'node:path';
import type { ThinkingConfig } from '@/lib/types/provider';
import { resolveVocationalActive } from '@/lib/config/feature-flags';
import { buildSearchQuery } from '@/lib/server/search-query-builder';
import { formatSearchResultsAsContext, searchWeb } from '@/lib/web-search';
import type { BaiduSubSources, WebSearchProviderId } from '@/lib/web-search/types';
import {
  ClassroomAlreadyExistsError,
  CLASSROOM_ID_MAX_ATTEMPTS,
  generateClassroomId,
  persistClassroom,
  releaseClassroomReservation,
  reserveClassroom,
  CLASSROOMS_DIR,
  writeJsonFileAtomic,
} from '@/lib/server/classroom-storage';
import {
  classroomTtsSummary,
  countNarratableSpeechActions,
  generateMediaForClassroom,
  replaceMediaPlaceholders,
  generateTTSForClassroom,
  type ClassroomTtsCoverage,
} from '@/lib/server/classroom-media-generation';
import { buildVideoManifestFromOutlines } from '@/lib/media/video-manifest';
import type { UserRequirements } from '@/lib/types/generation';
import type { Scene, Stage } from '@/lib/types/stage';
import { AGENT_COLOR_PALETTE, AGENT_DEFAULT_AVATARS } from '@/lib/constants/agent-defaults';
import { createSourceMaterial } from '@/lib/source-material';
import {
  auditSourceFidelity,
  createSourceContract,
  SourceFidelityError,
  withBundledQwenPromptBudget,
  isBundledQwenProfile,
  wrapGroundedAiCall,
  type FidelityIssue,
  type SourceFidelityAudit,
} from '@/lib/server/source-grounding';

const log = createLogger('Classroom');

interface SceneModelOutput { text: string; finishReason?: string; outputTokens?: number }
const COMPACT_LOCAL_INTERACTIVE = `\nBundled local interactive output contract: Return one compact, complete, self-contained HTML document within 8192 output tokens. Use concise HTML/CSS/JavaScript, no repeated boilerplate, external libraries or decorative code. Preserve all functional controls, reset/state handling, required postMessage actions, accessibility, source conditions and correct mechanism. Put full conceptual explanations in the teacher narration rather than duplicating verbose prose inside code. Close every script and the complete HTML document; never emit unfinished JavaScript. Keep the actual requested interaction; do not replace it with a static page.`;
const STRICT_SOURCE_INTERACTIVE = `\nStrict source widget contract: Fix all quantities, preset values, experiment conditions and parameter ranges to those supported by the source. Do not add arbitrary default values, sliders or new scenarios; enable only manipulations explicitly supported by the source. Keep computed/derived quantities read-only and calculate them from the same current source parameters, preserving their stated mathematical/causal relations. Repeated trials may use the unchanged source experiment. Every tick/action must update all displayed counts, state and derived values consistently. Pause/resume preserves state and continues the same run; reset alone clears the entire run. Avoid unnecessary controls/code, but preserve the core requested interaction. Explain runtime mechanisms in teacher speech; hidden JavaScript does not count as teaching. This rule applies only when supplementary examples are not permitted.`;

export class SceneContentGenerationError extends Error {
  readonly isRetryable = false;
  constructor(readonly code: 'OUTPUT_LIMIT' | 'SCENE_CONTENT_INVALID', detail: string) {
    super(`${code}: ${detail}`);
    this.name = 'SceneContentGenerationError';
  }
}

export function containPBLGenerationError(error: unknown, sceneTitle: string): null {
  if (!(error instanceof PBLGenerationError)) throw error;
  log.warn(`PBL generation failed for scene "${sceneTitle}": ${error.message}`);
  return null;
}

export interface GenerateClassroomInput {
  requirement: string;
  pdfContent?: import('@/lib/types/generation').ClassroomDocumentContent;
  enableWebSearch?: boolean;
  webSearchProviderId?: WebSearchProviderId;
  webSearchApiKey?: string;
  webSearchModelId?: string;
  baiduSubSources?: BaiduSubSources;
  enableImageGeneration?: boolean;
  enableVideoGeneration?: boolean;
  enableTTS?: boolean;
  agentMode?: 'default' | 'generate';
  allowSupplementaryExamples?: boolean;
}

export type ClassroomGenerationStep =
  | 'initializing'
  | 'researching'
  | 'generating_outlines'
  | 'generating_scenes'
  | 'generating_media'
  | 'generating_tts'
  | 'persisting'
  | 'completed';

export interface ClassroomGenerationProgress {
  step: ClassroomGenerationStep;
  progress: number;
  message: string;
  scenesGenerated: number;
  totalScenes?: number;
}

export interface GenerateClassroomResult {
  resolvedModel?: Awaited<ReturnType<typeof resolveModel>>['resolvedModel'];
  modelSnapshot?: Awaited<ReturnType<typeof resolveModel>>['modelSnapshot'];
  stageModels?: Record<string, Awaited<ReturnType<typeof resolveModel>>['resolvedModel']>;
  id: string;
  url: string;
  stage: Stage;
  scenes: Scene[];
  scenesCount: number;
  createdAt: string;
  /**
   * Present when TTS was requested. Omitted when TTS is disabled.
   * `written` is 0 when synthesis saved no clips.
   */
  ttsCoverage?: ClassroomTtsCoverage;
  /**
   * Set when requested narration is incomplete (`written` < `total`) or the TTS phase failed.
   * A requested run with no narratable speech (`total` 0) has coverage and no warning.
   */
  warning?: string;
}

function createInMemoryStore(stage: Stage): StageStore {
  let state = {
    stage: stage as Stage | null,
    scenes: [] as Scene[],
    currentSceneId: null as string | null,
    mode: 'playback' as const,
  };

  const listeners: Array<(s: typeof state, prev: typeof state) => void> = [];

  return {
    getState: () => state,
    setState: (partial: Partial<typeof state>) => {
      const prev = state;
      state = { ...state, ...partial };
      listeners.forEach((fn) => fn(state, prev));
    },
    subscribe: (listener: (s: typeof state, prev: typeof state) => void) => {
      listeners.push(listener);
      return () => {
        const idx = listeners.indexOf(listener);
        if (idx >= 0) listeners.splice(idx, 1);
      };
    },
  };
}

function stripCodeFences(text: string): string {
  let cleaned = text.trim();
  if (cleaned.startsWith('```')) {
    cleaned = cleaned.replace(/^```(?:json)?\s*\n?/, '').replace(/\n?```\s*$/, '');
  }
  return cleaned.trim();
}

async function generateAgentProfiles(
  requirement: string,
  languageDirective: string,
  aiCall: AICallFn,
): Promise<AgentInfo[]> {
  const systemPrompt =
    'You are an expert instructional designer. Generate agent profiles for a multi-agent classroom simulation. Return ONLY valid JSON, no markdown or explanation.';

  const userPrompt = `Generate agent profiles for a course with this requirement:
${requirement}

Requirements:
- Decide the appropriate number of agents based on the course content (typically 3-5)
- Exactly 1 agent must have role "teacher", the rest can be "assistant" or "student"
- Each agent needs: name, role, persona (2-3 sentences describing personality and teaching/learning style)
- Language directive for this course: ${languageDirective}
  Agent names and personas must follow this language directive.

Return a JSON object with this exact structure:
{
  "agents": [
    {
      "name": "string",
      "role": "teacher" | "assistant" | "student",
      "persona": "string (2-3 sentences)"
    }
  ]
}`;

  const response = await aiCall(systemPrompt, userPrompt);
  const rawText = stripCodeFences(response);
  const parsed = JSON.parse(rawText) as {
    agents: Array<{ name: string; role: string; persona: string }>;
  };

  if (!parsed.agents || !Array.isArray(parsed.agents) || parsed.agents.length < 2) {
    throw new Error(`Expected at least 2 agents, got ${parsed.agents?.length ?? 0}`);
  }

  const teacherCount = parsed.agents.filter((a) => a.role === 'teacher').length;
  if (teacherCount !== 1) {
    throw new Error(`Expected exactly 1 teacher, got ${teacherCount}`);
  }

  return parsed.agents.map((a, i) => ({
    id: `gen-server-${i}`,
    name: a.name,
    role: a.role,
    persona: a.persona,
  }));
}

/**
 * Reserve the classroom id before generating any media or TTS.
 *
 * Media and TTS write into `<CLASSROOMS_DIR>/<id>/{media,audio}`, so the id must
 * be claimed first: if the collision were only detected at persist time, the
 * retry would already have written the new classroom's media into an existing
 * classroom's directory and the retried document's media URLs would still point
 * at that other id. The reservation is an exclusive create of the classroom file
 * with a placeholder document (`reserved: true`, empty scenes) — the only token
 * that atomically covers the whole collision namespace, because a classroom
 * created through `POST /api/classroom` has a JSON file but no directory.
 * `readClassroom` hides reserved documents, so an in-flight (or crashed)
 * reservation is never served as an empty classroom. On `EEXIST` a fresh id is
 * generated and retried, bounded exactly like the create route. The process now
 * owns the id, so the final persist is an ordinary overwrite of that same file.
 */
async function reserveGeneratedClassroom(
  buildStage: (id: string) => Stage,
): Promise<{ id: string; stage: Stage }> {
  for (let attempt = 0; ; attempt += 1) {
    const id = generateClassroomId();
    const stage = buildStage(id);
    try {
      await reserveClassroom(id, stage);
      return { id, stage };
    } catch (error) {
      if (
        !(error instanceof ClassroomAlreadyExistsError) ||
        attempt >= CLASSROOM_ID_MAX_ATTEMPTS - 1
      ) {
        throw error;
      }
      log.warn(`Classroom id "${id}" already exists; reserving a fresh id`);
    }
  }
}

const TTS_PHASE_FAILED_WARNING = 'TTS generation phase failed';

function classroomTtsHeartbeatProgress(written: number, total: number): number {
  if (total <= 0) return 94;
  const ratio = Math.min(1, Math.max(0, written / total));
  return 94 + Math.floor(ratio * 3);
}

function ttsResultWarning(
  coverage: ClassroomTtsCoverage | undefined,
  fallback?: string,
): string | undefined {
  if (coverage && coverage.written < coverage.total) {
    return classroomTtsSummary(coverage.written, coverage.total);
  }
  return fallback;
}

export async function generateClassroom(
  input: GenerateClassroomInput,
  options: {
    baseUrl: string;
    signal?: AbortSignal;
    onProgress?: (progress: ClassroomGenerationProgress) => Promise<void> | void;
    modelConfig?: ContestProviderOptions['modelConfig'];
    ttsConfig?: ContestProviderOptions['ttsConfig'];
  },
): Promise<GenerateClassroomResult> {
  const { requirement, pdfContent } = input;

  await options.onProgress?.({
    step: 'initializing',
    progress: 5,
    message: 'Initializing classroom generation',
    scenesGenerated: 0,
  });

  const timings = createClassroomTimings();
  const resolvedConfiguration = await resolveModel({ ...options.modelConfig, stage: 'generate-classroom' });
  const {
    model: languageModel,
    modelInfo,
    modelString,
    modelId,
    baseUrl: modelBaseUrl,
    providerId,
    apiKey,
    thinkingConfig: classroomThinking,
  } = resolvedConfiguration;
  const resolvedIdentity = (resolvedConfiguration as { resolvedModel?: { model?: string } }).resolvedModel?.model ?? modelId;
  log.info(`Using server-configured model: ${modelString}`);

  // Fail fast if the resolved provider has no API key configured
  if (isProviderKeyRequired(providerId) && !apiKey) {
    throw new Error(
      `No API key configured for provider "${providerId}". ` +
        `Set the appropriate key in .env.local or server-providers.yml (e.g. ${providerId.toUpperCase()}_API_KEY).`,
    );
  }

  // The web-search query rewrite is a light, separable stage operators may route
  // to a cheaper model. It defaults to the classroom model and is only
  // re-resolved lazily (inside the web-search branch, and only when a route is
  // configured). This keeps a misconfigured optional route from aborting all
  // classroom generation, and skips the extra resolution when web search is off.
  let searchQueryModel = languageModel;
  let searchQueryThinking = classroomThinking;

  // Competition integration: preserve uploaded figures in the one-shot API.
  const hasVision = modelInfo?.capabilities?.vision ?? Boolean(options.modelConfig);
  const sourceImages: PdfImage[] = (pdfContent?.images ?? []).map((src, index) => ({
    id: `img_${index + 1}`, src, pageNumber: 0,
    ...imageDimensionsFromDataUrl(src),
    description: 'Uploaded source figure; page number is not supplied to this endpoint.',
  }));
  const imageMapping = Object.fromEntries(sourceImages.map((image) => [image.id, image.src]));
  const sourceContract = createSourceContract(pdfContent?.text, sourceImages,
    modelInfo?.contextWindow ?? 16384, input.allowSupplementaryExamples === true, input.requirement);
  const aiCall: AICallFn = withBundledQwenPromptBudget(async (systemPrompt, userPrompt, images) => {
    const result = await callLLM(
      {
        model: languageModel,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: hasVision && images?.length ? buildVisionUserContent(userPrompt, images) : userPrompt },
        ],
        maxOutputTokens: modelInfo?.outputWindow,
      },
      'generate-classroom',
      undefined,
      classroomThinking,
    );
    return result.text;
  }, { modelId, baseUrl: modelBaseUrl, outputWindow: modelInfo?.outputWindow });

  // Per-stage model resolution for the scene pipeline. The classroom used to
  // bind a single `languageModel` (from the `generate-classroom` stage) into one
  // `sceneAiCall` closure shared by scene-content and scene-actions. That made
  // every `MODEL_ROUTES` entry for `scene-content` / `scene-content:<type>` /
  // `scene-actions` a no-op on this path — the browser UI already routes each
  // stage independently via /api/generate/*, but the one-shot skill API did not.
  //
  // Each stage is resolved lazily and only when a route is actually configured
  // (getStageModel returns undefined), so unrouted deployments pay zero extra
  // cost and reuse the classroom model. Resolution failure (e.g. an unknown
  // provider in the route) degrades to the classroom model with a warn, mirroring
  // the existing web-search-query-rewrite handling below — a misconfigured
  // optional route never aborts classroom generation.
  const stageModelCache = new Map<
    LlmStage,
    {
      model: LanguageModel;
      outputWindow?: number;
      modelId?: string;
      baseUrl?: string;
      thinking: ThinkingConfig | undefined;
    }
  >();

  const resolveStageModel = async (
    stage: LlmStage,
  ): Promise<{
    model: LanguageModel;
    outputWindow?: number;
    modelId?: string;
    baseUrl?: string;
    thinking: ThinkingConfig | undefined;
  }> => {
    const cached = stageModelCache.get(stage);
    if (cached) return cached;

    // No route configured → reuse the classroom model, no extra resolution.
    if (!getStageModel(stage)) {
      const fallback = {
        model: languageModel,
        outputWindow: modelInfo?.outputWindow,
        modelId,
        baseUrl: modelBaseUrl,
        thinking: classroomThinking,
      };
      stageModelCache.set(stage, fallback);
      return fallback;
    }

    try {
      const resolved = await resolveModel({ ...options.modelConfig, stage });
      const entry = {
        model: resolved.model,
        outputWindow: resolved.modelInfo?.outputWindow,
        modelId: resolved.modelId,
        baseUrl: resolved.baseUrl,
        thinking: resolved.thinkingConfig,
      };
      log.info(`Stage "${stage}" routed to model: ${resolved.modelString}`);
      stageModelCache.set(stage, entry);
      return entry;
    } catch (err) {
      log.warn(
        `Stage "${stage}" route "${getStageModel(stage)}" could not be resolved; ` +
          `falling back to the generate-classroom model.`,
        err,
      );
      const fallback = {
        model: languageModel,
        outputWindow: modelInfo?.outputWindow,
        modelId,
        baseUrl: modelBaseUrl,
        thinking: classroomThinking,
      };
      stageModelCache.set(stage, fallback);
      return fallback;
    }
  };

  // scene-content routes per outline type via the composite key
  // `scene-content:<type>` (slide/quiz/interactive/pbl), falling back to the
  // base `scene-content` route — same resolution the browser UI uses at
  // /api/generate/scene-content. Returns the aiCall plus the resolved model
  // and thinking config, because PBL scene generation drives its own LLM
  // calls through the model object (generatePBLSceneContent) rather than the
  // aiCall closure, and consumes the route's thinking config separately.
  const resolveSceneContentCall = async (outlineType?: string, onOutput?: (output: SceneModelOutput) => Promise<void>, contentSignal?: AbortSignal) => {
    const stage = (outlineType ? `scene-content:${outlineType}` : 'scene-content') as LlmStage;
    const { model, outputWindow, thinking, modelId: sceneModelId, baseUrl } = await resolveStageModel(stage);
    const localInteractive = outlineType === 'interactive' && isBundledQwenProfile({ modelId: sceneModelId, baseUrl });
    // Request-local immutable cap; do not mutate the cached model or other
    // scenes. llama.cpp f2918cabb server-context.cpp:1951 gives the request
    // n_predict/max_tokens precedence over the CLI's default --n-predict.
    const effectiveOutputWindow = localInteractive ? 8192 : outputWindow;
    const aiCall: AICallFn = withBundledQwenPromptBudget(async (systemPrompt, userPrompt, images) => {
      const result = await callLLM(
        {
          model,
          messages: [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: hasVision && images?.length ? buildVisionUserContent(userPrompt, images) : userPrompt },
          ],
          maxOutputTokens: effectiveOutputWindow,
          abortSignal: contentSignal ?? options.signal,
          maxRetries: 0,
        },
        'generate-classroom-scene',
        undefined,
        thinking,
      );
      const output = { text: result.text, finishReason: result.finishReason,
        outputTokens: result.totalUsage?.outputTokens ?? result.usage?.outputTokens };
      await onOutput?.(output);
      if (outlineType === 'interactive' && result.finishReason === 'length') {
        throw new SceneContentGenerationError('OUTPUT_LIMIT', `Interactive output reached its ${effectiveOutputWindow ?? 'configured'} token limit; the failed draft was retained privately. No identical retry or incomplete scene was accepted.`);
      }
      return result.text;
    }, { modelId: sceneModelId, baseUrl, outputWindow: effectiveOutputWindow });
    return { aiCall, model, thinking, localInteractive };
  };

  // agent-profiles routes via the `agent-profiles` stage (matches the browser
  // UI's /api/generate/agent-profiles). Lazy + cached like the scene stages.
  let agentProfilesAiCall: AICallFn | undefined;
  const getAgentProfilesAiCall = async (): Promise<AICallFn> => {
    if (agentProfilesAiCall) return agentProfilesAiCall;
    const { model, outputWindow, thinking } = await resolveStageModel('agent-profiles');
    agentProfilesAiCall = async (systemPrompt, userPrompt, _images) => {
      const result = await callLLM(
        {
          model,
          messages: [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: userPrompt },
          ],
          maxOutputTokens: outputWindow,
        },
        'generate-classroom',
        undefined,
        thinking,
      );
      return result.text;
    };
    return agentProfilesAiCall;
  };

  // scene-actions routes via the `scene-actions` stage.
  let sceneActionsAiCall: AICallFn | undefined;
  const getSceneActionsAiCall = async (): Promise<AICallFn> => {
    if (sceneActionsAiCall) return sceneActionsAiCall;
    const { model, outputWindow, thinking, modelId: actionsModelId, baseUrl } = await resolveStageModel('scene-actions');
    sceneActionsAiCall = withBundledQwenPromptBudget(async (systemPrompt, userPrompt, _images) => {
      const result = await callLLM(
        {
          model,
          messages: [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: userPrompt },
          ],
          maxOutputTokens: outputWindow,
          maxRetries: 0,
        },
        'generate-classroom-scene',
        undefined,
        thinking,
      );
      return result.text;
    }, { modelId: actionsModelId, baseUrl, outputWindow });
    return sceneActionsAiCall;
  };

  const searchQueryAiCall: AICallFn = async (systemPrompt, userPrompt, _images) => {
    const result = await callLLM(
      {
        model: searchQueryModel,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: userPrompt },
        ],
        maxOutputTokens: 256,
      },
      'web-search-query-rewrite',
      undefined,
      searchQueryThinking,
    );
    return result.text;
  };

  const requirements: UserRequirements = {
    requirement,
  };
  const vocationalActive = resolveVocationalActive(requirements);
  const pdfText = pdfContent?.text || undefined;

  await options.onProgress?.({
    step: 'researching',
    progress: 10,
    message: 'Researching topic',
    scenesGenerated: 0,
  });

  // Web search (optional, graceful degradation)
  let researchContext: string | undefined;
  if (input.enableWebSearch) {
    const webSearchConfig = resolveClassroomWebSearchConfig(input);
    if (webSearchConfig) {
      // Re-resolve the query-rewrite model only when explicitly routed. If
      // resolution itself fails (e.g. unknown provider in the route), fall back
      // to the classroom model here; a route with a missing key resolves fine
      // and surfaces only later in callLLM, which the outer try/catch below
      // degrades gracefully — either way the pipeline still works.
      const rewriteRoute = getStageModel('web-search-query-rewrite');
      if (rewriteRoute) {
        try {
          const rewriteResolved = await resolveModel({ ...options.modelConfig, stage: 'web-search-query-rewrite' });
          searchQueryModel = rewriteResolved.model;
          searchQueryThinking = rewriteResolved.thinkingConfig;
        } catch (err) {
          log.warn(
            `web-search-query-rewrite route "${rewriteRoute}" unavailable; using classroom model for query rewrite`,
            err,
          );
        }
      }
      try {
        const searchQuery = await buildSearchQuery(requirement, pdfText, searchQueryAiCall);

        log.info('Running web search for classroom generation', {
          hasPdfContext: searchQuery.hasPdfContext,
          rawRequirementLength: searchQuery.rawRequirementLength,
          rewriteAttempted: searchQuery.rewriteAttempted,
          finalQueryLength: searchQuery.finalQueryLength,
        });

        const searchResult = await searchWeb({
          providerId: webSearchConfig.providerId,
          query: searchQuery.query,
          apiKey: webSearchConfig.apiKey,
          baseUrl: webSearchConfig.baseUrl,
          baiduSubSources: webSearchConfig.baiduSubSources,
          claudeModelId: webSearchConfig.claudeModelId,
        });
        researchContext = formatSearchResultsAsContext(searchResult);
        if (researchContext) {
          log.info(`Web search returned ${searchResult.sources.length} sources`);
        }
      } catch (e) {
        log.warn('Web search failed, continuing without search context:', e);
      }
    } else {
      log.warn('enableWebSearch is true but no web search API key configured, skipping web search');
    }
  }

  await options.onProgress?.({
    step: 'generating_outlines',
    progress: 15,
    message: 'Generating scene outlines',
    scenesGenerated: 0,
  });

  const outlinesResult = await generateSceneOutlinesFromRequirements(
    requirements,
    pdfText,
    sourceImages,
    wrapGroundedAiCall(aiCall, sourceContract, [], 'outline'),
    {
      imageGenerationEnabled: input.enableImageGeneration,
      videoGenerationEnabled: input.enableVideoGeneration,
      researchContext,
      imageMapping,
      visionEnabled: hasVision,
      // NO teacherContext — agents haven't been generated yet
    },
  );

  if (!outlinesResult.success || !outlinesResult.data) {
    log.error('Failed to generate outlines:', outlinesResult.error);
    throw new Error(outlinesResult.error || 'Failed to generate scene outlines');
  }

  const { languageDirective, courseTitle, outlines } = outlinesResult.data;
  log.info(
    `Generated ${outlines.length} scene outlines (languageDirective: ${languageDirective}, courseTitle: ${courseTitle ?? 'n/a'})`,
  );

  await options.onProgress?.({
    step: 'generating_outlines',
    progress: 30,
    message: `Generated ${outlines.length} scene outlines`,
    scenesGenerated: 0,
    totalScenes: outlines.length,
  });

  // Resolve agents based on agentMode — now AFTER outlines so we can use languageDirective
  let agents: AgentInfo[];
  const agentMode = input.agentMode || 'default';
  if (agentMode === 'generate') {
    log.info('Generating custom agent profiles via LLM...');
    try {
      const agentProfilesCall = await getAgentProfilesAiCall();
      agents = await generateAgentProfiles(requirement, languageDirective, agentProfilesCall);
      log.info(`Generated ${agents.length} agent profiles`);
    } catch (e) {
      log.warn('Agent profile generation failed, falling back to defaults:', e);
      agents = getDefaultAgents();
    }
  } else {
    agents = getDefaultAgents();
  }

  const { id: stageId, stage } = await reserveGeneratedClassroom((id) => ({
    id,
    name: courseTitle || outlines[0]?.title || requirement.slice(0, 50),
    description: undefined,
    languageDirective,
    sourceMaterial: pdfContent?.text?.trim()
      ? { ...createSourceMaterial(pdfContent.text)!, images: sourceImages,
          allowSupplementaryExamples: input.allowSupplementaryExamples === true, requestContext: input.requirement }
      : undefined,
    videoManifest: buildVideoManifestFromOutlines(outlines),
    style: 'interactive',
    createdAt: Date.now(),
    updatedAt: Date.now(),
    // For LLM-generated agents, embed full configs so the client can
    // hydrate the agent registry without prior IndexedDB data.
    // For default agents, just record IDs — the client already has them.
    ...(agentMode === 'generate'
      ? {
          generatedAgentConfigs: agents.map((a, i) => ({
            id: a.id,
            name: a.name,
            role: a.role,
            persona: a.persona || '',
            avatar: AGENT_DEFAULT_AVATARS[i % AGENT_DEFAULT_AVATARS.length],
            color: AGENT_COLOR_PALETTE[i % AGENT_COLOR_PALETTE.length],
            priority: a.role === 'teacher' ? 10 : a.role === 'assistant' ? 7 : 5,
          })),
        }
      : {
          agentIds: agents.map((a) => a.id),
        }),
  }));

  // The reservation above claims the id; everything below owns it. If
  // generation throws before `persistClassroom` succeeds, release the
  // placeholder so a failed run does not burn the id or leave an unreadable
  // file behind. `persisted` is the completion marker.
  let persisted: Awaited<ReturnType<typeof persistClassroom>> | undefined;
  try {
    const store = createInMemoryStore(stage);
    const api = createStageAPI(store);

    log.info('Stage 2: Generating scene content and actions...');
    let draftNumber = 0;
    const buildSceneDraft = async (repairIssues: FidelityIssue[] = []): Promise<Scene[]> => {
    const draftAttempt = ++draftNumber;
    // A repair is a fresh model generation, never manual edits of a published class.
    store.setState({ scenes: [], currentSceneId: null });
    let generatedScenes = 0;

    const contentWindow = classroomPrefetchWindow(resolvedIdentity, outlines,
      ['scene-content', 'scene-content:slide', 'scene-content:quiz', 'scene-content:interactive', 'scene-actions'].some(stage => Boolean(getStageModel(stage as LlmStage))));
    timings.setContentWindow(contentWindow);
    await options.onProgress?.({ step: 'generating_scenes', progress: 31,
      message: contentWindow === 2 ? 'Generating scene content (up to 2 pages in parallel)' : 'Generating scene content',
      scenesGenerated: 0, totalScenes: outlines.length });
    const prepareContent = (outline: (typeof outlines)[number], index: number, contentSignal: AbortSignal) =>
      timings.measure('content', { draft: draftAttempt, scene: index + 1 }, async () => {
      const safeOutline = applyOutlineFallbacks(outline, true, {
        allowProceduralSkill: vocationalActive,
      });
      const progressStart = 30 + Math.floor((index / Math.max(outlines.length, 1)) * 60);

      const reportSceneRetry = async (
        phase: 'content' | 'actions',
        event: { attempt: number; maxAttempts: number; reason: string },
      ) => {
        const nextAttempt = Math.min(event.attempt + 1, event.maxAttempts);
        const message = `Retrying scene ${index + 1}/${outlines.length} ${phase} (${nextAttempt}/${event.maxAttempts}): ${safeOutline.title}`;
        log.warn(`${message} — ${event.reason}`);
        await options.onProgress?.({
          step: 'generating_scenes',
          progress: Math.max(progressStart, 31),
          message,
          scenesGenerated: generatedScenes,
          totalScenes: outlines.length,
        });
      };

      // Resolve this scene's content model lazily, per outline type. The package
      // gets the provider-bound AICallFn and the app injects its agentic PBL loop
      // as the classified fallback, preserving single-call → loop routing.
      let lastOutput: SceneModelOutput | undefined;
      let validationAttempt = 1;
      const retainFailedOutput = async (reason: string, diagnostics: string[]) => {
        // Outside the publicly served classroom/media namespace. The report
        // and UI receive only the reason, never this raw model response.
        await writeJsonFileAtomic(path.join(path.dirname(CLASSROOMS_DIR), 'generation-failures', stageId,
          `draft-${draftAttempt}-scene-${index + 1}-content-${validationAttempt}.json`), {
          version: 1, reason, diagnostics, sceneType: safeOutline.type, draftAttempt,
          validationAttempt, sourceSha256: sourceContract?.sha256,
          output: lastOutput, private: true,
        });
      };
      const contentCall = await resolveSceneContentCall(safeOutline.type, async output => {
        lastOutput = output;
        if (safeOutline.type === 'interactive' && output.finishReason === 'length') {
          await retainFailedOutput('OUTPUT_LIMIT', ['Provider reported finishReason=length.']);
        }
      }, contentSignal);
      let repairFeedback = '';
      const content = await (async () => {
        try {
          for (validationAttempt = 1; validationAttempt <= (['interactive', 'slide'].includes(safeOutline.type) ? 2 : 1); validationAttempt++) {
          const diagnostics: string[] = [];
          let failureCode: string | undefined;
          const contentLogger = { debug: log.debug, info: log.info, warn: log.warn,
            error: (message: string, ...meta: unknown[]) => {
              // Generator response previews are raw material: keep them only
              // in the private failed-output artifact, not in public progress.
              if (message.startsWith('Response preview:')) return;
              const detail = [message, ...meta.filter(value => typeof value === 'string')].join(' ').slice(0, 500);
              diagnostics.push(detail); log.error(detail);
            } };
          const groundedCall = wrapGroundedAiCall(contentCall.aiCall, sourceContract, repairIssues, 'content');
          const promptedCall: AICallFn = (system, user, images) => groundedCall(system,
            `${user}${safeOutline.type === 'slide' ? SLIDE_LAYOUT_GUIDANCE : ''}${contentCall.localInteractive ? COMPACT_LOCAL_INTERACTIVE : ''}${safeOutline.type === 'interactive' && sourceContract && !sourceContract.allowSupplementaryExamples ? STRICT_SOURCE_INTERACTIVE : ''}${repairFeedback}`, images);
          let generated = await withGenerationRetry(
            () =>
              generateSceneContent(safeOutline, promptedCall, {
                assignedImages: safeOutline.suggestedImageIds?.length
                  ? sourceImages.filter((image) => safeOutline.suggestedImageIds!.includes(image.id))
                  : sourceImages,
                imageMapping,
                visionEnabled: hasVision,
                agents,
                languageDirective,
                paginateSlides: true,
                allowProceduralSkill: vocationalActive,
                logger: contentLogger,
                onFailure: failure => { failureCode = failure.code; },
                ...(safeOutline.type === 'pbl'
                  ? {
                      pblLoopFallback: (input) =>
                        generatePBLV2Project(
                          input,
                          contentCall.model,
                          callLLM,
                          { logger: log },
                          contentCall.thinking,
                        ),
                    }
                  : {}),
              }),
            {
              label: `scene ${index + 1}/${outlines.length} content`,
              // Network/HTTP retries keep their original policy. Invalid
              // interactive output uses the bounded feedback loop below.
              shouldRetryResult: ['interactive', 'slide'].includes(safeOutline.type) ? undefined : (result) => result === null,
              onRetry: (event) => reportSceneRetry('content', event),
            },
          ).catch(error => {
            // Layout validation is a content failure, not a transport retry.
            // The bounded repair loop below retains the raw draft and all
            // source content; abort and service failures still propagate.
            if (safeOutline.type !== 'slide' || !['SLIDE_LAYOUT_OVERFLOW', 'SLIDE_LAYOUT_UNSUPPORTED'].includes(error?.code)) throw error;
            failureCode = error.code;
            diagnostics.push(String(error.message));
            return null;
          });
          if (generated && safeOutline.type === 'quiz') {
            generated = await resolveQuizSourceImages(generated, imageMapping, stageId, CLASSROOMS_DIR);
          }
          if (generated && safeOutline.type === 'slide') {
            const orphanPages = findOrnamentOnlyPages(generated);
            if (orphanPages.length) {
              diagnostics.push(`Pages ${orphanPages.join(', ')} contain only a title and decoration. Regenerate the complete outline with substantive content on every page; remove decorative bars and keep headings with their explanations.`);
              generated = null;
            }
          }
          if (generated || !['interactive', 'slide'].includes(safeOutline.type)) return generated;
          const detail = diagnostics.join(' | ') || failureCode || 'Generator returned no valid scene content.';
          await retainFailedOutput('SCENE_CONTENT_INVALID', diagnostics.length ? diagnostics : [detail]);
          if (validationAttempt === 2 || failureCode === 'prompt-unavailable') {
            throw new SceneContentGenerationError('SCENE_CONTENT_INVALID', `Scene failed validation: ${detail}. Failed drafts were retained privately; this scene was not skipped.`);
          }
          repairFeedback = safeOutline.type === 'slide' ? `\nThe previous slide draft failed validation: ${detail}\nRegenerate the complete outline, retaining all scientific content and figures. ${SLIDE_LAYOUT_GUIDANCE}` : `\nThe previous interactive draft failed validation: ${detail}\nRegenerate a complete compact document from the full original source. Fix the reported HTML/JavaScript problem; preserve functional interactions and all source conditions. Do not merely append closing tags to broken code.`;
          await reportSceneRetry('content', { attempt: validationAttempt, maxAttempts: 2, reason: detail });
          }
          throw new SceneContentGenerationError('SCENE_CONTENT_INVALID', 'Scene validation attempts exhausted.');
        } catch (error) {
          return containPBLGenerationError(error, safeOutline.title);
        }
      })();
      return { safeOutline, content, reportSceneRetry };
    });
    for await (const prepared of orderedPrefetch(outlines, prepareContent, { windowSize: contentWindow, signal: options.signal })) {
      const index = prepared.index;
      const { safeOutline, content, reportSceneRetry } = prepared.value;
      const progressStart = 30 + Math.floor((index / Math.max(outlines.length, 1)) * 60);
      await options.onProgress?.({
        step: 'generating_scenes',
        progress: Math.max(progressStart, 31),
        message: `Generating scene ${index + 1}/${outlines.length}: ${safeOutline.title}`,
        scenesGenerated: generatedScenes,
        totalScenes: outlines.length,
      });

      if (!content) {
        throw new SceneContentGenerationError('SCENE_CONTENT_INVALID',
          `Scene "${safeOutline.title}" returned no content. The classroom cannot complete by silently omitting an outline.`);
      }

      const pageContents = expandGeneratedSlidePages(content);
      for (const [pageIndex, pageContent] of pageContents.entries()) {
      const pageOutline = { ...safeOutline,
        id: pageIndex ? `${safeOutline.id}_page_${pageIndex + 1}` : safeOutline.id,
        title: pageIndex ? `${safeOutline.title} (continued ${pageIndex + 1})` : safeOutline.title,
        order: generatedScenes + 1 };
      // The outline count is not a final page count: readable layout may split it.
      // Refresh this before every page so a recovered retry is no longer shown.
      await options.onProgress?.({
        step: 'generating_scenes',
        progress: Math.max(progressStart, 31),
        message: `Generating outline ${index + 1}/${outlines.length}, page ${pageIndex + 1}/${pageContents.length}: ${safeOutline.title}`,
        scenesGenerated: generatedScenes,
        totalScenes: generatedScenes + pageContents.length - pageIndex + outlines.length - index - 1,
      });
      const actionsAiCall = await getSceneActionsAiCall();
      const actions = await timings.measure('actions', { draft: draftAttempt, scene: index + 1, page: pageIndex + 1 }, () => withGenerationRetry(
        () =>
          generateSceneActions(pageOutline, pageContent, focusedNarrationCall(wrapGroundedAiCall(actionsAiCall, sourceContract, repairIssues, 'actions'), store.getState().scenes, pageIndex, pageContents.length), {
            agents,
            languageDirective,
            ctx: { pageIndex: generatedScenes + 1,
              totalPages: generatedScenes + pageContents.length - pageIndex + outlines.length - index - 1,
              allTitles: [...store.getState().scenes.map(item => item.title),
                ...pageContents.slice(pageIndex).map((_, offset) => offset + pageIndex ? `${safeOutline.title} (continued ${offset + pageIndex + 1})` : safeOutline.title),
                ...outlines.slice(index + 1).map(item => item.title)],
              previousSpeeches: store.getState().scenes.flatMap(scene =>
                (scene.actions ?? []).filter(action => action.type === 'speech').map(action => action.text)) },
          }),
        {
          label: `scene ${index + 1}/${outlines.length} actions`,
          onRetry: (event) => reportSceneRetry('actions', event),
        },
      ));
      log.info(`Scene "${safeOutline.title}": ${actions.length} actions`);

      const sceneId = createSceneWithActions(pageOutline, pageContent, actions, api);
      if (!sceneId) {
        throw new SceneContentGenerationError('SCENE_CONTENT_INVALID',
          `Scene "${pageOutline.title}" assembly or persistence validation failed; the classroom cannot complete without this scene.`);
      }

      generatedScenes += 1;
      }
      const progressEnd = 30 + Math.floor(((index + 1) / Math.max(outlines.length, 1)) * 60);
      await options.onProgress?.({
        step: 'generating_scenes',
        progress: Math.min(progressEnd, 90),
        message: `Completed ${index + 1}/${outlines.length} outlines; ${generatedScenes} pages generated`,
        scenesGenerated: generatedScenes,
        totalScenes: generatedScenes + outlines.length - index - 1,
      });
    }

    const draftScenes = retainOriginalSourceImages(compactAdjacentSlides(store.getState().scenes, layoutGeneratedSlidePages), sourceImages, stageId);
    store.setState({ scenes: draftScenes });
    if (draftScenes.length === 0) throw new Error('No scenes were generated');
    // Final visible media must exist before semantic verification; TTS runs only after it passes.
    if (input.enableImageGeneration || input.enableVideoGeneration) {
      await options.onProgress?.({ step: 'generating_media', progress: 90,
        message: 'Generating media files', scenesGenerated: draftScenes.length, totalScenes: draftScenes.length });
      const mediaMap = await generateMediaForClassroom(outlines, stageId, options.baseUrl);
      replaceMediaPlaceholders(draftScenes, mediaMap);
    }
    return draftScenes;
    };

    let scenes = await buildSceneDraft();
    if (sourceContract) {
      const attempts: NonNullable<Stage['sourceFidelity']>['attempts'] = [];
      // `scenes` changes only when a full draft has returned. A failed repair
      // may clear its working store, but must not discard the last full draft.
      const retainCompleteReviewDraft = async (phase: 'audit' | 'repair', attempt: number,
        error: unknown, priorAudit?: SourceFidelityAudit): Promise<never> => {
        const reason = error instanceof Error ? error.message : String(error);
        const code = typeof (error as { code?: unknown })?.code === 'string'
          ? String((error as { code: string }).code) : reason.match(/^([A-Z][A-Z_]+):/)?.[1] || 'SOURCE_OPERATION_FAILED';
        const failure = { phase, code, reason, classroomId: stageId };
        const audit: SourceFidelityAudit = { version: 1, method: 'model_semantic_audit_with_verified_evidence',
          passed: false, sourceSha256: sourceContract.sha256, requiredUnits: sourceContract.units.length,
          coveredUnits: priorAudit?.coveredUnits ?? 0, sourceImages: sourceContract.images.length,
          shownSourceImages: priorAudit?.shownSourceImages ?? 0, guarantee: false,
          issues: [...(priorAudit?.issues ?? []), { kind: 'invalid_audit',
            detail: `${phase} operation failed (${code}); the last complete draft was retained for review. ${reason}` }], failure };
        const draftArtifact = `source-fidelity-${phase}-failure-${attempt}.json`;
        await writeJsonFileAtomic(path.join(CLASSROOMS_DIR, stageId, draftArtifact),
          { version: 1, sourceSha256: sourceContract.sha256, attempt, failure, audit, scenes });
        attempts.push({ attempt, audit, draftArtifact });
        stage.sourceFidelity = { version: 1, status: 'needs_review', sourceSha256: sourceContract.sha256,
          guarantee: false, attempts };
        persisted = await persistClassroom({ id: stageId, stage, scenes }, options.baseUrl);
        throw new SourceFidelityError(audit, stageId, failure);
      };
      for (let attempt = 1; attempt <= 2; attempt += 1) {
        await options.onProgress?.({ step: 'generating_scenes', progress: 91,
          message: `Verifying source conditions, mechanisms, claims and figures (${attempt}/2)`,
          scenesGenerated: scenes.length, totalScenes: scenes.length });
        let audit: SourceFidelityAudit;
        try { audit = await timings.measure('source_audit', { attempt }, () => auditSourceFidelity(sourceContract, scenes, aiCall)); }
        catch (error) { return await retainCompleteReviewDraft('audit', attempt, error); }
        const draftArtifact = `source-fidelity-attempt-${attempt}.json`;
        // Keep the failed original model draft and its findings for transparent review.
        await writeJsonFileAtomic(path.join(CLASSROOMS_DIR, stageId, draftArtifact),
          { version: 1, sourceSha256: sourceContract.sha256, attempt, audit, scenes });
        attempts.push({ attempt, audit, draftArtifact });
        stage.sourceFidelity = { version: 1, status: audit.passed ? 'verified' : 'needs_review',
          sourceSha256: sourceContract.sha256, guarantee: false, attempts };
        if (audit.passed) break;
        if (attempt === 1) {
          await options.onProgress?.({ step: 'generating_scenes', progress: 31,
            message: 'Source verification found omissions or unsupported claims; regenerating once from the complete source',
            scenesGenerated: 0, totalScenes: outlines.length });
          try { scenes = await buildSceneDraft(audit.issues); }
          catch (error) { return await retainCompleteReviewDraft('repair', attempt + 1, error, audit); }
        } else {
          // Retain an explicitly unverified draft, without TTS/video or a ready result.
          persisted = await persistClassroom({ id: stageId, stage, scenes }, options.baseUrl);
          throw new SourceFidelityError(audit, stageId);
        }
      }
    }
    log.info(`Pipeline complete: ${scenes.length} scenes generated`);

    if (scenes.length === 0) {
      throw new Error('No scenes were generated');
    }

    // Phase: TTS generation
    let ttsCoverage: ClassroomTtsCoverage | undefined;
    let ttsFailureWarning: string | undefined;
    if (input.enableTTS) {
      await options.onProgress?.({
        step: 'generating_tts',
        progress: 94,
        message: 'Generating TTS audio',
        scenesGenerated: scenes.length,
        totalScenes: scenes.length,
      });

      try {
        ttsCoverage = await timings.measure('tts', {}, () => generateTTSForClassroom(
          scenes,
          stageId,
          options.baseUrl,
          options.signal,
          async ({ written, total }) => {
            await options.onProgress?.({
              step: 'generating_tts',
              progress: classroomTtsHeartbeatProgress(written, total),
              message: `Generating TTS audio (${written}/${total})`,
              scenesGenerated: scenes.length,
              totalScenes: scenes.length,
            });
          },
          options.ttsConfig,
        ));
      } catch (err) {
        if (isAbortError(err)) throw err;
        log.warn('TTS generation phase failed, continuing:', err);
        ttsCoverage = { written: 0, total: countNarratableSpeechActions(scenes) };
        ttsFailureWarning = TTS_PHASE_FAILED_WARNING;
      }
    }
    const ttsWarning = ttsResultWarning(ttsCoverage, ttsFailureWarning);

    await options.onProgress?.({
      step: 'persisting',
      progress: 98,
      message: 'Persisting classroom data',
      scenesGenerated: scenes.length,
      totalScenes: scenes.length,
    });

    // The id was reserved before media/TTS generation, so the process owns it and
    // this is an ordinary overwrite that replaces the placeholder.
    persisted = await persistClassroom({ id: stageId, stage, scenes }, options.baseUrl);

    log.info(`Classroom persisted: ${persisted.id}, URL: ${persisted.url}`);

    await options.onProgress?.({
      step: 'completed',
      progress: 100,
      message: ttsWarning ?? 'Classroom generation completed',
      scenesGenerated: persisted.scenes.length,
      totalScenes: persisted.scenes.length,
    });

    return {
      id: persisted.id,
      resolvedModel: resolvedConfiguration.resolvedModel,
      modelSnapshot: resolvedConfiguration.modelSnapshot,
      stageModels: {'generate-classroom': resolvedConfiguration.resolvedModel},
      url: persisted.url,
      stage: persisted.stage,
      scenes: persisted.scenes,
      scenesCount: persisted.scenes.length,
      createdAt: persisted.createdAt,
      ...(ttsCoverage ? { ttsCoverage } : {}),
      ...(ttsWarning ? { warning: ttsWarning } : {}),
    };
  } finally {
    try {
      await writeJsonFileAtomic(path.join(CLASSROOMS_DIR, stageId, 'generation-timings.json'), timings.snapshot());
    } catch { log.warn('Could not retain classroom phase timings'); }
    if (!persisted) {
      await releaseClassroomReservation(stageId);
    }
  }
}
