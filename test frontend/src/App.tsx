import { Navigate, Route, Routes } from "react-router-dom";

import AppShell from "./components/layout/AppShell";
import { HistoryProvider } from "./contexts/history-context";
import FeedbackPage from "./pages/FeedbackPage";
import HistoryPage from "./pages/HistoryPage";
import NewPacketPage from "./pages/NewPacketPage";
import QueuePage from "./pages/QueuePage";
import ResolvePage from "./pages/ResolvePage";
import SummaryTablePage from "./pages/SummaryTablePage";

function App() {
  return (
    <HistoryProvider>
      <AppShell>
        <Routes>
          <Route path="/" element={<Navigate to="/new" replace />} />
          <Route path="/new" element={<NewPacketPage />} />
          <Route path="/queue" element={<QueuePage />} />
          <Route path="/resolve/:batchId" element={<ResolvePage />} />
          <Route path="/resolve/:batchId/:docIndex" element={<ResolvePage />} />
          <Route path="/table/:batchId" element={<SummaryTablePage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/feedback" element={<FeedbackPage />} />
          <Route path="*" element={<Navigate to="/new" replace />} />
        </Routes>
      </AppShell>
    </HistoryProvider>
  );
}

export default App;
