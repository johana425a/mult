import { parseFragment } from 'parse5';
import type { PPTElement, PPTImageElement, PPTLineElement, PPTTextElement } from '@openmaic/dsl';
import type { GeneratedSceneContent, GeneratedSlideContent } from './scene-types.js';

/** Generated teaching slides use the same native coordinates in preview and video. */
export const GENERATED_SLIDE_LAYOUT = Object.freeze({
  width: 1000, height: 562.5, margin: 50, gap: 16, minimumFontSize: 24,
});

export class SlideLayoutError extends Error {
  constructor(public readonly code: 'SLIDE_LAYOUT_OVERFLOW' | 'SLIDE_LAYOUT_UNSUPPORTED', message: string) {
    super(`${code}: ${message}`);
    this.name = 'SlideLayoutError';
  }
}

export interface ImageDimensions { width: number; height: number }
export interface SlideLayoutOptions {
  /** Entries may be indexed by the original image id or its resolved src. */
  imageDimensions?: ReadonlyMap<string, ImageDimensions>;
}

function validDimensions(value: ImageDimensions | undefined): value is ImageDimensions {
  return !!value && Number.isFinite(value.width) && Number.isFinite(value.height) &&
    value.width > 0 && value.height > 0;
}

function base64Bytes(value: string): Uint8Array {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const clean = value.replace(/\s/g, '');
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(clean)) return new Uint8Array();
  const result: number[] = [];
  let accumulator = 0, bits = 0;
  for (const char of clean.replace(/=+$/, '')) {
    accumulator = (accumulator << 6) | alphabet.indexOf(char);
    bits += 6;
    if (bits >= 8) { bits -= 8; result.push((accumulator >> bits) & 255); }
  }
  return Uint8Array.from(result);
}

