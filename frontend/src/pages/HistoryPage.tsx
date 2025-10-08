import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useBatchStore } from "../state/batch-store"
import { UI_STATUS_LABELS } from "../constants/status"
import { routeForStatus } from "../utils/batch-routing"

const TEXT = {
  title: "\u0418\u0441\u0442\u043e\u0440\u0438\u044f",
  subtitle: "\u0412\u0441\u0435 \u043f\u0430\u043a\u0435\u0442\u044b, \u0447\u0442\u043e \u043f\u0440\u043e\u0445\u043e\u0434\u0438\u043b\u0438 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0443.",
  searchPlaceholder: "\u041f\u043e\u0438\u0441\u043a \u043f\u043e ID \u0438\u043b\u0438 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u044e",
  empty: "\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u043f\u043e\u043a\u0430 \u043f\u0443\u0441\u0442\u0430",
  loading: "\u0417\u0430\u0433\u0440\u0443\u0436\u0430\u0435\u043c \u0438\u0441\u0442\u043e\u0440\u0438\u044e\u2026",
}

const shortDate = new Intl.DateTimeFormat("ru-RU", {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
})

const HistoryPage = () => {
  const navigate = useNavigate()
  const { history, historyStatus, statusFor, refreshHistory } = useBatchStore()
  const [query, setQuery] = useState("")

  const filtered = useMemo(() => {
    if (!query.trim()) return history
    const lowered = query.trim().toLowerCase()
    return history.filter((item) =>
      item.id.toLowerCase().includes(lowered) || item.documents.some((doc) => doc.filename.toLowerCase().includes(lowered)),
    )
  }, [history, query])

  return (
    <div className="page history-page">
      <header className="page-header">
        <h1>{TEXT.title}</h1>
        <p>{TEXT.subtitle}</p>
      </header>
      <div className="history-toolbar">
        <input
          type="search"
          placeholder={TEXT.searchPlaceholder}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <button type="button" className="btn-ghost" onClick={refreshHistory}>
          {"\u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c"}
        </button>
      </div>
      {historyStatus === "loading" && <div className="callout info">{TEXT.loading}</div>}
      {historyStatus === "error" && <div className="callout error">{"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0438\u0441\u0442\u043e\u0440\u0438\u044e."}</div>}
      {!history.length && historyStatus !== "loading" && <div className="callout info">{TEXT.empty}</div>}
      <div className="history-list">
        {filtered.map((item) => {
          const uiStatus = statusFor(item.status)
          const label = UI_STATUS_LABELS[uiStatus] ?? uiStatus
          return (
            <button
              key={item.id}
              type="button"
              className="history-row"
              onClick={() => navigate(routeForStatus(uiStatus, item.id))}
            >
              <div className="history-row-main">
                <h3>{item.id}</h3>
                <p>
                  {item.documents.length} {"\u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u043e\u0432"}
                </p>
              </div>
              <div className="history-row-meta">
                <span className={`status-pill status-${uiStatus}`}>{label}</span>
                <span>{shortDate.format(new Date(item.created_at))}</span>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default HistoryPage

