import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/web";
export const API_JSON_BASE = `${API_BASE}/api`;

export function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return value;
  }
  return date.toLocaleString();
}

export function formatShortDate(value: string | null | undefined) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return value;
  }
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

export type StatusKey =
  | "uploaded"
  | "queued"
  | "processing"
  | "needs_review"
  | "ready_for_check"
  | "in_review"
  | "completed"
  | "error";

export function mapBatchStatus(status: string): StatusKey {
  const normalized = status.toUpperCase();
  if (["NEW", "PREPARED", "TEXT_READY", "CLASSIFIED"].includes(normalized)) {
    return "queued";
  }
  if (["FILLED_AUTO", "FILLED_REVIEWED"].includes(normalized)) {
    return "ready_for_check";
  }
  if (["VALIDATED", "DONE"].includes(normalized)) {
    return "completed";
  }
  if (["FAILED", "CANCELLED"].includes(normalized)) {
    return "error";
  }
  return "processing";
}

export function statusLabel(status: StatusKey): string {
  switch (status) {
    case "uploaded":
      return "Загружено";
    case "queued":
      return "В очереди";
    case "processing":
      return "Обработка";
    case "needs_review":
      return "Нужно проверить";
    case "ready_for_check":
      return "Готово к проверке";
    case "in_review":
      return "На проверке";
    case "completed":
      return "Завершено";
    case "error":
      return "Ошибка";
    default:
      return status;
  }
}

export type StatusBadgeVariant = "default" | "secondary" | "success" | "destructive" | "warning" | "outline";

export function statusVariant(status: StatusKey): StatusBadgeVariant {
  switch (status) {
    case "queued":
      return "secondary";
    case "processing":
      return "outline";
    case "ready_for_check":
      return "success";
    case "completed":
      return "success";
    case "error":
      return "destructive";
    case "needs_review":
    case "in_review":
      return "warning";
    default:
      return "outline";
  }
}

export function deriveHistoryRoute(batchId: string, status: StatusKey) {
  switch (status) {
    case "queued":
    case "processing":
      return `/queue?batch=${batchId}`;
    case "error":
    case "needs_review":
    case "ready_for_check":
      return `/resolve/${batchId}`;
    case "completed":
      return `/table/${batchId}`;
    default:
      return `/table/${batchId}`;
  }
}

export function getFileTypeIcon(ext: string): string {
  const normalized = ext.toLowerCase();
  if (normalized === "pdf") {
    return "/src/assets/pdf_icon.png";
  }
  if (["doc", "docx"].includes(normalized)) {
    return "/src/assets/word_icon.png";
  }
  if (["xls", "xlsx"].includes(normalized)) {
    return "/src/assets/excel_icon.png";
  }
  return "/src/assets/other_icon.png";
}
