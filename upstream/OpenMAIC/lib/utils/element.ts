import tinycolor from 'tinycolor2';
import { nanoid } from 'nanoid';
import type { PPTElement, PPTLineElement, Slide } from '@openmaic/dsl';
import { getElementRange } from '@openmaic/renderer';

export { getElementRange, getLineElementPath } from '@openmaic/renderer';

interface RotatedElementData {
  left: number;
  top: number;
  width: number;
  height: number;
  rotate: number;
}

interface IdMap {
  [id: string]: string;
}

/**
 * Compute the rotated bounding rectangle of a canvas element.
 * @param element Element position, size, and rotation.
 */
export const getRectRotatedRange = (element: RotatedElementData) => {
  const { left, top, width, height, rotate = 0 } = element;

  const radius = Math.sqrt(Math.pow(width, 2) + Math.pow(height, 2)) / 2;
  const auxiliaryAngle = (Math.atan(height / width) * 180) / Math.PI;

  const tlbraRadian = ((180 - rotate - auxiliaryAngle) * Math.PI) / 180;
  const trblaRadian = ((auxiliaryAngle - rotate) * Math.PI) / 180;

  const middleLeft = left + width / 2;
  const middleTop = top + height / 2;

  const xAxis = [
    middleLeft + radius * Math.cos(tlbraRadian),
    middleLeft + radius * Math.cos(trblaRadian),
    middleLeft - radius * Math.cos(tlbraRadian),
    middleLeft - radius * Math.cos(trblaRadian),
  ];
  const yAxis = [
    middleTop - radius * Math.sin(tlbraRadian),
    middleTop - radius * Math.sin(trblaRadian),
    middleTop + radius * Math.sin(tlbraRadian),
    middleTop + radius * Math.sin(trblaRadian),
  ];

  return {
    xRange: [Math.min(...xAxis), Math.max(...xAxis)],
    yRange: [Math.min(...yAxis), Math.max(...yAxis)],
  };
};

/**
 * Compute the offset between an element original and rotated bounding rectangles.
 * @param element Element position, size, and rotation.
 */
export const getRectRotatedOffset = (element: RotatedElementData) => {
  const { xRange: originXRange, yRange: originYRange } = getRectRotatedRange({
    left: element.left,
    top: element.top,
    width: element.width,
    height: element.height,
    rotate: 0,
  });
  const { xRange: rotatedXRange, yRange: rotatedYRange } = getRectRotatedRange({
    left: element.left,
    top: element.top,
    width: element.width,
    height: element.height,
    rotate: element.rotate,
  });
  return {
    offsetX: rotatedXRange[0] - originXRange[0],
    offsetY: rotatedYRange[0] - originYRange[0],
  };
};

/**
 * Compute the canvas bounds of a group of elements.
 * @param elementList Element collection.
 */
export const getElementListRange = (elementList: PPTElement[]) => {
  const leftValues: number[] = [];
  const topValues: number[] = [];
  const rightValues: number[] = [];
  const bottomValues: number[] = [];

  elementList.forEach((element) => {
    const { minX, maxX, minY, maxY } = getElementRange(element);
    leftValues.push(minX);
    topValues.push(minY);
    rightValues.push(maxX);
    bottomValues.push(maxY);
  });

  const minX = Math.min(...leftValues);
  const maxX = Math.max(...rightValues);
  const minY = Math.min(...topValues);
  const maxY = Math.max(...bottomValues);

  return { minX, maxX, minY, maxY };
};

/**
 * Compute the length of a line element.
 * @param element Line element.
 */
export const getLineElementLength = (element: PPTLineElement) => {
  const deltaX = element.end[0] - element.start[0];
  const deltaY = element.end[1] - element.start[1];
  const len = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
  return len;
};

export interface AlignLine {
  value: number;
  range: [number, number];
}

/**
 * Deduplicate alignment guides at the same coordinate, merging their minimum and maximum extents.
 * @param lines Alignment guide collection.
 */
export const uniqAlignLines = (lines: AlignLine[]) => {
  // Dedupe by `value` in O(n) via a Map keyed on value, instead of an
  // O(n²) `findIndex` over the accumulating result. This runs on every
  // drag/scale mousemove with one snap line per nearby element edge, so the
  // quadratic version janks on element-dense canvases. A Map preserves
  // first-occurrence insertion order (re-`set`-ting an existing key keeps its
  // position), so the output order and merge semantics are unchanged.
  const byValue = new Map<number, AlignLine>();
  for (const line of lines) {
    const existing = byValue.get(line.value);
    if (!existing) {
      byValue.set(line.value, line);
    } else {
      byValue.set(line.value, {
        value: line.value,
        range: [
          Math.min(existing.range[0], line.range[0]),
          Math.max(existing.range[1], line.range[1]),
        ],
      });
    }
  }
  return Array.from(byValue.values());
};

/**
 * Generate new IDs for every slide and create an old-to-new ID map.
 * Preserve relationships among slide IDs throughout the data.
 * @param slides Slide collection.
 */
export const createSlideIdMap = (slides: Slide[]) => {
  const slideIdMap: IdMap = {};
  for (const slide of slides) {
    slideIdMap[slide.id] = nanoid(10);
  }
  return slideIdMap;
};

/**
 * Generate new IDs for elements and create an old-to-new ID map.
 * Preserve element ID relationships while copying.
 * Elements sharing a groupId retain a shared new groupId after copying.
 * @param elements Element collection data.
 */
export const createElementIdMap = (elements: PPTElement[]) => {
  const groupIdMap: IdMap = {};
  const elIdMap: IdMap = {};
  for (const element of elements) {
    const groupId = element.groupId;
    if (groupId && !groupIdMap[groupId]) {
      groupIdMap[groupId] = nanoid(10);
    }
    elIdMap[element.id] = nanoid(10);
  }
  return {
    groupIdMap,
    elIdMap,
  };
};

/**
 * Get palette shades corresponding to a table theme color.
 * @param themeColor Theme color.
 */
export const getTableSubThemeColor = (themeColor: string) => {
  const rgba = tinycolor(themeColor);
  return [rgba.setAlpha(0.3).toRgbString(), rgba.setAlpha(0.1).toRgbString()];
};

/**
 * Determine whether an element is inside the visible area.
 * @param element Element.
 * @param parent Parent element.
 */
export const isElementInViewport = (element: HTMLElement, parent: HTMLElement): boolean => {
  const elementRect = element.getBoundingClientRect();
  const parentRect = parent.getBoundingClientRect();

  return elementRect.top >= parentRect.top && elementRect.bottom <= parentRect.bottom;
};
