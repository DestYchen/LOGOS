import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent } from "react";
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
import { confirmField, fetchBatchDetails, updateField } from "../lib/api";
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

type SelectedCell = {
  docId: string;
  fieldKey: string;
  value: string | null;
  confidence: number | null;
};

type DocPresenceItem = {
  docType: string;
  actualType: string;
  label: string;
  present: boolean;
  filenames: string[];
  count: number;
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

const EMPTY_DOC_ID = "00000000-0000-0000-0000-000000000000";
const PREVIEW_CALIBRATION = DOCUMENT_PREVIEW_CALIBRATION;

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
const PREVIEW_MAGNIFICATION = 4;
const MIN_FRAME_SIZE = 36;

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

  const baseWidth = (x2 - x1) * adjustedScaleX;
  const baseHeight = (y2 - y1) * adjustedScaleY;
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

  return {
    imageWidth,
    imageHeight,
    frame: {
      width: clampedWidth,
      height: clampedHeight,
      left: clampedLeft,
      top: clampedTop,
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
  const [selectedCell, setSelectedCell] = useState<SelectedCell | null>(null);
  const [saving, setSaving] = useState(false);
  const [hoverPreview, setHoverPreview] = useState<{
    doc: DocumentPayload;
    field: FieldState;
    anchor: { top: number; left: number };
  } | null>(null);
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
      const frameStyle: CSSProperties = slice ? { width: slice.width, height: slice.height } : { width: 560, height: 360 };
      const imageStyle: CSSProperties = { width: "100%", height: "100%", objectFit: "contain" };
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
      return;
    }
    const response = await fetchBatchDetails(batchId);
    setBatch(response.batch);
    void refresh();
  }, [batchId, refresh]);

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

  const documents = batch?.documents ?? [];
  const documentMap = useMemo(() => {
    const map = new Map<string, DocumentPayload>();
    documents.forEach((doc) => map.set(doc.id, doc));
    return map;
  }, [documents]);
  const openEditor = useCallback(
    (docId: string, fieldKey: string) => {
      const doc = documentMap.get(docId);
      if (!doc) return;
      const field = doc.fields.find((item) => item.field_key === fieldKey);
      const confidence =
        field && field.confidence !== null && field.confidence !== undefined ? Number(field.confidence) : null;
      setSelectedCell({
        docId,
        fieldKey,
        value: field?.value ?? null,
        confidence,
      });
      if (field) {
        ensurePreviewSlice(doc, field);
      }
    },
    [documentMap, ensurePreviewSlice],
  );

  const hidePreview = useCallback(() => setHoverPreview(null), []);

  const handleCellHover = useCallback(
    (event: ReactMouseEvent<HTMLTableCellElement>, doc: DocumentPayload, field: FieldState) => {
      if (typeof window === "undefined") {
        return;
      }
      ensurePreviewSlice(doc, field);
      const anchorLeft = event.clientX;
      const anchorTop = event.clientY;
      setHoverPreview({
        doc,
        field,
        anchor: {
          top: anchorTop,
          left: anchorLeft,
        },
      });
    },
    [ensurePreviewSlice],
  );

  const handleCellClick = useCallback(
    (field: FieldState, fallbackDocId?: string) => {
      hidePreview();
      const targetDocId = field.doc_id ?? fallbackDocId;
      if (targetDocId) {
        openEditor(targetDocId, field.field_key);
      }
    },
    [hidePreview, openEditor],
  );

  const fieldMatrix = useMemo(() => {
    const matrix = batch?.report?.field_matrix;
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
        docHeaders.forEach((doc) => {
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
      documents: docHeaders,
      rows,
    };
  }, [batch]);

  const docPresence: DocPresenceItem[] = useMemo(() => {
    if (!batch) {
      return [];
    }
    const presentByActual = new Map<string, { docIds: string[]; filenames: string[] }>();
    documents.forEach((doc) => {
      const entry = presentByActual.get(doc.doc_type) ?? { docIds: [], filenames: [] };
      entry.docIds.push(doc.id);
      if (doc.filename) {
        entry.filenames.push(doc.filename);
      }
      presentByActual.set(doc.doc_type, entry);
    });

    const remaining = new Map(presentByActual);
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
        });
      });

    return rows;
  }, [batch, documents]);

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
    if (!selectedCell) return;
    const { docId, fieldKey, value } = selectedCell;
    try {
      setSaving(true);
      const normalized = value?.trim() ? value.trim() : null;
      await updateField(docId, fieldKey, normalized);
      await confirmField(docId, fieldKey);
      await fetchBatch();
      setSelectedCell(null);
      setMessage("Поле сохранено и подтверждено");
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const selectedDocId = selectedCell?.docId;
  const selectedFieldKey = selectedCell?.fieldKey;
  const selectedDoc = selectedDocId ? documentMap.get(selectedDocId) : null;
  const selectedFieldState =
    selectedDoc && selectedFieldKey ? selectedDoc.fields.find((item) => item.field_key === selectedFieldKey) : null;
  useEffect(() => {
    if (hoverPreview) {
      ensurePreviewSlice(hoverPreview.doc, hoverPreview.field);
    }
  }, [hoverPreview, ensurePreviewSlice]);
  useEffect(() => {
    if (selectedDoc && selectedFieldState) {
      ensurePreviewSlice(selectedDoc, selectedFieldState);
    }
  }, [selectedDoc, selectedFieldState, ensurePreviewSlice]);
  const selectedPreviewSnapshot =
    selectedDoc && selectedFieldState ? buildFieldPreviewSnapshot(selectedDoc, selectedFieldState) : null;
  const selectedPreviewPending =
    selectedPreviewSnapshot && selectedPreviewSnapshot.sliceKey
      ? Boolean(previewSlicePending[selectedPreviewSnapshot.sliceKey])
      : false;

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

  const hoverPreviewPortal =
    hoverPreview && typeof document !== "undefined"
      ? (() => {
          const { previewUrl, frameStyle, imageStyle, confidenceValue, sliceKey } = buildFieldPreviewSnapshot(
            hoverPreview.doc,
            hoverPreview.field,
          );
          const isPreparing = sliceKey ? Boolean(previewSlicePending[sliceKey]) : false;
          return createPortal(
            <div
              className="pointer-events-none fixed z-50"
              style={{
                top: hoverPreview.anchor.top - 12,
                left: hoverPreview.anchor.left,
                transform: "translate(-50%, -100%)",
              }}
            >
              <Card className="w-[360px] overflow-hidden border bg-background shadow-2xl">
                <CardHeader className="py-3">
                  <CardTitle className="text-sm font-semibold">{hoverPreview.field.field_key}</CardTitle>
                  <p className="text-xs text-muted-foreground">{hoverPreview.doc.filename}</p>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div>
                    <p className="text-xs text-muted-foreground">Значение</p>
                    <p className="text-sm font-medium break-words">{hoverPreview.field.value ?? "-"}</p>
                  </div>
                  <p className="text-xs text-muted-foreground">Уверенность: {confidenceValue ?? "-"}</p>
                  {previewUrl ? (
                    <div className="relative overflow-hidden rounded-lg border bg-muted/30" style={frameStyle}>
                      <img src={previewUrl} alt="" style={imageStyle} />
                    </div>
                  ) : (
                    <div className="flex h-28 items-center justify-center rounded-lg border bg-muted/30 text-xs text-muted-foreground">
                      {isPreparing ? (
                        <span className="flex items-center gap-2">
                          <Spinner className="h-3.5 w-3.5" />
                          Готовим превью...
                        </span>
                      ) : (
                        "Нет превью"
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>,
            document.body,
          );
        })()
      : null;

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">Сводка по пакету</h1>
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

        {actionError ? <Alert variant="destructive">{actionError}</Alert> : null}
      {message ? <Alert variant="success">{message}</Alert> : null}

      <Card className="rounded-3xl border bg-background">
        <CardHeader>
          <CardTitle>Состав пакета</CardTitle>
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
                        item.present ? "text-emerald-600" : "text-destructive"
                      )}
                    >
                      Статус: {item.present ? "Есть" : "Нет"}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card className="rounded-3xl border bg-background">
        <CardHeader>
          <CardTitle>Матрица полей</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {!fieldMatrix ? (
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
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Поле</TableHead>
                      {fieldMatrix.documents.map((doc) => (
                        <TableHead key={doc}>{doc}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {fieldMatrix.rows.map((row) => (
                      <TableRow key={row.fieldKey}>
                        <TableCell className="font-medium">{row.fieldKey}</TableCell>
                        {fieldMatrix.documents.map((doc) => {
                          const cell = row.cells[doc];
                          const { docEntry, fieldState } = resolveDocField(doc, row.fieldKey);
                          const isInteractive = Boolean(docEntry && fieldState);
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
                              onClick={() => fieldState && docEntry && handleCellClick(fieldState, docEntry.id)}
                            >
                              <span className="whitespace-pre-wrap break-words">{cell?.value ?? "-"}</span>
                            </TableCell>
                          );
                        })}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
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

      {selectedCell ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-3xl border bg-background p-6 shadow-xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold">Редактирование поля</h2>
                <p className="text-sm text-muted-foreground">
                  Поле: {selectedCell.fieldKey} · уверенность: {" "}
                  {selectedCell.confidence !== null ? selectedCell.confidence.toFixed(2) : "-"}
                </p>
              </div>
              <Button variant="ghost" onClick={() => setSelectedCell(null)} disabled={saving}>
                Закрыть
              </Button>
            </div>
            <div className="mt-4 space-y-4">
              {(selectedCell.value ?? "").length > 80 ? (
                <Textarea
                  rows={6}
                  value={selectedCell.value ?? ""}
                  onChange={(event) =>
                    setSelectedCell((prev) => (prev ? { ...prev, value: event.target.value } : prev))
                  }
                />
              ) : (
                <Input
                  value={selectedCell.value ?? ""}
                  onChange={(event) =>
                    setSelectedCell((prev) => (prev ? { ...prev, value: event.target.value } : prev))
                  }
                />
              )}
              {selectedDoc && selectedFieldState ? (
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground">Документ: {selectedDoc.filename}</p>
                  {selectedPreviewSnapshot?.previewUrl ? (
                    <div className="relative overflow-hidden rounded-lg border bg-muted/30" style={selectedPreviewSnapshot.frameStyle}>
                      <img src={selectedPreviewSnapshot.previewUrl} alt="" style={selectedPreviewSnapshot.imageStyle} />
                    </div>
                  ) : (
                    <div className="flex h-28 items-center justify-center rounded-lg border bg-muted/30 text-xs text-muted-foreground">
                      {selectedPreviewPending ? (
                        <span className="flex items-center gap-2">
                          <Spinner className="h-4 w-4" />
                          Готовим превью...
                        </span>
                      ) : (
                        "Нет превью"
                      )}
                    </div>
                  )}
                </div>
              ) : null}
            </div>
            <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
              <Button variant="ghost" onClick={() => setSelectedCell(null)} disabled={saving}>
                Отмена
              </Button>
              <Button onClick={() => void handleSave()} disabled={saving}>
                Сохранить
              </Button>
            </div>
          </div>
        </div>
      ) : null}
      {hoverPreviewPortal}
    </div>
  );
}

export default SummaryTablePage;





