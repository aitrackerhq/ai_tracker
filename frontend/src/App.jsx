import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import Projects from "./pages/Projects";
import Overview from "./pages/Overview";
import Runs from "./pages/Runs";
import Providers from "./pages/Providers";
import History from "./pages/History";
import Orchestration from "./pages/Orchestration";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Projects />} />
        <Route path="/projects/:projectId" element={<Navigate to="overview" replace />} />
        <Route path="/projects/:projectId/overview" element={<Overview />} />
        <Route path="/projects/:projectId/runs" element={<Runs />} />
        <Route path="/projects/:projectId/providers" element={<Providers />} />
        <Route path="/projects/:projectId/orchestration" element={<Orchestration />} />
        <Route path="/projects/:projectId/history" element={<History />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
