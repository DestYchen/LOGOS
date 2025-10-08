import { Navigate, Route, Routes } from "react-router-dom"
import AppLayout from "./components/AppLayout"
import NewPacketPage from "./pages/NewPacketPage"
import QueuePageV2 from "./pages/QueuePageV2"
import ResolvePage from "./pages/ResolvePage"
import SummaryTablePage from "./pages/SummaryTablePage"
import HistoryPage from "./pages/HistoryPage"

const App = () => (
  <Routes>
    <Route path="/" element={<AppLayout />}>
      <Route index element={<Navigate to="/new" replace />} />
      <Route path="new" element={<NewPacketPage />} />
      <Route path="queue" element={<QueuePageV2 />} />
      <Route path="resolve/:packetId">
        <Route index element={<ResolvePage />} />
        <Route path=":docIndex" element={<ResolvePage />} />
      </Route>
      <Route path="table/:packetId" element={<SummaryTablePage />} />
      <Route path="history" element={<HistoryPage />} />
    </Route>
  </Routes>
)

export default App

