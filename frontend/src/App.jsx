import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import Projects from "./pages/Projects";
import Overview from "./pages/Overview";
import Runs from "./pages/Runs";
import Competitors from "./pages/Competitors";
import Providers from "./pages/Providers";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Projects />} />
        <Route path="/projects/:projectId" element={<Navigate to="overview" replace />} />
        <Route path="/projects/:projectId/overview" element={<Overview />} />
        <Route path="/projects/:projectId/runs" element={<Runs />} />
        <Route path="/projects/:projectId/competitors" element={<Competitors />} />
        <Route path="/projects/:projectId/providers" element={<Providers />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
