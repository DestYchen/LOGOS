import type { DocumentStatus, UiBatchState } from "../api/types"

export const UI_STATUS_LABELS: Record<UiBatchState, string> = {
  draft: "\u041d\u043e\u0432\u044b\u0439",
  waiting: "\u0412 \u043e\u0447\u0435\u0440\u0435\u0434\u0438",
  processing: "\u041e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430",
  manual: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430",
  done: "\u0413\u043e\u0442\u043e\u0432\u043e",
  failed: "\u041e\u0448\u0438\u0431\u043a\u0430",
  deleting: "\u0423\u0434\u0430\u043b\u0435\u043d\u0438\u0435",
  cancelled: "\u041e\u0442\u043c\u0435\u043d\u0451\u043d",
}

export const DOCUMENT_STATUS_LABELS: Record<DocumentStatus, string> = {
  NEW: "\u041d\u043e\u0432\u044b\u0439",
  TEXT_READY: "\u0422\u0435\u043a\u0441\u0442 \u0433\u043e\u0442\u043e\u0432",
  CLASSIFIED: "\u041a\u043b\u0430\u0441\u0441\u0438\u0444\u0438\u0446\u0438\u044f",
  FILLED_AUTO: "\u0417\u0430\u043f\u043e\u043b\u043d\u0435\u043d",
  FILLED_REVIEWED: "\u041f\u0440\u043e\u0432\u0435\u0440\u0435\u043d",
  FAILED: "\u041e\u0448\u0438\u0431\u043a\u0430",
}

