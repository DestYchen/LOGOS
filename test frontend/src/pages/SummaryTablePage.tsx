import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent } from "react";
import type { ChangeEvent } from "react";
import { ArrowLeft, ArrowRight, Eye, EyeOff } from "lucide-react";
import { createPortal } from "react-dom";
import { useNavigate, useParams } from "react-router-dom";

import { Alert } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Spinner } from "../components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Textarea } from "../components/ui/textarea";
import { useHistoryContext } from "../contexts/history-context";
import { confirmField, fetchBatchDetails, updateField, uploadDocumentsToBatch } from "../lib/api";
import { cn, formatDateTime, mapBatchStatus, statusLabel } from "../lib/utils";
import { formatPacketTimestamp } from "../lib/packet";
import { DOCUMENT_PREVIEW_CALIBRATION } from "../lib/preview-calibration";
import type { BatchDetails, DocumentPayload, FieldState } from "../types/api";

type ValidationRef = {
  doc_id?: string;
  doc_type?: string;
  field_key?: string;
  label?: string;
  message?: string;
  present?: boolean;
  note?: string;
};

type ValidationEntry = {
  ruleId: string;
  severity: string;
  message: string;
  refs: ValidationRef[];
};

type MatrixPopoverState = {
  doc: DocumentPayload;
  field: FieldState;
  anchor: { top: number; left: number };
  value: string;
  confidence: number | null;
  mode: "hover" | "edit";
};

type MatrixPreviewTarget = {
  docId: string;
  fieldKey: string;
};

type DocPresenceItem = {
  docType: string;
  actualType: string;
  label: string;
  present: boolean;
  filenames: string[];
  count: number;
  processing: boolean;
};

type FieldMatrixCell = {
  value: string | null;
  status: string | null;
};

type FieldMatrixRowView = {
  fieldKey: string;
  cells: Record<string, FieldMatrixCell>;
};

type ProductTableDoc = {
  label: string;
  fields: Record<string, { value: string | null; confidence: number | null }>;
};

type ProductComparisonTable = {
  id: string;
  title: string;
  docs: ProductTableDoc[];
};

type FieldPreviewSnapshot = {
  previewUrl: string | null;
  frameStyle: CSSProperties;
  imageStyle: CSSProperties;
  confidenceValue: string | null;
  sliceKey: string | null;
  sliceReady: boolean;
};

type PreviewSlice = {
  url: string;
  width: number;
  height: number;
};

type RawBBox = [number, number, number, number];

type MatrixPreviewHighlight = {
  fieldKey?: string;
  bbox?: RawBBox | null;
  page?: number | null;
};

type MatrixPreviewOverlay = {
  fieldKey: string;
  bbox: RawBBox;
  page?: number | null;
};

type MatrixPreviewRenderItem = {
  key: string;
  style: CSSProperties;
  color: string;
  thickness: number;
};

const EMPTY_DOC_ID = "00000000-0000-0000-0000-000000000000";
const PREVIEW_CALIBRATION = DOCUMENT_PREVIEW_CALIBRATION;
const ADD_MAX_FILE_SIZE_MB = 50;
const ADD_MAX_FILE_SIZE = ADD_MAX_FILE_SIZE_MB * 1024 * 1024;
const ADD_SUPPORTED_EXT = ["pdf", "doc", "docx", "xls", "xlsx", "txt", "png", "jpg", "jpeg"];

function validateAddedFile(file: File, existing: File[]) {
  const errors: string[] = [];
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  if (!ADD_SUPPORTED_EXT.includes(ext)) {
    errors.push("Неподдерживаемый формат");
  }
  if (file.size > ADD_MAX_FILE_SIZE) {
    errors.push(`Размер больше ${ADD_MAX_FILE_SIZE_MB} МБ`);
  }
  const duplicate = existing.some((entry) => entry.name === file.name && entry.size === file.size);
  if (duplicate) {
    errors.push("Файл уже добавлен");
  }
  return errors;
}

function uploadMessageKey(batchId: string) {
  return `batch-upload-message:${batchId}`;
}

const PRODUCT_FIELD_LABELS: Record<string, string> = {
  name_product: "Наименование",
  latin_name: "Латинское название",
  size_product: "Размер",
  unit_box: "Ед. / упаковка",
  packages: "Места",
  quantity: "Количество",
  weight: "Вес",
  net_weight: "Масса нетто",
  gross_weight: "Масса брутто",
  price_per_unit: "Цена за единицу",
  total_price: "Сумма",
  currency: "Валюта",
};

const FIELD_LABELS_RU: Record<string, string> = {
  proforma_date: "Дата проформы",
  proforma_no: "Номер проформы",
  invoice_date: "Дата инвойса",
  invoice_no: "Номер инвойса",
  country_of_origin: "Страна происхождения",
  producer: "Производитель",
  buyer: "Покупатель",
  seller: "Продавец",
  exporter: "Экспортер",
  importer: "Импортер",
  incoterms: "Инкотермс",
  terms_of_payment: "Условия оплаты",
  bank_details: "Банковские реквизиты",
  total_price: "Сумма",
  destination: "Пункт назначения",
  vessel: "Судно",
  container_no: "Номер контейнера",
  veterinary_seal: "Ветеринарная пломба",
  linear_seal: "Линейная пломба",
  veterinary_certificate_no: "Номер ветеринарного сертификата",
  veterinary_certificate_date: "Дата ветеринарного сертификата",
  HS_code: "Код ТНВЭД",
};


const MATRIX_STATUS_CLASSES: Record<string, string> = {
  anchor: "bg-sky-100",
  match: "bg-emerald-100",
  missing: "bg-rose-100",
  mismatch: "bg-amber-100",
};

const MATRIX_STATUS_LABELS: Record<string, string> = {
  anchor: "Опорный документ",
  match: "Совпадает",
  missing: "Нет значения",
  mismatch: "Значение отличается",
};


const PRODUCT_TABLE_FIELDS = [
  { key: "name_product", label: "Наименование" },
  { key: "latin_name", label: "Латинское название" },
  { key: "size_product", label: "Размер" },
  { key: "unit_box", label: "Ед. / упаковка" },
  { key: "packages", label: "Места" },
  { key: "price_per_unit", label: "Цена за единицу" },
  { key: "total_price", label: "Сумма" },
];

const EXPECTED_DOC_TYPES = [
  { key: "CONTRACT", label: "Контракт" },
  { key: "ADDENDUM", label: "Доп. соглашение" },
  { key: "PROFORMA", label: "Проформа" },
  { key: "INVOICE", label: "Инвойс" },
  { key: "BILL_OF_LADING", label: "Коносамент" },
  { key: "CMR", label: "CMR" },
  { key: "PACKING_LIST", label: "Пак-лист" },
  { key: "PRICE_LIST_1", label: "Прайс-лист 1" },
  { key: "PRICE_LIST_2", label: "Прайс-лист 2" },
  { key: "QUALITY_CERTIFICATE", label: "Сертификат качества" },
  { key: "VETERINARY_CERTIFICATE", label: "Вет. сертификат" },
  { key: "EXPORT_DECLARATION", label: "Экспортная декларация" },
  { key: "SPECIFICATION", label: "Спецификация" },
  { key: "CERTIFICATE_OF_ORIGIN", label: "Сертификат происхождения" },
  { key: "FORM_A", label: "FORM A" },
  { key: "EAV", label: "EAV" },
  { key: "CT-3", label: "CT-3" },
];

const DOC_TYPE_LABELS: Record<string, string> = EXPECTED_DOC_TYPES.reduce(
  (acc, entry) => {
    acc[entry.key] = entry.label;
    return acc;
  },
  {} as Record<string, string>,
);

const FIELD_MATRIX_DOC_TYPE_MAP: Record<string, string> = {
  CONTRACT: "CONTRACT",
  ADDENDUM: "ADDENDUM",
  PROFORMA: "PROFORMA",
  INVOICE: "INVOICE",
  BILL_OF_LADING: "BILL_OF_LANDING",
  CMR: "CMR",
  PACKING_LIST: "PACKING_LIST",
  PRICE_LIST_1: "PRICE_LIST_1",
  PRICE_LIST_2: "PRICE_LIST_2",
  QUALITY_CERTIFICATE: "QUALITY_CERTIFICATE",
  VETERINARY_CERTIFICATE: "VETERINARY_CERTIFICATE",
  EXPORT_DECLARATION: "EXPORT_DECLARATION",
  SPECIFICATION: "SPECIFICATION",
  CERTIFICATE_OF_ORIGIN: "CERTIFICATE_OF_ORIGIN",
  FORM_A: "FORM_A",
  EAV: "EAV",
  "CT-3": "CT-3",
};

