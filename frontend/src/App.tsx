import { Navigate, Route, Routes } from "react-router-dom";

import { Layout, ProjectsHome } from "./components/Layout";
import { EvalComparePage } from "./pages/EvalComparePage";
import { EvalRunPage } from "./pages/EvalRunPage";
import { EvalsPage } from "./pages/EvalsPage";
import { LoginPage } from "./pages/LoginPage";
import { MetricsPage } from "./pages/MetricsPage";
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
        <Route path="p/:projectId/metrics" element={<MetricsPage />} />
        <Route path="p/:projectId/evals" element={<EvalsPage />} />
        <Route path="p/:projectId/evals/compare" element={<EvalComparePage />} />
        <Route path="p/:projectId/evals/:runId" element={<EvalRunPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
