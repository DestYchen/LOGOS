import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import pdfIcon from "../assets/pdf_icon.png"
import wordIcon from "../assets/word_icon.png"
import excelIcon from "../assets/excel_icon.png"
import otherIcon from "../assets/other_icon.png"
import type { BatchSummary } from "../api/types"
import { fetchBatchSummary } from "../api/client"

type SubmitMode = "draft" | "process"

const UploadPage = () => {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [busy, setBusy] = useState<SubmitMode | "loading" | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [params] = useSearchParams()
  const [draftInfo, setDraftInfo] = useState<BatchSummary | null>(null)

  const kindOf = (name: string) => {
    const lower = name.toLowerCase()
    if (lower.endsWith(".pdf")) return "pdf" as const
    if (lower.endsWith(".doc") || lower.endsWith(".docx")) return "word" as const
    if (lower.endsWith(".xls") || lower.endsWith(".xlsx") || lower.endsWith(".csv")) return "excel" as const
    return "other" as const
  }

  const iconFor = (name: string) => {
    const kind = kindOf(name)
    return kind === "pdf" ? pdfIcon : kind === "word" ? wordIcon : kind === "excel" ? excelIcon : otherIcon
  }

  const onDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDragging(true)
  }
  const onDragLeave = () => setIsDragging(false)
  const onDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDragging(false)
    if (event.dataTransfer?.files?.length) {
      setFiles((prev) => [...prev, ...Array.from(event.dataTransfer.files)])
    }
  }
  const onPick = (event: React.ChangeEvent<HTMLInputElement>) => {
    const list = event.target.files
    if (list && list.length) {
      setFiles((prev) => [...prev, ...Array.from(list)])
      event.target.value = ""
    }
  }

  const resetLocal = () => {
    setFiles([])
    setError(null)
    setMessage(null)
    setDraftInfo(null)
  }

  useEffect(() => {
    const draftId = params.get("batch")
    if (!draftId) {
      resetLocal()
      return
    }

    const load = async () => {
      try {
        setBusy("loading")
        const summary = await fetchBatchSummary(draftId)
        setDraftInfo(summary)
        setMessage(`Черновик ${draftId} восстановлен. Можно продолжить загрузку.`)
      } catch (err) {
        console.error(err)
        setError("Не удалось восстановить черновик. Попробуйте позже.")
      } finally {
        setBusy(null)
      }
    }

    load().catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params])

  const submit = async (mode: SubmitMode) => {
    setBusy(mode)
    setError(null)
    setMessage(null)
    try {
      if (!files.length && !draftInfo) {
        setError("Добавьте документы для загрузки")
        return
      }

      let batchId: string | null = draftInfo?.id ?? null
      if (!batchId) {
        const create = await fetch("/batches/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ created_by: "web-ui" }),
        })
        if (!create.ok) throw new Error("batch_create_failed")
        const payload: { batch_id: string } = await create.json()
        batchId = payload.batch_id
      }

      if (files.length) {
        const form = new FormData()
        for (const file of files) {
          form.append("files", file)
        }
        const upload = await fetch(`/batches/${batchId}/upload`, {
          method: "POST",
          body: form,
        })
        if (!upload.ok) throw new Error("upload_failed")
      }

      if (mode === "process") {
        const trigger = await fetch(`/batches/${batchId}/process`, { method: "POST" })
        if (!trigger.ok) throw new Error("process_failed")
        setMessage("Пакет отправлен в обработку и появится в очереди через несколько секунд")
      } else {
        setMessage("Черновик сохранён. Найти его можно на странице очереди")
      }

      resetLocal()
      navigate("/queue")
    } catch (err) {
      console.error(err)
      setError("Не удалось загрузить документы. Попробуйте ещё раз")
    } finally {
      setBusy(null)
    }
  }

  const placeholders = !draftInfo && files.length === 0
  const listedItems = files.length ? files.map((file) => file.name) : draftInfo?.documents.map((doc) => doc.filename) ?? []

  return (
    <div className="screen upload-screen">
      <div className="upload-grid">
        <section className="upload-card">
          <div
            className={`dz-card ${isDragging ? "is-dragging" : ""}`}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
          >
            <input ref={inputRef} id="file-input" type="file" multiple onChange={onPick} />
            {placeholders ? (
              <div className="dz-empty">
                <div className="icons-row">
                  <img src={wordIcon} alt="" className="icon-img left" />
                  <img src={pdfIcon} alt="" className="icon-img center" />
                  <img src={excelIcon} alt="" className="icon-img right" />
                </div>
                <h2 className="dz-title">
                  Перетащите документы <span className="accent-blue">Word</span>, <span className="accent-purple">Excel</span> или <span className="accent-blue">PDF</span>
                </h2>
                <p className="dz-sub">
                  или <label htmlFor="file-input" className="link">выберите файлы</label> вручную
                </p>
              </div>
            ) : (
              <div className="file-grid">
                {listedItems.map((name, index) => (
                  <div key={`${name}-${index}`} className="file-item">
                    <img src={iconFor(name)} alt="" className="file-icon" />
                    <span className="file-name">{name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="controls">
            <button className="btn-secondary" type="button" onClick={resetLocal} disabled={busy !== null}>
              Очистить
            </button>
            <button className="btn-primary" type="button" onClick={() => submit("draft")} disabled={busy !== null || (!files.length && !draftInfo)}>
              Сохранить черновик
            </button>
            <button className="btn-primary" type="button" onClick={() => submit("process")} disabled={busy !== null || (!files.length && !draftInfo)}>
              Отправить в очередь
            </button>
          </div>
          {message && <div className="callout info">{message}</div>}
          {error && <div className="callout error">{error}</div>}
        </section>
      </div>
    </div>
  )
}

export default UploadPage