const FIELD_MATRIX_ACTUAL_TO_DISPLAY: Record<string, string> = Object.entries(FIELD_MATRIX_DOC_TYPE_MAP).reduce(
  (acc, [display, actual]) => {
    acc[actual] = display;
    return acc;
  },
  {} as Record<string, string>,
);

const BASE_VIEWER_HEIGHT = 640;
const TARGET_PREVIEW_HEIGHT = 360;
const PREVIEW_MAGNIFICATION = 6;
const MIN_FRAME_SIZE = 1;
const PREVIEW_PADDING = 6;
const MATRIX_STICKY_GAP = 24;
const MATRIX_STICKY_BOTTOM_GAP = 0;
const DIFF_TAG_OPEN = "{redacted}";
const DIFF_TAG_CLOSE = "{/redacted}";

function toActualDocType(docType: string): string {
  return FIELD_MATRIX_DOC_TYPE_MAP[docType] ?? docType;
}

function toDisplayDocType(docType: string): string {
  return FIELD_MATRIX_ACTUAL_TO_DISPLAY[docType] ?? docType;
}


function productFieldLabel(field: string): string {
  const normalized = field.toLowerCase();
  if (Object.prototype.hasOwnProperty.call(PRODUCT_FIELD_LABELS, normalized)) {
    return PRODUCT_FIELD_LABELS[normalized];
  }
  return field.replace(/[_\.]/g, " ");
}

function matrixStatusClass(status: string | null | undefined): string {
  if (!status) {
    return "";
  }
  return MATRIX_STATUS_CLASSES[status] ?? "";
}

function normalizeText(value: unknown): string | null {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  if (value === null || value === undefined) {
    return null;
  }
  return String(value);
}

function normalizeConfidence(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function extractProductField(entry: unknown): { value: string | null; confidence: number | null } {
  if (entry && typeof entry === "object") {
    const payload = entry as Record<string, unknown>;
    return {
      value: normalizeText(payload.value),
      confidence: normalizeConfidence(payload.confidence),
    };
  }
  return {
    value: normalizeText(entry),
    confidence: null,
  };
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(max, Math.max(min, value));
}

function ensureBBox(input: unknown): RawBBox | null {
  if (!input) {
    return null;
  }
  if (Array.isArray(input) && input.length >= 4) {
    const values = input.slice(0, 4).map((value) => Number(value));
    return values.every((value) => Number.isFinite(value)) ? ([...values.slice(0, 4)] as RawBBox) : null;
  }
  if (typeof input === "object") {
    const record = input as Record<string, unknown>;
    const candidates: Array<[string, string, string, string, ((values: number[]) => number[]) | null]> = [
      ["x1", "y1", "x2", "y2", null],
      ["left", "top", "right", "bottom", null],
      ["x", "y", "width", "height", (values) => [values[0], values[1], values[0] + values[2], values[1] + values[3]]],
    ];
    for (const [a, b, c, d, transform] of candidates) {
      const rawValues = [record[a], record[b], record[c], record[d]];
      if (rawValues.some((value) => value === undefined || value === null)) {
        continue;
      }
      const numbers = rawValues.map((value) => Number(value));
      if (numbers.every((value) => Number.isFinite(value))) {
        const finalValues = transform ? transform(numbers) : numbers;
        return [finalValues[0], finalValues[1], finalValues[2], finalValues[3]] as RawBBox;
      }
    }
  }
  return null;
}

function splitDiffSegments(value: string): Array<{ text: string; isDiff: boolean }> {
  const segments: Array<{ text: string; isDiff: boolean }> = [];
  let remaining = value;
  while (remaining.length > 0) {
    const openIndex = remaining.indexOf(DIFF_TAG_OPEN);
    if (openIndex === -1) {
      segments.push({ text: remaining, isDiff: false });
      break;
    }
    if (openIndex > 0) {
      segments.push({ text: remaining.slice(0, openIndex), isDiff: false });
    }
    remaining = remaining.slice(openIndex + DIFF_TAG_OPEN.length);
    const closeIndex = remaining.indexOf(DIFF_TAG_CLOSE);
    if (closeIndex === -1) {
      if (remaining.length > 0) {
        segments.push({ text: remaining, isDiff: true });
      }
      break;
    }
    if (closeIndex > 0) {
      segments.push({ text: remaining.slice(0, closeIndex), isDiff: true });
    }
    remaining = remaining.slice(closeIndex + DIFF_TAG_CLOSE.length);
  }
  return segments.filter((segment) => segment.text.length > 0);
}

function resolvePreviewSource(doc: DocumentPayload, field: FieldState) {
  const previews = Array.isArray(doc.previews) ? doc.previews : [];
  const totalPages = previews.length;
  const rawPage = typeof field.page === "number" && Number.isFinite(field.page) && field.page > 0 ? field.page : 1;
  const pageIndex = totalPages > 0 ? Math.max(0, Math.min(rawPage - 1, totalPages - 1)) : 0;
  const previewUrl = totalPages > 0 ? previews[pageIndex] ?? previews[0] ?? null : null;
  return { previewUrl, pageIndex, totalPages };
}

function buildPreviewSliceKey(
  docId: string,
  fieldKey: string,
  pageIndex: number,
  previewUrl: string | null,
  bbox: RawBBox | null,
): string | null {
  if (!previewUrl || !bbox) {
    return null;
  }
  const bboxKey = bbox.map((value) => (Number.isFinite(value) ? value.toFixed(1) : "0")).join(":");
  return JSON.stringify([docId, fieldKey, pageIndex, bboxKey, previewUrl]);
}

function loadPreviewImage(
  url: string,
  cache: Map<string, Promise<HTMLImageElement>>,
): Promise<HTMLImageElement> {
  if (!url) {
    return Promise.reject(new Error("Preview URL is empty."));
  }
  const cached = cache.get(url);
  if (cached) {
    return cached;
  }
  if (typeof window === "undefined" || typeof Image === "undefined") {
    return Promise.reject(new Error("Preview loading is not available in this environment."));
  }
  const promise = new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => resolve(image);
    image.onerror = () => {
      cache.delete(url);
      reject(new Error(`Failed to load preview: ${url}`));
    };
    image.src = url;
  });
  cache.set(url, promise);
  return promise;
}

function computeOverlayFrame(bbox: RawBBox, metaWidth: number, metaHeight: number) {
  if (metaWidth <= 0 || metaHeight <= 0) {
    return null;
  }
  const [x1Raw, y1Raw, x2Raw, y2Raw] = bbox;
  const x1 = Math.min(x1Raw, x2Raw);
  const y1 = Math.min(y1Raw, y2Raw);
  const x2 = Math.max(x1Raw, x2Raw);
  const y2 = Math.max(y1Raw, y2Raw);

  const baseDisplayHeight = BASE_VIEWER_HEIGHT;
  const baseDisplayWidth = (baseDisplayHeight * metaWidth) / metaHeight;
  const baseScaleX = baseDisplayWidth / metaWidth;
  const baseScaleY = baseDisplayHeight / metaHeight;
  const adjustedScaleX = baseScaleX * PREVIEW_CALIBRATION.scaleX;
  const adjustedScaleY = baseScaleY * PREVIEW_CALIBRATION.scaleY;

  const rawWidth = x2 - x1;
  const rawHeight = y2 - y1;
  if (rawWidth <= 0 || rawHeight <= 0) {
    return null;
  }

  const baseWidth = rawWidth * adjustedScaleX;
  const baseHeight = rawHeight * adjustedScaleY;
  const baseLeft = x1 * adjustedScaleX + PREVIEW_CALIBRATION.offsetX;
  const baseTop = y1 * adjustedScaleY + PREVIEW_CALIBRATION.offsetY;

  if (!Number.isFinite(baseWidth) || !Number.isFinite(baseHeight) || baseWidth <= 0 || baseHeight <= 0) {
    return null;
  }

  const scale = TARGET_PREVIEW_HEIGHT / baseDisplayHeight;
  const imageWidth = baseDisplayWidth * scale;
  const imageHeight = TARGET_PREVIEW_HEIGHT;

  const overlayWidth = baseWidth * scale;
  const overlayHeight = baseHeight * scale;
  const overlayLeft = baseLeft * scale;
  const overlayTop = baseTop * scale;

  const maxLeft = Math.max(imageWidth - MIN_FRAME_SIZE, 0);
  const maxTop = Math.max(imageHeight - MIN_FRAME_SIZE, 0);
  const clampedLeft = clamp(overlayLeft, 0, maxLeft);
  const clampedTop = clamp(overlayTop, 0, maxTop);
  const clampedWidth = clamp(overlayWidth, MIN_FRAME_SIZE, imageWidth - clampedLeft);
  const clampedHeight = clamp(overlayHeight, MIN_FRAME_SIZE, imageHeight - clampedTop);

  const paddedLeft = clamp(clampedLeft - PREVIEW_PADDING, 0, Math.max(imageWidth - MIN_FRAME_SIZE, 0));
  const paddedTop = clamp(clampedTop - PREVIEW_PADDING, 0, Math.max(imageHeight - MIN_FRAME_SIZE, 0));
  const paddedWidth = clamp(clampedWidth + PREVIEW_PADDING * 2, MIN_FRAME_SIZE, imageWidth - paddedLeft);
  const paddedHeight = clamp(clampedHeight + PREVIEW_PADDING * 2, MIN_FRAME_SIZE, imageHeight - paddedTop);

  return {
    imageWidth,
    imageHeight,
    frame: {
      width: paddedWidth,
      height: paddedHeight,
      left: paddedLeft,
      top: paddedTop,
    },
  };
}

