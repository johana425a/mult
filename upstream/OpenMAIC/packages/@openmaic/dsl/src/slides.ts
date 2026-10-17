/**
 * The MAIC slide object model — the canonical, dependency-free contract.
 *
 * This file is the single source of truth that supersedes the three copies that
 * had drifted apart before @openmaic/dsl existed:
 *   - app:      lib/types/slides.ts
 *   - renderer: packages/@openmaic/renderer/src/types/slides.ts
 *   - importer: packages/@openmaic/importer/src/openmaic/types/slides.ts
 *
 * It is a *superset*: every field that appeared in any of the three copies is
 * kept here so that the renderer and the importer can adopt this contract
 * without losing data. Fields that only existed in one copy are annotated with
 * `@since-merge` so the reconciliation history stays explicit. See README.md
 * (the "Divergence reconciled" section) for the full list.
 *
 * Pure types only — no runtime imports, no React/pptx/echarts.
 */

import type { AssetRef } from './storage.js';

/**
 * Regular (not `const`) enum on purpose: consumers compile with
 * `isolatedModules`, under which importing an ambient `const enum` across the
 * package boundary is an error (TS2748). A regular enum emits a runtime object
 * that bundles cleanly and is usable as both a value and a type.
 */
export enum ShapePathFormulasKeys {
  ROUND_RECT = 'roundRect',
  ROUND_RECT_DIAGONAL = 'roundRectDiagonal',
  ROUND_RECT_SINGLE = 'roundRectSingle',
  ROUND_RECT_SAMESIDE = 'roundRectSameSide',
  CUT_RECT_DIAGONAL = 'cutRectDiagonal',
  CUT_RECT_SINGLE = 'cutRectSingle',
  CUT_RECT_SAMESIDE = 'cutRectSameSide',
  CUT_ROUND_RECT = 'cutRoundRect',
  MESSAGE = 'message',
  ROUND_MESSAGE = 'roundMessage',
  L = 'L',
  RING_RECT = 'ringRect',
  PLUS = 'plus',
  TRIANGLE = 'triangle',
  PARALLELOGRAM_LEFT = 'parallelogramLeft',
  PARALLELOGRAM_RIGHT = 'parallelogramRight',
  TRAPEZOID = 'trapezoid',
  BULLET = 'bullet',
  INDICATOR = 'indicator',
  DONUT = 'donut',
  DIAGSTRIPE = 'diagStripe',
}

export enum ElementTypes {
  TEXT = 'text',
  IMAGE = 'image',
  SHAPE = 'shape',
  LINE = 'line',
  CHART = 'chart',
  TABLE = 'table',
  LATEX = 'latex',
  VIDEO = 'video',
  AUDIO = 'audio',
  CODE = 'code',
}


export type GradientType = 'linear' | 'radial';
export type GradientColor = {
  pos: number;
  color: string;
};
export interface Gradient {
  type: GradientType;
  colors: GradientColor[];
  rotate: number;
}

export type LineStyleType = 'solid' | 'dashed' | 'dotted';


export interface PPTElementShadow {
  h: number;
  v: number;
  blur: number;
  color: string;
}


export interface PPTElementOutline {
  style?: LineStyleType;
  width?: number;
  color?: string;
}

export type ElementLinkType = 'web' | 'slide';


export interface PPTElementLink {
  type: ElementLinkType;
  target: string;
}


export interface PPTBaseElement {
  id: string;
  left: number;
  top: number;
  lock?: boolean;
  groupId?: string;
  width: number;
  height: number;
  rotate: number;
  link?: PPTElementLink;
  name?: string;
}

export type TextType =
  | 'title'
  | 'subtitle'
  | 'content'
  | 'item'
  | 'itemTitle'
  | 'notes'
  | 'header'
  | 'footer'
  | 'partNumber'
  | 'itemNumber';


export interface PPTTextElement extends PPTBaseElement {
  type: 'text';
  /** @default "" */
  content: string;
  /** @default "Microsoft YaHei" */
  defaultFontName: string;
  /** @default "#333333" */
  defaultColor: string;
  outline?: PPTElementOutline;
  fill?: string;
  lineHeight?: number;
  wordSpace?: number;
  opacity?: number;
  shadow?: PPTElementShadow;
  paragraphSpace?: number;
  vertical?: boolean;
  textType?: TextType;
  /**
   * @since-merge renderer + importer
   * Vertical anchor of the text within the box, parsed from `<a:bodyPr anchor="...">`.
   * `top` / undefined keeps the legacy top-anchored behavior. `middle` and `bottom`
   * vertically center / bottom-align the content inside the box.
   */
  vAlign?: 'top' | 'middle' | 'bottom';
}


