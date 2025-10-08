import { useCallback, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { createBatch, processBatch, uploadBatchDocuments } from "../api/client"
import UploadDropzoneCard, { type UploadDisplayItem, type UploadIcon } from "../components/upload/UploadDropzoneCard"
import { useBatchStore } from "../state/batch-store"
import wordIcon from "../assets/word_icon.png"
import pdfIcon from "../assets/pdf_icon.png"
import excelIcon from "../assets/excel_icon.png"

const MAX_FILE_SIZE_MB = 25
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
const allowedExtensions = [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt"]

const TEXT = {
  title: "\u041d\u043e\u0432\u044b\u0439 \u043f\u0430\u043a\u0435\u0442",
  subtitle:
    "\u0417\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u0435 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u044b, \u0447\u0442\u043e\u0431\u044b \u0441\u043e\u0431\u0440\u0430\u0442\u044c \u043f\u0430\u043a\u0435\u0442 \u0434\u043b\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438.",
  chooseFiles: "\u0412\u044b\u0431\u0440\u0430\u0442\u044c \u0444\u0430\u0439\u043b\u044b",
  continue: "\u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c",
  reset: "\u041e\u0447\u0438\u0441\u0442\u0438\u0442\u044c",
  emptyError: "\u0414\u043e\u0431\u0430\u0432\u044c\u0442\u0435 \u0444\u0430\u0439\u043b\u044b \u043f\u0435\u0440\u0435\u0434 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435\u043c.",
  submitError: "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u043f\u0430\u043a\u0435\u0442. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0451 \u0440\u0430\u0437.",
  dropTitle:
    "\u041f\u0435\u0440\u0435\u0442\u0430\u0449\u0438\u0442\u0435 \u0444\u0430\u0439\u043b\u044b \u0438\u043b\u0438 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 \u043d\u0430\u0436\u0430\u0442\u0438\u0435 \u0434\u043b\u044f \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438.",
  dropHintPrefix: "\u0418\u043b\u0438 ",
  dropHintSuffix:
    " \u0434\u043b\u044f \u0432\u044b\u0431\u043e\u0440\u0430 \u0438\u0437 \u043a\u043e\u043c\u043f\u044c\u044e\u0442\u0435\u0440\u0430.",
  duplicates: "\u0414\u0443\u0431\u043b\u0438\u0440\u0443\u044e\u0449\u0438\u0435\u0441\u044f \u0444\u0430\u0439\u043b\u044b \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u044b.",
  invalidType: "\u041d\u0435\u0434\u043e\u043f\u0443\u0441\u0442\u0438\u043c\u044b\u0435 \u0444\u0430\u0439\u043b\u044b \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u044b.",
  largeFilesPrefix: "\u0424\u0430\u0439\u043b\u044b \u0431\u043e\u043b\u044c\u0448\u0435 ",
  largeFilesSuffix: " \u041c\u0411 \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u044b.",
}

type FileEntry = {
  id: string
  file: File
  signature: string
}

const makeId = () => {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return `f_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

const signatureFor = (file: File) => `${file.name.toLowerCase()}::${file.size}::${file.lastModified}`

const iconForFilename = (name: string): UploadIcon => {
  const lower = name.toLowerCase()
  if (lower.endsWith(".pdf")) return "pdf"
  if (lower.endsWith(".doc") || lower.endsWith(".docx")) return "word"
  if (lower.endsWith(".xls") || lower.endsWith(".xlsx") || lower.endsWith(".csv")) return "excel"
  return "other"
}

const isAllowedExtension = (name: string) => {
  const ext = name.includes(".") ? name.substring(name.lastIndexOf(".")).toLowerCase() : ""
  return allowedExtensions.includes(ext)
}

const formatSize = (size: number) => {
  if (size >= 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} \u041c\u0411`
  }
  if (size >= 1024) {
    return `${Math.round(size / 1024)} \u041a\u0411`
  }
  return `${size} \u0431`
}

const NewPacketPage = () => {
  const navigate = useNavigate()
  const { refreshHistory } = useBatchStore()
  const [files, setFiles] = useState<FileEntry[]>([])
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const dragDepth = useRef(0)

  const resetDrag = () => {
    dragDepth.current = 0
    setDragging(false)
  }

  const handleDragEnter = () => {
    dragDepth.current += 1
    setDragging(true)
  }

  const handleDragLeave = () => {
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (dragDepth.current === 0) {
      setDragging(false)
    }
  }

  const handleAddFiles = useCallback(
    (incoming: File[]) => {
      if (busy) return
      let duplicates = 0
      let invalid = 0
      let oversize = 0
      setFiles((current) => {
        const existing = new Set(current.map((entry) => entry.signature))
        const next = [...current]
        for (const file of incoming) {
          const signature = signatureFor(file)
          if (existing.has(signature)) {
            duplicates += 1
            continue
          }
          if (!isAllowedExtension(file.name)) {
            invalid += 1
            continue
          }
          if (file.size > MAX_FILE_SIZE_BYTES) {
            oversize += 1
            continue
          }
          next.push({ id: makeId(), file, signature })
          existing.add(signature)
        }
        return next
      })

      const messages: string[] = []
      if (duplicates) messages.push(TEXT.duplicates)
      if (invalid) messages.push(TEXT.invalidType)
      if (oversize) messages.push(`${TEXT.largeFilesPrefix}${MAX_FILE_SIZE_MB}${TEXT.largeFilesSuffix}`)
      setInfo(messages.length ? messages.join(" ") : null)
      setError(null)
    },
    [busy],
  )

  const handleRemove = useCallback(
    (id: string) => {
      if (busy) return
      setFiles((current) => current.filter((item) => item.id !== id))
    },
    [busy],
  )

  const handleReset = () => {
    if (busy) return
    setFiles([])
    setInfo(null)
    setError(null)
  }

  const handleSubmit = async () => {
    if (!files.length || busy) {
      if (!files.length) {
        setError(TEXT.emptyError)
      }
      return
    }
    setBusy(true)
    setError(null)
    setInfo(null)
    try {
      const batchId = await createBatch()
      await uploadBatchDocuments(batchId, files.map((entry) => entry.file))
      await processBatch(batchId)
      await refreshHistory()
      setFiles([])
      resetDrag()
      navigate("/queue", { state: { focusBatchId: batchId } })
    } catch (err) {
      console.error(err)
      setError(TEXT.submitError)
    } finally {
      setBusy(false)
    }
  }

  const displayedItems = useMemo<UploadDisplayItem[]>(
    () =>
      files.map((entry) => ({
        id: entry.id,
        name: entry.file.name,
        sizeLabel: formatSize(entry.file.size),
        icon: iconForFilename(entry.file.name),
        removable: !busy,
      })),
    [busy, files],
  )

  const placeholder = (
    <div className="upload-illustration">
      <img src={wordIcon} alt="" className="upload-illustration-icon left" />
      <img src={pdfIcon} alt="" className="upload-illustration-icon center" />
      <img src={excelIcon} alt="" className="upload-illustration-icon right" />
      <h2 className="upload-illustration-title">{TEXT.dropTitle}</h2>
    </div>
  )

  const hint = (
    <p className="upload-illustration-hint">
      {TEXT.dropHintPrefix}
      <span className="upload-illustration-link">{TEXT.chooseFiles}</span>
      {TEXT.dropHintSuffix}
    </p>
  )

  return (
    <div className="page page-upload">
      <header className="page-header">
        <h1>{TEXT.title}</h1>
        <p>{TEXT.subtitle}</p>
      </header>
      <div className="upload-panel">
        <UploadDropzoneCard
          items={displayedItems}
          dragging={dragging}
          disabled={busy}
          placeholder={placeholder}
          hint={hint}
          onPickFiles={handleAddFiles}
          onDropFiles={(incoming) => {
            handleAddFiles(incoming)
            resetDrag()
          }}
          onRemoveItem={handleRemove}
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
        />
        <div className="upload-actions">
          <button type="button" className="btn-ghost" onClick={handleReset} disabled={busy || !files.length}>
            {TEXT.reset}
          </button>
          <button type="button" className="btn-primary" onClick={handleSubmit} disabled={busy || !files.length}>
            {TEXT.continue}
          </button>
        </div>
        {info && <div className="callout info">{info}</div>}
        {error && <div className="callout error">{error}</div>}
      </div>
    </div>
  )
}

export default NewPacketPage
