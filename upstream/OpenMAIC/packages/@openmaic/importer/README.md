# OpenMAIC PPTX importer

`@openmaic/importer` converts PPTX presentations into readable intermediate JSON or editable OpenMAIC canvas slides. Its parser builds on [pptxtojson](https://github.com/pipipi-pikachu/pptxtojson), originally developed for [PPTist](https://github.com/pipipi-pikachu/PPTist). Original ownership and the MIT license are preserved.

## Runtime and build

The browser parser requires DOM APIs, including `XMLHttpRequest`, `DOMMatrix`, and `Path2D` through its browser-targeted PDF.js dependency. Use the browser entry from client code. Do not assume importing that entry in a plain Node.js process will work. Server-side integration uses its separately configured parsing workflow.

The TypeScript implementation lives in `src/`; build outputs live in `dist/`. The legacy `src1/` implementation is a read-only reference and is not built.

Install the workspace dependencies and build this package before use. The application copies its browser bundle into `public/vendor/maic-importer/` using `scripts/sync-maic-importer.mjs`. This directory is generated and not committed. Deployment must execute the workspace postinstall build or explicitly build and synchronize the importer. `scripts/assert-vendor-maic-importer.mjs` checks that the vendor bundle exists before an application build. Rebuild after updating source so runtime JavaScript and workspace types stay aligned.

## Public API

| Export | Purpose |
| --- | --- |
| `parse(buffer, options?)` | Convert PPTX bytes to readable intermediate JSON. |
| `importPptx(input, options?)` | Convert a `File`, `Blob`, or `ArrayBuffer` to OpenMAIC `Slide[]`, waiting for media uploads to settle. |
| `parsedToSlides(json, options?)` | Convert existing parser output to `Slide[]`. |
| `normalizeImportedSlides(slides)` | Apply the slide contract, supply defaults, and discard unrecoverable elements with warnings. |
| `OssUpload` | An optional media-upload callback returning a usable URL. |
| `ImportPptxOptions` | Import options, including the optional `upload` callback. |
| `CanvasSlide` | The exported OpenMAIC slide type. |

`importPptx()` combines `parse(buffer, { mediaMode: 'base64' })` and `parsedToSlides()`. Both public conversion paths apply normalization. Consumers calling the lower-level `transformParsedToSlides` directly must apply normalization themselves to obtain the same contract.

```ts
import {
  importPptx,
  parsedToSlides,
  normalizeImportedSlides,
  type OssUpload,
  type ImportPptxOptions,
  type CanvasSlide,
} from '@openmaic/importer';

const slides: CanvasSlide[] = await importPptx(file);
```

Intermediate JSON uses points; OpenMAIC canvas slides use pixels. The intermediate output preserves slide size, theme colors, notes, backgrounds, transitions, slide elements, and master/layout elements. Supported element categories include text, shapes, images, tables, charts, audio, video, formulas, diagrams, and groups. Rich text can preserve common formatting, hyperlinks, rotation, alignment, and supported autofit properties. Formula conversion supports common structures and retains a rendered image where available.

## Media storage

Without `upload`, images remain data URLs and audio/video can retain temporary blob URLs. Temporary blob URLs work only in the current browser tab and do not survive reload. For persisted content, provide a storage callback:

```ts
const upload: OssUpload = async (blob, filename, dir) => {
  const form = new FormData();
  form.append('file', blob, filename);
  form.append('dir', dir ?? 'pptx-import');
  const response = await fetch('/api/upload', { method: 'POST', body: form });
  if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
  const { url } = await response.json();
  return url;
};

const slides = await importPptx(file, { upload });
```

The callback signature is `(blob: Blob, filename: string, dir?: string) => Promise<string>`. It receives converted background images, image elements, video posters, formula images, pattern fills, audio, and video. Image uploads use bounded concurrency. Existing remote posters are not uploaded again. A failed poster upload retains the original poster. Individual media failures are reported by the conversion layer and can preserve source media; a parser failure rejects the import. Uploads settle before the slide array is returned.

If calling `parse()` first, use `mediaMode: 'base64'` before `parsedToSlides()` so media can be uploaded and used after navigation. A blob URL from a previous tab is not a portable source.

## Client bundle loading

PDF.js uses dynamic dependency loading that can conflict with application bundlers. The application therefore loads the generated static browser bundle without bundler processing:

```ts
import type * as Importer from '@openmaic/importer';

const module = (await import(
  /* webpackIgnore: true */
  /* turbopackIgnore: true */
  /* @vite-ignore */
  '/vendor/maic-importer/index.js'
)) as typeof Importer;

const slides = await module.importPptx(file, { upload });
```

Workspace types remain available to editors. The client import hook checks bundle availability before loading it and reports a missing parser bundle distinctly from malformed PPTX content.

## Fidelity and layout limits

Imported presentations can differ visually from their originals. Font availability, browser measurements, supported geometry, and video codecs affect results. Font resolution currently preserves source names and relies on fallback when a font is unavailable. Codec detection does not fully validate every browser-supported video format. SVG path parsing supports the standard commands, while arc bounding boxes use endpoint approximations.

PPTX tab columns become editable fixed-width inline containers. Browser imports use canvas font measurement; server workflows without that measurement estimate widths. Server columns allow expansion with `min-width:max-content`, reducing overlap but potentially shifting later columns. Existing imports are not automatically remeasured after opening in a browser. For closer font-dependent alignment, load the target fonts and reimport the source presentation in the browser.

## Attribution

The original parser draws on [PPTX2HTML](https://github.com/g21589/PPTX2HTML) and [PPTXjs](https://github.com/meshesha/PPTXjs). The parser produces structured JSON rather than directly producing complete HTML presentations. MIT License; original pptxtojson copyright 2020-present [pipipi-pikachu](https://github.com/pipipi-pikachu). Read the package `LICENSE` and the repository attribution notices when redistributing.
