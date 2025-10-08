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
  | "CANCEL_REQUESTED"
  | "CANCELLED"

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

export interface BatchCreateResponse {
  batch_id: string
}

export interface BatchUploadResponse {
  saved: string[]
}

export interface ReviewField {
  doc_id: string
  document_filename: string
  field_key: string
  value: string | null
  confidence: number
  required: boolean
  threshold: number
  source: string
  page: number | null
  bbox: number[] | null
  token_refs: string[] | null
  doc_type: DocumentType
}

export interface ReviewResponse {
  batch_id: string
  status: BatchStatus
  low_conf_threshold: number
  fields: ReviewField[]
}

export interface FieldUpdateRequestPayload {
  value: string | null
  bbox?: number[] | null
  token_refs?: string[] | null
}

export interface FieldUpdateResponse {
  doc_id: string
  field_key: string
  version: number
  confidence: number
}

export interface ValidationRef {
  doc_id?: string
  field_key?: string
  page?: number | null
  bbox?: number[] | null
}

export interface ValidationResult {
  rule_id: string
  severity: string
  message: string
  refs: ValidationRef[]
}

export interface BatchReportResponse {
  batch_id: string
  status: BatchStatus
  validations: ValidationResult[]
  meta: Record<string, unknown>
}

export type UiBatchState =
  | "draft"
  | "waiting"
  | "processing"
  | "manual"
  | "done"
  | "failed"
  | "deleting"
  | "cancelled"

export interface QueueCardData extends BatchSummary {
  uiStatus: UiBatchState
  title: string
  company: string | null
  docPreview: Array<{ label: string; icon: "pdf" | "word" | "excel" | "other" }>
}
