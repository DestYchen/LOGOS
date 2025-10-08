import { useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import pdfIcon from "../../assets/pdf_icon.png"
import wordIcon from "../../assets/word_icon.png"
import excelIcon from "../../assets/excel_icon.png"
import otherIcon from "../../assets/other_icon.png"
import { fetchBatchSummary, mapBatchStatus } from "../../api/client"
import type { BatchSummary } from "../../api/types"

const iconMap = {
  pdf: pdfIcon,
  word: wordIcon,
  excel: excelIcon,
  other: otherIcon,
} as const

const iconForName = (filename: string) => {
  const lower = filename.toLowerCase()
  if (lower.endsWith(".pdf")) return iconMap.pdf
  if (lower.endsWith(".doc") || lower.endsWith(".docx")) return iconMap.word
  if (lower.endsWith(".xls") || lower.endsWith(".xlsx") || lower.endsWith(".csv")) return iconMap.excel
  return iconMap.other
}

const DraftView = ({ batch }: { batch: BatchSummary }) => {
  const navigate = useNavigate()
  return (
    <div className="panel">
      <h2>Черновик пакета</h2>
      <p className="muted">Пакет ещё не отправлен в очередь. Можно продолжить загрузку документов и запустить обработку.</p>
      <div className="file-grid compact">
        {batch.documents.map((doc) => (
          <div key={doc.id} className="file-item">
            <img src={iconForName(doc.filename)} alt="" className="file-icon" />
            <span className="file-name">{doc.filename}</span>
          </div>
        ))}
        {batch.documents.length === 0 && <span className="muted">Документы пока не добавлены</span>}
      </div>
      <div className="btn-row" style={{ marginTop: 16 }}>
        <button className="btn-primary" type="button" onClick={() => navigate(`/?batch=${batch.id}`)}>
          Продолжить загрузку
        </button>
        <Link to="/queue" className="btn-secondary">
          Назад в очередь
        </Link>
      </div>
    </div>
  )
}

const WaitingView = ({ batch, title }: { batch: BatchSummary; title: string }) => {
  return (
    <div className="panel">
      <h2>{title}</h2>
      <p className="muted">Пакет стоит в очереди или уже отправлен на обработку. Следите за статусом — страница обновляется автоматически.</p>
      <div className="processing-stage">
        <div className="timer-box">
          <div className="timer-value">--:--</div>
          <div className="timer-label">Примерное ожидание</div>
        </div>
        <div className="placeholder-poster">Графика в разработке</div>
      </div>
      <div className="doc-list">
        {batch.documents.map((doc) => (
          <div key={doc.id} className="doc-row">
            <img src={iconForName(doc.filename)} alt="" />
            <div>
              <div className="doc-row-title">{doc.filename}</div>
              <div className="doc-row-meta">Статус: {doc.status}</div>
            </div>
          </div>
        ))}
      </div>
      <Link to="/queue" className="btn-secondary" style={{ marginTop: 24, alignSelf: "flex-start" }}>
        Вернуться в очередь
      </Link>
    </div>
  )
}

const ManualView = ({ batch }: { batch: BatchSummary }) => {
  return (
    <div className="panel">
      <h2>Требуется ручная разметка</h2>
      <p className="muted">Некоторые поля нуждаются в подтверждении. Здесь появится полноценная страница ручной разметки.</p>
      <div className="doc-list">
        {batch.documents.map((doc) => (
          <div key={doc.id} className="doc-row">
            <img src={iconForName(doc.filename)} alt="" />
            <div>
              <div className="doc-row-title">{doc.filename}</div>
              <div className="doc-row-meta">Тип: {doc.doc_type}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="btn-row" style={{ marginTop: 20 }}>
        <button className="btn-primary" type="button" disabled>
          Открыть разметку (скоро)
        </button>
        <Link to="/queue" className="btn-secondary">
          Назад в очередь
        </Link>
      </div>
    </div>
  )
}

const DeletingView = ({ batch }: { batch: BatchSummary }) => {
  return (
    <div className="panel">
      <h2>Удаление партии</h2>
      <p className="muted">Партия {batch.id} помечена на удаление. Обновите очередь позже, чтобы убедиться, что она исчезла из списка.</p>
      <Link to="/queue" className="btn-secondary" style={{ marginTop: 16, alignSelf: "flex-start" }}>
        Вернуться к очереди
      </Link>
    </div>
  )
}

const CancelledView = ({ batch }: { batch: BatchSummary }) => {
  return (
    <div className="panel">
      <h2>Партия удалена</h2>
      <p className="muted">Данные партии {batch.id} удалены и больше недоступны.</p>
      <Link to="/queue" className="btn-secondary" style={{ marginTop: 16, alignSelf: "flex-start" }}>
        Вернуться к очереди
      </Link>
    </div>
  )
}

const ResultView = ({ batch }: { batch: BatchSummary }) => {
  return (
    <div className="panel">
      <h2>Результаты</h2>
      <p className="muted">Итоговая информация по пакету. Позже здесь появится таблица с полями и отчёт.</p>
      <table className="results-table" style={{ marginTop: 12 }}>
        <thead>
          <tr>
            <th>Файл</th>
            <th>Тип</th>
            <th>Статус</th>
          </tr>
        </thead>
        <tbody>
          {batch.documents.map((doc) => (
            <tr key={doc.id}>
              <td>{doc.filename}</td>
              <td>{doc.doc_type}</td>
              <td>{doc.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Link to="/queue" className="btn-secondary" style={{ marginTop: 24, alignSelf: "flex-start" }}>
        Вернуться в очередь
      </Link>
    </div>
  )
}

const BatchRouter = () => {
  const { batchId } = useParams()
  const [batch, setBatch] = useState<BatchSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!batchId) return
    const load = async () => {
      try {
        setLoading(true)
        const summary = await fetchBatchSummary(batchId)
        setBatch(summary)
        setError(null)
      } catch (err) {
        console.error(err)
        setError("Не удалось загрузить пакет. Возможно, его не существует или доступ ограничен.")
      } finally {
        setLoading(false)
      }
    }
    load().catch(() => undefined)
  }, [batchId])

  if (loading) {
    return (
      <div className="screen">
        <div className="callout info">Загружаем пакет...</div>
      </div>
    )
  }

  if (error || !batch) {
    return (
      <div className="screen">
        <div className="callout error">{error ?? "Пакет не найден"}</div>
        <Link to="/queue" className="btn-secondary" style={{ marginTop: 16, alignSelf: "flex-start" }}>
          Вернуться в очередь
        </Link>
      </div>
    )
  }

  const uiStatus = mapBatchStatus(batch.status)

  if (uiStatus === "draft") return <DraftView batch={batch} />
  if (uiStatus === "waiting") return <WaitingView batch={batch} title="Пакет ожидает обработки" />
  if (uiStatus === "processing") return <WaitingView batch={batch} title="Пакет обрабатывается" />
  if (uiStatus === "manual") return <ManualView batch={batch} />
  if (uiStatus === "done") return <ResultView batch={batch} />
  if (uiStatus === "deleting") return <DeletingView batch={batch} />
  if (uiStatus === "cancelled") return <CancelledView batch={batch} />

  return (
    <div className="screen">
      <div className="panel">
        <h2>Пакет завершился с ошибкой</h2>
        <p className="muted">Нужно посмотреть логи обработки и повторить попытку. Страница ошибок появится позже.</p>
        <Link to="/queue" className="btn-secondary" style={{ marginTop: 16, alignSelf: "flex-start" }}>
          Вернуться в очередь
        </Link>
      </div>
    </div>
  )
}

export default BatchRouter
