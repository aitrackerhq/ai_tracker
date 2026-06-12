// Intentionally rendered OUTSIDE <Layout> — it's a standalone full-screen page.
import { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { supabase } from "../lib/supabase";

/**
 * Creates a new user account using Supabase authentication.
 *
 * Duplicate-email behaviour:
 *   When email-confirmation is enabled, Supabase does NOT return an error for
 *   duplicate signups. Instead it returns { user: { identities: [] }, session: null }.
 *   The empty identities array is the documented signal that the email is already
 *   registered. Without this check, the UI incorrectly tells the user to check
 *   their inbox — no email ever arrives and they are stuck.
 *
 *   When email-confirmation is disabled, Supabase returns a live session for
 *   both new and returning users, so this case does not arise.
 *
 * Accepts optional pre-filled state from LoginPage:
 *   location.state.email — pre-fills the email field when navigating from login.
 */

export default function SignupPage() {
  const navigate = useNavigate();
  const location = useLocation();

  const [name, setName] = useState("");
  const [email, setEmail] = useState(location.state?.email ?? "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  // Separate state for the "already registered" case so we can render a
  // sign-in CTA rather than a generic error — safe here because the user
  // submitted this email themselves (not enumeration).
  const [alreadyExists, setAlreadyExists] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setAlreadyExists(false);
    setLoading(true);

    const { data, error: signUpError } = await supabase.auth.signUp({
      email,
      password,
      options: { data: { name } },
    });

    if (signUpError) {
      setError(signUpError.message);
      setLoading(false);
      return;
    }

    // Supabase returns identities: [] (empty array) when the email is already
    // registered and email confirmation is enabled. No error is thrown.
    if (data.user && data.user.identities?.length === 0) {
      setAlreadyExists(true);
      setLoading(false);
      return;
    }

    if (data.session) {
      // Email confirmation disabled — user is immediately logged in.
      navigate("/", { replace: true });
    } else {
      // Email confirmation enabled — send to login with a message.
      navigate("/login", {
        state: {
          message: "Check your email to confirm your account, then sign in.",
        },
      });
    }
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center px-4">
      <div className="card w-full max-w-md p-8">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-semibold text-text-primary">
            Create Account
          </h1>
          <p className="mt-2 text-sm text-text-muted">
            Start tracking AI visibility
          </p>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            {error}
          </div>
        )}

        {alreadyExists && (
          <div className="mb-4 rounded-md border border-blue-500/30 bg-blue-500/10 p-3 text-sm text-blue-300">
            <p>An account with this email already exists.</p>
            <Link
              to="/login"
              state={{ email }}
              className="mt-2 inline-block font-medium text-blue-200 hover:underline"
            >
              Sign in instead →
            </Link>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-2 block text-sm text-text-muted">Name</label>
            <input
              type="text"
              autoComplete="name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm text-text-muted">Email</label>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setAlreadyExists(false);
                setError(null);
              }}
              className="input"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm text-text-muted">
              Password
            </label>
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input"
            />
            <p className="mt-1 text-xs text-text-dim">Minimum 8 characters</p>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full"
          >
            {loading ? "Creating account..." : "Create Account"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-text-muted">
          Already have an account?{" "}
          <Link to="/login" className="text-accent hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
