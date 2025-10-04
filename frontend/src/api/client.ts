import type {
  BatchStatus,
  BatchSummary,
  DocumentSummary,
  QueueCardData,
  UiBatchState,
} from "./types"

const parseJson = async <T>(response: Response): Promise<T> => {
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || response.statusText)
  }
  return response.json() as Promise<T>
}

export const fetchQueueBatches = async (): Promise<BatchSummary[]> => {
  const response = await fetch("/batches/")
  return parseJson<BatchSummary[]>(response)
}

export const fetchBatchSummary = async (batchId: string): Promise<BatchSummary> => {
  const response = await fetch(`/batches/${batchId}`)
  return parseJson<BatchSummary>(response)
}

export const mapBatchStatus = (status: BatchStatus): UiBatchState => {
  if (status === "FAILED") return "failed"
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
  const title = `Пакет ${batch.id.slice(0, 8)} · ${formatted}`

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
      label: item.count > 1 ? `${item.label} · ${item.count}` : item.label,
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

