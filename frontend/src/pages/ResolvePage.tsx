import { useCallback, useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import DocumentViewer, { type ViewerBox } from "../components/resolve/DocumentViewer"
import { useBatchStore } from "../state/batch-store"
import { completeReview, deleteDocument, fetchReview, setDocumentType, updateReviewField } from "../api/client"
import type { BatchSummary, DocumentSummary, DocumentType, ReviewField, ReviewResponse } from "../api/types"
import { prettifyFieldKey } from "../utils/field-label"
import { buildPreviewCandidates, getPrimaryPreview } from "../utils/preview"

const TEXT = {
  title: "\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442 \u2014 \u0438\u0441\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u043e\u0448\u0438\u0431\u043e\u043a",
  subtitle:
    "\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0442\u0438\u043f \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430, \u0437\u0430\u043f\u043e\u043b\u043d\u0438\u0442\u0435 \u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u044b\u0435 \u043f\u043e\u043b\u044f \u0438 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0435 \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u044f \u0441 \u043d\u0438\u0437\u043a\u043e\u0439 \u0443\u0432\u0435\u0440\u0435\u043d\u043d\u043e\u0441\u0442\u044c\u044e.",
  progressLabel: "\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442",
  noBatch: "\u041f\u0430\u043a\u0435\u0442 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d \u0438\u043b\u0438 \u043d\u0435 \u0433\u043e\u0442\u043e\u0432 \u043a \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0435.",
  loadError: "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0434\u0430\u043d\u043d\u044b\u0435 \u0434\u043b\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438.",
  loading: "\u0413\u043e\u0442\u043e\u0432\u0438\u043c \u0431\u043b\u043e\u043a \u0434\u043b\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438\u2026",
  typeCardTitle: "\u041d\u0443\u0436\u043d\u043e \u0443\u043a\u0430\u0437\u0430\u0442\u044c \u0442\u0438\u043f \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430",
  typeCardHint:
    "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043d\u0443\u0436\u043d\u0443\u044e \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044e, \u0447\u0442\u043e\u0431\u044b \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u043e \u0440\u0430\u0441\u043f\u043e\u0437\u043d\u0430\u0442\u044c \u0434\u0430\u043d\u043d\u044b\u0435.",
  selectPlaceholder: "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0442\u0438\u043f",
  deleteDoc: "\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442",
  saveAndRecalc: "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u0438 \u043f\u0435\u0440\u0435\u0441\u0447\u0438\u0442\u0430\u0442\u044c",
  recalcProgress: "\u041f\u0435\u0440\u0435\u0441\u0447\u0451\u0442 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430\u2026",
  missingTitle: "\u041e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u044b\u0435 \u043f\u043e\u043b\u044f",
  missingHint:
    "\u0417\u0430\u043f\u043e\u043b\u043d\u0438\u0442\u0435 \u0432\u0435\u0441\u044c \u043f\u0435\u0440\u0435\u0447\u0435\u043d\u044c, \u0447\u0442\u043e\u0431\u044b \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c.",
  showOnDoc: "\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u043d\u0430 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0435",
  saveAndContinue: "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u0438 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c",
  missingError: "\u0417\u0430\u043f\u043e\u043b\u043d\u0438\u0442\u0435 \u0432\u0441\u0435 \u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u044b\u0435 \u043f\u043e\u043b\u044f.",
  lowTitle: "\u041f\u043e\u043b\u044f \u0441 \u043d\u0438\u0437\u043a\u043e\u0439 \u0443\u0432\u0435\u0440\u0435\u043d\u043d\u043e\u0441\u0442\u044c\u044e",
  confirm: "\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u044c",
  edit: "\u0418\u0437\u043c\u0435\u043d\u0438\u0442\u044c",
  save: "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c",
  cancel: "\u041e\u0442\u043c\u0435\u043d\u0430",
  allFields: "\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u0432\u0441\u0435 \u043f\u043e\u043b\u044f",
  hideFields: "\u0421\u043a\u0440\u044b\u0442\u044c \u0432\u0441\u0435 \u043f\u043e\u043b\u044f",
  allResolvedTitle: "\u0412\u0441\u0435 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u044b \u043f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043b\u0435\u043d\u044b",
  allResolvedHint:
    "\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0441\u043f\u0438\u0441\u043e\u043a \u0438 \u043e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u043d\u0430 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443.",
  sendForCheck: "\u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u043d\u0430 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443",
  confirmDelete:
    "\u0412\u044b \u0442\u043e\u0447\u043d\u043e \u0445\u043e\u0442\u0438\u0442\u0435 \u0443\u0434\u0430\u043b\u0438\u0442\u044c \u044d\u0442\u043e\u0442 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442?",
  deleteError: "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0443\u0434\u0430\u043b\u0438\u0442\u044c \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442.",
  updateError: "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0431\u043d\u043e\u0432\u0438\u0442\u044c \u043f\u043e\u043b\u0435.",
  typeError: "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0434\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0442\u0438\u043f \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430.",
  finalizing: "\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u044f\u0435\u043c \u043f\u0430\u043a\u0435\u0442 \u043d\u0430 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443\u2026",
}

const DOC_TYPE_OPTIONS: Array<{ value: DocumentType; label: string }> = [
  { value: "EXPORT_DECLARATION", label: "\u042d\u043a\u0441\u043f\u043e\u0440\u0442\u043d\u0430\u044f \u0434\u0435\u043a\u043b\u0430\u0440\u0430\u0446\u0438\u044f" },
  { value: "INVOICE", label: "\u0421\u0447\u0451\u0442-\u0444\u0430\u043a\u0442\u0443\u0440\u0430" },
  { value: "PACKING_LIST", label: "\u0423\u043f\u0430\u043a\u043e\u0432\u043e\u0447\u043d\u044b\u0439 \u043b\u0438\u0441\u0442" },
  { value: "BILL_OF_LANDING", label: "\u041a\u043e\u043d\u043e\u0441\u0430\u043c\u0435\u043d\u0442" },
  { value: "PROFORMA", label: "\u041f\u0440\u043e\u0444\u043e\u0440\u043c\u0430-\u0438\u043d\u0432\u043e\u0439\u0441" },
  { value: "SPECIFICATION", label: "\u0421\u043f\u0435\u0446\u0438\u0444\u0438\u043a\u0430\u0446\u0438\u044f" },
  { value: "PRICE_LIST_1", label: "\u041f\u0440\u0430\u0439\u0441-\u043b\u0438\u0441\u0442 1" },
  { value: "PRICE_LIST_2", label: "\u041f\u0440\u0430\u0439\u0441-\u043b\u0438\u0441\u0442 2" },
  { value: "QUALITY_CERTIFICATE", label: "\u0421\u0435\u0440\u0442\u0438\u0444\u0438\u043a\u0430\u0442 \u043a\u0430\u0447\u0435\u0441\u0442\u0432\u0430" },
  { value: "CERTIFICATE_OF_ORIGIN", label: "\u0421\u0435\u0440\u0442\u0438\u0444\u0438\u043a\u0430\u0442 \u043f\u0440\u043e\u0438\u0441\u0445\u043e\u0436\u0434\u0435\u043d\u0438\u044f" },
  { value: "VETERINARY_CERTIFICATE", label: "\u0412\u0435\u0442\u0435\u0440\u0438\u043d\u0430\u0440\u043d\u044b\u0439 \u0441\u0435\u0440\u0442\u0438\u0444\u0438\u043a\u0430\u0442" },
]

const fieldKeyFor = (docId: string, fieldKey: string) => `${docId}::${fieldKey}`



type ResolveDocumentState = {
  summary: DocumentSummary
  fields: ReviewField[]
  missing: ReviewField[]
  low: ReviewField[]
  needsType: boolean
  resolved: boolean
}

const ResolvePage = () => {
  const { packetId, docIndex: docIndexParam } = useParams<{ packetId: string; docIndex?: string }>()
  const navigate = useNavigate()
  const { getBatch, refreshHistory } = useBatchStore()

  const [batch, setBatch] = useState<BatchSummary | null>(null)
  const [review, setReview] = useState<ReviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const [highlightField, setHighlightField] = useState<string | null>(null)
  const [activePage, setActivePage] = useState<number>(1)
  const [draftValues, setDraftValues] = useState<Record<string, string>>({})
  const [editingField, setEditingField] = useState<string | null>(null)
  const [savingMissing, setSavingMissing] = useState(false)
  const [missingError, setMissingError] = useState<string | null>(null)
  const [confirmingField, setConfirmingField] = useState<string | null>(null)
  const [typeChoice, setTypeChoice] = useState<Record<string, DocumentType>>({})
  const [typeLoading, setTypeLoading] = useState<string | null>(null)
  const [showAllFields, setShowAllFields] = useState(false)
  const [panelMessage, setPanelMessage] = useState<string | null>(null)
  const [finalizing, setFinalizing] = useState(false)

  const loadData = useCallback(
    async (targetId: string) => {
      setLoading(true)
      try {
        const summary = await getBatch(targetId, true)
        if (!summary) {
          setBatch(null)
          setReview(null)
          setError(TEXT.noBatch)
          return
        }

        if (summary.status === "VALIDATED" || summary.status === "DONE") {
          navigate(`/table/${summary.id}`)
          return
        }

        if (summary.status === "FILLED_AUTO" && summary.documents.some((doc) => doc.status === "FILLED_AUTO")) {
          navigate(`/resolve/${summary.id}`)
        }

        let reviewPayload: ReviewResponse | null = null
        try {
          reviewPayload = await fetchReview(summary.id)
        } catch (err) {
          console.error(err)
          setError(TEXT.loadError)
          return
        }

        setBatch(summary)
        setReview(reviewPayload)
        setError(null)
        setPanelMessage(null)
        setTypeChoice((current) => {
          const next = { ...current }
          for (const doc of summary.documents) {
            if (!(doc.id in next)) {
              next[doc.id] = doc.doc_type
            }
          }
          return next
        })
      } catch (err) {
        console.error(err)
        setError(TEXT.loadError)
      } finally {
        setLoading(false)
      }
    },
    [getBatch, navigate],
  )
  useEffect(() => {
    if (!packetId) return
    loadData(packetId).catch(() => undefined)
  }, [packetId, loadData])

  const documents = useMemo<ResolveDocumentState[]>(() => {
    if (!batch || !review) return []
    const fieldsByDoc = new Map<string, ReviewField[]>()
    for (const field of review.fields) {
      const bucket = fieldsByDoc.get(field.doc_id) ?? []
      bucket.push(field)
      fieldsByDoc.set(field.doc_id, bucket)
    }
    const threshold = review.low_conf_threshold
    return batch.documents.map<ResolveDocumentState>((doc) => {
      const docFields = (fieldsByDoc.get(doc.id) ?? []).slice().sort((a, b) => a.field_key.localeCompare(b.field_key))
      const missing = docFields.filter(
        (field) => field.required && (field.value === null || field.value === undefined || field.value === ""),
      )
      const low = docFields.filter(
        (field) =>
          !missing.includes(field) &&
          field.value !== null &&
          field.value !== undefined &&
          field.value !== "" &&
          field.confidence < threshold,
      )
      const needsType = doc.doc_type === "UNKNOWN"
      const resolved = !needsType && missing.length === 0 && low.length === 0
      return {
        summary: doc,
        fields: docFields,
        missing,
        low,
        needsType,
        resolved,
      }
    })
  }, [batch, review])

  useEffect(() => {
    if (!documents.length) return
    if (docIndexParam) {
      const parsed = Number(docIndexParam)
      if (!Number.isNaN(parsed) && parsed > 0) {
        const normalized = Math.min(documents.length - 1, Math.max(0, parsed - 1))
        setActiveIndex(normalized)
        return
      }
    }
    const firstIssue = documents.findIndex((doc) => !doc.resolved)
    const fallback = firstIssue === -1 ? 0 : firstIssue
    setActiveIndex((current) => (current >= documents.length ? documents.length - 1 : fallback))
  }, [documents, docIndexParam])

  useEffect(() => {
    setHighlightField(null)
    setActivePage(1)
    setEditingField(null)
    setMissingError(null)
  }, [activeIndex])

  const activeDocState = documents[activeIndex]
  const allResolved = documents.length > 0 && documents.every((doc) => doc.resolved)

  const goToDoc = useCallback(
    (index: number) => {
      if (!packetId || !documents.length) return
      const safeIndex = Math.min(documents.length - 1, Math.max(0, index))
      setActiveIndex(safeIndex)
      navigate(`/resolve/${packetId}/${safeIndex + 1}`, { replace: true })
    },
    [documents.length, navigate, packetId],
  )

  const refresh = useCallback(async () => {
    if (!packetId) return
    await loadData(packetId)
  }, [loadData, packetId])

  const handleTypeChange = (docId: string, value: DocumentType) => {
    setTypeChoice((current) => ({ ...current, [docId]: value }))
  }

  const handleTypeApply = async (docId: string) => {
    const choice = typeChoice[docId]
    if (!packetId || !choice) return
    try {
      setTypeLoading(docId)
      await setDocumentType(docId, choice)
      await refresh()
      await refreshHistory()
    } catch (err) {
      console.error(err)
      setPanelMessage(TEXT.typeError)
    } finally {
      setTypeLoading(null)
    }
  }

  const handleDelete = async (docId: string) => {
    if (!packetId) return
    if (!window.confirm(TEXT.confirmDelete)) return
    try {
      await deleteDocument(docId)
      await refresh()
      await refreshHistory()
      setPanelMessage(null)
      if (activeIndex >= documents.length - 1) {
        goToDoc(documents.length - 2 >= 0 ? documents.length - 2 : 0)
      }
    } catch (err) {
      console.error(err)
      setPanelMessage(TEXT.deleteError)
    }
  }

  const handleMissingSave = async () => {
    if (!activeDocState || !packetId) return
    if (!activeDocState.missing.length) return
    const pending = activeDocState.missing.map((field) => {
      const key = fieldKeyFor(activeDocState.summary.id, field.field_key)
      const draft = draftValues[key]
      return { field, value: draft }
    })
    const hasEmpty = pending.some((item) => item.value === undefined || item.value === null || item.value.trim() === "")
    if (hasEmpty) {
      setMissingError(TEXT.missingError)
      return
    }
    setMissingError(null)
    setSavingMissing(true)
    try {
      await Promise.all(
        pending.map((item) =>
          updateReviewField(item.field.doc_id, item.field.field_key, { value: item.value.trim() || null }),
        ),
      )
      setReview((current) => {
        if (!current) return current
        return {
          ...current,
          fields: current.fields.map((field) => {
            const match = pending.find(
              (item) => item.field.doc_id === field.doc_id && item.field.field_key === field.field_key,
            )
            if (!match) return field
            return {
              ...field,
              value: match.value.trim(),
              confidence: 1,
              source: "user",
            }
          }),
        }
      })
      setDraftValues((current) => {
        const next = { ...current }
        for (const item of pending) {
          delete next[fieldKeyFor(item.field.doc_id, item.field.field_key)]
        }
        return next
      })
      setPanelMessage(null)
      const afterRefresh = documents[activeIndex]
      if (afterRefresh && afterRefresh.low.length === 0 && !afterRefresh.needsType) {
        goToDoc(activeIndex + 1)
      } else {
        await refresh()
      }
    } catch (err) {
      console.error(err)
      setPanelMessage(TEXT.updateError)
    } finally {
      setSavingMissing(false)
    }
  }
  const handleFieldConfirm = async (field: ReviewField) => {
    const key = fieldKeyFor(field.doc_id, field.field_key)
    try {
      setConfirmingField(key)
      await updateReviewField(field.doc_id, field.field_key, { value: field.value })
      setReview((current) => {
        if (!current) return current
        return {
          ...current,
          fields: current.fields.map((item) =>
            item.doc_id === field.doc_id && item.field_key === field.field_key
              ? { ...item, confidence: 1, source: "user" }
              : item,
          ),
        }
      })
      setPanelMessage(null)
    } catch (err) {
      console.error(err)
      setPanelMessage(TEXT.updateError)
    } finally {
      setConfirmingField(null)
    }
  }

  const handleFieldSave = async (field: ReviewField) => {
    const composite = fieldKeyFor(field.doc_id, field.field_key)
    const value = draftValues[composite]
    if (value === undefined) {
      setEditingField(null)
      return
    }
    try {
      setConfirmingField(composite)
      await updateReviewField(field.doc_id, field.field_key, { value: value.trim() })
      setReview((current) => {
        if (!current) return current
        return {
          ...current,
          fields: current.fields.map((item) =>
            item.doc_id === field.doc_id && item.field_key === field.field_key
              ? { ...item, value: value.trim(), confidence: 1, source: "user" }
              : item,
          ),
        }
      })
      setEditingField(null)
      setPanelMessage(null)
    } catch (err) {
      console.error(err)
      setPanelMessage(TEXT.updateError)
    } finally {
      setConfirmingField(null)
    }
  }

  const handleComplete = async () => {
    if (!packetId) return
    setFinalizing(true)
    try {
      await completeReview(packetId)
      await refreshHistory()
      navigate(`/table/${packetId}`)
    } catch (err) {
      console.error(err)
      setPanelMessage(TEXT.updateError)
    } finally {
      setFinalizing(false)
    }
  }

  const viewerBoxes: ViewerBox[] = useMemo(() => {
    if (!activeDocState) return []
    const candidates = showAllFields ? activeDocState.fields : [...activeDocState.missing, ...activeDocState.low]
    return candidates
      .filter((field) => Array.isArray(field.bbox) && field.bbox.length >= 4)
      .filter((field) => {
        if (!field.page) return true
        return field.page === activePage
      })
      .map((field) => {
        const key = fieldKeyFor(field.doc_id, field.field_key)
        return {
          key,
          bbox: field.bbox,
          label: prettifyFieldKey(field.field_key),
          active: highlightField === key,
        }
      })
  }, [activeDocState, activePage, highlightField, showAllFields])

  const imageCandidates =
    packetId && activeDocState ? buildPreviewCandidates(packetId, activeDocState.summary.id, activePage) : []
  const imageUrl = imageCandidates[0] ?? null

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

  if (!activeDocState) {
    return (
      <div className="page">
        <header className="page-header">
          <h1>{TEXT.title}</h1>
          <p>{TEXT.subtitle}</p>
        </header>
        <div className="callout info">{TEXT.noBatch}</div>
      </div>
    )
  }

  const docLabel = `${TEXT.progressLabel} ${activeIndex + 1} \u0438\u0437 ${documents.length}`
  return (
    <div className="page resolve-page">
      <header className="page-header">
        <h1>{TEXT.title}</h1>
        <p>{TEXT.subtitle}</p>
      </header>
      <div className="resolve-layout">
        <aside className="resolve-panel">
          <div className="resolve-progress">
            <div className="resolve-progress-label">{docLabel}</div>
            <div className="resolve-dots">
              {documents.map((doc, index) => (
                <button
                  key={doc.summary.id}
                  type="button"
                  className={`resolve-dot${index === activeIndex ? " is-active" : ""}${doc.resolved ? " is-complete" : ""}`}
                  onClick={() => goToDoc(index)}
                >
                  <span className="sr-only">{doc.summary.filename}</span>
                </button>
              ))}
            </div>
          </div>

          {activeDocState.needsType && (
            <section className={`resolve-card type-card${typeLoading === activeDocState.summary.id ? " is-loading" : ""}`}>
              <h3>{TEXT.typeCardTitle}</h3>
              <p>{TEXT.typeCardHint}</p>
              <select
                value={typeChoice[activeDocState.summary.id] ?? "UNKNOWN"}
                onChange={(event) => handleTypeChange(activeDocState.summary.id, event.target.value as DocumentType)}
              >
                <option value="UNKNOWN">{TEXT.selectPlaceholder}</option>
                {DOC_TYPE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <div className="resolve-actions">
                <button
                  type="button"
                  className="btn-danger"
                  onClick={() => handleDelete(activeDocState.summary.id)}
                  disabled={typeLoading === activeDocState.summary.id}
                >
                  {TEXT.deleteDoc}
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => handleTypeApply(activeDocState.summary.id)}
                  disabled={typeLoading === activeDocState.summary.id || (typeChoice[activeDocState.summary.id] ?? "UNKNOWN") === "UNKNOWN"}
                >
                  {TEXT.saveAndRecalc}
                </button>
              </div>
              {typeLoading === activeDocState.summary.id && <div className="resolve-loader">{TEXT.recalcProgress}</div>}
            </section>
          )}

          {!activeDocState.needsType && activeDocState.missing.length > 0 && (
            <section className="resolve-card">
              <h3>{TEXT.missingTitle}</h3>
              <p>{TEXT.missingHint}</p>
              <div className="resolve-fields">
                {activeDocState.missing.map((field) => {
                  const key = fieldKeyFor(field.doc_id, field.field_key)
                  const value = draftValues[key] ?? ""
                  return (
                    <div key={key} className="resolve-field">
                      <label htmlFor={key}>{prettifyFieldKey(field.field_key)}</label>
                      <input
                        id={key}
                        value={value}
                        onChange={(event) =>
                          setDraftValues((current) => ({ ...current, [key]: event.target.value }))
                        }
                      />
                      <div className="resolve-field-actions">
                        <button
                          type="button"
                          className="btn-ghost"
                          onClick={() => {
                            setHighlightField(key)
                            if (field.page) setActivePage(field.page)
                          }}
                        >
                          {TEXT.showOnDoc}
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
              {missingError && <div className="callout error">{missingError}</div>}
              <button
                type="button"
                className="btn-primary"
                onClick={handleMissingSave}
                disabled={savingMissing}
              >
                {TEXT.saveAndContinue}
              </button>
            </section>
          )}

          {!activeDocState.needsType && activeDocState.low.length > 0 && (
            <section className="resolve-card">
              <h3>{TEXT.lowTitle}</h3>
              <div className="resolve-low-list">
                {activeDocState.low.map((field) => {
                  const key = fieldKeyFor(field.doc_id, field.field_key)
                  const isEditing = editingField === key
                  const pendingValue = draftValues[key] ?? field.value ?? ""
                  const fieldLoading = confirmingField === key
                  return (
                    <div key={key} className={`resolve-low-item${highlightField === key ? " is-active" : ""}`}>
                      <div className="resolve-low-header">
                        <span className="resolve-low-label">{prettifyFieldKey(field.field_key)}</span>
                        <span className="resolve-low-conf">{Math.round(field.confidence * 100)}%</span>
                      </div>
                      {!isEditing && <div className="resolve-low-value">{field.value ?? "\u2014"}</div>}
                      {isEditing && (
                        <input
                          value={pendingValue}
                          onChange={(event) =>
                            setDraftValues((current) => ({ ...current, [key]: event.target.value }))
                          }
                        />
                      )}
                      <div className="resolve-field-actions">
                        <button
                          type="button"
                          className="btn-ghost"
                          onClick={() => {
                            setHighlightField(key)
                            if (field.page) setActivePage(field.page)
                          }}
                        >
                          {TEXT.showOnDoc}
                        </button>
                        {!isEditing && (
                          <button
                            type="button"
                            className="btn-ghost"
                            onClick={() => handleFieldConfirm(field)}
                            disabled={fieldLoading}
                          >
                            {TEXT.confirm}
                          </button>
                        )}
                        {!isEditing && (
                          <button type="button" className="btn-ghost" onClick={() => setEditingField(key)}>
                            {TEXT.edit}
                          </button>
                        )}
                        {isEditing && (
                          <>
                            <button
                              type="button"
                              className="btn-primary"
                              onClick={() => handleFieldSave(field)}
                              disabled={fieldLoading}
                            >
                              {TEXT.save}
                            </button>
                            <button
                              type="button"
                              className="btn-ghost"
                              onClick={() => {
                                setEditingField(null)
                                setDraftValues((current) => {
                                  const next = { ...current }
                                  delete next[key]
                                  return next
                                })
                              }}
                            >
                              {TEXT.cancel}
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>
          )}

          <section className="resolve-card">
            <button
              type="button"
              className="btn-ghost full"
              onClick={() => setShowAllFields((value) => !value)}
            >
              {showAllFields ? TEXT.hideFields : TEXT.allFields}
            </button>
            {showAllFields && (
              <div className="resolve-all-fields">
                {activeDocState.fields.map((field) => {
                  const key = fieldKeyFor(field.doc_id, field.field_key)
                  return (
                    <button
                      key={key}
                      type="button"
                      className={`resolve-all-field${highlightField === key ? " is-active" : ""}`}
                      onClick={() => {
                        setHighlightField(key)
                        if (field.page) setActivePage(field.page)
                      }}
                    >
                      <span>{prettifyFieldKey(field.field_key)}</span>
                      <span className="resolve-all-field-value">{field.value ?? "\u2014"}</span>
                    </button>
                  )
                })}
              </div>
            )}
          </section>

          {panelMessage && <div className="callout info">{panelMessage}</div>}

          {allResolved && (
            <section className="resolve-card final-card">
              <h3>{TEXT.allResolvedTitle}</h3>
              <p>{TEXT.allResolvedHint}</p>
              <div className="resolve-final-list">
                {documents.map((doc) => (
                  <div key={doc.summary.id} className="resolve-final-item">
                    <div className="resolve-final-thumbnail">
                      <img
                        src={getPrimaryPreview(packetId, doc.summary.id, 1) ?? ""}
                        alt={doc.summary.filename}
                        onError={(event) => {
                          event.currentTarget.style.visibility = "hidden"
                        }}
                      />
                    </div>
                    <div>
                      <div className="resolve-final-name">{doc.summary.filename}</div>
                      <div className="resolve-final-status">\u0413\u043e\u0442\u043e\u0432\u043e</div>
                    </div>
                  </div>
                ))}
              </div>
              <button
                type="button"
                className="btn-primary"
                onClick={handleComplete}
                disabled={finalizing}
              >
                {finalizing ? TEXT.finalizing : TEXT.sendForCheck}
              </button>
            </section>
          )}
        </aside>

        <section className="resolve-view">
          <DocumentViewer
            imageUrl={imageUrl}
            imageCandidates={imageCandidates}
            title={activeDocState.summary.filename}
            boxes={viewerBoxes}
            onHoverBox={(key) => setHighlightField(key)}
          />
          <div className="resolve-page-switcher">
            {Array.from({ length: Math.max(activeDocState.summary.pages || 1, 1) }, (_, index) => {
              const pageNumber = index + 1
              return (
                <button
                  key={pageNumber}
                  type="button"
                  className={`resolve-page-dot${pageNumber === activePage ? " is-active" : ""}`}
                  onClick={() => setActivePage(pageNumber)}
                >
                  {pageNumber}
                </button>
              )
            })}
          </div>
        </section>
      </div>
    </div>
  )
}

export default ResolvePage

