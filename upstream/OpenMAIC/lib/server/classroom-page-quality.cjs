"use strict";
// DeepSteam: do not narrate a continuation page containing only decoration.
// This gate rejects a draft for regeneration; it never deletes source material.
exports.SLIDE_LAYOUT_GUIDANCE = `
Readable teaching-slide layout:
Use a plain, compact teaching layout, not a decorative poster. Do not add standalone accent bars, divider rules, ornamental shapes, or metadata-only panels. Keep meaningful scientific diagrams, formulas and original source figures.
Use a single title paragraph at 32px with natural wrapping. Use body text at 24px or larger. Combine a short subheading and its explanation in one text element, instead of separate heading-only elements. Use coherent paragraphs; avoid forcing each short phrase into a separate paragraph.
Keep related short points in a single text box. A short heading, its explanation and its citation need not each occupy a separate block. When a source image and concise explanatory text can fit legibly beside one another, use two columns with at least 16px separation and preserve the full image aspect ratio. Leave enough real height for wrapped text. A whole-page source image may need a dedicated readable reference page; do not crop or hide it.
All text boxes, including axis labels and diagram labels, need room for 20px total padding and at least two characters at their actual font size. Use at least 100px width and 70px height for short 24px labels; longer labels need more room. Connecting lines must not cross text boxes. Keep tables as native tables with explicit positive column widths, rows and cells.
Put each table cell's complete value or calculation in that cell's text. Do not leave empty cells and overlay separate floating formula elements on them: the table and its contents must move together during readable pagination. Prefer one calculation table to separately repeated formulas and a redundant chart of the same three values. Use a native chart only when it adds a distinct teaching purpose, reserving at least 480px width and 260px height. Keep figure captions outside node labels and connectors. Use groupId to explicitly associate a diagram's nodes, arrows and short labels, without grouping a nearby paragraph or citation into the diagram.
Teach this outline's assigned concepts and figure evidence. Full-source coverage is across the lesson, not repeated on every slide. Keep provenance and page references beside the relevant teaching content. Preserve original figures and their aspect ratios. Never shrink text, crop source figures, omit essential conditions or replace scientific diagrams with decoration to save space. Continuation pages are allowed when substantive content requires them.
`;

exports.findOrnamentOnlyPages = function findOrnamentOnlyPages(content) {
  const pages = [content, ...(content?.continuationSlides || [])];
  return pages.flatMap((page, index) => {
    if (!Array.isArray(page?.elements)) return [];
    const elements = page.elements;
    const title = elements.find(e => e.type === 'text' && e.top <= 130 &&
      [...String(e.content || '').matchAll(/font-size\s*:\s*([\d.]+)px/gi)].some(m => Number(m[1]) >= 28));
    if (!title) return [];
    const body = elements.filter(e => e !== title);
    const ornamentsOnly = body.length === 0 || body.every(e =>
      e.type === 'shape' && !e.text?.content && !e.groupId &&
      ((e.width > 0 && e.width <= 6) || (e.height > 0 && e.height <= 6)));
    return ornamentsOnly ? [index + 1] : [];
  });
};
