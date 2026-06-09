import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

/**
 * Guards protected routes from unauthenticated access.
 *
 * Redirects unauthenticated users to the login page while preserving
 * the originally requested route for post-login navigation.
 */

export function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  // Don't flash-redirect while the session is being restored from localStorage
  if (loading) {
    return (
      <div
        style={{
          display: "flex",
          height: "100vh",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span style={{ color: "#6b7280", fontSize: "0.875rem" }}>Loading…</span>
      </div>
    );
  }

  if (!user) {
    // Preserve the intended destination so LoginPage can redirect back after login
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
}
