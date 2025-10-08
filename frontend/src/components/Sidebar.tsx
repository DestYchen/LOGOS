import { NavLink, useLocation, useNavigate } from "react-router-dom"
import { useCallback } from "react"
import { useBatchStore } from "../state/batch-store"
import { UI_STATUS_LABELS } from "../constants/status"
import { routeForStatus } from "../utils/batch-routing"

const LABELS = {
  newPacket: "\u041d\u043e\u0432\u044b\u0439 \u043f\u0430\u043a\u0435\u0442",
  queue: "\u041e\u0447\u0435\u0440\u0435\u0434\u044c",
  history: "\u0418\u0441\u0442\u043e\u0440\u0438\u044f",
}

const shortDateFormatter = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "short",
})

const Sidebar = () => {
  const location = useLocation()
  const navigate = useNavigate()
  const { history, historyStatus, statusFor } = useBatchStore()

  const handleSelect = useCallback(
    (batchId: string) => {
      const batch = history.find((item) => item.id === batchId)
      if (!batch) return
      const uiStatus = statusFor(batch.status)
      const target = routeForStatus(uiStatus, batchId)
      navigate(target, { state: { focusBatchId: batchId } })
    },
    [history, navigate, statusFor],
  )

  const activeHistoryId =
    (location.state as { focusBatchId?: string } | null)?.focusBatchId ??
    history.find((batch) => location.pathname.includes(batch.id))?.id

  return (
    <aside className="app-sidebar">
      <div className="sidebar-header">
        <div className="sidebar-brand">LOGOS</div>
      </div>
      <nav className="sidebar-primary">
        <NavLink
          to="/new"
          data-variant="primary"
          className={({ isActive }) => `sidebar-link${isActive ? " is-active" : ""}`}
        >
          {LABELS.newPacket}
        </NavLink>
        <NavLink
          to="/queue"
          data-variant="secondary"
          className={({ isActive }) => `sidebar-link${isActive ? " is-active" : ""}`}
        >
          {LABELS.queue}
        </NavLink>
      </nav>
      <div className="sidebar-section">
        <div className="sidebar-section-header">
          <NavLink
            to="/history"
            data-variant="secondary"
            className={({ isActive }) => `sidebar-history-link${isActive ? " is-active" : ""}`}
          >
            {LABELS.history}
          </NavLink>
        </div>
        <div className="sidebar-history">
          {historyStatus === "loading" && <div className="sidebar-empty">{"\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430\u2026"}</div>}
          {historyStatus === "error" && <div className="sidebar-empty">{"\u041e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438"}</div>}
          {historyStatus === "idle" && history.length === 0 && <div className="sidebar-empty">{"\u041d\u0435\u0442 \u043f\u0430\u043a\u0435\u0442\u043e\u0432"}</div>}
          {history.map((batch) => {
            const uiStatus = statusFor(batch.status)
            const displayStatus = UI_STATUS_LABELS[uiStatus] ?? uiStatus
            const formattedDate = shortDateFormatter.format(new Date(batch.created_at))
            const isActive = activeHistoryId === batch.id
            return (
              <button
                key={batch.id}
                type="button"
                className={`history-item${isActive ? " is-active" : ""}`}
                onClick={() => handleSelect(batch.id)}
              >
                <div className="history-top">
                  <span className="history-name">{batch.id.slice(0, 8)}</span>
                  <span className={`status-pill status-${uiStatus}`}>{displayStatus}</span>
                </div>
                <div className="history-meta">{formattedDate}</div>
              </button>
            )
          })}
        </div>
      </div>
    </aside>
  )
}

export default Sidebar
