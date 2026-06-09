// App.jsx — MODIFIED
// Changes:
//   1. Import ProtectedRoute, LoginPage, SignupPage
//   2. /login and /signup render OUTSIDE <Layout> (full-screen auth pages)
//   3. All existing dashboard routes wrapped with <ProtectedRoute>
//   4. All existing routes, Layout, and structure are preserved exactly.

import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";

import LoginPage from "./pages/LoginPage";
import SignupPage from "./pages/SignupPage";

import Projects from "./pages/Projects";
import Overview from "./pages/Overview";
import Runs from "./pages/Runs";
import Providers from "./pages/Providers";
import History from "./pages/History";
import Orchestration from "./pages/Orchestration";

function DashboardRoutes() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Projects />} />
        <Route
          path="/projects/:projectId"
          element={<Navigate to="overview" replace />}
        />
        <Route path="/projects/:projectId/overview" element={<Overview />} />
        <Route path="/projects/:projectId/runs" element={<Runs />} />
        <Route path="/projects/:projectId/providers" element={<Providers />} />
        <Route
          path="/projects/:projectId/orchestration"
          element={<Orchestration />}
        />
        <Route path="/projects/:projectId/history" element={<History />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />

      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <DashboardRoutes />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}