export interface ImageOrShapeFlip {
  flipH?: boolean;
  flipV?: boolean;
}


export type ImageElementFilterKeys =
  | 'blur'
  | 'brightness'
  | 'contrast'
  | 'grayscale'
  | 'saturate'
  | 'hue-rotate'
  | 'opacity'
  | 'sepia'
  | 'invert';
export interface ImageElementFilters {
  blur?: string;
  brightness?: string;
  contrast?: string;
  grayscale?: string;
  saturate?: string;
  'hue-rotate'?: string;
  sepia?: string;
  invert?: string;
  opacity?: string;
}

export type ImageClipDataRange = [[number, number], [number, number]];


export interface ImageElementClip {
  range: ImageClipDataRange;
  shape: string;
}

export type ImageType = 'pageFigure' | 'itemFigure' | 'background';


export interface PPTImageElement extends PPTBaseElement {
  type: 'image';
  /** @default true */
  fixedRatio: boolean;
  /**
   * An asset reference. Legacy documents and import/render paths also store placeholder ids or
   * concrete URLs here; such values are foreign to the asset pool and are addressed by later
   * delivery-plan steps.
   */
  src: AssetRef;
  outline?: PPTElementOutline;
  filters?: ImageElementFilters;
  clip?: ImageElementClip;
  flipH?: boolean;
  flipV?: boolean;
  shadow?: PPTElementShadow;
  radius?: number;
  colorMask?: string;
  imageType?: ImageType;
  /**
   * @since-merge renderer + importer
   * Soft-edge feather radius in px (`a:effectLst>softEdge@rad`): fades image
   * alpha to transparent over this radius at every edge.
   */
  softEdge?: number;
}

export type ShapeTextAlign = 'top' | 'middle' | 'bottom';


export interface ShapeText {
  /** @default "" */
  content: string;
  /** @default "Microsoft YaHei" */
  defaultFontName: string;
  /** @default "#333333" */
  defaultColor: string;
  /** @default "middle" */
  align: ShapeTextAlign;
  lineHeight?: number;
  wordSpace?: number;
  paragraphSpace?: number;
  type?: TextType;
}


export interface PPTShapeElement extends PPTBaseElement {
  type: 'shape';
  viewBox: [number, number];
  path: string;
  /** @default false */
  fixedRatio: boolean;
  /** @default "#5b9bd5" */
  fill: string;
  gradient?: Gradient;
  pattern?: string;
  outline?: PPTElementOutline;
  opacity?: number;
  flipH?: boolean;
  flipV?: boolean;
  shadow?: PPTElementShadow;
  special?: boolean;
  text?: ShapeText;
  pathFormula?: ShapePathFormulasKeys;
  keypoints?: number[];
}

export type LinePoint = '' | 'arrow' | 'dot';


export interface PPTLineElement extends Omit<PPTBaseElement, 'height' | 'rotate'> {
  type: 'line';
  start: [number, number];
  end: [number, number];
  /** @default "solid" */
  style: LineStyleType;
  /** @default "#333333" */
  color: string;
  /** @default ["", ""] */
  points: [LinePoint, LinePoint];
  shadow?: PPTElementShadow;
  broken?: [number, number];
  broken2?: [number, number];
  curve?: [number, number];
  cubic?: [[number, number], [number, number]];
}

export type ChartType = 'bar' | 'column' | 'line' | 'pie' | 'ring' | 'area' | 'radar' | 'scatter';

export interface ChartOptions {
  lineSmooth?: boolean;
  stack?: boolean;
  /** Explicit generated-slide label size; absent preserves existing chart styling. */
  fontSize?: number;
  /** Plot category shares while retaining original data for labels and editing. */
  percentStack?: boolean;
}

/** Explicit imported chart formatting; absent for legacy/authored charts. */
export type ChartFill =
  | string
  | {
      type: 'linear';
      x: number;
      y: number;
      x2: number;
      y2: number;
      colorStops: { offset: number; color: string }[];
    };
