import { NextRequest, NextResponse } from 'next/server';
import {
  isServerConfiguredProvider,
  resolvePDFApiKey,
  resolvePDFBaseUrl,
} from '@/lib/server/provider-config';
import type { PDFProviderId } from '@/lib/pdf/types';
import type { ParsedPdfContent } from '@/lib/types/pdf';
import { documentArtifactToParsedPdfContent, extractDocument } from '@/lib/document';
import { createLogger } from '@/lib/logger';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { checkClientDocumentExtractorBaseUrl } from '@/lib/server/client-extractor-endpoint';
import { MAX_EXTRACT_DOCUMENT_FILE_SIZE_BYTES } from '@/lib/constants/generation';
import { withRequestOwnerId } from '@/lib/server/agent-runtime/with-owner';
import { withOwnerResponseHeaders } from '@/lib/server/agent-runtime/route-response';
import { DocumentExtractionError } from '@/lib/document/extractors/deepsteam-local';
const log = createLogger('Parse PDF');
export const runtime = 'nodejs';

async function handlePost(req: NextRequest, ownerScope: string) {
  let pdfFileName: string | undefined;
  let resolvedProviderId: string | undefined;
  try {
    const contentType = req.headers.get('content-type') || '';
    if (!contentType.includes('multipart/form-data')) {
      log.error('Invalid Content-Type for PDF upload:', contentType);
      return apiError(
        'INVALID_REQUEST',
        400,
        `Invalid Content-Type: expected multipart/form-data, got "${contentType}"`,
      );
    }

    const formData = await req.formData();
    const pdfFile = formData.get('pdf') as File | null;
    const providerId = formData.get('providerId') as PDFProviderId | null;
    const apiKey = formData.get('apiKey') as string | null;
    const baseUrl = formData.get('baseUrl') as string | null;

    if (!pdfFile || typeof pdfFile === 'string') {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'No PDF file provided');
    }

    // providerId is required from the client — no server-side store to fall back to
    if (pdfFile.size > MAX_EXTRACT_DOCUMENT_FILE_SIZE_BYTES) return apiError('INVALID_REQUEST', 413, 'Course material file is too large. Maximum size is 200MB.');
    const effectiveProviderId = providerId || ('deepsteam-local' as PDFProviderId);
    pdfFileName = pdfFile?.name;
    resolvedProviderId = effectiveProviderId;

    // Managed providers are admin-owned: ignore any client-sent key/baseUrl.
    const local = effectiveProviderId === 'deepsteam-local';
    const managed = !local && isServerConfiguredProvider('pdf', effectiveProviderId);
    let clientBaseUrl = local || managed ? undefined : baseUrl || undefined;
    if (clientBaseUrl) {
      const checked = await checkClientDocumentExtractorBaseUrl(effectiveProviderId, clientBaseUrl);
      if (!checked.ok) {
        return apiError('INVALID_URL', 403, checked.message);
      }
      clientBaseUrl = checked.baseUrl;
    }

    const config = local ? { providerId: effectiveProviderId } : {
      providerId: effectiveProviderId,
      apiKey: resolvePDFApiKey(effectiveProviderId, managed ? undefined : apiKey || undefined),
      baseUrl: resolvePDFBaseUrl(effectiveProviderId, clientBaseUrl),
      managed,
    };

    // Convert PDF to buffer
    const arrayBuffer = await pdfFile.arrayBuffer();
    const buffer = Buffer.from(arrayBuffer);

    // Route the existing PDF API through the document extraction boundary.
    const artifact = await extractDocument({
      buffer,
      fileName: pdfFile.name,
      fileSize: pdfFile.size,
      mimeType: 'application/pdf',
      config,
      serverContext: { ownerScope },
    });
    const result = documentArtifactToParsedPdfContent(artifact);

    // Add file metadata
    const resultWithMetadata: ParsedPdfContent = {
      ...result,
      metadata: {
        ...result.metadata,
        pageCount: result.metadata?.pageCount ?? 0, // Ensure pageCount is always a number
        fileName: pdfFile.name,
        fileSize: pdfFile.size,
      },
    };

    return apiSuccess({ data: resultWithMetadata });
  } catch (error) {
    log.error(
      `PDF parsing failed [provider=${resolvedProviderId ?? 'unknown'}, file="${pdfFileName ?? 'unknown'}"]:`,
      error,
    );
    if (error instanceof DocumentExtractionError && error.recovery) {
      return NextResponse.json({ success: false, errorCode: 'PARSE_FAILED', error: error.message,
        recovery: error.recovery }, { status: 500 });
    }
    return apiError('PARSE_FAILED', 500, error instanceof Error ? error.message : 'Unknown error');
  }
}

export async function POST(req: NextRequest) {
  return withRequestOwnerId(req, async (ownerScope, headers) =>
    withOwnerResponseHeaders(await handlePost(req, ownerScope), headers));
}
