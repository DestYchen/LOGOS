import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent } from "react";
import type { ChangeEvent } from "react";
import { ArrowLeft, ArrowRight, ChevronDown, ChevronRight, Eye, EyeOff } from "lucide-react";
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
import type { BatchDetails, DocumentPayload, FieldState, ProductColumn, ProductRow } from "../types/api";

type ValidationRef = {
  doc_id?: string;
  doc_type?: string;
  field_key?: string;
  label?: string;
  message?: string;
  value?: string | null;
  present?: boolean;
  note?: string;
};

type ValidationRuleRow = {
  key: string;
  docLabel: string;
  docFilename: string | null;
  fieldLabel: string;
  status: string;
  value: string | null;
};

type ValidationRuleView = {
  id: string;
  message: string;
  severity: string;
  rows: ValidationRuleRow[];
  baseRuleId?: string;
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

type DocumentProductTable = {
  id: string;
  title: string;
  filename: string;
  columns: ProductColumn[];
  rows: ProductRow[];
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

const VALIDATION_RULE_MESSAGES: Record<string, string> = {
  date_proforma_earliest: "Дата проформы должна быть самой ранней среди связанных документов",
  date_invoice_not_too_early: "Дата инвойса не должна быть раньше даты отгрузки и даты сертификатов",
  date_bill_of_landing_after_sources: "Дата коноссамента должна быть позже дат проформы, инвойса и прайс листов",
  date_cmr_after_sources: "Дата CMR должна быть позже даты инвойса, позже проформы и прайс-листа 1",
  date_packing_list_before_ship: "Дата пакинг листа должна быть раньше чем дата коносамента и не позже чем дата инвойса",
  date_price_list_1_before_proforma: "Дата прайс листа 1 должна быть раньше или равна дате проформы",
  date_price_list_2_between_proforma_invoice: "Дата прайс листа 2 должна быть позже даты профомы и не позжедаты инвойса",
  date_quality_certificate_after_bol: "Дата сертификатат качества должна быть позже или равна дате коноссамента",
  date_veterinary_certificate_before_bol: "Дата ветеринарного сертификата должна быть раньше чем дата коноссамента",
  date_export_declaration_after_bol: "Дата экспортной декларации должна быть позже или равна даты коноссамента",
  date_specification_not_after_invoice: "Дата спецификации должна быть не позже, чем дата инвойса",
  date_certificate_origin_after_invoice: "Дата сертификата происхождения должна быть позже или равно дате инвойса",
  date_form_a_after_invoice: "Дата FORM A должна быть равна или позже даты инвойса",
  date_eav_after_invoice: "Дата EAV должна быть равна или позже даты инвойса",
  contract_no_alignment: "Номер контракта должен совпадать во всех связанных документах",
  additional_agreements_alignment: "Дополнительные соглашения должны совпадать во всех связанных документах",
  country_of_origin_consistency:
    "Страна происхождения в ветеринарном сертификате должна совпадать с другими документами",
  total_price_consistency: "Общая стоимость в инвойсе должна совпадать с другими документами",
  producer_consistency: "Производитель в ветеринарном сертификате должен совпадать с другими документами",
  incoterms_consistency: "Условия доставки из инвойса должны совпадать с другими документами",
  terms_of_payment_consistency: "Условия оплаты из инвойса должны совпадать с другими документами",
  bank_details_consistency: "Банковские реквизиты в контракте должны совпадать с инвойсом и проформой",
  exporter_consistency: "Экспортер в ветеринарном сертификате должен совпадать с другими",
  recipient_matches_contract_buyer:
    "Получатель из контракта должен совпадать с импортёрами в транспортных документах",
  proforma_number_consistency: "Номер проформы должен совпадать в инвойсе и экспортной декларации",
  invoice_number_consistency: "Номер инвойса должен совпадать с другими документами",
  veterinary_seal_consistency:
    "Ветеринарная пломба в ветеринарном сертификате должна совпадать с другими документами",
  linear_seal_consistency: "Линейная прлобма в коноссаменте должна совпадать с другими документами",
  buyer_alignment:
    "Покупатель должен быть одинаковый среди проформы, инвойса, экспортной декларации, спецификации, ветеринарного сертификата и серфтификата происхождения: значения отличаются между документами",
  seller_alignment:
    "Продавец должен быть одинаковый среди проформы, инвойса, экспортной декларации, спецификации и прайс листов",
  container_number_alignment:
    "Номер контейнера должен быть одинаковый среди инвойса, ветеринарного сертификата, сертификата качества, серфтификата происхождения и коноссамента",
  vessel_alignment:
    "Транспорт доставки должен быть одинаковый среди инвойса, ветеринарного сертификата, серфтификата качества и коноссамента",
  importer_alignment:
    "Импортер должен быть одинаковым у коноссамента и сертификата происхождения",
};

const VALIDATION_RULE_ORDER = [
  "date_proforma_earliest",
  "date_invoice_not_too_early",
  "date_bill_of_landing_after_sources",
  "date_cmr_after_sources",
  "date_packing_list_before_ship",
  "date_price_list_1_before_proforma",
  "date_price_list_2_between_proforma_invoice",
  "date_quality_certificate_after_bol",
  "date_veterinary_certificate_before_bol",
  "date_export_declaration_after_bol",
  "date_specification_not_after_invoice",
  "date_certificate_origin_after_invoice",
  "date_form_a_after_invoice",
  "date_eav_after_invoice",
  "contract_no_alignment",
  "additional_agreements_alignment",
  "country_of_origin_consistency",
  "total_price_consistency",
  "producer_consistency",
  "incoterms_consistency",
  "terms_of_payment_consistency",
  "bank_details_consistency",
  "exporter_consistency",
  "recipient_matches_contract_buyer",
  "proforma_number_consistency",
  "invoice_number_consistency",
  "veterinary_seal_consistency",
  "linear_seal_consistency",
  "buyer_alignment",
  "seller_alignment",
  "container_number_alignment",
  "vessel_alignment",
  "importer_alignment",
];

const FIELD_DOC_LABELS: Record<string, string> = {
  proforma_date: "Проформа",
  invoice_date: "Инвойс",
  bill_of_landing_date: "Коносамент",
  packing_list_date: "Пак-лист",
  price_list_1_date: "Прайс-лист 1",
  price_list_2_date: "Прайс-лист 2",
  quality_certificate_date: "Сертификат качества",
  veterinary_certificate_date: "Вет. сертификат",
  export_declaration_date: "Экспортная декларация",
  specification_date: "Спецификация",
  certificate_of_origin_date: "Сертификат происхождения",
  cmr_date: "CMR",
  form_a_date: "FORM A",
  eav_date: "EAV",
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
  { key: "T1", label: "T1" },
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
  T1: "T1",
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

function severityLabel(severity: string): string {
  const normalized = severity.toLowerCase();
  if (normalized === "error" || normalized === "critical") {
    return "Ошибка";
  }
  if (normalized === "warn" || normalized === "warning") {
    return "Предупреждение";
  }
  return "Инфо";
}

function formatFieldLabel(fieldKey: string | undefined, fallback?: string): string {
  if (fallback && fallback.trim()) {
    return fallback;
  }
  if (!fieldKey) {
    return "Поле";
  }
  const mapped = FIELD_LABELS_RU[fieldKey];
  if (mapped) {
    return mapped;
  }
  return fieldKey.replace(/[_\.]/g, " ");
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
  const valueValue = data["value"];
  const presentValue = data["present"];
  const noteValue = data["note"];
  const docId = typeof docIdValue === "string" ? docIdValue : undefined;
  const docType = typeof docTypeValue === "string" ? docTypeValue : undefined;
  const fieldKey = typeof fieldKeyValue === "string" ? fieldKeyValue : undefined;
  const label = typeof labelValue === "string" ? labelValue : undefined;
  const message = typeof messageValue === "string" ? messageValue : undefined;
  const valueText =
    valueValue === null || valueValue === undefined ? null : typeof valueValue === "string" ? valueValue : String(valueValue);
  const present =
    typeof presentValue === "boolean"
      ? presentValue
      : docId === EMPTY_DOC_ID
        ? false
        : undefined;
  const note = typeof noteValue === "string" ? noteValue : undefined;
  return { doc_id: docId, doc_type: docType, field_key: fieldKey, label, message, value: valueText, present, note };
}

function parseRefs(entry: Record<string, unknown>): ValidationRef[] {
  const raw = entry?.refs;
  if (typeof raw === "string" && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed.map(parseRefEntry).filter((item): item is ValidationRef => item !== null);
      }
      if (parsed && typeof parsed === "object") {
        return parseRefs({ refs: parsed });
      }
      return [];
    } catch {
      return [];
    }
  }
  if (Array.isArray(raw)) {
    return raw.map(parseRefEntry).filter((item): item is ValidationRef => item !== null);
  }
  if (raw && typeof raw === "object") {
    const refs: ValidationRef[] = [];
    Object.entries(raw as Record<string, unknown>).forEach(([docId, fields]) => {
      if (!fields || typeof fields !== "object") {
        return;
      }
      Object.entries(fields as Record<string, unknown>).forEach(([fieldKey, fieldValue]) => {
        const valueText =
          fieldValue === null || fieldValue === undefined
            ? null
            : typeof fieldValue === "string"
              ? fieldValue
              : String(fieldValue);
        const present = valueText !== null && valueText.trim().length > 0;
        refs.push({
          doc_id: docId || undefined,
          field_key: fieldKey || undefined,
          value: valueText,
          present,
        });
      });
    });
    return refs;
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
  const [expandedRules, setExpandedRules] = useState<Record<string, boolean>>({});
  const [expandedProductTables, setExpandedProductTables] = useState<Record<string, boolean>>({});
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

  const toggleRule = useCallback((ruleId: string) => {
    setExpandedRules((prev) => ({ ...prev, [ruleId]: !prev[ruleId] }));
  }, []);
  const toggleProductTable = useCallback((tableId: string) => {
    setExpandedProductTables((prev) => ({ ...prev, [tableId]: !prev[tableId] }));
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

  const missingDocNames = useMemo(() => missingDocEntries.map((item) => item.label), [missingDocEntries]);

  const validationRules: ValidationRuleView[] = useMemo(() => {
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
        if (ruleId === "document_matrix" || ruleId === "document_matrix_diff") {
          return null;
        }
        const baseRuleId = ruleId.endsWith("_availability") ? ruleId.replace(/_availability$/, "") : ruleId;
        const baseMessage = VALIDATION_RULE_MESSAGES[baseRuleId];
        if (!baseMessage) {
          return null;
        }
        const severity = typeof severityValue === "string" ? severityValue : "info";
        const messageSuffix = ruleId.endsWith("_availability")
          ? baseRuleId.startsWith("date_")
            ? "пропущены даты или значения невалидны"
            : "пропущены данные или значения невалидны"
          : "";
        const message = messageSuffix ? `${baseMessage}: ${messageSuffix}` : baseMessage;
        const ruleKey = `${ruleId}-${index}`;
        const rows = refs.map((ref, refIndex) => {
          const docEntry = ref.doc_id ? documentMap.get(ref.doc_id) : null;
          const docType = docEntry?.doc_type ?? ref.doc_type;
          const docLabelFromField = ref.field_key ? FIELD_DOC_LABELS[ref.field_key] : undefined;
          const docLabel = docType
            ? DOC_TYPE_LABELS[toDisplayDocType(docType)] ?? docType
            : docLabelFromField ?? "Документ";
          const docFilename = docEntry?.filename ?? null;
          const fieldKey = ref.field_key;
          const fieldLabel = formatFieldLabel(fieldKey, ref.label);
          const fieldState = docEntry && fieldKey ? docEntry.fields.find((item) => item.field_key === fieldKey) : null;
          const rawValue = fieldState?.value ?? ref.value ?? null;
          const valueText = rawValue !== null && rawValue !== undefined ? String(rawValue).trim() : "";
          const hasValue = valueText.length > 0;
          const status = ref.present === false || !hasValue ? "Отсутствует" : "Заполнено";
          return {
            key: `${ruleKey}-${docEntry?.id ?? docType ?? "doc"}-${fieldKey ?? "field"}-${refIndex}`,
            docLabel,
            docFilename,
            fieldLabel,
            status,
            value: hasValue ? valueText : null,
          };
        });
        if (rows.length === 0) {
          return null;
        }
        return {
          id: ruleKey,
          message,
          severity,
          rows,
          baseRuleId,
        } as ValidationRuleView;
      })
      .filter((entry): entry is ValidationRuleView => entry !== null)
      .sort((a, b) => {
        const indexA = VALIDATION_RULE_ORDER.indexOf((a as ValidationRuleView & { baseRuleId?: string }).baseRuleId ?? a.id);
        const indexB = VALIDATION_RULE_ORDER.indexOf((b as ValidationRuleView & { baseRuleId?: string }).baseRuleId ?? b.id);
        if (indexA === -1 && indexB === -1) {
          return a.message.localeCompare(b.message);
        }
        if (indexA === -1) {
          return 1;
        }
        if (indexB === -1) {
          return -1;
        }
        return indexA - indexB;
      });
  }, [batch, documentMap]);

  const documentProductTables = useMemo(() => {
    if (documents.length === 0) {
      return [];
    }
    return documents
      .map((doc) => {
        const columns = doc.products?.columns ?? [];
        const rows = doc.products?.rows ?? [];
        if (columns.length === 0 || rows.length === 0) {
          return null;
        }
        const title = DOC_TYPE_LABELS[toDisplayDocType(doc.doc_type)] ?? doc.doc_type;
        return {
          id: doc.id,
          title,
          filename: doc.filename,
          columns,
          rows,
        };
      })
      .filter((table): table is DocumentProductTable => table !== null);
  }, [documents]);

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
                  <div className="max-h-[70vh] overflow-auto" ref={matrixTableScrollRef}>
                    <Table ref={matrixTableRef}>
                      <TableHeader className="sticky top-0 z-20 bg-background">
                        <TableRow>
                          <TableHead className="sticky top-0 z-20 bg-background">Поле</TableHead>
                          {activeMatrix.documents.map((doc) => (
                            <TableHead key={doc} className="sticky top-0 z-20 bg-background">
                              {doc}
                            </TableHead>
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

      {documentProductTables.length === 0 ? (
        <Card className="rounded-3xl border bg-background">
          <CardHeader>
            <CardTitle>Товары</CardTitle>
          </CardHeader>
          <CardContent>
            <Alert variant="info">Нет товаров.</Alert>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {documentProductTables.map((table) => (
            <Card key={table.id} className="rounded-3xl border bg-background">
              <CardHeader className="space-y-1">
                <button
                  type="button"
                  onClick={() => toggleProductTable(table.id)}
                  className="flex w-full items-start justify-between gap-3 text-left"
                  aria-label="Toggle products"
                  aria-expanded={Boolean(expandedProductTables[table.id])}
                >
                  <div className="space-y-1">
                    <CardTitle>{table.title}</CardTitle>
                    {table.filename ? (
                      <p className="text-sm text-muted-foreground">{table.filename}</p>
                    ) : null}
                  </div>
                  <span className="mt-1 text-muted-foreground">
                    {expandedProductTables[table.id] ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  </span>
                </button>
              </CardHeader>
              {expandedProductTables[table.id] ? (
                <CardContent>
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Поле</TableHead>
                          {table.rows.map((row, index) => (
                            <TableHead key={row.key}>{`Продукт ${index + 1}`}</TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {table.columns.map((column) => (
                          <TableRow key={`${table.id}-${column.key}`}>
                            <TableCell className="font-medium">{column.label}</TableCell>
                            {table.rows.map((row, index) => {
                              const field = row.cells[column.key] ?? { value: null, confidence: null };
                              return (
                                <TableCell key={`${table.id}-${column.key}-${row.key}-${index}`} className="align-top text-sm">
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
              ) : null}
            </Card>
          ))}
        </div>
      )}

      <Card className="rounded-3xl border bg-background">
        <CardHeader>
          <CardTitle>Проверки</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {validationRules.length === 0 ? (
            <Alert variant="info">Нет проверок.</Alert>
          ) : (
            validationRules.map((rule) => {
              const isOpen = Boolean(expandedRules[rule.id]);
              return (
                <div key={rule.id} className="rounded-2xl border border-muted/60 bg-muted/10 p-3">
                  <button
                    type="button"
                    onClick={() => toggleRule(rule.id)}
                    className="flex w-full items-start justify-between gap-3 text-left"
                  >
                    <div className="space-y-1">
                      <div className="text-sm font-semibold">{rule.message || rule.id}</div>
                      <div className={cn("text-xs font-medium", severityClass(rule.severity))}>
                        {severityLabel(rule.severity)}
                      </div>
                    </div>
                    <span className="mt-1 text-muted-foreground">
                      {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </span>
                  </button>
                  {isOpen ? (
                    <div className="mt-3 overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Документ</TableHead>
                            <TableHead>Поле</TableHead>
                            <TableHead>Статус</TableHead>
                            <TableHead>Значение</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {rule.rows.map((row) => (
                            <TableRow key={row.key}>
                              <TableCell className="align-top text-sm">
                                <div className="font-medium">{row.docLabel}</div>
                                {row.docFilename ? (
                                  <div className="text-xs text-muted-foreground">{row.docFilename}</div>
                                ) : null}
                              </TableCell>
                              <TableCell className="align-top text-sm">{row.fieldLabel}</TableCell>
                              <TableCell className="align-top text-sm">
                                <span
                                  className={cn(
                                    "text-xs font-semibold",
                                    row.status === "Отсутствует" ? "text-amber-600" : "text-emerald-600",
                                  )}
                                >
                                  {row.status}
                                </span>
                              </TableCell>
                              <TableCell className="align-top text-sm">{row.value ?? "Нет значения"}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
        </CardContent>
      </Card>

      {matrixPopoverPortal}
    </div>
  );
}

export default SummaryTablePage;





