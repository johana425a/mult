# Document reading

The document layer separates file extraction from the language model that teaches
or answers questions. A model connection does not imply that an external parsing
API or embedding service has been configured.

## Default local reader

The DeepSteam desktop distribution selects `deepsteam-local`. It calls the
shared document service used by the workspace assistant and uploaded materials.
The service retains source locators, original page images, extraction notes, and
recovery information. PDF, DOCX, PPTX, Markdown, and the supported spreadsheet
formats use the same ownership and completeness checks.

Scanned pages are passed to the installed OCR components. MinerU is an optional
local parsing tool for more complex layouts, tables, and formulas. It is not a
chat model and does not replace the selected teaching model.

The local extraction request limit is 200 MiB. Large files are processed in
bounded batches rather than being silently truncated. A pending request retains
a recovery reference; reopen the material to continue after a connection timeout.
Cancelling a reading request retains the original file.

OCR and formula recognition require verification against the source when the
layout is ambiguous. Preserve the original page image and extraction notes
instead of treating generated transcription as a guaranteed exact copy.

## Extractor registry

`lib/document/extractors/manifest.ts` declares the available extractor
capabilities. `lib/document/extractors/deepsteam-local.ts` manages the local
reader connection, recovery validation, original image locators, and document
ownership. Configure or install the reader through the desktop application;
users do not need to supply an internal transport address.

The legacy PDF adapter also supports:

- `unpdf`: built-in text and image extraction without an API key.
- `mineru`: an explicitly configured external MinerU service.

These remain optional integrations. Do not assume an external MinerU service is
installed merely because the local desktop reader is available.

## PDF upload contract

```typescript
const formData = new FormData();
formData.append('pdf', pdfFile);
formData.append('providerId', 'unpdf');

const response = await fetch('/api/parse-pdf', {
  method: 'POST',
  body: formData,
});
const result = await response.json();
```

Use a provider endpoint selected in the application settings for an external
parser. Keep API keys in the secure provider configuration and out of document
text, source exports, and model-visible prompts.

## Extraction results

Text results may contain Markdown, tables, formulas, and image references.
Images retain source page numbers and an image mapping used by classroom
generation. Structured layout data can describe titles, paragraphs, tables,
images, and formulas together with positions.

The legacy `ParsedPdfContent` contract contains:

```typescript
interface ParsedPdfContent {
  text: string;
  images: string[];
  tables?: Array<{ page: number; data: string[][]; caption?: string }>;
  formulas?: Array<{
    page: number;
    latex: string;
    position?: { x: number; y: number; width: number; height: number };
  }>;
  layout?: Array<{
    page: number;
    type: 'title' | 'text' | 'image' | 'table' | 'formula';
    content: string;
    position?: { x: number; y: number; width: number; height: number };
  }>;
  metadata?: {
    pageCount: number;
    parser: 'unpdf' | 'mineru';
    fileName?: string;
    fileSize?: number;
    processingTime?: number;
    imageMapping?: Record<string, string>;
    pdfImages?: Array<{
      id: string;
      src: string;
      pageNumber: number;
      description?: string;
    }>;
  };
}
```

The unified document extractor adds explicit source units, reading notes, and
recovery/completeness metadata. Consumers must validate these fields before
claiming a document has been completely read.

## Classroom generation

Pass extracted source text and page-linked images to outline generation. Scene
generation then receives only the images assigned to the scene and resolves
image identifiers through the source mapping. Preserve page locators so users
can compare generated content with the original document.

Workspace selection and uploaded resources share the reader; uploading another
copy is not required solely to use a different product surface. The language
model still receives selected, bounded source material for the current task.
Full-workspace processing uses the persisted catalog and per-source progress
rather than inserting every file into one model request.

## Diagnostics

Distinguish missing runtime components, unsupported formats, invalid ownership,
incomplete results, and recoverable waiting states. A retry resumes or reuses a
validated job where possible. Do not map these states to an unrelated embedding
configuration problem.

Run the document extractor, queue/recovery, source-grounding, and classroom image
tests when changing this layer. Keep local parser assets and their license
notices together in redistributable packages.
