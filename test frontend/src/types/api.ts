export type ApiError = {
  detail: string;
};

export type ApiMessageResponse = {
  status: string;
  message: string;
  [key: string]: unknown;
};

export type UploadResponse = {
  status: string;
  batch_id: string;
  documents: number;
  document_urls: string[];
};

export type BatchSummary = {
  id: string;
  status: string;
  documents_count: number;
  created_at: string | null;
  created_at_display: string | null;
  can_delete: boolean;
};

export type BatchesResponse = {
  batches: BatchSummary[];
};

export type FieldState = {
  doc_id: string;
  field_key: string;
  value: string | null;
  confidence: number | null;
  confidence_display: string | null;
  required: boolean;
  reason: string;
  needs_confirmation: boolean;
  actionable: boolean;
  editable: boolean;
  bbox?: number[] | null;
  page?: number | null;
  token_refs?: string[] | null;
};

export type ProductColumn = {
  key: string;
  label: string;
};

export type ProductCell = {
  value: string | null;
  confidence: number | null;
  confidence_display: string | null;
};

export type ProductRow = {
  key: string;
  cells: Record<string, ProductCell>;
};

export type ProductTable = {
  columns: ProductColumn[];
  rows: ProductRow[];
};

export type ReportDocumentEntry = {
  doc_id: string | null;
  filename: string | null;
  doc_type: string | null;
  status: string | null;
  field_key: string;
  value: string | null;
  confidence: number | null;
  source?: string | null;
  page?: number | null;
};

export type ReportValidationRef = {
  doc_id?: string | null;
  doc_type?: string | null;
  field_key?: string | null;
  label?: string | null;
  message?: string | null;
  present?: boolean;
  note?: string | null;
};

export type ReportValidationEntry = {
  rule_id: string;
  severity: string;
  message: string;
  refs: ReportValidationRef[];
};

export type DocumentPayload = {
  id: string;
  filename: string;
  status: string;
  doc_type: string;
  filled_json: string | null;
  fields: FieldState[];
  pending_count: number;
  processing: boolean;
  products: ProductTable;
  previews: string[];
};

export type ReportSection = {
  available: boolean;
  documents: ReportDocumentEntry[];
  validations: ReportValidationEntry[];
  product_comparisons: Record<string, unknown>[];
  product_matrix_columns: Record<string, string>[];
  product_matrix: Record<string, unknown>[];
  validation_matrix_columns: Record<string, string>[];
  validation_matrix: Record<string, unknown>[];
  raw_json: string | null;
};

export type BatchDetails = {
  id: string;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  documents: DocumentPayload[];
  documents_count: number;
  doc_types: string[];
  pending_total: number;
  awaiting_processing: boolean;
  can_complete: boolean;
  processing_warnings: string[];
  report: ReportSection;
  links: {
    report_xlsx: string | null;
  };
};

export type BatchDetailsResponse = {
  batch: BatchDetails;
};
