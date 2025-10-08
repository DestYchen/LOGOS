import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import pdfIcon from "../assets/pdf_icon.png"
import wordIcon from "../assets/word_icon.png"
import excelIcon from "../assets/excel_icon.png"
import otherIcon from "../assets/other_icon.png"
import { fetchQueueBatches, toQueueCard } from "../api/client"
import type { QueueCardData, UiBatchState } from "../api/types"

const iconMap = {
  pdf: pdfIcon,
  word: wordIcon,
  excel: excelIcon,
  other: otherIcon,
} as const

const statusLabels: Record<UiBatchState, { label: string; className: string }> = {
  draft: { label: "Черновик", className: "badge badge-draft" },
  waiting: { label: "Ожидает", className: "badge badge-wait" },
  processing: { label: "Обработка", className: "badge badge-processing" },
  manual: { label: "Нужно разметить", className: "badge badge-manual" },
  done: { label: "Готово", className: "badge badge-done" },
  deleting: { label: "Удаляется", className: "badge badge-deleting" },
  cancelled: { label: "Удалено", className: "badge badge-cancelled" },
  failed: { label: "Ошибка", className: "badge badge-failed" },
}

const QueuePage = () => {
  const navigate = useNavigate()
  const [items, setItems] = useState<QueueCardData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    try {
      setLoading(true)
      const batches = await fetchQueueBatches()
      setItems(batches.map(toQueueCard))
      setError(null)
    } catch (err) {
      console.error(err)
      setError("Не удалось загрузить очередь. Попробуйте обновить страницу позже.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load().catch(() => undefined)
  }, [])

  return (
    <div className="screen queue-screen">
      <div className="queue-header">
        <div>
          <h1>Очередь обработки</h1>
          <p className="muted">Последние пакеты документов. Можно открыть любой статус и продолжить работу.</p>
        </div>
        <div className="queue-actions">
          <button className="btn-secondary" type="button" onClick={load} disabled={loading}>
            Обновить
          </button>
          <Link to="/" className="btn-primary">
            Новый пакет
          </Link>
        </div>
      </div>

      {loading && <div className="callout info">Загружаем очередь...</div>}
      {error && <div className="callout error">{error}</div>}

      <div className="queue-grid">
        {items.map((item) => {
          const status = statusLabels[item.uiStatus]
          return (
            <button
              key={item.id}
              type="button"
              className="queue-card"
              onClick={() => navigate(`/queue/${item.id}`)}
            >
              <div className="qcard-top">
                <div>
                  <div className="qcard-title">{item.title}</div>
                  <div className="qcard-meta">
                    Компания: {item.company ?? "—"}
                  </div>
                </div>
                <span className={status.className}>{status.label}</span>
              </div>
              <div className="qcard-docs">
                {item.docPreview.map((doc) => (
                  <div key={doc.label} className="doc-tag">
                    <img src={iconMap[doc.icon]} alt="" />
                    <span>{doc.label}</span>
                  </div>
                ))}
                {item.docPreview.length === 0 && <span className="muted">Документы будут доступны позже</span>}
              </div>
              <div className="qcard-footer">
                <span>Обновлён: {new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" }).format(new Date(item.updated_at))}</span>
                <span>Документов: {item.documents.length}</span>
              </div>
            </button>
          )
        })}
      </div>

      {!loading && !items.length && !error && (
        <div className="callout info">Очередь пока пустая. Создайте первый пакет.</div>
      )}
    </div>
  )
}

export default QueuePage
