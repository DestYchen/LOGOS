import { useEffect, useMemo, useState } from "react"
import { useLocation, useSearchParams } from "react-router-dom"
import UploadDropzoneCard, { type UploadDisplayItem, type UploadIcon } from "../components/upload/UploadDropzoneCard"
import { DOCUMENT_STATUS_LABELS, UI_STATUS_LABELS } from "../constants/status"
import { useBatchStore } from "../state/batch-store"
import type { BatchSummary } from "../api/types"

const TEXT = {
  title: "\u0412 \u043e\u0447\u0435\u0440\u0435\u0434\u0438",
  subtitle:
    "\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u044b \u043f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043b\u0435\u043d\u044b \u043a \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0435. \u041c\u044b \u043e\u0431\u043d\u043e\u0432\u0438\u043c \u0441\u0442\u0430\u0442\u0443\u0441 \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438.",
  queueHelp: "\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u044b \u0432 \u043e\u0447\u0435\u0440\u0435\u0434\u0438 \u043d\u0430 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0443.",
  loading: "\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430 \u043f\u0430\u043a\u0435\u0442\u0430\u2026",
  error: "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u0434\u0430\u043d\u043d\u044b\u0435 \u043e \u043f\u0430\u043a\u0435\u0442\u0435.",
  empty: "\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u043f\u0430\u043a\u0435\u0442 \u0432 \u0438\u0441\u0442\u043e\u0440\u0438\u0438, \u0447\u0442\u043e\u0431\u044b \u0441\u043b\u0435\u0434\u0438\u0442\u044c \u0437\u0430 \u043e\u0447\u0435\u0440\u0435\u0434\u044c\u044e.",
  packetPrefix: "\u041f\u0430\u043a\u0435\u0442",
  documentsCount: "\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u043e\u0432:",
  pagesPrefix: "\u0421\u0442\u0440\u0430\u043d\u0438\u0446:",
}

const iconForFilename = (name: string): UploadIcon => {
  const lower = name.toLowerCase()
  if (lower.endsWith(".pdf")) return "pdf"
  if (lower.endsWith(".doc") || lower.endsWith(".docx")) return "word"
  if (lower.endsWith(".xls") || lower.endsWith(".xlsx") || lower.endsWith(".csv")) return "excel"
  return "other"
}

const QueuePageV2 = () => {
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { history, statusFor, getBatch } = useBatchStore()

  const [activeId, setActiveId] = useState<string | null>(() => {
    const byQuery = searchParams.get("id")
    if (byQuery) return byQuery
    const byState = (location.state as { focusBatchId?: string } | null)?.focusBatchId
    return byState ?? null
  })

  const [batch, setBatch] = useState<BatchSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const byState = (location.state as { focusBatchId?: string } | null)?.focusBatchId
    if (byState) {
      setActiveId(byState)
    }
  }, [location.state])

  useEffect(() => {
    const byQuery = searchParams.get("id")
    if (byQuery) {
      setActiveId(byQuery)
    }
  }, [searchParams])

  useEffect(() => {
    if (activeId) return
    const candidate = history.find((item) => {
      const uiState = statusFor(item.status)
      return uiState === "waiting" || uiState === "processing"
    })
    if (candidate) {
      setActiveId(candidate.id)
    }
  }, [activeId, history, statusFor])

  useEffect(() => {
    if (!activeId) {
      setBatch(null)
      return
    }
    let cancelled = false
    let initialLoad = true

    const load = async () => {
      if (initialLoad) {
        setLoading(true)
        setError(null)
      }
      try {
        const summary = await getBatch(activeId, true)
        if (cancelled) return
        setBatch(summary)
        setError(summary ? null : TEXT.error)
      } catch (err) {
        console.error(err)
        if (!cancelled) {
          setError(TEXT.error)
        }
      } finally {
        if (!cancelled && initialLoad) {
          setLoading(false)
          initialLoad = false
        }
      }
    }

    load().catch(() => undefined)
    const timer = window.setInterval(() => {
      load().catch(() => undefined)
    }, 7000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [activeId, getBatch])

  const displayedItems = useMemo<UploadDisplayItem[]>(() => {
    if (!batch) return []
    return batch.documents.map((doc) => ({
      id: doc.id,
      name: doc.filename,
      sizeLabel: DOCUMENT_STATUS_LABELS[doc.status],
      meta: `${TEXT.pagesPrefix} ${doc.pages}`,
      icon: iconForFilename(doc.filename),
    }))
  }, [batch])

  const packetStatus = batch ? statusFor(batch.status) : null
  const packetStatusLabel = packetStatus ? UI_STATUS_LABELS[packetStatus] ?? packetStatus : null

  return (
    <div className="page page-queue">
      <header className="page-header">
        <h1>{TEXT.title}</h1>
        <p>{TEXT.subtitle}</p>
      </header>

      <div className="upload-panel queue">
        {batch && (
          <div className="queue-meta">
            <span className="queue-meta-id">
              {TEXT.packetPrefix} {batch.id.slice(0, 8)}
            </span>
            {packetStatusLabel && <span className={`status-pill status-${packetStatus}`}>{packetStatusLabel}</span>}
            <span className="queue-meta-count">
              {TEXT.documentsCount} {batch.documents.length}
            </span>
          </div>
        )}

        <UploadDropzoneCard
          items={displayedItems}
          dragging={false}
          disabled
          highlight="queue"
          placeholder={<div className="queue-placeholder">{TEXT.queueHelp}</div>}
          hint={null}
        />

        <div className="queue-footer">
          {loading && <div className="callout info">{TEXT.loading}</div>}
          {!loading && error && <div className="callout error">{error}</div>}
          {!loading && !error && !batch && <div className="callout info">{TEXT.empty}</div>}
          {!loading && batch && <div className="queue-help">{TEXT.queueHelp}</div>}
        </div>
      </div>
    </div>
  )
}

export default QueuePageV2
