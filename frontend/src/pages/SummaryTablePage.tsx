﻿import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useParams } from "react-router-dom"
import DocumentViewer, { type ViewerBox } from "../components/resolve/DocumentViewer"
import { useBatchStore } from "../state/batch-store"
import { completeReview, downloadReport, fetchReport, fetchReview, updateReviewField } from "../api/client"
import type { BatchReportResponse, BatchSummary, ReviewField, ReviewResponse, ValidationResult } from "../api/types"
import { prettifyFieldKey } from "../utils/field-label"
import { buildPreviewCandidates } from "../utils/preview"

const sleep = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms))

const TEXT = {
  title: "\u0418\u0442\u043e\u0433\u043e\u0432\u0430\u044f \u0442\u0430\u0431\u043b\u0438\u0446\u0430",
  subtitle:
    "\u041f\u0440\u043e\u0441\u043c\u043e\u0442\u0440\u0438\u0442\u0435 \u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0434\u0430\u043d\u043d\u044b\u0435, \u0441\u043f\u0438\u0441\u043e\u043a \u0437\u0430\u043c\u0435\u0447\u0430\u043d\u0438\u0439 \u0438 \u043e\u0442\u0447\u0451\u0442.",
  export: "\u042d\u043a\u0441\u043f\u043e\u0440\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u043e\u0442\u0447\u0451\u0442",
  loading: "\u0417\u0430\u0433\u0440\u0443\u0436\u0430\u0435\u043c \u0441\u0432\u043e\u0434\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435\u2026",
  loadError: "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0438\u0442\u043e\u0433\u043e\u0432\u0443\u044e \u0442\u0430\u0431\u043b\u0438\u0446\u0443.",
  noBatch: "\u041f\u0430\u043a\u0435\u0442 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.",
  modalTitle: "\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435",
  save: "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c",
  cancel: "\u041e\u0442\u043c\u0435\u043d\u0430",
  reportPendingTitle: "\u0424\u043e\u0440\u043c\u0438\u0440\u0443\u0435\u043c \u043e\u0442\u0447\u0451\u0442",
  reportPendingHint:
    "\u042d\u0442\u043e \u043c\u043e\u0436\u0435\u0442 \u0437\u0430\u043d\u044f\u0442\u044c \u043f\u0430\u0440\u0443 \u043c\u0438\u043d\u0443\u0442. \u041c\u044b \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438 \u043e\u0431\u043d\u043e\u0432\u0438\u043c \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0443, \u043a\u0430\u043a \u0442\u043e\u043b\u044c\u043a\u043e \u0438\u0442\u043e\u0433\u043e\u0432\u044b\u0439 \u043e\u0442\u0447\u0451\u0442 \u0431\u0443\u0434\u0435\u0442 \u0433\u043e\u0442\u043e\u0432.",
  processingWarningTitle: "\u0415\u0441\u0442\u044c \u043f\u0440\u0435\u0434\u0443\u043f\u0440\u0435\u0436\u0434\u0435\u043d\u0438\u044f",
  processingWarningHint:
    "\u041e\u0442\u0447\u0451\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d, \u043d\u043e \u043f\u043e\u0436\u0430\u043b\u0443\u0439\u0441\u0442\u0430 \u043f\u0440\u043e\u0441\u043c\u043e\u0442\u0440\u0438\u0442\u0435 \u0437\u0430\u043c\u0435\u0447\u0430\u043d\u0438\u044f \u043d\u0438\u0436\u0435.",
}

const WARNING_MESSAGE_LOOKUP: Record<string, string> = {
  review_not_complete:
    "\u041d\u0435 \u0432\u0441\u0435 \u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u044b\u0435 \u043f\u043e\u043b\u044f \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u044b; \u043e\u0442\u0447\u0451\u0442 \u0441\u043e\u0431\u0440\u0430\u043d \u0441 \u043f\u0440\u0435\u0434\u0443\u043f\u0440\u0435\u0436\u0434\u0435\u043d\u0438\u044f\u043c\u0438.",
}

