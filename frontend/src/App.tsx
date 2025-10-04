import { NavLink, Outlet, Route, Routes } from "react-router-dom"
import UploadPage from "./pages/UploadPage"
import QueuePage from "./pages/QueuePage"
import BatchRouter from "./pages/batch/BatchRouter"

const Shell = () => {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">LOGOS Console</div>
        <nav className="nav">
          <NavLink to="/" className={({ isActive }) => `nav-link${isActive ? " is-active" : ""}`} end>
            Загрузка
          </NavLink>
          <NavLink to="/queue" className={({ isActive }) => `nav-link${isActive ? " is-active" : ""}`}>
            Очередь
          </NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}

const App = () => {
  return (
    <Routes>
      <Route path="/" element={<Shell />}>
        <Route index element={<UploadPage />} />
        <Route path="queue" element={<QueuePage />} />
        <Route path="queue/:batchId/*" element={<BatchRouter />} />
      </Route>
    </Routes>
  )
}

export default App