function createPreviewSlice(image: HTMLImageElement, bbox: RawBBox): PreviewSlice | null {
  if (typeof document === "undefined") {
    return null;
  }
  const { naturalWidth, naturalHeight } = image;
  if (!naturalWidth || !naturalHeight) {
    return null;
  }
  const overlay = computeOverlayFrame(bbox, naturalWidth, naturalHeight);
  if (!overlay) {
    return null;
  }
  const zoom = PREVIEW_MAGNIFICATION;
  const canvas = document.createElement("canvas");
  const deviceScale = typeof window !== "undefined" && window.devicePixelRatio ? window.devicePixelRatio : 1;
  const outputWidth = Math.max(Math.round(overlay.frame.width * zoom), MIN_FRAME_SIZE);
  const outputHeight = Math.max(Math.round(overlay.frame.height * zoom), MIN_FRAME_SIZE);
  canvas.width = Math.max(Math.round(outputWidth * deviceScale), 1);
  canvas.height = Math.max(Math.round(outputHeight * deviceScale), 1);
  const context = canvas.getContext("2d");
  if (!context) {
    return null;
  }
  context.scale(deviceScale, deviceScale);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(
    image,
    0,
    0,
    naturalWidth,
    naturalHeight,
    -overlay.frame.left * zoom,
    -overlay.frame.top * zoom,
    overlay.imageWidth * zoom,
    overlay.imageHeight * zoom,
  );
  const url = canvas.toDataURL("image/png");
  return { url, width: outputWidth, height: outputHeight };
}

function MatrixDocumentPreview({
  previews,
  highlight,
  boxes,
  showBoxes,
  onToggleBoxes,
}: {
  previews: string[];
  highlight: MatrixPreviewHighlight | null;
  boxes: MatrixPreviewOverlay[];
  showBoxes: boolean;
  onToggleBoxes?: () => void;
}) {
  const [origin, setOrigin] = useState({ x: 50, y: 50 });
  const [dims, setDims] = useState({ naturalWidth: 0, naturalHeight: 0, width: 0, height: 0 });
  const [isHovered, setIsHovered] = useState(false);
  const [isControlHovered, setIsControlHovered] = useState(false);
  const imgRef = useRef<HTMLImageElement | null>(null);

  const previewCount = previews.length;
  const imageIndex =
    highlight?.page && highlight.page > 0 && previewCount > 0
      ? Math.min(highlight.page - 1, previewCount - 1)
      : 0;
  const currentPage = previewCount > 0 ? imageIndex + 1 : 1;
  const src = previews[imageIndex] ?? previews[0];

  const updateSizes = useCallback(() => {
    if (!imgRef.current) return;
    const { naturalWidth, naturalHeight, clientWidth, clientHeight } = imgRef.current;
    setDims({ naturalWidth, naturalHeight, width: clientWidth, height: clientHeight });
  }, []);

  const onMouseMove = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (isControlHovered) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - bounds.left) / bounds.width) * 100;
    const y = ((event.clientY - bounds.top) / bounds.height) * 100;
    setOrigin({ x, y });
  };

  useEffect(() => {
    if (typeof ResizeObserver === "undefined" || !imgRef.current) return;
    const observer = new ResizeObserver(() => updateSizes());
    observer.observe(imgRef.current);
    return () => observer.disconnect();
  }, [updateSizes, src]);

  const createOverlay = useCallback(
    (
      fieldKey: string,
      bbox?: RawBBox | null,
      color = "hsl(var(--primary) / 0.45)",
      thickness = 3,
    ): MatrixPreviewRenderItem | null => {
      if (!bbox || bbox.length !== 4 || dims.naturalWidth === 0 || dims.naturalHeight === 0) return null;
      const padding = 6;
      const [x1, y1, x2, y2] = bbox;
      const baseScaleX = dims.width / dims.naturalWidth;
      const baseScaleY = dims.height / dims.naturalHeight;
      const adjustedScaleX = baseScaleX * PREVIEW_CALIBRATION.scaleX;
      const adjustedScaleY = baseScaleY * PREVIEW_CALIBRATION.scaleY;
      const width = Math.max((x2 - x1) * adjustedScaleX, 1.5);
      const height = Math.max((y2 - y1) * adjustedScaleY, 1.5);
      const left = x1 * adjustedScaleX + PREVIEW_CALIBRATION.offsetX;
      const top = y1 * adjustedScaleY + PREVIEW_CALIBRATION.offsetY;
      return {
        key: fieldKey,
        style: {
          left: `${left - padding}px`,
          top: `${top - padding}px`,
          width: `${width + padding * 2}px`,
          height: `${height + padding * 2}px`,
        },
        color,
        thickness,
      };
    },
    [dims],
  );

  const baseOverlays = useMemo(() => {
    if (!boxes.length) return [] as MatrixPreviewRenderItem[];
    return boxes
      .filter((box) => (box.page && box.page > 0 ? box.page : 1) === currentPage)
      .map((box) => createOverlay(box.fieldKey, box.bbox))
      .filter((item): item is MatrixPreviewRenderItem => Boolean(item));
  }, [boxes, currentPage, createOverlay]);

  const highlightOverlay = useMemo(() => {
    if (!highlight) return null;
    const pageNumber = highlight.page && highlight.page > 0 ? highlight.page : 1;
    if (pageNumber !== currentPage) return null;
    return createOverlay(highlight.fieldKey ?? "highlight", highlight.bbox ?? null, "hsl(var(--primary))", 4);
  }, [highlight, currentPage, createOverlay]);

  const overlaysToRender = useMemo(() => {
    const items: MatrixPreviewRenderItem[] = [];
    if (showBoxes) {
      items.push(...baseOverlays.filter((item) => item.key !== highlightOverlay?.key));
    }
    if (highlightOverlay) {
      items.push(highlightOverlay);
    }
    return items;
  }, [showBoxes, baseOverlays, highlightOverlay]);

  const zoomScale = isHovered ? 3 : 1;
  const transformOriginValue = `${origin.x}% ${origin.y}%`;
  const sharedTransformStyle = {
    transformOrigin: transformOriginValue,
    transform: `scale(${zoomScale})`,
  };

  const highlightCoversDocument = Boolean(highlight) && (!highlight?.bbox || highlight.bbox.length !== 4);

  const renderOverlay = (overlay: MatrixPreviewRenderItem) => (
    <div
      key={overlay.key}
      className="pointer-events-none absolute"
      style={{
        ...overlay.style,
        border: `${overlay.thickness}px solid ${overlay.color}`,
        boxShadow: "0 0 10px rgba(0,0,0,0.18)",
        borderRadius: "14px",
      }}
    />
  );

  return (
    <div
      className={cn(
        "group relative aspect-[3/4] w-full overflow-hidden rounded-3xl border bg-background shadow-lg transition-colors",
        highlightCoversDocument ? "border-4 border-primary/70" : "",
      )}
      onMouseMove={onMouseMove}
      onMouseEnter={() => {
        if (!isControlHovered) {
          setIsHovered(true);
        }
      }}
      onMouseLeave={() => {
        setIsHovered(false);
        setIsControlHovered(false);
      }}
    >
      {src ? (
        <>
          <img
            ref={imgRef}
            src={src}
            alt=" "
            onLoad={updateSizes}
            style={sharedTransformStyle}
            className="h-full w-full object-contain transition-transform duration-200 ease-out"
          />
          <div className="pointer-events-none absolute inset-0" style={sharedTransformStyle}>
            {overlaysToRender.map(renderOverlay)}
          </div>
          {onToggleBoxes ? (
            <div className="pointer-events-none absolute inset-0">
              <div
                className="pointer-events-auto absolute right-3 top-3 flex gap-2"
                onMouseEnter={(event) => {
                  event.stopPropagation();
                  setIsControlHovered(true);
                  setIsHovered(false);
                }}
                onMouseLeave={(event) => {
                  event.stopPropagation();
                  setIsControlHovered(false);
                  setIsHovered(false);
                }}
              >
                <Button
                  size="icon"
                  variant="secondary"
                  aria-label={showBoxes ? "Скрыть контуры" : "Показать контуры"}
                  onClick={onToggleBoxes}
                  className="shadow-sm"
                >
                  {showBoxes ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
              </div>
            </div>
          ) : null}
        </>
      ) : (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Нет превью</div>
      )}
    </div>
  );
}

