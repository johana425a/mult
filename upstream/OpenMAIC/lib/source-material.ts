import type { ClassroomSourceMaterial, Scene, ScenePatch } from '@/lib/types/stage';
import type { Stage } from '@/lib/types/stage';

/** A model/editor change invalidates prior semantic evidence until the whole lesson is re-audited. */
export function invalidateSourceFidelity(stage: Stage): Stage {
  if (!stage.sourceFidelity) return stage;
  return { ...stage, sourceFidelity: { ...stage.sourceFidelity, status: 'needs_review' } };
}

function semanticActions(actions: Scene['actions']): string {
  return JSON.stringify((actions ?? []).map(action => {
    const record = { ...action } as Record<string, unknown>;
    for (const key of ['id', 'audioId', 'audioUrl', 'audioInvalidated', 'voice', 'speed']) delete record[key];
    return record;
  }));
}

/** Audio caching alone preserves evidence; changed text, pictures, actions or page structure do not. */
export function hasSourceRelevantSceneChange(scene: Scene | undefined, updates: ScenePatch): boolean {
  if (!scene) return true;
  return (updates.content !== undefined && JSON.stringify(updates.content) !== JSON.stringify(scene.content)) ||
    (updates.title !== undefined && updates.title !== scene.title) ||
    (updates.type !== undefined && updates.type !== scene.type) ||
    (updates.order !== undefined && updates.order !== scene.order) ||
    (updates.actions !== undefined && semanticActions(updates.actions) !== semanticActions(scene.actions));
}

// These are prompt budgets, not storage truncation. Persist the complete original.
export const SOURCE_PROMPT_CHARACTERS = 2400;
export const OTHER_SCENES_PROMPT_CHARACTERS = 1200;

export function createSourceMaterial(text?: string, complete = true): ClassroomSourceMaterial | undefined {
  if (typeof text !== 'string' || !text.trim()) return undefined;
  return { kind: 'uploaded_document', text, originalCharacters: text.length, complete };
}

function searchTerms(query: string): string[] {
  const terms: string[] = query.toLowerCase().match(/[\p{L}\p{N}]{2,}/gu) ?? [];
  const cjk = query.match(/[\u3400-\u9fff]{2,}/g) ?? [];
  for (const word of cjk) {
    for (let i = 0; i < word.length - 1; i++) terms.push(word.slice(i, i + 2));
  }
  return [...new Set(terms)].slice(0, 80);
}

/** Quote exact source slices. Retrieval never asks a model to rewrite the material. */
export function selectSourceExcerpt(
  text: string,
  query = '',
  maxCharacters = SOURCE_PROMPT_CHARACTERS,
): { text: string; excerpted: boolean } {
  if (text.length <= maxCharacters) return { text, excerpted: false };
  const terms = searchTerms(query);
  const chunks = (text.match(/[\s\S]{1,700}/g) ?? []).map((content, index) => ({
    index,
    content,
    score: terms.reduce((score, term) => score + (content.toLowerCase().includes(term) ? 1 : 0), 0),
  }));
  // Preserve document context, then prefer passages matching the question/scene.
  const ranked = [...chunks.slice(1)].sort((a, b) => b.score - a.score || a.index - b.index);
  const selected = [chunks[0]];
  let used = chunks[0].content.length;
  for (const chunk of ranked) {
    if (used + chunk.content.length + 8 > maxCharacters) continue;
    selected.push(chunk);
    used += chunk.content.length + 8;
  }
  return {
    text: selected.sort((a, b) => a.index - b.index).map((chunk) => chunk.content).join('\n[…]\n')
      .slice(0, maxCharacters),
    excerpted: true,
  };
}

function slideText(scene: Scene): string {
  if (scene.content.type !== 'slide') return '';
  return scene.content.canvas.elements.map((element) => {
    if (element.type === 'text') return element.content.replace(/<[^>]*>/g, ' ').trim();
    if (element.type === 'latex') return element.latex;
    return '';
  }).filter(Boolean).join('\n');
}

/** Supplement current-slide summaries without exposing unsubmitted quiz answers. */
export function otherSceneContext(scenes: Scene[], currentSceneId: string | null, query = ''): string {
  const terms = searchTerms(query);
  const entries = scenes.filter((scene) => scene.id !== currentSceneId && scene.content.type === 'slide')
    .map((scene, order) => {
      const text = slideText(scene);
      return {
        order,
        text: `Scene "${scene.title}" (${scene.id}):\n${text}`,
        score: terms.reduce((score, term) => score + (text.toLowerCase().includes(term) ? 1 : 0), 0),
      };
    }).filter((entry) => entry.text.trim()).sort((a, b) => b.score - a.score || a.order - b.order);
  let remaining = OTHER_SCENES_PROMPT_CHARACTERS;
  const selected: string[] = [];
  for (const entry of entries) {
    if (remaining < 100) break;
    const excerpt = entry.text.slice(0, Math.min(500, remaining));
    selected.push(excerpt);
    remaining -= excerpt.length + 2;
  }
  return selected.join('\n\n');
}
