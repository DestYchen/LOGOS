import type { PreviewCalibration } from "./preview-calibration";

export type PreviewBBox = [number, number, number, number];

export type BBoxCoordinateSpace =
  | { kind: "normalized" }
  | { kind: "highres"; sourceWidth: number; sourceHeight: number }
  | { kind: "legacy" };

export type DisplayBBoxFrame = {
  left: number;
  top: number;
  width: number;
  height: number;
};

const HIGH_RES_THRESHOLD = 1.25;
const PDF_300DPI_REFERENCE_SHORT_SIDE = 2480;

function isNormalizedBBox(bbox: PreviewBBox): boolean {
  return bbox.every((value) => Number.isFinite(value) && value >= 0 && value <= 1);
}

function normalizedBox(bbox: PreviewBBox): PreviewBBox {
  const [x1Raw, y1Raw, x2Raw, y2Raw] = bbox;
  return [Math.min(x1Raw, x2Raw), Math.min(y1Raw, y2Raw), Math.max(x1Raw, x2Raw), Math.max(y1Raw, y2Raw)];
}

export function detectBBoxCoordinateSpace(
  bboxes: Array<PreviewBBox | null | undefined>,
  naturalWidth: number,
  naturalHeight: number,
): BBoxCoordinateSpace {
  const valid = bboxes.filter((bbox): bbox is PreviewBBox => Boolean(bbox && bbox.length === 4));
  if (!valid.length || naturalWidth <= 0 || naturalHeight <= 0) {
    return { kind: "legacy" };
  }
  if (valid.every(isNormalizedBBox)) {
    return { kind: "normalized" };
  }

  const maxX = Math.max(...valid.flatMap((bbox) => [bbox[0], bbox[2]]).filter(Number.isFinite));
  const maxY = Math.max(...valid.flatMap((bbox) => [bbox[1], bbox[3]]).filter(Number.isFinite));
  const highRes = maxX > naturalWidth * HIGH_RES_THRESHOLD || maxY > naturalHeight * HIGH_RES_THRESHOLD;
  if (!highRes) {
    return { kind: "legacy" };
  }

  const aspect = naturalWidth / naturalHeight;
  if (!Number.isFinite(aspect) || aspect <= 0) {
    return { kind: "legacy" };
  }

  let sourceWidth: number;
  let sourceHeight: number;
  if (naturalHeight >= naturalWidth) {
    sourceWidth = PDF_300DPI_REFERENCE_SHORT_SIDE;
    sourceHeight = sourceWidth / aspect;
  } else {
    sourceHeight = PDF_300DPI_REFERENCE_SHORT_SIDE;
    sourceWidth = sourceHeight * aspect;
  }

  return {
    kind: "highres",
    sourceWidth: Math.max(sourceWidth, maxX),
    sourceHeight: Math.max(sourceHeight, maxY),
  };
}

export function computeDisplayBBoxFrame({
  bbox,
  naturalWidth,
  naturalHeight,
  displayWidth,
  displayHeight,
  coordinateSpace,
  calibration,
}: {
  bbox: PreviewBBox;
  naturalWidth: number;
  naturalHeight: number;
  displayWidth: number;
  displayHeight: number;
  coordinateSpace: BBoxCoordinateSpace;
  calibration: PreviewCalibration;
}): DisplayBBoxFrame | null {
  if (naturalWidth <= 0 || naturalHeight <= 0 || displayWidth <= 0 || displayHeight <= 0) {
    return null;
  }

  const [x1, y1, x2, y2] = normalizedBox(bbox);
  if (x2 <= x1 || y2 <= y1) {
    return null;
  }

  if (coordinateSpace.kind === "normalized") {
    return {
      left: x1 * displayWidth,
      top: y1 * displayHeight,
      width: Math.max((x2 - x1) * displayWidth, 1.5),
      height: Math.max((y2 - y1) * displayHeight, 1.5),
    };
  }

  if (coordinateSpace.kind === "highres") {
    return {
      left: (x1 / coordinateSpace.sourceWidth) * displayWidth,
      top: (y1 / coordinateSpace.sourceHeight) * displayHeight,
      width: Math.max(((x2 - x1) / coordinateSpace.sourceWidth) * displayWidth, 1.5),
      height: Math.max(((y2 - y1) / coordinateSpace.sourceHeight) * displayHeight, 1.5),
    };
  }

  const baseScaleX = displayWidth / naturalWidth;
  const baseScaleY = displayHeight / naturalHeight;
  const adjustedScaleX = baseScaleX * calibration.scaleX;
  const adjustedScaleY = baseScaleY * calibration.scaleY;
  return {
    left: x1 * adjustedScaleX + calibration.offsetX,
    top: y1 * adjustedScaleY + calibration.offsetY,
    width: Math.max((x2 - x1) * adjustedScaleX, 1.5),
    height: Math.max((y2 - y1) * adjustedScaleY, 1.5),
  };
}
