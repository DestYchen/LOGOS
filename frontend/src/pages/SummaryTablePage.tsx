import { useCallback, useEffect, useMemo, useState } from "react"
import { useParams } from "react-router-dom"
import DocumentViewer, { type ViewerBox } from "../components/resolve/DocumentViewer"
import { useBatchStore } from "../state/batch-store"
import { downloadReport, fetchReport, fetchReview, updateReviewField } from "../api/client"
import type { BatchSummary, ReviewField, ReviewResponse, ValidationResult } from "../api/types"
import { prettifyFieldKey } from "../utils/field-label"
import { buildPreviewCandidates } from "../utils/preview"

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
  const [batch, setBatch] = useState<BatchSummary | null>(null)
  const [review, setReview] = useState<ReviewResponse | null>(null)
  const [validations, setValidations] = useState<ValidationResult[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const [highlightKey, setHighlightKey] = useState<string | null>(null)
  const [modalField, setModalField] = useState<ReviewField | null>(null)
  const [modalValue, setModalValue] = useState<string>("")
  const [modalSaving, setModalSaving] = useState(false)
  const [downloading, setDownloading] = useState(false)

  const load = useCallback(async () => {
    if (!packetId) return
    setLoading(true)
    try {
      const [summary, reviewPayload, reportPayload] = await Promise.all([
        getBatch(packetId, true),
        fetchReview(packetId),
        fetchReport(packetId),
      ])
      if (!summary) {
        setBatch(null)
        setReview(null)
        setValidations([])
        setError(TEXT.noBatch)
        return
      }
      setBatch(summary)
      setReview(reviewPayload)
      setValidations(reportPayload.validations)
      setError(null)
    } catch (err) {
      console.error(err)
      setError(TEXT.loadError)
    } finally {
      setLoading(false)
    }
  }, [getBatch, packetId])
  useEffect(() => {
    load().catch(() => undefined)
  }, [load])

  const fieldLookup = useMemo(() => {
    const map = new Map<string, Map<string, ReviewField>>()
    if (!review) return map
    for (const field of review.fields) {
      const bucket = map.get(field.doc_id) ?? new Map<string, ReviewField>()
      bucket.set(field.field_key, field)
      map.set(field.doc_id, bucket)
    }
    return map
  }, [review])

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
    if (!packetId) return
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

  const documents = batch.documents
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
        <button type="button" className="btn-primary" onClick={handleDownload} disabled={downloading}>
          {TEXT.export}
        </button>
      </div>
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




