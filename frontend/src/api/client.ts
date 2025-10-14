import type {
  BatchCreateResponse,
  BatchReportResponse,
  BatchStatus,
  BatchSummary,
  BatchUploadResponse,
  DocumentSummary,
  FieldUpdateRequestPayload,
  FieldUpdateResponse,
  QueueCardData,
  ReviewResponse,
  UiBatchState,
} from "./types"

const parseJson = async <T>(response: Response): Promise<T> => {
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || response.statusText)
  }
  return response.json() as Promise<T>
}

const ensureOk = async (response: Response): Promise<void> => {
  if (response.ok || (response.status >= 200 && response.status < 400)) {
    return
  }
  const text = await response.text()
  throw new Error(text || response.statusText)
}

export const fetchQueueBatches = async (): Promise<BatchSummary[]> => {
  const response = await fetch("/batches/")
  return parseJson<BatchSummary[]>(response)
}

export const fetchBatchSummary = async (batchId: string): Promise<BatchSummary> => {
  const response = await fetch(`/batches/${batchId}`)
  return parseJson<BatchSummary>(response)
}

export const createBatch = async (createdBy = "web-ui"): Promise<string> => {
  const response = await fetch("/batches/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ created_by: createdBy }),
  })
  const payload = await parseJson<BatchCreateResponse>(response)
  return payload.batch_id
}

export const uploadBatchDocuments = async (batchId: string, files: File[]): Promise<BatchUploadResponse> => {
  const form = new FormData()
  for (const file of files) {
    form.append("files", file)
  }
  const response = await fetch(`/batches/${batchId}/upload`, {
    method: "POST",
    body: form,
  })
  return parseJson<BatchUploadResponse>(response)
}

export const processBatch = async (batchId: string): Promise<void> => {
  const response = await fetch(`/batches/${batchId}/process`, { method: "POST" })
  await ensureOk(response)
}

export const fetchReview = async (batchId: string): Promise<ReviewResponse> => {
  const response = await fetch(`/batches/${batchId}/review`)
  return parseJson<ReviewResponse>(response)
}

export const fetchReport = async (batchId: string): Promise<BatchReportResponse | null> => {
  const response = await fetch(`/batches/${batchId}/report`)
  if (response.status === 404) {
    return null
  }
  return parseJson<BatchReportResponse>(response)
}

export const downloadReport = async (batchId: string): Promise<Blob> => {
  const response = await fetch(`/web/batches/${batchId}/report.xlsx`)
  await ensureOk(response)
  return response.blob()
}

export const updateReviewField = async (
  docId: string,
  fieldKey: string,
  payload: FieldUpdateRequestPayload,
): Promise<FieldUpdateResponse> => {
  const response = await fetch(`/batches/documents/${docId}/fields/${encodeURIComponent(fieldKey)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  return parseJson<FieldUpdateResponse>(response)
}

export const completeReview = async (batchId: string, options?: { force?: boolean }): Promise<void> => {
  const params = new URLSearchParams()
  if (options?.force) {
    params.set("force", "true")
  }
  const query = params.toString()
  const response = await fetch(`/batches/${batchId}/review/complete${query ? `?${query}` : ""}`, { method: "POST" })
  await ensureOk(response)
}

export const deleteDocument = async (docId: string): Promise<void> => {
  const response = await fetch(`/documents/${docId}/delete`, { method: "POST" })
  await ensureOk(response)
}

export const setDocumentType = async (docId: string, docType: string): Promise<void> => {
  const form = new FormData()
  form.append("doc_type", docType)
  const response = await fetch(`/documents/${docId}/set_type`, {
    method: "POST",
    body: form,
  })
  await ensureOk(response)
}

export const refillDocument = async (docId: string): Promise<void> => {
  const response = await fetch(`/documents/${docId}/refill`, { method: "POST" })
  await ensureOk(response)
}

export const mapBatchStatus = (status: BatchStatus): UiBatchState => {
  if (status === "FAILED") return "failed"
  if (status === "CANCEL_REQUESTED") return "deleting"
  if (status === "CANCELLED") return "cancelled"
  if (status === "NEW") return "draft"
  if (status === "PREPARED") return "waiting"
  if (status === "TEXT_READY" || status === "CLASSIFIED") return "processing"
  if (status === "FILLED_AUTO") return "manual"
  if (status === "FILLED_REVIEWED") return "processing"
  if (status === "VALIDATED" || status === "DONE") return "done"
  return "waiting"
}

const iconForDocument = (doc: DocumentSummary): "pdf" | "word" | "excel" | "other" => {
  const name = doc.filename.toLowerCase()
  if (name.endsWith(".pdf")) return "pdf"
  if (name.endsWith(".doc") || name.endsWith(".docx")) return "word"
  if (name.endsWith(".xls") || name.endsWith(".xlsx") || name.endsWith(".csv")) return "excel"
  return "other"
}

const labelFor = (doc: DocumentSummary): string => {
  const ext = doc.filename.split(".").pop()?.toUpperCase()
  if (ext) return ext
  return doc.doc_type !== "UNKNOWN" ? doc.doc_type : "FILE"
}

export const toQueueCard = (batch: BatchSummary): QueueCardData => {
  const uiStatus = mapBatchStatus(batch.status)
  const date = new Date(batch.created_at)
  const formatted = new Intl.DateTimeFormat("ru-RU", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
  const prefix = "\u041f\u0430\u043a\u0435\u0442" // "Пакет"
  const title = `${prefix} ${batch.id.slice(0, 8)} \u00b7 ${formatted}`

  const buckets = new Map<string, { label: string; icon: "pdf" | "word" | "excel" | "other"; count: number }>()
  for (const doc of batch.documents) {
    const icon = iconForDocument(doc)
    const label = labelFor(doc)
    const entry = buckets.get(label)
    if (entry) {
      entry.count += 1
    } else {
      buckets.set(label, { label, icon, count: 1 })
    }
  }

  const docPreview = Array.from(buckets.values())
    .sort((a, b) => b.count - a.count)
    .slice(0, 4)
    .map((item) => ({
      label: item.count > 1 ? `${item.label} \u00d7 ${item.count}` : item.label,
      icon: item.icon,
    }))

  return {
    ...batch,
    uiStatus,
    title,
    company: batch.created_by,
    docPreview,
  }
}