export interface ImportedChartAxis {
  show?: boolean;
  gridlines?: boolean;
  gridlineColor?: string;
  lineColor?: string;
  lineVisible?: boolean;
  labelVisible?: boolean;
  labelColor?: string;
  labelFontSize?: number; // canvas units (import adapter uses points before scaling)
  labelBold?: boolean;
  min?: number;
  max?: number;
  majorUnit?: number;
  numberFormat?: string;
}
export interface ImportedChartStyle {
  series: {
    fill?: ChartFill;
    pointFills?: Record<string, ChartFill>;
    pointImages?: Record<string, string>;
    showValue?: boolean;
  }[];
  categoryAxis?: ImportedChartAxis;
  valueAxis?: ImportedChartAxis;
  gapWidth?: number;
  plotArea?: { x: number; y: number; w: number; h: number };
}

export interface ChartData {
  labels: string[];
  legends: string[];
  series: number[][];
}


export interface PPTChartElement extends PPTBaseElement {
  type: 'chart';
  fill?: string;
  chartType: ChartType;
  data: ChartData;
  options?: ChartOptions;
  importedStyle?: ImportedChartStyle;
  outline?: PPTElementOutline;
  themeColors: string[];
  textColor?: string;
  lineColor?: string;
}

export type TextAlign = 'left' | 'center' | 'right' | 'justify';


export interface TableCellStyle {
  bold?: boolean;
  em?: boolean;
  underline?: boolean;
  strikethrough?: boolean;
  color?: string;
  backcolor?: string;
  fontsize?: string;
  fontname?: string;
  align?: TextAlign;
}

/**
 * @since-merge renderer + importer
 * Single side of a per-cell border, already scaled to px.
 */
export interface TableCellBorder {
  width: number;
  style: 'solid' | 'dashed' | 'dotted';
  color: string;
}


export interface TableCell {
  id: string;
  colspan: number;
  rowspan: number;
  text: string;
  style?: TableCellStyle;
  /**
   * @since-merge renderer + importer
   * CSS padding string (e.g. "3.6pt 7.2pt") applied to the cell. When undefined
   * the renderer applies no padding — data is the single source of truth for
   * cell inner spacing.
   */
  padding?: string;
  /**
   * @since-merge renderer + importer
   * CSS-native `vertical-align` value applied to the cell. When undefined the
   * renderer applies no vertical alignment (browser baseline).
   *
   * NOTE: the importer currently also emits the PPTist aliases `up | mid | down`.
   * Those are *not* part of this canonical contract — the importer must
   * normalize them to `top | middle | bottom` before producing DSL output.
   */
  vAlign?: 'top' | 'middle' | 'bottom';
  /**
   * @since-merge renderer + importer
   * Per-side cell borders, already scaled to px. When any side is present the
   * renderer draws each side independently (a side left undefined renders no
   * border) instead of falling back to the table-level uniform `outline`.
   */
  borders?: {
    top?: TableCellBorder;
    bottom?: TableCellBorder;
    left?: TableCellBorder;
    right?: TableCellBorder;
  };
}


export interface TableTheme {
  color: string;
  rowHeader: boolean;
  rowFooter: boolean;
  colHeader: boolean;
  colFooter: boolean;
}


export interface PPTTableElement extends PPTBaseElement {
  type: 'table';
  outline: PPTElementOutline;
  theme?: TableTheme;
  colWidths: number[];
  cellMinHeight: number;
  /**
   * @since-merge renderer + importer
   * Optional per-row heights in CSS pixels. Acts as a min-height — content
   * exceeding the value still expands the row. When omitted the renderer falls
   * back to `cellMinHeight` for every row.
   */
  rowHeights?: number[];
  data: TableCell[][];
}


export interface PPTLatexElement extends PPTBaseElement {
  type: 'latex';
  latex: string;
  html?: string;
  path?: string;
  color?: string;
  strokeWidth?: number;
  viewBox?: [number, number];
  fixedRatio?: boolean;
  align?: 'left' | 'center' | 'right';
}


