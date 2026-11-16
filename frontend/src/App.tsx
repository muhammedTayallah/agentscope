import { Navigate, Route, Routes } from "react-router-dom";

import { Layout, ProjectsHome } from "./components/Layout";
import { LoginPage } from "./pages/LoginPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";

export default function App() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route element={<Layout />}>
        <Route index element={<ProjectsHome />} />
        <Route path="p/:projectId/runs" element={<RunsPage />} />
        <Route path="p/:projectId/runs/:traceId" element={<RunDetailPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
