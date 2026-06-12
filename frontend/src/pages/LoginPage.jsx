// Intentionally rendered OUTSIDE <Layout> — it's a standalone full-screen page.
import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { supabase } from "../lib/supabase";

/**
 * Login page for AI Tracker.
 *
 * Authenticates users using Supabase email/password authentication
 * and redirects them back to their intended destination after login.
 *
 * Error handling note:
 *   Supabase intentionally returns the same "Invalid login credentials" message
 *   for both wrong-password and account-not-found cases to prevent account
 *   enumeration attacks. We do not attempt to distinguish them — the error
 *   message is kept neutral and the footer signup link serves users who
 *   don't yet have an account.
 */

/**
 * Maps raw Supabase auth error messages to user-friendly copy.
 * Falls back to a generic message for unexpected errors.
 */
function friendlyAuthError(authError) {
  switch (authError?.code) {
    case "invalid_credentials":
      return "Invalid email or password.";
    case "email_not_confirmed":
      return "Please confirm your email address before signing in. Check your inbox for a verification link.";
    case "over_request_rate_limit":
      return "Too many sign-in attempts. Please wait a moment and try again.";
    default:
      // Intentionally surface authError.message for unmapped codes.
      // Supabase auth messages are already user-readable English; this avoids
      // silently swallowing errors we haven't explicitly mapped yet (e.g.
      // email_provider_disabled, user_banned, captcha_failed). If a new code
      // needs friendlier copy, add a case above rather than masking it here.
      if (authError?.code) {
        console.warn("[LoginPage] Unmapped auth error code:", authError.code);
      }
      return authError?.message ?? "Something went wrong. Please try again.";
  }
}

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname ?? "/";
  const infoMessage = location.state?.message ?? null;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    const { error: authError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (authError) {
      setError(friendlyAuthError(authError));
      setLoading(false);
      return;
    }

    navigate(from, { replace: true });
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center px-4">
      <div className="card w-full max-w-md p-8">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-semibold text-text-primary">
            AI Tracker
          </h1>
          <p className="mt-2 text-sm text-text-muted">Sign in to continue</p>
        </div>

        {infoMessage && (
          <div className="mb-4 rounded-md border border-blue-500/30 bg-blue-500/10 p-3 text-sm text-blue-300">
            {infoMessage}
          </div>
        )}

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            {error}
          </div>
        )}

        {/* ── SSO slot ──────────────────────────────────────────────────────
            Reserved for future OAuth providers (Google, GitHub, etc.).
            When adding SSO, render provider buttons here and add the
            divider below. Remove this comment block at that point.

            <button className="btn-secondary w-full">Continue with Google</button>
            <div className="relative my-4">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-border" />
              </div>
              <div className="relative flex justify-center text-xs text-text-dim">
                <span className="bg-bg-panel px-2">or continue with email</span>
              </div>
            </div>
        ─────────────────────────────────────────────────────────────────── */}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-2 block text-sm text-text-muted">Email</label>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setError(null);
              }}
              className="input"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm text-text-muted">
              Password
            </label>
            <div className="relative">
              <input
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setError(null);
                }}
                className="input pr-10"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-text-dim hover:text-text-muted"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full"
          >
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-text-muted">
          Don't have an account?{" "}
          <Link to="/signup" className="text-accent hover:underline">
            Sign up
          </Link>
        </p>
      </div>
    </div>
  );
}
