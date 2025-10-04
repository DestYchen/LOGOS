export type BatchStatus =
  | "NEW"
  | "PREPARED"
  | "TEXT_READY"
  | "CLASSIFIED"
  | "FILLED_AUTO"
  | "FILLED_REVIEWED"
  | "VALIDATED"
  | "DONE"
  | "FAILED"

export type DocumentStatus =
  | "NEW"
  | "TEXT_READY"
  | "CLASSIFIED"
  | "FILLED_AUTO"
  | "FILLED_REVIEWED"
  | "FAILED"

export type DocumentType =
  | "UNKNOWN"
  | "EXPORT_DECLARATION"
  | "INVOICE"
  | "PACKING_LIST"
  | "BILL_OF_LANDING"
  | "PROFORMA"
  | "SPECIFICATION"
  | "PRICE_LIST_1"
  | "PRICE_LIST_2"
  | "QUALITY_CERTIFICATE"
  | "CERTIFICATE_OF_ORIGIN"
  | "VETERINARY_CERTIFICATE"

export interface DocumentSummary {
  id: string
  filename: string
  status: DocumentStatus
  doc_type: DocumentType
  pages: number
}

export interface BatchSummary {
  id: string
  status: BatchStatus
  created_at: string
  updated_at: string
  created_by: string | null
  documents: DocumentSummary[]
}

export type UiBatchState =
  | "draft"
  | "waiting"
  | "processing"
  | "manual"
  | "done"
  | "failed"

export interface QueueCardData extends BatchSummary {
  uiStatus: UiBatchState
  title: string
  company: string | null
  docPreview: Array<{ label: string; icon: "pdf" | "word" | "excel" | "other" }>
}