const confidenceTint = (value: number) => {
  const clamped = Math.max(0, Math.min(1, value))
  const intensity = (1 - clamped) * 0.4
  return `rgba(99, 102, 241, ${intensity.toFixed(3)})`
}

const fieldKeyFor = (docId: string, fieldKey: string) => `${docId}::${fieldKey}`

const SummaryTablePage = () => {
  const { packetId } = useParams<{ packetId: string }>()
  const { getBatch } = useBatchStore()
  const latestPacketId = useRef<string | null>(null)
  const runRef = useRef<symbol | null>(null)
  const retryTimeoutRef = useRef<number | null>(null)
  const [batch, setBatch] = useState<BatchSummary | null>(null)
  const [review, setReview] = useState<ReviewResponse | null>(null)
  const [report, setReport] = useState<BatchReportResponse | null>(null)
  const [validations, setValidations] = useState<ValidationResult[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const [highlightKey, setHighlightKey] = useState<string | null>(null)
  const [modalField, setModalField] = useState<ReviewField | null>(null)
  const [modalValue, setModalValue] = useState<string>("")
  const [modalSaving, setModalSaving] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [reportPending, setReportPending] = useState(false)

  const processingWarnings = useMemo(() => {
    const meta = report?.meta
    if (!meta || typeof meta !== "object") return []
    const raw = (meta as Record<string, unknown>).processing_warnings
    if (!Array.isArray(raw)) return []
    return raw.filter((item): item is string => typeof item === "string")
  }, [report])

  const warningMessages = useMemo(
    () => processingWarnings.map((key) => WARNING_MESSAGE_LOOKUP[key] ?? key),
    [processingWarnings],
  )

  useEffect(() => {
    latestPacketId.current = packetId ?? null
  }, [packetId])

  useEffect(() => {
    return () => {
      if (retryTimeoutRef.current !== null) {
        window.clearTimeout(retryTimeoutRef.current)
        retryTimeoutRef.current = null
      }
    }
  }, [])

  const load = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!packetId) return
      const silent = options?.silent ?? false
      if (!silent) {
        setLoading(true)
        setError(null)
      }
      if (retryTimeoutRef.current !== null) {
        window.clearTimeout(retryTimeoutRef.current)
        retryTimeoutRef.current = null
      }
      try {
        const summary = await getBatch(packetId, true)
        if (!summary) {
          setBatch(null)
          setReview(null)
          setReport(null)
          setValidations([])
          setReportPending(false)
          setError(TEXT.noBatch)
          return
        }

        const reviewPayload = await fetchReview(packetId)

        setBatch(summary)
        setReview(reviewPayload)
        setError(null)
        setReport(null)
        setValidations([])
        setReportPending(true)

        const runId = Symbol("report-run")
        runRef.current = runId
        const currentPacketId = packetId

        const run = async () => {
          try {
            await sleep(1000)
            await completeReview(currentPacketId).catch((err) => {
              console.warn("completeReview failed; continuing to fetch report", err)
            })
            const reportPayload = await fetchReport(currentPacketId)
            if (runRef.current !== runId || latestPacketId.current !== currentPacketId) {
              return
            }
            setReport(reportPayload)
            setValidations(reportPayload?.validations ?? [])
            setReportPending(!reportPayload)
            if (reportPayload) {
              if (retryTimeoutRef.current !== null) {
                window.clearTimeout(retryTimeoutRef.current)
                retryTimeoutRef.current = null
              }
            } else if (latestPacketId.current === currentPacketId) {
              if (retryTimeoutRef.current !== null) {
                window.clearTimeout(retryTimeoutRef.current)
              }
              retryTimeoutRef.current = window.setTimeout(() => {
                if (latestPacketId.current === currentPacketId) {
                  load({ silent: true }).catch(() => undefined)
                }
              }, 3000)
            }
          } catch (err) {
            console.error(err)
            if (runRef.current === runId && latestPacketId.current === currentPacketId) {
              setReportPending(true)
              if (retryTimeoutRef.current !== null) {
                window.clearTimeout(retryTimeoutRef.current)
              }
              retryTimeoutRef.current = window.setTimeout(() => {
                if (latestPacketId.current === currentPacketId) {
                  load({ silent: true }).catch(() => undefined)
                }
              }, 3000)
            }
          } finally {
            if (runRef.current === runId) {
              runRef.current = null
            }
          }
        }

        run().catch((err) => {
          console.error(err)
        })
      } catch (err) {
        console.error(err)
        if (!silent) {
          setError(TEXT.loadError)
        }
      } finally {
        if (!silent) {
          setLoading(false)
        }
      }
    },
    [getBatch, packetId],
  )
  useEffect(() => {
    load().catch(() => undefined)
  }, [load])

  const fieldLookup = useMemo(() => {
    const map = new Map<string, Map<string, ReviewField>>()
    if (review && review.fields.length > 0) {
      for (const field of review.fields) {
        const bucket = map.get(field.doc_id) ?? new Map<string, ReviewField>()
        bucket.set(field.field_key, field)
        map.set(field.doc_id, bucket)
      }
      return map
    }
    if (report && report.documents.length > 0) {
      const threshold = review?.low_conf_threshold ?? 0
      const batchDocs = batch ? batch.documents : []
      const byId = new Map(batchDocs.map((doc) => [doc.id, doc]))
      for (const doc of report.documents) {
        const bucket = map.get(doc.doc_id) ?? new Map<string, ReviewField>()
        const filename = doc.filename || byId.get(doc.doc_id)?.filename || doc.doc_id
        const fields = Object.entries(doc.fields ?? {})
        for (const [key, value] of fields) {
          bucket.set(key, {
            doc_id: doc.doc_id,
            document_filename: filename,
            field_key: key,
            value: value?.value ?? null,
            confidence: value?.confidence ?? 0,
            required: false,
            threshold,
            source: value?.source ?? "report",
            page: value?.page ?? null,
            bbox: value?.bbox ?? null,
            token_refs: null,
            doc_type: doc.doc_type,
          })
        }
        if (bucket.size > 0) {
          map.set(doc.doc_id, bucket)
        }
      }
    }
    return map
  }, [batch, report, review])

  const fieldKeys = useMemo(() => {
    const keys = new Set<string>()
    fieldLookup.forEach((fields) => {
      fields.forEach((_value, key) => keys.add(key))
    })
    return Array.from(keys).sort()
  }, [fieldLookup])

  const mistakeKeys = useMemo(() => {
    const set = new Set<string>()
    for (const validation of validations) {
      for (const ref of validation.refs) {
        if (ref.doc_id && ref.field_key) {
          set.add(fieldKeyFor(ref.doc_id, ref.field_key))
        }
      }
    }
    return set
  }, [validations])

  const handleDownload = async () => {
    if (!packetId || reportPending) return
    try {
      setDownloading(true)
      const blob = await downloadReport(packetId)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = `report-${packetId}.xlsx`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error(err)
      setError(TEXT.loadError)
    } finally {
      setDownloading(false)
    }
  }

  const openModal = (field: ReviewField) => {
    setModalField(field)
    setModalValue(field.value ?? "")
    setHighlightKey(fieldKeyFor(field.doc_id, field.field_key))
  }

  const closeModal = () => {
    setModalField(null)
    setModalValue("")
    setModalSaving(false)
  }

  const saveModal = async () => {
    const field = modalField
    if (!field) return
    try {
      setModalSaving(true)
      await updateReviewField(field.doc_id, field.field_key, { value: modalValue.trim() })
      setReview((current) => {
        if (!current) return current
        return {
          ...current,
          fields: current.fields.map((item) =>
            item.doc_id === field.doc_id && item.field_key === field.field_key
              ? { ...item, value: modalValue.trim(), confidence: 1, source: "user" }
              : item,
          ),
        }
      })
      closeModal()
    } catch (err) {
      console.error(err)
      setError(TEXT.loadError)
      setModalSaving(false)
    }
  }

  const getField = useCallback(
    (docId: string, fieldKey: string) => fieldLookup.get(docId)?.get(fieldKey) ?? null,
    [fieldLookup],
  )

  const hoverField = useMemo(() => {
    if (!hoverKey) return null
    const [docId, field] = hoverKey.split("::")
    return getField(docId, field)
  }, [getField, hoverKey])

  const highlightField = useMemo(() => {
    if (!highlightKey) return null
    const [docId, field] = highlightKey.split("::")
    return getField(docId, field)
  }, [getField, highlightKey])

  const previewCandidatesForField = useCallback(
    (field: ReviewField | null): string[] => {
      if (!packetId || !field) return []
      return buildPreviewCandidates(packetId, field.doc_id, field.page ?? 1)
    },
    [packetId],
  )

  const buildCutoutStyle = useCallback(
    (field: ReviewField | null) => {
      if (!field) return {}
      const image = previewCandidatesForField(field)[0]
      if (!image) return {}
      if (!field.bbox || field.bbox.length < 4) {
        return {
          backgroundImage: `url(${image})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }
      }
      const [x1, y1, x2, y2] = field.bbox
      const isNormalized = x1 <= 1 && y1 <= 1 && x2 <= 1 && y2 <= 1
      const centerX = isNormalized ? ((x2 >= x1 ? x1 + (x2 - x1) / 2 : x1 + x2 / 2) * 100) : 50
      const centerY = isNormalized ? ((y2 >= y1 ? y1 + (y2 - y1) / 2 : y1 + y2 / 2) * 100) : 50
      return {
        backgroundImage: `url(${image})`,
        backgroundSize: "220% 220%",
        backgroundPosition: `${centerX}% ${centerY}%`,
      }
    },
    [previewCandidatesForField],
  )
  if (!packetId) {
    return (
      <div className="page">
        <div className="callout error">{TEXT.noBatch}</div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="page">
        <header className="page-header">
          <h1>{TEXT.title}</h1>
          <p>{TEXT.subtitle}</p>
        </header>
        <div className="callout info">{TEXT.loading}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="page">
        <header className="page-header">
          <h1>{TEXT.title}</h1>
          <p>{TEXT.subtitle}</p>
        </header>
        <div className="callout error">{error}</div>
      </div>
    )
  }

  if (!batch || !review) {
    return (
      <div className="page">
        <div className="callout info">{TEXT.noBatch}</div>
      </div>
    )
  }

  const documents = report && report.documents.length > 0
    ? report.documents.map((doc) => {
        const fallback = batch.documents.find((item) => item.id === doc.doc_id)
        return {
          id: doc.doc_id,
          filename: doc.filename || fallback?.filename || doc.doc_id,
          doc_type: doc.doc_type,
          status: fallback?.status ?? doc.status,
          pages: fallback?.pages ?? 0,
        }
      })
    : batch.documents
  const hoverStyle = buildCutoutStyle(hoverField)
  const highlightStyle = buildCutoutStyle(highlightField)
  const modalCandidates = previewCandidatesForField(modalField)
  const modalBoxes: ViewerBox[] = modalField
    ? [
        {
          key: fieldKeyFor(modalField.doc_id, modalField.field_key),
          bbox: modalField.bbox,
          active: true,
        },
      ]
    : []

  return (
    <div className="page summary-page">
      <header className="page-header">
        <h1>{TEXT.title}</h1>
        <p>{TEXT.subtitle}</p>
      </header>
      <div className="summary-toolbar">
        <button
          type="button"
          className="btn-primary"
          onClick={handleDownload}
          disabled={downloading || reportPending}
        >
          {TEXT.export}
        </button>
      </div>
      {reportPending && (
        <div className="callout info">
          <strong>{TEXT.reportPendingTitle}</strong>
          <p className="muted">{TEXT.reportPendingHint}</p>
        </div>
      )}
      {warningMessages.length > 0 && (
        <div className="callout warning">
          <strong>{TEXT.processingWarningTitle}</strong>
          <p className="muted">{TEXT.processingWarningHint}</p>
          <ul>
            {warningMessages.map((message, index) => (
              <li key={`${message}-${index}`}>{message}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="summary-content">
        <div className="summary-table-wrapper">
          <table className="summary-table">
            <thead>
              <tr>
                <th>{"\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442"}</th>
                <th>{"\u0422\u0438\u043f"}</th>
                {fieldKeys.map((key) => (
                  <th key={key}>{prettifyFieldKey(key)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td>{doc.filename}</td>
                  <td>{doc.doc_type}</td>
                  {fieldKeys.map((key) => {
                    const field = getField(doc.id, key)
                    const cellKey = fieldKeyFor(doc.id, key)
                    const tint = field ? confidenceTint(field.confidence) : "transparent"
                    const isError = mistakeKeys.has(cellKey)
                    const isHighlighted = highlightKey === cellKey
                    return (
                      <td
                        key={cellKey}
                        className={`summary-cell${isError ? " is-error" : ""}${isHighlighted ? " is-highlight" : ""}`}
                        style={{ background: tint }}
                        onMouseEnter={() => setHoverKey(cellKey)}
                        onMouseLeave={() => setHoverKey(null)}
                        onClick={() => {
                          if (field) openModal(field)
                        }}
                      >
                        {field?.value ?? "—"}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="summary-previews">
          <div className="summary-preview-card">
            <h4>{"\u041d\u0430\u0432\u0435\u0434\u0435\u043d\u0438\u0435"}</h4>
            <div className="summary-cutout" style={hoverStyle} />
          </div>
          <div className="summary-preview-card">
            <h4>{"\u0412\u044b\u0434\u0435\u043b\u0435\u043d\u043e"}</h4>
            <div className="summary-cutout" style={highlightStyle} />
          </div>
        </div>
      </div>
      <section className="summary-validations">
        <h3>{"\u0417\u0430\u043c\u0435\u0447\u0430\u043d\u0438\u044f"}</h3>
        {validations.length === 0 && <p className="muted">{"\u041e\u0448\u0438\u0431\u043e\u043a \u043d\u0435\u0442."}</p>}
        {validations.length > 0 && (
          <ul>
            {validations.map((item) => (
              <li key={`${item.rule_id}-${item.message}`}>
                <button
                  type="button"
                  onClick={() => {
                    const ref = item.refs.find((ref) => ref.doc_id && ref.field_key)
                    if (ref && ref.doc_id && ref.field_key) {
                      const key = fieldKeyFor(ref.doc_id, ref.field_key)
                      setHighlightKey(key)
                    }
                  }}
                >
                  <span className={`summary-badge summary-badge-${item.severity.toLowerCase()}`}>{item.severity}</span>
                  <span>{item.message}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {modalField && (
        <div className="summary-modal">
          <div className="summary-modal-backdrop" onClick={closeModal} />
          <div className="summary-modal-dialog">
            <div className="summary-modal-header">
              <h3>{TEXT.modalTitle}</h3>
              <button type="button" className="btn-ghost subtle" onClick={closeModal}>
                {TEXT.cancel}
              </button>
            </div>
            <div className="summary-modal-body">
            <DocumentViewer
              imageUrl={modalCandidates[0] ?? null}
              imageCandidates={modalCandidates}
              title={modalField.document_filename}
              boxes={modalBoxes}
            />
              <label>{prettifyFieldKey(modalField.field_key)}</label>
              <textarea value={modalValue} onChange={(event) => setModalValue(event.target.value)} />
            </div>
            <div className="summary-modal-footer">
              <button type="button" className="btn-primary" onClick={saveModal} disabled={modalSaving}>
                {TEXT.save}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default SummaryTablePage



