// DeepSteam r9: only bound prompt assembly memory here. The caller checks the
// selected model's real context budget and keeps the complete original source.
export const MAX_PDF_CONTENT_CHARS = 4 * 1024 * 1024;
export const MAX_VISION_IMAGES = 20;
