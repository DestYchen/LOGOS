import { Navigate, Route, Routes } from "react-router-dom";

import AppShell from "./components/layout/AppShell";
import BatchDetailPage from "./pages/BatchDetailPage";
import BatchListPage from "./pages/BatchListPage";
import UploadPage from "./pages/UploadPage";

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Navigate to="/upload" replace />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/batches" element={<BatchListPage />} />
        <Route path="/batches/:batchId" element={<BatchDetailPage />} />
        <Route path="*" element={<Navigate to="/upload" replace />} />
      </Routes>
    </AppShell>
  );
}

export default App;
