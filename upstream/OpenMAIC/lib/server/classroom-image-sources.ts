// DeepSteam: preserve document-reader figure provenance in classroom generation.
import { imageDimensionsFromDataUrl } from '@openmaic/generation';
import type { ClassroomDocumentContent, ClassroomImageSource, PdfImage, SourceDocumentLocator } from '@/lib/types/generation';

const numericLocatorKeys = new Set(['page', 'slide', 'paragraph', 'table', 'line_start', 'line_end', 'row', 'image']);
const locatorKeys = new Set([...numericLocatorKeys, 'page_kind', 'sheet', 'part', 'section']);

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function boundedString(value: unknown, max: number): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= max && !/[\u0000-\u001f\u007f]/.test(value);
}

function validLocator(value: unknown): value is SourceDocumentLocator {
  if (!record(value) || Object.keys(value).length === 0) return false;
  for (const [key, item] of Object.entries(value)) {
    if (!locatorKeys.has(key)) return false;
    if (numericLocatorKeys.has(key) && (!Number.isSafeInteger(item) || Number(item) <= 0)) return false;
    if (key === 'page_kind' && (item !== 'pdf_physical' || value.page === undefined)) return false;
    if (key === 'sheet' && !boundedString(item, 128)) return false;
    if (key === 'part' && (typeof item !== 'string' || !/^\/word\/(?:header\d+|footer\d+|footnotes|endnotes|comments)\.xml$/.test(item))) return false;
    if (key === 'section' && item !== 'word_supplement') return false;
  }
  if (value.line_end !== undefined && (value.line_start === undefined || Number(value.line_end) < Number(value.line_start))) return false;
  if (value.image !== undefined && Object.keys(value).length !== 1) return false;
  if ((value.part !== undefined || value.section !== undefined) &&
      (value.part === undefined || value.section !== 'word_supplement' || Object.keys(value).length !== 2)) return false;
  return true;
}

export function validClassroomImageSources(value: unknown, imageCount: number): value is ClassroomImageSource[] {
  return Array.isArray(value) && value.length === imageCount && value.every((item, index) => {
    if (!record(item) || item.image_index !== index + 1) return false;
    if (!boundedString(item.asset_id, 512) || !validLocator(item.locator)) return false;
    if (typeof item.document_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(item.document_sha256)) return false;
    return item.source_document_name === undefined || (boundedString(item.source_document_name, 160) && !/[\\/]/.test(item.source_document_name));
  });
}

export function buildClassroomSourceImages(content?: ClassroomDocumentContent): PdfImage[] {
  if (content?.image_sources !== undefined && !validClassroomImageSources(content.image_sources, content.images.length)) {
    throw new Error('Invalid source image metadata');
  }
  return (content?.images ?? []).map((src, index) => {
    const source = content?.image_sources?.[index];
    return {
      id: `img_${index + 1}`,
      src,
      pageNumber: source?.locator.page ?? 0,
      ...imageDimensionsFromDataUrl(src),
      ...(source ? {
        originalId: source.asset_id,
        sourceDocumentId: source.document_sha256,
        sourceDocumentName: source.source_document_name,
        sourceLocator: { ...source.locator },
        description: `Source figure from ${source.source_document_name || 'document'}; original location: ${JSON.stringify(source.locator)}.`,
      } : {
        description: 'Uploaded source figure; page number is not supplied to this endpoint.',
      }),
    };
  });
}
