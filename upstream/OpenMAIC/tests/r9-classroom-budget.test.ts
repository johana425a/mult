/** Capacity fixtures only: no provider/network inference or user data. */
import { describe, expect, it } from 'vitest';
import { getDefaultThinkingConfig, normalizeThinkingConfig } from '@/lib/ai/thinking-config';
import { assertClassroomOutputComplete, classroomOutputTokens, classroomContextTokens, type ClassroomInputModel } from '@/lib/server/classroom-image-input';
import { assertPromptFits, createSourceContract, estimatePromptInputTokens } from '@/lib/server/source-grounding';
import { buildDocumentBundle, type ParsedDocumentPart } from '@/lib/document/bundle';
import { buildOutlinePrompt } from '../packages/@openmaic/generation/src/outline-generator';

const model = (context = 500_000, output = 128_000): ClassroomInputModel => ({
  modelInfo: { id: 'fixture-model', name: 'Fixture model', contextWindow: context, outputWindow: output },
});

describe('r9 highest regular reasoning and actual classroom capacity', () => {
  it('chooses the highest supported regular effort while retaining explicit low or off', () => {
    const full = { control: 'effort' as const, requestAdapter: 'openai' as const,
      effortValues: ['none', 'low', 'medium', 'high', 'xhigh', 'max'] as const, defaultEffort: 'medium' as const };
    const capability = { ...full, effortValues: [...full.effortValues] };
    expect(getDefaultThinkingConfig(capability)?.effort).toBe('max');
    expect(normalizeThinkingConfig(capability, undefined)?.effort).toBe('max');
    expect(normalizeThinkingConfig(capability, { mode: 'enabled', effort: 'low' })?.effort).toBe('low');
    expect(normalizeThinkingConfig(capability, { mode: 'disabled' })?.effort).toBe('none');
    expect(getDefaultThinkingConfig({ ...capability, effortValues: ['low', 'high', 'xhigh'] })?.effort).toBe('xhigh');
    expect(getDefaultThinkingConfig({ ...capability, effortValues: ['low', 'high'] })?.effort).toBe('high');
  });

  it('uses supported levels, toggle and bounded reasoning budgets without changing explicit choices', () => {
    expect(getDefaultThinkingConfig({ control: 'level', requestAdapter: 'google',
      levelValues: ['low', 'high'], defaultLevel: 'low' })?.level).toBe('high');
    expect(getDefaultThinkingConfig({ control: 'toggle', requestAdapter: 'qwen', defaultEnabled: false })?.mode).toBe('enabled');
    const budget = { control: 'toggle-budget' as const, requestAdapter: 'anthropic' as const,
      budgetRange: { min: 1024, max: 64000 }, defaultBudgetTokens: 2048 };
    expect(getDefaultThinkingConfig(budget)?.budgetTokens).toBe(64000);
    expect(normalizeThinkingConfig(budget, { mode: 'enabled', budgetTokens: 4096 })?.budgetTokens).toBe(4096);
    expect(normalizeThinkingConfig(budget, { mode: 'disabled', budgetTokens: 4096 })?.mode).toBe('disabled');
  });

  it('uses the actual 128k output ceiling instead of the former 4k product limit', () => {
    expect(classroomOutputTokens(model(), 'Source evidence', 'Teach this chapter in detail')).toBe(128_000);
    const text = 'Original source. '.repeat(23_000);
    const expected = 500_000 - estimatePromptInputTokens('', text, 0);
    expect(classroomOutputTokens(model(), '', text)).toBe(Math.min(128_000, expected));
    expect(classroomOutputTokens(model(32_768, 32_768), '', 'a'.repeat(60_000)))
      .toBe(32_768 - estimatePromptInputTokens('', 'a'.repeat(60_000), 0));
  });

  it('does not reserve an arbitrary 3k output block, and refuses true full-window input', () => {
    expect(() => assertPromptFits('', 'a'.repeat(13_800), 0, 5000)).not.toThrow();
    expect(classroomOutputTokens(model(5000, 8192), '', 'a'.repeat(13_800))).toBe(272);
    expect(() => classroomOutputTokens(model(5000, 8192), '', 'a'.repeat(15_000))).toThrow('SOURCE_CONTEXT_LIMIT');
    const unknown = model();
    delete unknown.modelInfo!.contextWindow;
    expect(() => classroomContextTokens(unknown)).toThrow('model_context_unavailable');
  });

  it('keeps complete sources above 50k characters and 180 units when the selected model fits', () => {
    const text = 'Complete original clause. '.repeat(2500) + 'ORIGINAL_END_SENTINEL';
    const contract = createSourceContract(text, [], 500_000)!;
    expect(contract.text).toBe(text);
    expect(contract.units.length).toBeGreaterThan(180);
    expect(contract.units.at(-1)?.text).toContain('ORIGINAL_END_SENTINEL');
    expect(() => createSourceContract(text, [], 8192)).toThrow('SOURCE_CONTEXT_LIMIT');
    const prompt = buildOutlinePrompt({ requirement: 'Teach the complete supplied source' }, { pdfText: text });
    expect(prompt.user).toContain('ORIGINAL_END_SENTINEL');
  });

  it('retains all bundle text or explicitly requests a smaller scope instead of clipping', () => {
    const text = 'Original source clause. '.repeat(2500) + 'BUNDLE_END_SENTINEL';
    const part: ParsedDocumentPart = { source: { id: 'fixture-source', name: 'fixture.md', order: 1, size: text.length },
      text, rawTextLength: text.length, images: [] };
    const bundle = buildDocumentBundle([part]);
    expect(bundle.text).toContain(text);
    expect(bundle.text).toContain('BUNDLE_END_SENTINEL');
    expect(() => buildDocumentBundle([part], { maxChars: 5000 })).toThrow('no text was clipped');
    expect(() => createSourceContract('a'.repeat(4 * 1024 * 1024 + 1), [], 8_000_000)).toThrow('memory limit');
  });

  it('will not silently lower an explicit reasoning budget when the full source cannot fit', () => {
    const selected = model(20_000, 16_000);
    selected.thinkingConfig = { mode: 'enabled', budgetTokens: 12_000 };
    expect(() => classroomOutputTokens(selected, '', 'a'.repeat(30_000))).toThrow('reasoning choice was silently reduced');
    expect(selected.thinkingConfig.budgetTokens).toBe(12_000);
  });

  it('rejects output-limit responses instead of accepting a finished-looking prefix', () => {
    expect(() => assertClassroomOutputComplete('stop')).not.toThrow();
    expect(() => assertClassroomOutputComplete('length')).toThrow('no incomplete response was accepted');
  });
});
