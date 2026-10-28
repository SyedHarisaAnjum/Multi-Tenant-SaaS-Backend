import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";

import { ErrorBox } from "../components/States";
import { useAuth } from "../hooks/useAuth";
import { AuthLayout } from "../layouts/AuthLayout";

/** Only same-app paths: never redirect to an attacker-supplied absolute URL. */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/orgs";
}

export function LoginPage() {
  const { status, login, sessionExpired } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  if (status === "authenticated") return <Navigate to={next} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
      navigate(next, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout title="Sign in">
      {sessionExpired && !error && (
        <div className="alert alert-info">Your session expired. Please sign in again.</div>
      )}
      {params.get("registered") && !error && (
        <div className="alert alert-info">Account created. You can sign in now.</div>
      )}
      <form onSubmit={submit} className="form">
        <label>
          Email
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error !== null && <ErrorBox error={error} />}
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="muted small">
        No account? <Link to="/register">Create one</Link>
      </p>
    </AuthLayout>
  );
}
