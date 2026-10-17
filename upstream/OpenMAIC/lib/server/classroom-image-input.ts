/** DeepSteam r9: selected-model image input, with no provider substitution. */
import { buildVisionUserContent, type AICallFn } from '@openmaic/generation';
import type { ResolvedModel } from './resolve-model';
import type { ThinkingConfig } from '@/lib/types/provider';
import { assertPromptFits, estimatePromptInputTokens } from './source-grounding';

export const IMAGE_INPUT_UNVERIFIED = 'The current model has not passed image-input verification. Switch to an image-capable model (for example V4.1-Flash) and verify its image input in Settings.';

export class ClassroomImageInputError extends Error {
  readonly isRetryable = false;
  constructor(readonly code: 'model_image_unverified' | 'model_context_unavailable' | 'SOURCE_CONTEXT_LIMIT', message: string) {
    super(`${code}: ${message}`);
    this.name = 'ClassroomImageInputError';
  }
}

export class ClassroomOutputLimitError extends Error {
  readonly code = 'OUTPUT_LIMIT';
  readonly isRetryable = false;
  constructor() {
    super('OUTPUT_LIMIT: the selected model reached its available output allowance before completing the response. Select fewer complete pages or sections; no incomplete response was accepted as finished.');
    this.name = 'ClassroomOutputLimitError';
  }
}

export function assertClassroomOutputComplete(finishReason?: string): void {
  if (finishReason === 'length') throw new ClassroomOutputLimitError();
}

export type ClassroomInputModel = Pick<ResolvedModel, 'resolvedModel' | 'modelInfo'> & { thinkingConfig?: ThinkingConfig };
type Images = NonNullable<Parameters<AICallFn>[2]>;

/** Only server-resolved probe evidence may enable image calls. A caller's
 * model name, catalog vision flag, or supplied model config is insufficient. */
export function hasVerifiedClassroomImageInput(value: ClassroomInputModel): boolean {
  return value.resolvedModel?.capabilities?.vision_verified === true
    && value.resolvedModel?.image_verification?.verified === true;
}

export function assertClassroomImageInput(value: ClassroomInputModel, images?: Images): void {
  if (!images?.length) return;
  if (!hasVerifiedClassroomImageInput(value)) throw new ClassroomImageInputError('model_image_unverified', IMAGE_INPUT_UNVERIFIED);
  if (images.length > 20) throw new ClassroomImageInputError('SOURCE_CONTEXT_LIMIT',
    'This source contains more than 20 images. Select fewer complete pages or slides for this lesson. All originals are retained; no image was omitted.');
  if (!Number.isSafeInteger(value.modelInfo?.contextWindow) || (value.modelInfo?.contextWindow ?? 0) <= 0) {
    throw new ClassroomImageInputError('model_context_unavailable',
      'The selected model has no configured context capacity. Configure its actual context window in model settings, then retry or select fewer pages.');
  }
}

/** The same frozen model receives every supplied pixel. Text-only models are
 * rejected, rather than stripping images and claiming that the source was read. */
export function classroomUserContent(value: ClassroomInputModel, system: string, user: string, images?: Images) {
  assertClassroomImageInput(value, images);
  if (value.modelInfo?.contextWindow) assertPromptFits(system, user, images?.length ?? 0, value.modelInfo.contextWindow);
  return images?.length ? buildVisionUserContent(user, images) : user;
}

export function classroomContextTokens(value: ClassroomInputModel): number {
  const context = value.modelInfo?.contextWindow;
  if (!Number.isSafeInteger(context) || (context ?? 0) <= 0) {
    throw new ClassroomImageInputError('model_context_unavailable',
      'Configure this selected model\'s actual context window in Settings before supplying a document. No former local-model window or guessed capacity was substituted.');
  }
  return context!;
}

/** Allocate the actual provider output ceiling within this request's remaining
 * context, without a product-owned 4k cap or a silent source-prefix substitution. */
export function classroomOutputTokens(value: ClassroomInputModel, system: string, user: string, images?: Images): number | undefined {
  const context = value.modelInfo?.contextWindow;
  const ceiling = value.modelInfo?.outputWindow;
  if (context) {
    assertPromptFits(system, user, images?.length ?? 0, context);
    const remaining = context - estimatePromptInputTokens(system, user, images?.length ?? 0);
    const allowed = Number.isSafeInteger(ceiling) && (ceiling ?? 0) > 0 ? Math.min(ceiling!, remaining) : undefined;
    const reasoningBudget = value.thinkingConfig?.mode === 'disabled' ? 0 : value.thinkingConfig?.budgetTokens;
    if (allowed && reasoningBudget && reasoningBudget > 0 && reasoningBudget >= allowed) {
      throw new ClassroomImageInputError('SOURCE_CONTEXT_LIMIT',
        'The complete source leaves insufficient output space for this selected reasoning budget and an answer. Select fewer complete pages or explicitly change that budget; no source or reasoning choice was silently reduced.');
    }
    return allowed;
  }
  return Number.isSafeInteger(ceiling) && (ceiling ?? 0) > 0 ? ceiling : undefined;
}