export interface PPTVideoElement extends PPTBaseElement {
  type: 'video';
  /**
   * An asset reference. Legacy documents and render/import paths also store placeholder ids or
   * concrete URLs here; such values are foreign to the asset pool and are addressed by later
   * delivery-plan steps. Merging `src` and `mediaRef` is deliberately out of scope for this
   * type-unification step.
   */
  src?: AssetRef;
  /**
   * An asset reference for generated video. Legacy documents and generation paths also store
   * generated-video placeholder ids here; such values are foreign to the asset pool and are
   * addressed by later delivery-plan steps. Merging `src` and `mediaRef` is deliberately out of
   * scope for this type-unification step.
   */
  mediaRef?: AssetRef;
  autoplay: boolean;
  poster?: string;
  ext?: string;
}


export interface PPTAudioElement extends PPTBaseElement {
  type: 'audio';
  fixedRatio: boolean;
  color: string;
  loop: boolean;
  autoplay: boolean;
  src: string;
  ext?: string;
}

/**
 * Code line
 *
 * id: stable line ID (e.g. "L1", "L2"), auto-generated by the system
 *
 * content: line content (no trailing newline)
 */
export interface CodeLine {
  id: string;
  content: string;
}

/**
 * Code element
 *
 * type: element type (code)
 *
 * language: programming language identifier (e.g. 'python', 'javascript', 'typescript')
 *
 * lines: code content stored as lines, each with a stable ID
 *
 * fileName?: optional file name title (e.g. "main.py")
 *
 * showLineNumbers?: whether to show line numbers, default true
 *
 * fontSize?: font size in pixels, default 14
 */
export interface PPTCodeElement extends PPTBaseElement {
  type: 'code';
  language: string;
  lines: CodeLine[];
  fileName?: string;
  showLineNumbers?: boolean;
  fontSize?: number;
}

export type PPTElement =
  | PPTTextElement
  | PPTImageElement
  | PPTShapeElement
  | PPTLineElement
  | PPTChartElement
  | PPTTableElement
  | PPTLatexElement
  | PPTVideoElement
  | PPTAudioElement
  | PPTCodeElement;

export type AnimationType = 'in' | 'out' | 'attention';
export type AnimationTrigger = 'click' | 'meantime' | 'auto';


export interface PPTAnimation {
  id: string;
  elId: string;
  effect: string;
  type: AnimationType;
  duration: number;
  trigger: AnimationTrigger;
}

export type SlideBackgroundType = 'solid' | 'image' | 'gradient';
export type SlideBackgroundImageSize = 'cover' | 'contain' | 'repeat';
export interface SlideBackgroundImage {
  src: string;
  size: SlideBackgroundImageSize;
}


export interface SlideBackground {
  type: SlideBackgroundType;
  color?: string;
  image?: SlideBackgroundImage;
  gradient?: Gradient;
}

export type TurningMode =
  | 'no'
  | 'fade'
  | 'slideX'
  | 'slideY'
  | 'random'
  | 'slideX3D'
  | 'slideY3D'
  | 'rotate'
  | 'scaleY'
  | 'scaleX'
  | 'scale'
  | 'scaleReverse';

export interface SectionTag {
  id: string;
  title?: string;
}

export type SlideType = 'cover' | 'contents' | 'transition' | 'content' | 'end';


export interface SlideTheme {
  backgroundColor: string;
  themeColors: string[];
  fontColor: string;
  fontName: string;
  outline?: PPTElementOutline;
  shadow?: PPTElementShadow;
}


export interface Slide {
  id: string;
  viewportSize: number;
  viewportRatio: number;
  theme: SlideTheme;
  elements: PPTElement[];
  background?: SlideBackground;
  animations?: PPTAnimation[];
  turningMode?: TurningMode;
  sectionTag?: SectionTag;
  type?: SlideType;
  /**
   * @since-merge importer
   * Speaker notes carried over from the source .pptx.
   */
  script?: string;
}

export interface SlideTemplate {
  name: string;
  id: string;
  cover: string;
  origin?: string;
}

/**
 * @deprecated SlideData is deprecated, use {@link Slide} instead. Retained only
 * for backward compatibility with persisted/legacy payloads.
 */
export interface SlideData {
  id: string;
  viewportSize: number;
  viewportRatio: number;
  theme: {
    themeColors: string[];
    fontColor: string;
    fontName: string;
    backgroundColor: string;
  };
  elements: PPTElement[];
  background?: SlideBackground;
  animations?: unknown[];
}