function productColumnLabel(key: string): string {
  const match = key.match(/(\d+)/);
  if (match) {
    return `Продукт ${match[1]}`;
  }
  return key.replace(/_/g, " ");
}

function severityClass(severity: string): string {
  const normalized = severity.toLowerCase();
  if (normalized === "error" || normalized === "critical") {
    return "text-destructive";
  }
  if (normalized === "warn" || normalized === "warning") {
    return "text-amber-600";
  }
  return "text-muted-foreground";
}

function parseRefEntry(value: unknown): ValidationRef | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const data = value as Record<string, unknown>;
  const docIdValue = data["doc_id"];
  const docTypeValue = data["doc_type"];
  const fieldKeyValue = data["field_key"];
  const labelValue = data["label"];
  const messageValue = data["message"];
  const presentValue = data["present"];
  const noteValue = data["note"];
  const docId = typeof docIdValue === "string" ? docIdValue : undefined;
  const docType = typeof docTypeValue === "string" ? docTypeValue : undefined;
  const fieldKey = typeof fieldKeyValue === "string" ? fieldKeyValue : undefined;
  const label = typeof labelValue === "string" ? labelValue : undefined;
  const message = typeof messageValue === "string" ? messageValue : undefined;
  const present =
    typeof presentValue === "boolean"
      ? presentValue
      : docId === EMPTY_DOC_ID
        ? false
        : undefined;
  const note = typeof noteValue === "string" ? noteValue : undefined;
  return { doc_id: docId, doc_type: docType, field_key: fieldKey, label, message, present, note };
}

function parseRefs(entry: Record<string, unknown>): ValidationRef[] {
  const raw = entry?.refs;
  if (typeof raw === "string" && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed.map(parseRefEntry).filter((item): item is ValidationRef => item !== null);
      }
      return [];
    } catch {
      return [];
    }
  }
  if (Array.isArray(raw)) {
    return raw.map(parseRefEntry).filter((item): item is ValidationRef => item !== null);
  }
  return [];
}

