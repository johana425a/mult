import { describe, expect, it, vi } from 'vitest';
import { createHash } from 'node:crypto';
import { hasVerifiedClassroomImageInput, classroomUserContent, type ClassroomInputModel } from '@/lib/server/classroom-image-input';
import { createSourceContract, wrapGroundedAiCall } from '@/lib/server/source-grounding';
import { deepsteamDocumentArtifact } from '@/lib/document/extractors/deepsteam-local';
import { documentArtifactToParsedPdfContent } from '@/lib/document/pdf-compat';
import { getDefaultThinkingConfig, normalizeThinkingConfig } from '@/lib/ai/thinking-config';
import { llmApiError } from '@/lib/server/llm-error-response';

const png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==';
const model = (verified: boolean, contextWindow = 1_000_000): ClassroomInputModel => ({
  modelInfo: { id: 'selected-fixture', name: 'Selected fixture', contextWindow, capabilities: { vision: true } },
  resolvedModel: { provider: 'fixture-provider', provider_label: 'Fixture provider', model: 'selected-fixture',
    model_name: 'Selected fixture', selection_source: 'override', capabilities: { vision: true, vision_verified: verified },
    image_verification: { verified, status: verified ? 'verified' : 'not_verified', supported: true } },
});
const images = [{ id: 'img_1', src: png }];

describe('r9 selected classroom image input (fixtures; no provider calls)', () => {
  it('defaults supported reasoning to high and preserves explicit choices', () => {
    const capability = { control: 'effort' as const, requestAdapter: 'openai' as const,
      effortValues: ['low', 'medium', 'high'] as const, defaultEffort: 'medium' as const };
    const thinking = { ...capability, effortValues: [...capability.effortValues] };
    expect(getDefaultThinkingConfig(thinking)?.effort).toBe('high');
    expect(normalizeThinkingConfig(thinking, { mode: 'enabled', effort: 'low' })?.effort).toBe('low');
    expect(getDefaultThinkingConfig({ control: 'none' })).toBeUndefined();
  });
  it('rejects catalog vision and model config without successful image verification', () => {
    expect(hasVerifiedClassroomImageInput(model(false))).toBe(false);
    expect(() => classroomUserContent(model(false), 'Read the original', 'Explain', images))
      .toThrow('model_image_unverified');
    expect(classroomUserContent(model(false), 'Read the text', 'Original text', undefined)).toBe('Original text');
  });

  it('returns an actionable image verification error instead of a generic retry message', async () => {
    let failure: unknown;
    try { classroomUserContent(model(false), 'Read original evidence', 'Explain', images); }
    catch (error) { failure = error; }
    const response = llmApiError(failure);
    const body = await response.json();
    expect(response.status).toBe(409);
    expect(body.errorCode).toBe('model_image_unverified');
    expect(body.error).toContain('has not passed image-input verification');
    expect(body.error).toContain('Settings');
  });

  it('passes actual image parts for the frozen model and refuses stale contradictory verification', () => {
    const selected = model(true);
    const content = classroomUserContent(selected, 'Original source is evidence', 'Explain page 3', images);
    expect(Array.isArray(content)).toBe(true);
    expect((content as Array<{ type: string }>).filter(part => part.type === 'image')).toHaveLength(1);
    expect(selected.resolvedModel?.model).toBe('selected-fixture');
    selected.resolvedModel!.image_verification!.verified = false;
    expect(() => classroomUserContent(selected, 'Original source', 'Explain', images)).toThrow('model_image_unverified');
    delete selected.resolvedModel!.image_verification;
    expect(() => classroomUserContent(selected, 'Original source', 'Explain', images)).toThrow('model_image_unverified');
  });

  it('uses selected capacity rather than the old local window, and requests segmentation without truncation', () => {
    const longText = 'Original complete source. '.repeat(2500);
    expect(() => classroomUserContent(model(true, 500_000), 'Read', longText, images)).not.toThrow();
    expect(() => classroomUserContent(model(true, 16_384), 'Read', longText, images)).toThrow('SOURCE_CONTEXT_LIMIT');
    expect(longText).toContain('Original complete source.');
    expect(() => classroomUserContent(model(true, 0), 'Read', 'Explain', images)).toThrow('model_context_unavailable');
  });

  it('keeps every scan/figure in grounded requests when the upstream relevance selector omits it', async () => {
    const originals = [1, 2].map(number => ({ id: `img_${number}`, src: png, pageNumber: number,
      sourceLocator: { page: number, page_kind: 'pdf_physical' as const } }));
    const contract = createSourceContract('Original full source text.', originals, 500_000)!;
    const underlying = vi.fn().mockResolvedValue('fixture-response');
    const call = wrapGroundedAiCall(underlying, contract);
    expect(await call('Read source evidence', 'Teach it', [{ id: 'img_2', src: png }])).toBe('fixture-response');
    expect(underlying.mock.calls[0][2].map((image: { id: string }) => image.id)).toEqual(['img_1', 'img_2']);
    expect(underlying.mock.calls[0][1]).toContain('Original full source text.');
    expect(createSourceContract('', originals, 500_000)?.images).toHaveLength(2);
    expect(createSourceContract('', originals, 500_000)?.text).toContain('visual content requires recognition');
  });

  it('imports image-ready partial sources while preserving pending status and real locations', () => {
    const buffer = Buffer.from('synthetic scanned source');
    const digest = createHash('sha256').update(buffer).digest('hex');
    const result = { ok: true as const, status: 'partial', recovery: { ingestion_id: 'a'.repeat(32),
      source_ref: 'fixture', document_sha256: digest }, document: { sha256: digest, unit_count: 1 },
      units: [{ text: '[Original page image; not yet recognized]', locator: { page: 3, page_kind: 'pdf_physical' as const },
        status: 'visual_pending', coverage: { visual_status: 'pending' } }],
      images: [{ base64: png.split(',')[1], mime_type: 'image/png', source_asset_id: 'pdf-page:3', unit_index: 0,
        locator: { page: 3, page_kind: 'pdf_physical' as const } }], warnings: ['Original pixels require selected-model reading'],
      coverage: { source_units_enumerated: true, text_layer_complete: true, document_fully_read: false },
      requires_image_reading: true, visual_pending: true, next_tool: 'read_document_image' };
    const artifact = deepsteamDocumentArtifact(result, { buffer, fileName: 'fixture.pdf', mimeType: 'application/pdf',
      config: { providerId: 'deepsteam-local' } });
    const parsed = documentArtifactToParsedPdfContent(artifact);
    expect(parsed.images).toEqual([png]);
    expect(parsed.image_sources?.[0].locator).toEqual({ page: 3, page_kind: 'pdf_physical' });
    expect(parsed.metadata?.readingStatus).toBe('partial');
    expect(parsed.metadata?.requiresImageReading).toBe(true);
    expect((parsed.metadata?.coverage as Record<string, unknown>).document_fully_read).toBe(false);
    result.coverage.source_units_enumerated = false;
    expect(() => deepsteamDocumentArtifact(result, { buffer, mimeType: 'application/pdf', config: { providerId: 'deepsteam-local' } }))
      .toThrow('completeness');
  });
});
