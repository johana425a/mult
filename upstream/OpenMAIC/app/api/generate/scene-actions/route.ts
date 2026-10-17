/**
 * Scene Actions Generation API
 *
 * Generates actions for a scene given its outline and content,
 * then assembles the complete Scene object.
 * This is the second half of the two-step scene generation pipeline.
 */

import { NextRequest } from 'next/server';
import { callLLM } from '@/lib/ai/llm';
import { rethrowIfGenerationCancelled, throwIfGenerationAborted } from '@/lib/server/generation-cancellation';
import {
  generateSceneActions,
  buildCompleteScene,
  type SceneGenerationContext,
  type AgentInfo,
} from '@openmaic/generation';
import type { SceneOutline } from '@/lib/types/generation';
import type {
  GeneratedSlideContent,
  GeneratedQuizContent,
  GeneratedInteractiveContent,
  GeneratedPBLContent,
} from '@/lib/types/generation';
import type { SpeechAction } from '@/lib/types/action';
import type { PBLContent } from '@/lib/types/stage';
import { createLogger } from '@/lib/logger';
import { normalizeLegacyPBLContent } from '@/lib/pbl/legacy/read';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { llmApiError } from '@/lib/server/llm-error-response';
import { resolveModelFromRequest } from '@/lib/server/resolve-model';
import { assertClassroomOutputComplete, classroomUserContent, classroomOutputTokens, classroomContextTokens } from '@/lib/server/classroom-image-input';
import { resolveVisionImagesForPrompt } from '@/lib/persistence/resolve-vision-images';
import { contractFromMaterial, wrapGroundedAiCall } from '@/lib/server/source-grounding';
import type { ClassroomSourceMaterial } from '@/lib/types/stage';

const log = createLogger('Scene Actions API');

export const maxDuration = 60;

export async function POST(req: NextRequest) {
  let outlineTitle: string | undefined;
  let resolvedModelString: string | undefined;
  try {
    throwIfGenerationAborted(req.signal);
    const body = await req.json();
    throwIfGenerationAborted(req.signal);
    const {
      outline,
      allOutlines,
      content,
      stageId,
      agents,
      previousSpeeches: incomingPreviousSpeeches,
      userProfile,
      languageDirective,
      sourceMaterial,
    } = body as {
      outline: SceneOutline;
      allOutlines: SceneOutline[];
      content:
        | GeneratedSlideContent
        | GeneratedQuizContent
        | GeneratedInteractiveContent
        | GeneratedPBLContent
        | PBLContent;
      stageId: string;
      agents?: AgentInfo[];
      previousSpeeches?: string[];
      userProfile?: string;
      languageDirective?: string;
      sourceMaterial?: ClassroomSourceMaterial;
    };

    // Validate required fields
    if (!outline) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'outline is required');
    }
    if (!allOutlines || allOutlines.length === 0) {
      return apiError(
        'MISSING_REQUIRED_FIELD',
        400,
        'allOutlines is required and must not be empty',
      );
    }
    if (!content) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'content is required');
    }
    if (!stageId) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'stageId is required');
    }

    // ── Model resolution from request headers/body ──
    const {
      model: languageModel,
      modelInfo,
      modelString,
      thinkingConfig,
      resolvedModel,
    } = await resolveModelFromRequest(req, body, 'scene-actions');
    throwIfGenerationAborted(req.signal);
    outlineTitle = outline?.title;
    resolvedModelString = modelString;

    // Detect vision capability
    const imageInputModel = { modelInfo, resolvedModel, thinkingConfig };

    // AI call function (actions typically don't use vision, but kept for consistency)
    const aiCall = async (
      systemPrompt: string,
      userPrompt: string,
      images?: Array<{ id: string; src: string }>,
    ): Promise<string> => {
      throwIfGenerationAborted(req.signal);
      if (images?.length) {
        const resolvedImages = await resolveVisionImagesForPrompt(images, req.headers);
        throwIfGenerationAborted(req.signal);
        if (resolvedImages.length !== images.length) throw new Error(
          'SOURCE_IMAGE_UNAVAILABLE: original source pixels are unavailable. No image was silently omitted.');
        const result = await callLLM(
          {
            model: languageModel,
            system: systemPrompt,
            messages: [
              {
                role: 'user' as const,
                content: classroomUserContent(imageInputModel, systemPrompt, userPrompt, resolvedImages),
              },
            ],
            maxOutputTokens: classroomOutputTokens(imageInputModel, systemPrompt, userPrompt, resolvedImages),
            maxRetries: 0,
            abortSignal: req.signal,
          },
          'scene-actions',
          undefined,
          thinkingConfig,
        );
        throwIfGenerationAborted(req.signal);
        assertClassroomOutputComplete(result.finishReason);
        return result.text;
      }
      const result = await callLLM(
        {
          model: languageModel,
          system: systemPrompt,
          prompt: userPrompt,
          maxOutputTokens: classroomOutputTokens(imageInputModel, systemPrompt, userPrompt),
          maxRetries: 0,
          abortSignal: req.signal,
        },
        'scene-actions',
        undefined,
        thinkingConfig,
      );
      throwIfGenerationAborted(req.signal);
      assertClassroomOutputComplete(result.finishReason);
      return result.text;
    };

    // ── Build cross-scene context ──
    const allTitles = allOutlines.map((o) => o.title);
    const pageIndex = allOutlines.findIndex((o) => o.id === outline.id);
    const ctx: SceneGenerationContext = {
      pageIndex: (pageIndex >= 0 ? pageIndex : 0) + 1,
      totalPages: allOutlines.length,
      allTitles,
      previousSpeeches: incomingPreviousSpeeches ?? [],
    };

    // ── Generate actions ──
    log.info(`Generating actions: "${outline.title}" (${outline.type}) [model=${modelString}]`);

    const generationContent = (
      'type' in content && content.type === 'pbl' ? normalizeLegacyPBLContent(content) : content
    ) as
      | GeneratedSlideContent
      | GeneratedQuizContent
      | GeneratedInteractiveContent
      | GeneratedPBLContent;

    const actions = await generateSceneActions(outline, generationContent,
      wrapGroundedAiCall(aiCall, contractFromMaterial(sourceMaterial,
        sourceMaterial ? classroomContextTokens(imageInputModel) : undefined), [], 'actions'), {
      ctx,
      agents,
      userProfile,
      languageDirective,
    });
    throwIfGenerationAborted(req.signal);

    log.info(`Generated ${actions.length} actions for: "${outline.title}"`);

    // ── Build complete scene ──
    const scene = buildCompleteScene(outline, generationContent, actions, stageId);

    if (!scene) {
      log.error(`Failed to build scene: "${outline.title}"`);

      return apiError('GENERATION_FAILED', 500, `Failed to build scene: ${outline.title}`);
    }

    // ── Extract speeches for cross-scene coherence ──
    const outputPreviousSpeeches = (scene.actions || [])
      .filter((a): a is SpeechAction => a.type === 'speech')
      .map((a) => a.text);

    log.info(
      `Scene assembled successfully: "${outline.title}" — ${scene.actions?.length ?? 0} actions`,
    );

    return apiSuccess({ scene, previousSpeeches: outputPreviousSpeeches });
  } catch (error) {
    rethrowIfGenerationCancelled(error, req.signal);
    log.error(
      `Scene actions generation failed [scene="${outlineTitle ?? 'unknown'}", model=${resolvedModelString ?? 'unknown'}]:`,
      error,
    );
    return llmApiError(error);
  }
}