function SummaryTablePage() {
  const params = useParams();
  const navigate = useNavigate();
  const { refresh } = useHistoryContext();

  const batchId = params.batchId;

  const [batch, setBatch] = useState<BatchDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [addingDocs, setAddingDocs] = useState(false);
  const addDocsInputRef = useRef<HTMLInputElement | null>(null);
  const [matrixPopover, setMatrixPopover] = useState<MatrixPopoverState | null>(null);
  const [saving, setSaving] = useState(false);
  const [diffMode, setDiffMode] = useState(false);
  const [previewEnabled, setPreviewEnabled] = useState(false);
  const [previewHover, setPreviewHover] = useState<MatrixPreviewTarget | null>(null);
  const [previewSelected, setPreviewSelected] = useState<MatrixPreviewTarget | null>(null);
  const [showPreviewBoxes, setShowPreviewBoxes] = useState(true);
  const matrixBodyRef = useRef<HTMLDivElement | null>(null);
  const matrixTableScrollRef = useRef<HTMLDivElement | null>(null);
  const matrixTableRef = useRef<HTMLTableElement | null>(null);
  const previewStickyRef = useRef<HTMLDivElement | null>(null);
  const [previewStyle, setPreviewStyle] = useState<CSSProperties>({ top: "0px" });
  const [previewSlices, setPreviewSlices] = useState<Record<string, PreviewSlice>>({});
  const [previewSlicePending, setPreviewSlicePending] = useState<Record<string, boolean>>({});
  const previewImageCache = useRef(new Map<string, Promise<HTMLImageElement>>());

  const markSlicePending = useCallback((key: string | null, pending: boolean) => {
    if (!key) {
      return;
    }
    setPreviewSlicePending((prev) => {
      if (pending) {
        if (prev[key]) {
          return prev;
        }
        return { ...prev, [key]: true };
      }
      if (!prev[key]) {
        return prev;
      }
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const loadPreview = useCallback(
    (url: string | null) =>
      url ? loadPreviewImage(url, previewImageCache.current) : Promise.reject(new Error("No preview URL")),
    [],
  );

  const ensurePreviewSlice = useCallback(
    (doc: DocumentPayload, field: FieldState) => {
      if (typeof window === "undefined") {
        return;
      }
      const { previewUrl, pageIndex } = resolvePreviewSource(doc, field);
      const bbox = ensureBBox(field.bbox);
      const sliceKey = buildPreviewSliceKey(doc.id, field.field_key, pageIndex, previewUrl, bbox);
      if (!sliceKey || !previewUrl || !bbox || previewSlices[sliceKey] || previewSlicePending[sliceKey]) {
        return;
      }
      markSlicePending(sliceKey, true);
      loadPreview(previewUrl)
        .then((image) => createPreviewSlice(image, bbox))
        .then((slice) => {
          if (slice) {
            setPreviewSlices((prev) => (prev[sliceKey] ? prev : { ...prev, [sliceKey]: slice }));
          }
        })
        .catch((error) => {
          console.error("Failed to prepare preview slice", error);
        })
        .finally(() => {
          markSlicePending(sliceKey, false);
        });
    },
    [previewSlices, previewSlicePending, loadPreview, markSlicePending],
  );

  const buildFieldPreviewSnapshot = useCallback(
    (doc: DocumentPayload, field: FieldState): FieldPreviewSnapshot => {
      const { previewUrl, pageIndex } = resolvePreviewSource(doc, field);
      const bbox = ensureBBox(field.bbox);
      const sliceKey = buildPreviewSliceKey(doc.id, field.field_key, pageIndex, previewUrl, bbox);
      const slice = sliceKey ? previewSlices[sliceKey] : null;
      const frameStyle: CSSProperties = slice
        ? {
            width: "100%",
            maxWidth: `${slice.width}px`,
            aspectRatio: `${slice.width} / ${slice.height}`,
          }
        : { width: 560, height: 360 };
      const imageStyle: CSSProperties = slice
        ? {
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }
        : { width: "100%", height: "100%", objectFit: "contain" };
      const confidenceValue =
        field.confidence_display ?? (field.confidence != null ? Number(field.confidence).toFixed(2) : null);
      return {
        previewUrl: slice ? slice.url : null,
        frameStyle,
        imageStyle,
        confidenceValue,
        sliceKey,
        sliceReady: Boolean(slice),
      };
    },
    [previewSlices],
  );

  const fetchBatch = useCallback(async () => {
    if (!batchId) {
      return null;
    }
    const response = await fetchBatchDetails(batchId);
    setBatch(response.batch);
    void refresh();
    return response;
  }, [batchId, refresh]);

  useEffect(() => {
    setActionError(null);
    setMessage(null);
    if (!batchId || typeof window === "undefined") {
      setUploadMessage(null);
      return;
    }
    const stored = window.sessionStorage.getItem(uploadMessageKey(batchId));
    setUploadMessage(stored);
  }, [batchId]);

  useEffect(() => {
    if (!batchId || typeof window === "undefined") {
      return;
    }
    if (!uploadMessage) {
      window.sessionStorage.removeItem(uploadMessageKey(batchId));
      return;
    }
    const timeoutId = window.setTimeout(() => {
      setUploadMessage(null);
      window.sessionStorage.removeItem(uploadMessageKey(batchId));
    }, 5000);
    return () => window.clearTimeout(timeoutId);
  }, [batchId, uploadMessage]);

  const handleAddDocuments = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      if (!batchId) {
        return;
      }
      const selected = Array.from(event.target.files || []);
      event.target.value = "";
      if (selected.length === 0) {
        return;
      }
      const errors: string[] = [];
      const validFiles: File[] = [];
      selected.forEach((file) => {
        const issues = validateAddedFile(file, validFiles);
        if (issues.length) {
          errors.push(`${file.name}: ${issues.join(", ")}`);
        } else {
          validFiles.push(file);
        }
      });
      if (!validFiles.length) {
        setActionError(errors.join("; ") || "Нет подходящих файлов для загрузки.");
        return;
      }
      setActionError(null);
      setMessage(null);
      setUploadMessage(null);
      if (typeof window !== "undefined") {
        window.sessionStorage.removeItem(uploadMessageKey(batchId));
      }
      try {
        setAddingDocs(true);
        const response = await uploadDocumentsToBatch(batchId, validFiles);
        const updated = await fetchBatch();
        const baseMessage = `Добавлено документов: ${response.documents}. Перейдите к подготовке.`;
        const combined = errors.length ? `${baseMessage} Пропущены: ${errors.join("; ")}` : baseMessage;
        setUploadMessage(combined);
        if (typeof window !== "undefined") {
          window.sessionStorage.setItem(uploadMessageKey(batchId), combined);
        }
        if (updated?.batch && !updated.batch.prep_complete) {
          navigate(`/queue?batch=${batchId}`, { replace: true });
        }
      } catch (err) {
        setActionError((err as Error).message);
      } finally {
        setAddingDocs(false);
      }
    },
    [batchId, fetchBatch],
  );

  useEffect(() => {
    let cancelled = false;
    if (!batchId) {
      setError(new Error("Не указан идентификатор пакета."));
      setLoading(false);
      return;
    }
    setLoading(true);
    fetchBatch()
      .catch((err) => {
        if (!cancelled) {
          setError(err as Error);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [batchId, fetchBatch]);

  useEffect(() => {
    if (!batchId || !batch || !uploadMessage || typeof window === "undefined") {
      return;
    }
    if (!batch.prep_complete || (batch.report?.available && !batch.awaiting_processing)) {
      setUploadMessage(null);
      window.sessionStorage.removeItem(uploadMessageKey(batchId));
    }
  }, [batchId, batch, uploadMessage]);

  const documents = batch?.documents ?? [];
  const documentMap = useMemo(() => {
    const map = new Map<string, DocumentPayload>();
    documents.forEach((doc) => map.set(doc.id, doc));
    return map;
  }, [documents]);
  const presentDocInfo = useMemo(() => {
    const presentByActual = new Map<
      string,
      { docIds: string[]; filenames: string[]; processingCount: number }
    >();
    documents.forEach((doc) => {
      const entry =
        presentByActual.get(doc.doc_type) ?? { docIds: [], filenames: [], processingCount: 0 };
      entry.docIds.push(doc.id);
      if (doc.filename) {
        entry.filenames.push(doc.filename);
      }
      if (doc.processing && doc.status !== "FAILED") {
        entry.processingCount += 1;
      }
      presentByActual.set(doc.doc_type, entry);
    });
    return presentByActual;
  }, [documents]);
  const buildPopoverState = useCallback(
    (
      doc: DocumentPayload,
      field: FieldState,
      anchor: { top: number; left: number },
      mode: "hover" | "edit",
    ): MatrixPopoverState => {
      const confidence =
        field.confidence !== null && field.confidence !== undefined ? Number(field.confidence) : null;
      return {
        doc,
        field,
        anchor,
        value: field.value ?? "",
        confidence,
        mode,
      };
    },
    [],
  );

  const getCellAnchor = useCallback((event: ReactMouseEvent<HTMLTableCellElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      top: rect.top,
      left: rect.left + rect.width / 2,
    };
  }, []);

  const hidePreview = useCallback(() => {
    setPreviewHover(null);
    setMatrixPopover((prev) => (prev?.mode === "hover" ? null : prev));
  }, []);

  const handleCellHover = useCallback(
    (event: ReactMouseEvent<HTMLTableCellElement>, doc: DocumentPayload, field: FieldState) => {
      if (typeof window === "undefined") {
        return;
      }
      setPreviewHover({ docId: doc.id, fieldKey: field.field_key });
      if (matrixPopover?.mode === "edit") {
        return;
      }
      ensurePreviewSlice(doc, field);
      const anchorLeft = event.clientX;
      const anchorTop = event.clientY;
      setMatrixPopover(buildPopoverState(doc, field, { top: anchorTop, left: anchorLeft }, "hover"));
    },
    [buildPopoverState, ensurePreviewSlice, matrixPopover],
  );

  const handleCellClick = useCallback(
    (event: ReactMouseEvent<HTMLTableCellElement>, doc: DocumentPayload, field: FieldState) => {
      const anchor =
        matrixPopover?.mode === "hover" &&
        matrixPopover.doc.id === doc.id &&
        matrixPopover.field.field_key === field.field_key
          ? matrixPopover.anchor
          : getCellAnchor(event);
      setMatrixPopover(buildPopoverState(doc, field, anchor, "edit"));
      setPreviewSelected({ docId: doc.id, fieldKey: field.field_key });
    },
    [buildPopoverState, getCellAnchor, matrixPopover],
  );

  const handleMatrixScroll = useCallback((direction: "left" | "right") => {
    const container = matrixTableRef.current?.parentElement ?? matrixTableScrollRef.current;
    if (!container) {
      return;
    }
    const maxScroll = Math.max(0, container.scrollWidth - container.clientWidth);
    const targetLeft = direction === "left" ? 0 : maxScroll;
    if (typeof container.scrollTo === "function") {
      container.scrollTo({ left: targetLeft, behavior: "smooth" });
    } else {
      container.scrollLeft = targetLeft;
    }
  }, []);

  const presentDocTypes = useMemo(() => {
    const set = new Set<string>();
    presentDocInfo.forEach((_, actualType) => {
      set.add(actualType);
      set.add(toDisplayDocType(actualType));
    });
    return set;
  }, [presentDocInfo]);

  const buildFieldMatrixView = useCallback(
    (matrix: unknown) => {
      if (!matrix || typeof matrix !== "object") {
        return null;
      }
      const matrixData = matrix as Record<string, unknown>;
      const documentsRaw = Array.isArray(matrixData.documents) ? matrixData.documents : [];
      const docHeaders = documentsRaw
        .map((entry) => (typeof entry === "string" && entry.trim().length > 0 ? entry : null))
        .filter((entry): entry is string => entry !== null);
      if (docHeaders.length === 0) {
        return null;
      }
      const filteredDocHeaders = docHeaders.filter((doc) => {
        const displayDoc = toDisplayDocType(doc);
        const actualDoc = toActualDocType(doc);
        return (
          presentDocTypes.has(doc) ||
          presentDocTypes.has(displayDoc) ||
          presentDocTypes.has(actualDoc)
        );
      });
      if (filteredDocHeaders.length === 0) {
        return null;
      }
      const rowsRaw = Array.isArray(matrixData.rows) ? matrixData.rows : [];
      const rows: FieldMatrixRowView[] = rowsRaw
        .map((entry) => {
          if (!entry || typeof entry !== "object") {
            return null;
          }
          const data = entry as Record<string, unknown>;
          const fieldKeyRaw = data["FieldKey"];
          if (typeof fieldKeyRaw !== "string" || fieldKeyRaw.trim().length === 0) {
            return null;
          }
          const statusesRaw = data["statuses"];
          const statuses =
            statusesRaw && typeof statusesRaw === "object" ? (statusesRaw as Record<string, unknown>) : {};
          const cells: Record<string, FieldMatrixCell> = {};
          filteredDocHeaders.forEach((doc) => {
            const value = normalizeText(data[doc]);
            const rawStatus = statuses[doc];
            cells[doc] = {
              value,
              status: typeof rawStatus === "string" ? rawStatus : null,
            };
          });
          return {
            fieldKey: fieldKeyRaw,
            cells,
          };
        })
        .filter((row): row is FieldMatrixRowView => row !== null);
      if (rows.length === 0) {
        return null;
      }
      return {
        documents: filteredDocHeaders,
        rows,
      };
    },
    [presentDocTypes],
  );

  const fieldMatrix = useMemo(
    () => buildFieldMatrixView(batch?.report?.field_matrix),
    [batch, buildFieldMatrixView],
  );

  const fieldMatrixDiff = useMemo(
    () => buildFieldMatrixView(batch?.report?.field_matrix_diff),
    [batch, buildFieldMatrixView],
  );
  const activeMatrix = diffMode && fieldMatrixDiff ? fieldMatrixDiff : fieldMatrix;

  useEffect(() => {
    if (!fieldMatrixDiff && diffMode) {
      setDiffMode(false);
    }
  }, [fieldMatrixDiff, diffMode]);

  const docPresence: DocPresenceItem[] = useMemo(() => {
    if (!batch) {
      return [];
    }
    const remaining = new Map(presentDocInfo);
    const rows: DocPresenceItem[] = [];

    EXPECTED_DOC_TYPES.forEach((item) => {
      const actualType = toActualDocType(item.key);
      const info = remaining.get(actualType);
      if (info) {
        remaining.delete(actualType);
      }
      rows.push({
        docType: item.key,
        actualType,
        label: item.label,
        present: Boolean(info),
        filenames: info ? info.filenames : [],
        count: info ? info.docIds.length : 0,
        processing: info ? info.processingCount > 0 : false,
      });
    });

    Array.from(remaining.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .forEach(([actualType, info]) => {
        const displayType = toDisplayDocType(actualType);
      rows.push({
        docType: displayType,
        actualType,
        label: DOC_TYPE_LABELS[displayType] ?? displayType,
        present: true,
        filenames: info.filenames,
        count: info.docIds.length,
        processing: info.processingCount > 0,
      });
      });

    return rows;
  }, [batch, presentDocInfo]);

  const resolveDocField = useCallback(
    (displayDoc: string, fieldKey: string) => {
      let fallbackDoc: DocumentPayload | null = null;
      for (const doc of documents) {
        const docDisplay = toDisplayDocType(doc.doc_type);
        if (docDisplay !== displayDoc) {
          continue;
        }
        if (!fallbackDoc) {
          fallbackDoc = doc;
        }
        const foundField = doc.fields.find((item) => item.field_key === fieldKey);
        if (foundField) {
          return { docEntry: doc, fieldState: foundField };
        }
      }
      if (fallbackDoc) {
        return { docEntry: fallbackDoc, fieldState: fallbackDoc.fields.find((item) => item.field_key === fieldKey) ?? null };
      }
      return { docEntry: null, fieldState: null };
    },
    [documents],
  );

  const missingDocEntries = useMemo(() => docPresence.filter((item) => !item.present), [docPresence]);

  const missingDocTypes = useMemo(
    () => new Set(missingDocEntries.map((item) => item.actualType)),
    [missingDocEntries]
  );

  const missingDocNames = useMemo(() => missingDocEntries.map((item) => item.label), [missingDocEntries]);

  const validations: ValidationEntry[] = useMemo(() => {
    if (!batch?.report?.available) {
      return [];
    }
    const rawEntries = (batch.report.validations ?? []) as Record<string, unknown>[];
    return rawEntries
      .map((entry, index) => {
        const refs = parseRefs(entry);
        const ruleIdValue = entry["rule_id"];
        const severityValue = entry["severity"];
        const messageValue = entry["message"];
        const ruleId =
          typeof ruleIdValue === "string" && ruleIdValue.trim().length > 0 ? ruleIdValue : `rule_${index + 1}`;
        const severity = typeof severityValue === "string" ? severityValue : "info";
        const message = typeof messageValue === "string" ? messageValue : "";
        const realRefs = refs.filter((ref) => {
          if (!ref.doc_id || ref.doc_id === EMPTY_DOC_ID) {
            return false;
          }
          if (ref.present === false) {
            return false;
          }
          const doc = documentMap.get(ref.doc_id);
          if (!doc) {
            return false;
          }
          if (missingDocTypes.has(doc.doc_type)) {
            return false;
          }
          return true;
        });
        const missingRefs = refs.filter((ref) => {
          if (ref.present === false) {
            return true;
          }
          if (ref.doc_id === EMPTY_DOC_ID) {
            return true;
          }
          if (!ref.doc_id && ref.doc_type && missingDocTypes.has(ref.doc_type)) {
            return true;
          }
          return false;
        });
        if (missingRefs.length > 0 && realRefs.length <= 1) {
          return null;
        }
        return {
          ruleId,
          severity,
          message,
          refs: realRefs,
        } as ValidationEntry;
      })
      .filter((entry): entry is ValidationEntry => entry !== null);
  }, [batch, documentMap, missingDocTypes]);

  const productTables = useMemo(() => {
    const comparisons = batch?.report?.product_comparisons;
    if (!Array.isArray(comparisons) || comparisons.length === 0) {
      return [];
    }
    return comparisons
      .map((entry, index) => {
        if (!entry || typeof entry !== "object") {
          return null;
        }
        const data = entry as Record<string, unknown>;
        const productKey = data["product_key"] as Record<string, unknown> | undefined;
        const name = productKey ? normalizeText(productKey["name_product"]) : null;
        const latin = productKey ? normalizeText(productKey["latin_name"]) : null;
        const size = productKey ? normalizeText(productKey["size_product"]) : null;
        const titleParts = [name, latin, size].filter((part): part is string => Boolean(part));
        const fallbackTitle = `Product ${index + 1}`;
        const title = titleParts.length > 0 ? titleParts.join(" / ") : fallbackTitle;
        const docsRaw = Array.isArray(data["documents"]) ? (data["documents"] as unknown[]) : [];
        const docs: ProductTableDoc[] = docsRaw
          .map((docEntry) => {
            if (!docEntry || typeof docEntry !== "object") {
              return null;
            }
            const docData = docEntry as Record<string, unknown>;
            const docType = normalizeText(docData["doc_type"]) ?? "-";
            const productId = normalizeText(docData["product_id"]);
            const docId = normalizeText(docData["doc_id"]);
            const labelParts = [docType];
            if (productId) {
              labelParts.push(`(${productId})`);
            } else if (docId) {
              labelParts.push(`(${docId})`);
            }
            const label = labelParts.join(" ");
            const fieldsRaw = docData["fields"];
            const normalizedFields: Record<string, { value: string | null; confidence: number | null }> = {};
            if (fieldsRaw && typeof fieldsRaw === "object") {
              Object.entries(fieldsRaw as Record<string, unknown>).forEach(([key, payload]) => {
                normalizedFields[key] = extractProductField(payload);
              });
            }
            return {
              label,
              fields: normalizedFields,
            };
          })
          .filter((doc): doc is ProductTableDoc => doc !== null);
        if (docs.length === 0) {
          return null;
        }
        return {
          id: `product-${index}`,
          title,
          docs,
        };
      })
      .filter((table): table is ProductComparisonTable => table !== null);
  }, [batch]);

  const handleSave = async () => {
    if (!matrixPopover || matrixPopover.mode !== "edit") return;
    const { doc, field, value } = matrixPopover;
    try {
      setSaving(true);
      const normalized = value.trim() ? value.trim() : null;
      await updateField(doc.id, field.field_key, normalized);
      await confirmField(doc.id, field.field_key);
      await fetchBatch();
      setMatrixPopover(null);
      setMessage("Поле сохранено и подтверждено");
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    if (matrixPopover) {
      ensurePreviewSlice(matrixPopover.doc, matrixPopover.field);
    }
  }, [matrixPopover, ensurePreviewSlice]);
  const popoverPreviewSnapshot = matrixPopover
    ? buildFieldPreviewSnapshot(matrixPopover.doc, matrixPopover.field)
    : null;
  const popoverPreviewPending =
    popoverPreviewSnapshot && popoverPreviewSnapshot.sliceKey
      ? Boolean(previewSlicePending[popoverPreviewSnapshot.sliceKey])
      : false;

  const previewTarget = previewHover ?? previewSelected;
  const previewDoc = previewTarget ? documentMap.get(previewTarget.docId) : null;
  const previewField =
    previewDoc && previewTarget ? previewDoc.fields.find((item) => item.field_key === previewTarget.fieldKey) : null;

  const previewHighlight: MatrixPreviewHighlight | null = previewField
    ? {
        fieldKey: previewField.field_key,
        bbox: ensureBBox(previewField.bbox),
        page: previewField.page ?? null,
      }
    : null;

  const previewBoxes = useMemo(() => {
    if (!previewDoc) {
      return [];
    }
    const unique = new Map<string, MatrixPreviewOverlay>();
    previewDoc.fields.forEach((field) => {
      const bbox = ensureBBox(field.bbox);
      if (!bbox) {
        return;
      }
      const page = field.page ?? null;
      const key = `${page ?? "?"}|${bbox.join(",")}`;
      if (!unique.has(key)) {
        unique.set(key, { fieldKey: field.field_key, bbox, page });
      }
    });
    return Array.from(unique.values());
  }, [previewDoc]);

  const previewDocLabel = previewDoc ? DOC_TYPE_LABELS[toDisplayDocType(previewDoc.doc_type)] ?? previewDoc.doc_type : null;

  const getMatrixScrollContainer = useCallback((): HTMLElement | Window => {
    const body = matrixBodyRef.current;
    if (!body || typeof window === "undefined") {
      return window;
    }
    const main = body.closest("main");
    if (main && main.scrollHeight > main.clientHeight) {
      return main;
    }
    let current = body.parentElement;
    while (current) {
      const style = window.getComputedStyle(current);
      if (/(auto|scroll)/.test(style.overflowY) && current.scrollHeight > current.clientHeight) {
        return current;
      }
      current = current.parentElement;
    }
    return window;
  }, []);

  const updateMatrixSticky = useCallback(() => {
    if (!previewEnabled) {
      return;
    }
    const body = matrixBodyRef.current;
    const viewer = previewStickyRef.current;
    if (!body || !viewer) {
      return;
    }
    const scrollParent = getMatrixScrollContainer();
    const isWindowScroll = scrollParent === window;
    const scrollElement = isWindowScroll ? null : (scrollParent as HTMLElement);
    const scrollTop = isWindowScroll ? window.scrollY : scrollElement?.scrollTop ?? 0;
    const scrollRectTop = isWindowScroll ? 0 : scrollElement?.getBoundingClientRect().top ?? 0;
    const parentRect = body.getBoundingClientRect();
    const parentTop = parentRect.top - scrollRectTop + scrollTop;
    const parentHeight = body.offsetHeight;
    const viewerHeight = viewer.offsetHeight;
    const minTop = parentTop;
    const maxTop = Math.max(parentTop, parentTop + parentHeight - viewerHeight - MATRIX_STICKY_BOTTOM_GAP);
    const targetTop = Math.min(Math.max(scrollTop + MATRIX_STICKY_GAP, minTop), maxTop);
    const topInParent = Math.max(0, targetTop - parentTop);
    setPreviewStyle((prev) => {
      const topValue = `${topInParent}px`;
      if (prev.top === topValue) {
        return prev;
      }
      return { ...prev, top: topValue };
    });
  }, [getMatrixScrollContainer, previewEnabled]);

  useEffect(() => {
    if (!previewEnabled) {
      return;
    }
    const scrollParent = getMatrixScrollContainer();
    const target = scrollParent === window ? window : scrollParent;
    const main = matrixBodyRef.current?.closest("main") ?? null;
    let rafId: number | null = null;
    const onScroll = () => {
      if (rafId !== null) return;
      rafId = window.requestAnimationFrame(() => {
        rafId = null;
        updateMatrixSticky();
      });
    };
    target.addEventListener("scroll", onScroll, { passive: true });
    if (target !== window) {
      window.addEventListener("scroll", onScroll, { passive: true });
    }
    if (main && main !== target) {
      main.addEventListener("scroll", onScroll, { passive: true });
    }
    window.addEventListener("resize", onScroll);
    updateMatrixSticky();
    return () => {
      target.removeEventListener("scroll", onScroll);
      if (target !== window) {
        window.removeEventListener("scroll", onScroll);
      }
      if (main && main !== target) {
        main.removeEventListener("scroll", onScroll);
      }
      window.removeEventListener("resize", onScroll);
      if (rafId !== null) {
        window.cancelAnimationFrame(rafId);
      }
    };
  }, [getMatrixScrollContainer, updateMatrixSticky, previewEnabled]);

  useEffect(() => {
    if (!previewEnabled) {
      return;
    }
    const body = matrixBodyRef.current;
    const viewer = previewStickyRef.current;
    if (!body || !viewer || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(() => updateMatrixSticky());
    observer.observe(body);
    observer.observe(viewer);
    return () => observer.disconnect();
  }, [previewEnabled, updateMatrixSticky]);

  if (!batchId) {
    return <Alert variant="destructive">Не указан идентификатор пакета.</Alert>;
  }

  if (loading) {
    return (
      <div className="flex h-80 items-center justify-center text-muted-foreground">
        <Spinner className="mr-3" /> Загружаем итоговый отчёт...
      </div>
    );
  }

  if (error) {
    return <Alert variant="destructive">{error.message}</Alert>;
  }

  if (!batch) {
    return <Alert variant="info">Данные отчёта недоступны.</Alert>;
  }

  const batchTitle = typeof batch.title === "string" ? batch.title.trim() : "";
  const needsPrep = !batch.prep_complete;
  const isPopoverEditing = matrixPopover?.mode === "edit";
  const matrixPopoverPortal =
    matrixPopover && typeof document !== "undefined"
      ? (() => {
          const snapshot: FieldPreviewSnapshot =
            popoverPreviewSnapshot ?? {
              previewUrl: null,
              frameStyle: { width: 560, height: 360 },
              imageStyle: { width: "100%", height: "100%", objectFit: "contain" },
              confidenceValue: null,
              sliceKey: null,
              sliceReady: false,
            };
          const { previewUrl, frameStyle, imageStyle, confidenceValue } = snapshot;
          const value = matrixPopover.value ?? "";
          const showTextarea = value.length > 80;
          const diffValue = (() => {
            if (!fieldMatrixDiff) {
              return null;
            }
            const docDisplay = toDisplayDocType(matrixPopover.doc.doc_type);
            const row = fieldMatrixDiff.rows.find((item) => item.fieldKey === matrixPopover.field.field_key);
            const cell = row?.cells[docDisplay];
            if (!cell || cell.value == null) {
              return null;
            }
            if (typeof cell.value === "string") {
              return cell.value.replace(/\[missing\]/g, "");
            }
            return String(cell.value);
          })();
          const diffSegments = diffValue ? splitDiffSegments(diffValue) : null;
          return createPortal(
            <div
              className={cn("fixed z-50", isPopoverEditing ? "pointer-events-auto" : "pointer-events-none")}
              style={{
                top: matrixPopover.anchor.top - 12,
                left: matrixPopover.anchor.left,
                transform: "translate(-50%, -100%)",
              }}
            >
              <Card className="w-[380px] overflow-hidden border bg-background shadow-2xl">
                <CardHeader className="py-3">
                  <CardTitle className="text-sm font-semibold">{matrixPopover.field.field_key}</CardTitle>
                  <p className="text-xs text-muted-foreground">{matrixPopover.doc.filename}</p>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div>
                    <p className="text-xs text-muted-foreground">Значение</p>
                    {isPopoverEditing ? (
                      showTextarea ? (
                        <Textarea
                          rows={5}
                          value={value}
                          onChange={(event) =>
                            setMatrixPopover((prev) =>
                              prev && prev.mode === "edit" ? { ...prev, value: event.target.value } : prev,
                            )
                          }
                          disabled={saving}
                        />
                      ) : (
                        <Input
                          value={value}
                          onChange={(event) =>
                            setMatrixPopover((prev) =>
                              prev && prev.mode === "edit" ? { ...prev, value: event.target.value } : prev,
                            )
                          }
                          disabled={saving}
                        />
                      )
                    ) : (
                      <p className="text-sm font-medium break-words">{value.trim() ? value : "-"}</p>
                    )}
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Различие с якорным полем</p>
                    <p className="text-sm font-medium break-words">
                      {diffSegments
                        ? diffSegments.map((segment, index) => (
                            <span
                              key={`diff-${matrixPopover.field.field_key}-${index}`}
                              className={
                                segment.isDiff
                                  ? "rounded-sm bg-rose-100 px-0.5 font-semibold text-rose-700"
                                  : undefined
                              }
                            >
                              {segment.text}
                            </span>
                          ))
                        : "—"}
                    </p>
                  </div>
                  <p className="text-xs text-muted-foreground">Уверенность: {confidenceValue ?? "-"}</p>
                  {previewUrl ? (
                    <div className="relative overflow-hidden rounded-lg border bg-muted/30" style={frameStyle}>
                      <img src={previewUrl} alt="" style={imageStyle} />
                    </div>
                  ) : (
                    <div className="flex h-28 items-center justify-center rounded-lg border bg-muted/30 text-xs text-muted-foreground">
                      {popoverPreviewPending ? (
                        <span className="flex items-center gap-2">
                          <Spinner className="h-3.5 w-3.5" />
                          Готовим превью...
                        </span>
                      ) : (
                        "Нет превью"
                      )}
                    </div>
                  )}
                  {isPopoverEditing ? (
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <Button variant="ghost" size="sm" onClick={() => setMatrixPopover(null)} disabled={saving}>
                        Отмена
                      </Button>
                      <Button size="sm" onClick={() => void handleSave()} disabled={saving}>
                        Сохранить
                      </Button>
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            </div>,
            document.body,
          );
        })()
      : null;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">
            Сводка по пакету{batchTitle ? `: ${batchTitle}` : ""}
          </h1>
          <p className="text-muted-foreground">
            Загружен {formatPacketTimestamp(batch.created_at)} · Статус: {statusLabel(mapBatchStatus(batch.status))} · Обновлён {formatDateTime(batch.updated_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={() => navigate(`/resolve/${batch.id}`)}>
            Открыть проверку
          </Button>
          {batch.links?.report_xlsx ? (
            <Button asChild variant="outline">
              <a href={batch.links.report_xlsx} target="_blank" rel="noopener noreferrer" download>
                Скачать XLSX
              </a>
            </Button>
          ) : null}
        </div>
      </header>

      {needsPrep ? (
        <Alert variant="warning" className="flex flex-wrap items-center justify-between gap-3">
          <span>Пакет в подготовке. Перейдите к подготовке, чтобы повернуть или удалить страницы.</span>
          <Button size="sm" variant="secondary" onClick={() => navigate(`/queue?batch=${batch.id}`)}>
            Перейти к подготовке
          </Button>
        </Alert>
      ) : null}
      {actionError ? <Alert variant="destructive">{actionError}</Alert> : null}
      {uploadMessage ? <Alert variant="success">{uploadMessage}</Alert> : null}
      {message ? <Alert variant="success">{message}</Alert> : null}

      <Card className="rounded-3xl border bg-background">
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle>Состав пакета</CardTitle>
          <div className="flex items-center gap-2">
            {addingDocs ? <Spinner className="h-4 w-4" /> : null}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => addDocsInputRef.current?.click()}
              disabled={addingDocs || !batchId}
            >
              Добавить документы
            </Button>
            <input
              ref={addDocsInputRef}
              type="file"
              multiple
              className="hidden"
              accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.png,.jpg,.jpeg"
              onChange={handleAddDocuments}
              disabled={addingDocs}
            />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {docPresence.length === 0 ? (
            <Alert variant="info">Документы ещё не загружены.</Alert>
          ) : (
            <>
              {missingDocNames.length > 0 ? (
                <Alert variant="warning">Отсутствуют документы: {missingDocNames.join(", ")}</Alert>
              ) : null}
              <div className="flex flex-wrap gap-4">
                {docPresence.map((item) => (
                  <div
                    key={item.docType}
                    className={cn(
                      "flex-1 rounded-2xl border px-4 py-3",
                      "min-w-[220px] max-w-sm",
                      item.present ? "bg-muted/20 border-muted" : "border-destructive/40 bg-destructive/5"
                    )}
                  >
                    <div className="text-sm font-semibold">{item.label}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Файлы: {item.filenames.length ? item.filenames.join(", ") : "-"}
                    </div>
                    <div
                      className={cn(
                        "mt-2 text-sm font-semibold",
                        !item.present
                          ? "text-destructive"
                          : item.processing
                            ? "text-amber-600"
                            : "text-emerald-600",
                      )}
                    >
                      Статус:{" "}
                      {!item.present ? "Нет" : item.processing ? "В процессе" : "Есть"}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card className="rounded-3xl border bg-background">
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle>Матрица полей</CardTitle>
          {fieldMatrix ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleMatrixScroll("left")}
                aria-label="Прокрутить таблицу влево"
                disabled={!activeMatrix}
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleMatrixScroll("right")}
                aria-label="Прокрутить таблицу вправо"
                disabled={!activeMatrix}
              >
                <ArrowRight className="h-4 w-4" />
              </Button>
              <Button
                variant={diffMode ? "secondary" : "outline"}
                size="sm"
                onClick={() => setDiffMode((prev) => !prev)}
                aria-pressed={diffMode}
                disabled={!fieldMatrixDiff}
              >
                Показать различия
              </Button>
              <Button
                variant={previewEnabled ? "secondary" : "outline"}
                size="sm"
                onClick={() => setPreviewEnabled((prev) => !prev)}
                aria-pressed={previewEnabled}
              >
                Предпросмотр документа
              </Button>
            </div>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-4">
          {!activeMatrix ? (
            <Alert variant="info">Для пакета пока нет матрицы полей.</Alert>
          ) : (
            <>
              <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                {Object.entries(MATRIX_STATUS_LABELS).map(([status, label]) => (
                  <span key={status} className={cn("rounded-full border px-3 py-1", matrixStatusClass(status))}>
                    {label}
                  </span>
                ))}
              </div>
              <div
                ref={matrixBodyRef}
                className={cn("flex flex-col gap-6", previewEnabled ? "lg:flex-row" : "")}
              >
                <div className="min-w-0 flex-1">
                  <div className="overflow-x-auto" ref={matrixTableScrollRef}>
                    <Table ref={matrixTableRef}>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Поле</TableHead>
                          {activeMatrix.documents.map((doc) => (
                            <TableHead key={doc}>{doc}</TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {activeMatrix.rows.map((row) => (
                          <TableRow key={row.fieldKey}>
                            <TableCell className="font-medium">
                              {FIELD_LABELS_RU[row.fieldKey] ?? row.fieldKey}
                            </TableCell>
                            {activeMatrix.documents.map((doc) => {
                              const cell = row.cells[doc];
                              const { docEntry, fieldState } = resolveDocField(doc, row.fieldKey);
                              const isInteractive = Boolean(docEntry && fieldState);
                              const rawValue = cell?.value ?? "-";
                              const cleanedValue =
                                diffMode && typeof rawValue === "string"
                                  ? rawValue.replace(/\[missing\]/g, "")
                                  : rawValue;
                              const displayValue =
                                diffMode && typeof cleanedValue === "string" ? splitDiffSegments(cleanedValue) : null;
                              return (
                                <TableCell
                                  key={`${row.fieldKey}-${doc}`}
                                  className={cn(
                                    "align-top text-sm",
                                    matrixStatusClass(cell?.status),
                                    isInteractive && "cursor-pointer"
                                  )}
                                  onMouseEnter={(event) =>
                                    fieldState && docEntry && handleCellHover(event, docEntry, fieldState)
                                  }
                                  onMouseLeave={hidePreview}
                                  onClick={(event) =>
                                    fieldState && docEntry && handleCellClick(event, docEntry, fieldState)
                                  }
                                >
                                  <span className="whitespace-pre-wrap break-words">
                                    {displayValue
                                      ? displayValue.map((segment, index) => (
                                          <span
                                            key={`${row.fieldKey}-${doc}-${index}`}
                                            className={
                                              segment.isDiff
                                                ? "rounded-sm bg-rose-100 px-0.5 font-semibold text-rose-700"
                                                : undefined
                                            }
                                          >
                                            {segment.text}
                                          </span>
                                        ))
                                      : cleanedValue}
                                  </span>
                                </TableCell>
                              );
                            })}
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
                {previewEnabled ? (
                  <div className="relative lg:w-[360px] lg:shrink-0 lg:self-stretch">
                    <div ref={previewStickyRef} className="space-y-3 lg:absolute left-0 right-0" style={previewStyle}>
                      {previewDoc ? (
                        <>
                          <div className="space-y-1">
                            <div className="text-sm font-semibold break-words">{previewDoc.filename}</div>
                            <div className="text-xs text-muted-foreground">
                              {previewDocLabel ?? "Документ"}
                              {previewField ? ` · поле: ${previewField.field_key}` : ""}
                            </div>
                          </div>
                          <MatrixDocumentPreview
                            previews={previewDoc.previews}
                            highlight={previewHighlight}
                            boxes={previewBoxes}
                            showBoxes={showPreviewBoxes}
                            onToggleBoxes={() => setShowPreviewBoxes((prev) => !prev)}
                          />
                        </>
                      ) : (
                        <div className="rounded-2xl border bg-muted/20 p-4 text-sm text-muted-foreground">
                          Наведите на поле в таблице, чтобы открыть предпросмотр документа.
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {productTables.length === 0 ? (
        <Card className="rounded-3xl border bg-background">
          <CardHeader>
            <CardTitle>Сопоставление товаров</CardTitle>
          </CardHeader>
          <CardContent>
            <Alert variant="info">Нет объединённых товаров.</Alert>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {productTables.map((table) => (
            <Card key={table.id} className="rounded-3xl border bg-background">
              <CardHeader>
                <CardTitle>{table.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Поле</TableHead>
                        {table.docs.map((doc) => (
                          <TableHead key={doc.label}>{doc.label}</TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {PRODUCT_TABLE_FIELDS.map(({ key, label }) => (
                        <TableRow key={`${table.id}-${key}`}>
                          <TableCell className="font-medium">{label}</TableCell>
                          {table.docs.map((doc) => {
                            const field = doc.fields[key] ?? { value: null, confidence: null };
                            return (
                              <TableCell key={`${table.id}-${key}-${doc.label}`} className="align-top text-sm">
                                <div>{field.value ?? "-"}</div>
                                {field.confidence != null ? (
                                  <div className="text-xs text-muted-foreground">({field.confidence.toFixed(2)})</div>
                                ) : null}
                              </TableCell>
                            );
                          })}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {matrixPopoverPortal}
    </div>
  );
}

export default SummaryTablePage;