/** Read intrinsic dimensions locally. Never fetch an asset or trust its authored box. */
export function imageDimensionsFromDataUrl(src: string): ImageDimensions | undefined {
  const match = /^data:image\/([^;,]+)([^,]*),([\s\S]*)$/.exec(src);
  if (!match) return undefined;
  const mime = match[1].toLowerCase();
  if (mime === 'svg+xml') {
    try {
      const svg = match[2].includes(';base64')
        ? new TextDecoder().decode(base64Bytes(match[3])) : decodeURIComponent(match[3]);
      const tag = /<svg\b[^>]*>/i.exec(svg)?.[0] ?? '';
      const viewBox = /\bviewBox\s*=\s*["']\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)\s*["']/i.exec(tag);
      const width = /\bwidth\s*=\s*["']([\d.]+)(?:px)?["']/i.exec(tag);
      const height = /\bheight\s*=\s*["']([\d.]+)(?:px)?["']/i.exec(tag);
      const result = width && height ? { width: +width[1], height: +height[1] }
        : viewBox ? { width: +viewBox[1], height: +viewBox[2] } : undefined;
      return validDimensions(result) ? result : undefined;
    } catch { return undefined; }
  }
  if (!match[2].includes(';base64')) return undefined;
  const bytes = base64Bytes(match[3]);
  const u16 = (offset: number) => (bytes[offset] << 8) | bytes[offset + 1];
  const u32 = (offset: number) => bytes[offset] * 16777216 + bytes[offset + 1] * 65536 +
    bytes[offset + 2] * 256 + bytes[offset + 3];
  let result: ImageDimensions | undefined;
  if (bytes.length >= 24 && bytes[0] === 137 && bytes[1] === 80 && bytes[2] === 78 && bytes[3] === 71) {
    result = { width: u32(16), height: u32(20) };
  } else if (bytes.length >= 10 && bytes[0] === 71 && bytes[1] === 73 && bytes[2] === 70) {
    result = { width: bytes[6] | (bytes[7] << 8), height: bytes[8] | (bytes[9] << 8) };
  } else if (bytes[0] === 255 && bytes[1] === 216) {
    for (let offset = 2; offset + 8 < bytes.length;) {
      if (bytes[offset] !== 255) break;
      const marker = bytes[offset + 1];
      if (marker === 216 || marker === 1) { offset += 2; continue; }
      if (marker === 217 || marker === 218) break;
      const size = u16(offset + 2);
      if (size < 2 || offset + size + 2 > bytes.length) break;
      if ([192, 193, 194, 195, 197, 198, 199, 201, 202, 203, 205, 206, 207].includes(marker)) {
        result = { width: u16(offset + 7), height: u16(offset + 5) }; break;
      }
      offset += size + 2;
    }
  } else if (bytes.length >= 30 && bytes[0] === 82 && bytes[1] === 73 && bytes[8] === 87 && bytes[9] === 69) {
    const kind = String.fromCharCode(...bytes.slice(12, 16));
    if (kind === 'VP8X') {
      result = { width: 1 + bytes[24] + (bytes[25] << 8) + (bytes[26] << 16),
        height: 1 + bytes[27] + (bytes[28] << 8) + (bytes[29] << 16) };
    } else if (kind === 'VP8 ' && bytes.length >= 30 && bytes[23] === 157 && bytes[24] === 1 && bytes[25] === 42) {
      result = { width: (bytes[26] | bytes[27] << 8) & 16383,
        height: (bytes[28] | bytes[29] << 8) & 16383 };
    } else if (kind === 'VP8L' && bytes.length >= 25 && bytes[20] === 47) {
      result = { width: 1 + (bytes[21] | (bytes[22] & 63) << 8),
        height: 1 + ((bytes[22] >> 6) | bytes[23] << 2 | (bytes[24] & 15) << 10) };
    }
  }
  return validDimensions(result) ? result : undefined;
}

type HtmlNode = { nodeName: string; value?: string; childNodes?: HtmlNode[]; attrs?: { name: string; value: string }[] };
function textLines(html: string): string[] {
  let text = '';
  function visit(node: HtmlNode) {
    if (node.nodeName === '#text') text += node.value ?? '';
    else if (node.nodeName === 'br') text += '\n';
    else {
      for (const child of node.childNodes ?? []) visit(child);
      if (['p', 'div', 'li', 'h1', 'h2', 'h3'].includes(node.nodeName)) text += '\n';
    }
  }
  visit(parseFragment(html) as unknown as HtmlNode);
  return text.replace(/\n$/, '').split('\n');
}

function visibleFormulaText(element: Extract<PPTElement, { type: 'latex' }>): string {
  if (!element.html) return element.latex;
  const fragment = parseFragment(element.html) as unknown as HtmlNode;
  const find = (node: HtmlNode): HtmlNode | undefined => {
    if (node.attrs?.some((attr) => attr.name === 'class' && attr.value.split(/\s+/).includes('katex-html'))) return node;
    for (const child of node.childNodes ?? []) { const result = find(child); if (result) return result; }
    return undefined;
  };
  const visible = find(fragment);
  if (!visible) throw new SlideLayoutError('SLIDE_LAYOUT_UNSUPPORTED', `Formula ${element.id} has no measurable KaTeX display.`);
  const text = (node: HtmlNode): string => node.nodeName === '#text' ? node.value ?? ''
    : (node.childNodes ?? []).map(text).join('');
  return text(visible);
}

/** Increase small generated fonts; never shrink text or change its wording. */
function readableText(element: PPTTextElement): PPTTextElement {
  const minimum = GENERATED_SLIDE_LAYOUT.minimumFontSize;
  let found = false;
  const content = element.content.replace(/font-size\s*:\s*([\d.]+)px/gi, (full, number) => {
    found = true;
    return +number < minimum ? `font-size: ${minimum}px` : full;
  });
  if (/font-size\s*:\s*[^;"']*(?:em|rem|pt|%)/i.test(content)) {
    throw new SlideLayoutError('SLIDE_LAYOUT_UNSUPPORTED', `Text ${element.id} uses an unmeasurable font unit; use px.`);
  }
  return { ...element, content: found ? content : `<div style="font-size: ${minimum}px;">${content}</div>` };
}

function maximumFont(html: string): number {
  return Math.max(GENERATED_SLIDE_LAYOUT.minimumFontSize,
    ...Array.from(html.matchAll(/font-size\s*:\s*([\d.]+)px/gi), (match) => +match[1]));
}

/** Conservative painted bounds include the renderer's 10px padding and paragraph gaps. */
function textHeight(element: PPTTextElement, width: number): number {
  const font = maximumFont(element.content);
  const lineHeight = Math.max(1.5, element.lineHeight ?? 1.5);
  const available = width - 20;
  if (available < font * 2) throw new SlideLayoutError('SLIDE_LAYOUT_OVERFLOW', `Text ${element.id} has no readable width.`);
  let count = 0;
  const lines = textLines(element.content);
  for (const line of lines) {
    let used = 0;
    count += 1;
    for (const char of line) {
      // CJK/emoji use a full em; Latin is deliberately wider than common fonts.
      const charWidth = font * (/\s/u.test(char) ? 0.4 : char.codePointAt(0)! > 255 ? 1 : 0.75) +
        Math.max(0, element.wordSpace ?? 0);
      if (used + charWidth > available) { count += 1; used = 0; }
      used += charWidth;
    }
  }
  const paragraphCount = (element.content.match(/<(?:p|li|h[1-3])\b/gi) ?? []).length;
  return Math.ceil(20 + count * font * lineHeight + paragraphCount * Math.max(5, element.paragraphSpace ?? 5) + 8);
}

function dimensionsForImage(element: PPTImageElement, options: SlideLayoutOptions): ImageDimensions {
  const dimensions = options.imageDimensions?.get(element.src) ?? options.imageDimensions?.get(element.id) ??
    imageDimensionsFromDataUrl(element.src);
  if (!validDimensions(dimensions)) {
    throw new SlideLayoutError('SLIDE_LAYOUT_UNSUPPORTED', `Image ${element.id} has no intrinsic dimensions; provide source width and height.`);
  }
  if (element.clip) throw new SlideLayoutError('SLIDE_LAYOUT_UNSUPPORTED', `Generated source image ${element.id} is cropped.`);
  return dimensions;
}

type LaidOutElement = Extract<PPTElement, { type: 'text' | 'image' | 'latex' | 'video' }>;
function sized(element: PPTElement, width: number, availableHeight: number, options: SlideLayoutOptions): LaidOutElement {
  if (('rotate' in element && element.rotate) || (element.type === 'text' && element.vertical)) {
    throw new SlideLayoutError('SLIDE_LAYOUT_UNSUPPORTED', `Rotated or vertical element ${element.id} requires an explicit layout.`);
  }
  if (element.type === 'text') {
    const readable = readableText(element);
    return { ...readable, width, height: textHeight(readable, width) };
  }
  if (element.type === 'image') {
    const dimensions = dimensionsForImage(element, options);
    const ratio = dimensions.width / dimensions.height;
    // Fit uniformly. Both axes derive from the source, not from the model's box.
    const targetWidth = Math.min(width, Math.max(320, element.width), availableHeight * ratio);
    return { ...element, width: targetWidth, height: targetWidth / ratio, fixedRatio: true };
  }
  if (element.type === 'latex') {
    // Reserve the full row and a readable base font; a long atomic formula must
    // fail instead of being hidden by the renderer's shrink-to-fit behavior.
    const visible = visibleFormulaText(element).replace(/\s/g, '');
    const estimatedWidth = visible.length * GENERATED_SLIDE_LAYOUT.minimumFontSize;
    if (estimatedWidth > width * 1.2) {
      throw new SlideLayoutError('SLIDE_LAYOUT_OVERFLOW', `Formula ${element.id} needs a wider page or an explicit line break.`);
    }
    return { ...element, width, height: Math.max(80, element.height),
      ...(element.html ? { html: `<div style="font-size: 24px;">${element.html}</div>` } : {}) };
  }
  if (element.type === 'video') {
    if (element.width > width || element.height > availableHeight) {
      throw new SlideLayoutError('SLIDE_LAYOUT_OVERFLOW', `Video ${element.id} needs its own readable page.`);
    }
    return { ...element };
  }
  // Moving diagram primitives independently would break their meaning.
  throw new SlideLayoutError('SLIDE_LAYOUT_UNSUPPORTED', `Element ${element.id} (${element.type}) needs a grouped layout; content was retained.`);
}

type Bounds = { left: number; top: number; right: number; bottom: number };
type LayoutUnit = { elements: PPTElement[]; atomic: boolean; index: number; bounds: Bounds };
function unionBounds(bounds: Bounds[]): Bounds {
  return { left: Math.min(...bounds.map((b) => b.left)), top: Math.min(...bounds.map((b) => b.top)),
    right: Math.max(...bounds.map((b) => b.right)), bottom: Math.max(...bounds.map((b) => b.bottom)) };
}
function intersects(a: Bounds, b: Bounds, gap = 0): boolean {
  return a.left <= b.right + gap && b.left <= a.right + gap && a.top <= b.bottom + gap && b.top <= a.bottom + gap;
}

/** Local coordinates determine the path; width is stroke thickness, not its span. */
function lineBounds(element: PPTLineElement): Bounds {
  const isPair = (point: unknown): point is [number, number] => Array.isArray(point) && point.length === 2 &&
    point.every((number) => typeof number === 'number' && Number.isFinite(number));
  if (!isPair(element.start) || !isPair(element.end) || !Array.isArray(element.points) || element.points.length !== 2 ||
    element.points.some((point) => !['', 'arrow', 'dot'].includes(point))) {
    throw new SlideLayoutError('SLIDE_LAYOUT_UNSUPPORTED', `Line ${element.id} requires local start/end pairs and points containing only empty, arrow, or dot.`);
  }
  const pairs = [element.start, element.end, element.broken, element.broken2, element.curve,
    ...(element.cubic ?? [])].filter((point): point is [number, number] => point !== undefined);
  if (pairs.some((point) => !Array.isArray(point) || point.length !== 2 || point.some((n) => !Number.isFinite(n))) ||
    !Number.isFinite(element.width) || element.width <= 0) {
    throw new SlideLayoutError('SLIDE_LAYOUT_UNSUPPORTED', `Line ${element.id} requires finite local start/end/control pairs and a positive stroke width.`);
  }
  const xs = [element.start[0], element.end[0]], ys = [element.start[1], element.end[1]];
  if (element.broken) { xs.push(element.broken[0]); ys.push(element.broken[1]); }
  else if (element.broken2) {
    if (Math.max(...xs) >= Math.max(...ys)) xs.push(element.broken2[0]); else ys.push(element.broken2[1]);
  } else if (element.curve) { xs.push(element.curve[0]); ys.push(element.curve[1]); }
  else if (element.cubic) {
    xs.push(element.cubic[0][0], element.cubic[1][0]); ys.push(element.cubic[0][1], element.cubic[1][1]);
  }
  // Control hulls conservatively enclose Bezier paths, like the native renderer.
  // Markers are 3*max(2, stroke) square and rotate with the path; reserve their hull.
  const padding = element.points.some(Boolean) ? 3 * Math.max(2, element.width) : element.width / 2;
  const shadow = element.shadow;
  const horizontal = shadow ? Math.abs(shadow.h) + shadow.blur : 0;
  const vertical = shadow ? Math.abs(shadow.v) + shadow.blur : 0;
  return { left: element.left + Math.min(...xs) - padding - horizontal,
    right: element.left + Math.max(...xs) + padding + horizontal,
    top: element.top + Math.min(...ys) - padding - vertical,
    bottom: element.top + Math.max(...ys) + padding + vertical };
}
function elementBounds(element: PPTElement): Bounds {
  if (element.type === 'line') return lineBounds(element);
  const angle = (element.rotate ?? 0) * Math.PI / 180;
  const cx = element.left + element.width / 2, cy = element.top + element.height / 2;
  const points = [[-1, -1], [-1, 1], [1, -1], [1, 1]].map(([x, y]) => ({
    x: cx + x * element.width / 2 * Math.cos(angle) - y * element.height / 2 * Math.sin(angle),
    y: cy + x * element.width / 2 * Math.sin(angle) + y * element.height / 2 * Math.cos(angle),
  }));
  return { left: Math.min(...points.map((p) => p.x)), right: Math.max(...points.map((p) => p.x)),
    top: Math.min(...points.map((p) => p.y)), bottom: Math.max(...points.map((p) => p.y)) };
}

/** Preserve explicit groups and infer connected nodes from the native line's painted hull. */
function layoutUnits(body: { element: PPTElement; index: number }[]): LayoutUnit[] {
  const bounds = body.map(({ element }) => elementBounds(element));
  const parent = body.map((_, index) => index);
  const root = (index: number): number => parent[index] === index ? index : (parent[index] = root(parent[index]));
  const join = (a: number, b: number) => { parent[root(b)] = root(a); };
  for (let a = 0; a < body.length; a++) for (let b = a + 1; b < body.length; b++) {
    const first = body[a].element, second = body[b].element;
    if ((first.groupId && first.groupId === second.groupId) ||
      ((first.type === 'line' || second.type === 'line') && intersects(bounds[a], bounds[b], GENERATED_SLIDE_LAYOUT.gap))) join(a, b);
  }
  // A separate text label inside a connected shape belongs to that diagram too.
  for (let a = 0; a < body.length; a++) for (let b = 0; b < body.length; b++) {
    if (body[a].element.type === 'shape' && body[b].element.type === 'text' && intersects(bounds[a], bounds[b])) join(a, b);
  }
  const groups = new Map<number, number[]>();
  body.forEach((_, index) => { const key = root(index); groups.set(key, [...(groups.get(key) ?? []), index]); });
  return [...groups.values()].map((indices) => ({
    elements: indices.map((index) => body[index]).sort((a, b) => a.index - b.index).map(({ element }) => element),
    atomic: indices.length > 1 || indices.some((index) => ['line', 'shape'].includes(body[index].element.type)),
    index: Math.min(...indices.map((index) => body[index].index)), bounds: unionBounds(indices.map((index) => bounds[index])),
  })).sort((a, b) => a.bounds.top - b.bounds.top || a.bounds.left - b.bounds.left || a.index - b.index);
}

/** An atomic diagram may be translated, never resized or split across pages. */
function readableDiagram(unit: LayoutUnit, options: SlideLayoutOptions): PPTElement[] {
  const elements = unit.elements.map((element): PPTElement => {
    if (element.type === 'line') {
      lineBounds(element);
      // Producers historically attach zero rotate/height. Neither is part of
      // the native line schema; start/end already encode its actual direction.
      const copy = { ...element } as PPTLineElement & { rotate?: number; height?: number };
      if (copy.rotate) throw new SlideLayoutError('SLIDE_LAYOUT_UNSUPPORTED', `Line ${element.id} uses rotate; encode its direction in local start/end.`);
      delete copy.rotate; delete copy.height;
      return copy;
    }
    if (element.type === 'text') {
      const readable = readableText(element);
      if (textHeight(readable, element.width) > element.height) {
        throw new SlideLayoutError('SLIDE_LAYOUT_OVERFLOW', `Connected text ${element.id} needs a larger readable box; its diagram was retained.`);
      }
      return readable;
    }
    if (element.type === 'shape') {
      if (!Array.isArray(element.viewBox) || element.viewBox.length !== 2 ||
        element.viewBox.some((number) => !Number.isFinite(number) || number <= 0) || typeof element.path !== 'string' || !element.path.trim()) {
        throw new SlideLayoutError('SLIDE_LAYOUT_UNSUPPORTED', `Diagram shape ${element.id} requires a positive viewBox and its native SVG path.`);
      }
      if (element.text?.content) {
        const text = readableText({ ...element, type: 'text', content: element.text.content,
          defaultFontName: element.text.defaultFontName, defaultColor: element.text.defaultColor });
        if (textHeight(text, element.width) > element.height) {
          throw new SlideLayoutError('SLIDE_LAYOUT_OVERFLOW', `Diagram shape ${element.id} needs a larger readable text box.`);
        }
        return { ...element, text: { ...element.text, content: text.content } };
      }
      return element;
    }
    if (element.type === 'image') {
      const intrinsic = dimensionsForImage(element, options);
      if (Math.abs(element.width / element.height - intrinsic.width / intrinsic.height) > 0.000001) {
        throw new SlideLayoutError('SLIDE_LAYOUT_UNSUPPORTED', `Connected image ${element.id} must retain its intrinsic aspect ratio before connecting a diagram.`);
      }
      return element;
    }
    if (element.type === 'latex' || element.type === 'video') {
      const measured = sized(element, element.width, element.height, options);
      if (measured.height > element.height) throw new SlideLayoutError('SLIDE_LAYOUT_OVERFLOW', `Connected element ${element.id} needs a larger readable box.`);
      return { ...measured, left: element.left, top: element.top };
    }
    throw new SlideLayoutError('SLIDE_LAYOUT_UNSUPPORTED', `Connected element ${element.id} (${element.type}) requires explicit measurable diagram geometry.`);
  });
  for (let a = 0; a < elements.length; a++) for (let b = a + 1; b < elements.length; b++) {
    const first = elements[a], second = elements[b];
    if ((first.type === 'image' && ['text', 'latex'].includes(second.type)) ||
      (second.type === 'image' && ['text', 'latex'].includes(first.type)) ||
      (['text', 'latex'].includes(first.type) && ['text', 'latex'].includes(second.type))) {
      const x = elementBounds(first), y = elementBounds(second);
      if (Math.min(x.right, y.right) > Math.max(x.left, y.left) && Math.min(x.bottom, y.bottom) > Math.max(x.top, y.top)) {
        throw new SlideLayoutError('SLIDE_LAYOUT_OVERFLOW', `Connected content ${first.id} and ${second.id} overlaps; its diagram was retained.`);
      }
    }
  }
  return elements;
}

/**
 * Reflow generated educational blocks, keeping every body element exactly once.
 * Header copies are the only duplicated content. Imported/designed slides do not
 * call this producer helper. An indivisible oversized block fails explicitly.
 */
export function layoutGeneratedSlidePages(content: GeneratedSlideContent, options: SlideLayoutOptions = {}): GeneratedSlideContent[] {
  const { width, height, margin, gap } = GENERATED_SLIDE_LAYOUT;
  const usableWidth = width - 2 * margin;
  const bottom = height - margin;
  const originals = structuredClone(content.elements);
  const titleIndex = originals.findIndex((element) => element.type === 'text' && element.top <= 130 &&
    maximumFont(element.content) >= 28 && !originals.some((other) => other !== element &&
      ((element.groupId && element.groupId === other.groupId) ||
        (other.type === 'line' && intersects(elementBounds(element), lineBounds(other), gap)))));
  const title = titleIndex >= 0 ? sized(originals[titleIndex], usableWidth, bottom - margin, options) : undefined;
  const bodyTop = title ? margin + title.height + gap : margin;
  const bodyHeight = bottom - bodyTop;
  if (bodyHeight <= 0) throw new SlideLayoutError('SLIDE_LAYOUT_OVERFLOW', 'Slide title does not fit at a readable size.');
  const body = originals.map((element, index) => ({ element, index }))
    .filter(({ index }) => index !== titleIndex)
    .sort((a, b) => a.element.top - b.element.top || a.element.left - b.element.left || a.index - b.index);
  const units = layoutUnits(body);
  const pages: GeneratedSlideContent[] = [];
  let page: GeneratedSlideContent;
  let cursor: number;
  const startPage = () => {
    page = { ...content, elements: [], continuationSlides: undefined };
    if (title) page.elements.push({ ...structuredClone(title), left: margin, top: margin,
      id: pages.length ? `${title.id}_continued_${pages.length + 1}` : title.id });
    pages.push(page);
    cursor = bodyTop;
  };
  startPage();
  for (let index = 0; index < units.length; index++) {
    const unit = units[index];
    if (unit.atomic) {
      const elements = readableDiagram(unit, options);
      const bounds = unionBounds(elements.map(elementBounds));
      const rowWidth = bounds.right - bounds.left, rowHeight = bounds.bottom - bounds.top;
      if (rowWidth > usableWidth || rowHeight > bodyHeight) {
        throw new SlideLayoutError('SLIDE_LAYOUT_OVERFLOW', `Connected diagram ${elements.map((element) => element.id).join(', ')} cannot fit at its authored readable size; split the diagram explicitly.`);
      }
      if (cursor! + rowHeight > bottom + 0.01) startPage();
      const dx = margin + (usableWidth - rowWidth) / 2 - bounds.left, dy = cursor! - bounds.top;
      page!.elements.push(...elements.map((element) => ({ ...element, left: element.left + dx, top: element.top + dy })));
      cursor! += rowHeight + gap;
      continue;
    }
    const current = unit.elements[0];
    const nextUnit = units[index + 1];
    const next = nextUnit && !nextUnit.atomic ? nextUnit.elements[0] : undefined;
    // Preserve an authored two-column row when two short content boxes shared
    // its vertical position. Images always get their own reserved row.
    const paired = next && ['text', 'latex'].includes(current.type) && ['text', 'latex'].includes(next.type) &&
      Math.abs(current.top - next.top) < 8 && current.width <= usableWidth / 2 && next.width <= usableWidth / 2 &&
      next.left >= current.left + current.width;
    const rowWidth = paired ? (usableWidth - gap) / 2 : usableWidth;
    const row = [sized(current, rowWidth, bodyHeight, options)];
    if (paired) { row.push(sized(next, rowWidth, bodyHeight, options)); index += 1; }
    const rowHeight = Math.max(...row.map((element) => element.height));
    if (rowHeight > bodyHeight) {
      throw new SlideLayoutError('SLIDE_LAYOUT_OVERFLOW', `Element ${current.id} cannot fit without splitting its content.`);
    }
    if (cursor! + rowHeight > bottom + 0.01) startPage();
    for (const [column, element] of row.entries()) {
      page!.elements.push({ ...element, left: paired ? margin + column * (rowWidth + gap)
        : margin + (usableWidth - element.width) / 2, top: cursor! });
    }
    cursor! += rowHeight + gap;
  }
  return pages;
}

/** Consumers that opt in to pagination must expand before generating actions. */
export function expandGeneratedSlidePages(content: GeneratedSceneContent): GeneratedSceneContent[] {
  if (!('elements' in content)) return [content];
  const { continuationSlides, ...first } = content;
  return [first, ...(continuationSlides ?? [])];
}
