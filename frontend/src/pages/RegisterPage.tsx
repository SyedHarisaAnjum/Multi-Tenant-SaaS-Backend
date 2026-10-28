import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";

import { ErrorBox } from "../components/States";
import { useAuth } from "../hooks/useAuth";
import { AuthLayout } from "../layouts/AuthLayout";
import { auth } from "../services/endpoints";

const MIN_PASSWORD = 12;

export function RegisterPage() {
  const { status, login } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  if (status === "authenticated") return <Navigate to="/orgs" replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await auth.register({ email, password, full_name: fullName.trim() || undefined });
      try {
        await login(email, password);
        navigate("/orgs", { replace: true });
      } catch {
        // Account exists; let them sign in manually (e.g. if login is rate-limited).
        navigate("/login?registered=1", { replace: true });
      }
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout title="Create your account">
      <form onSubmit={submit} className="form">
        <label>
          Full name <span className="muted">(optional)</span>
          <input autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </label>
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
            autoComplete="new-password"
            required
            minLength={MIN_PASSWORD}
            maxLength={128}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <span className="hint">At least {MIN_PASSWORD} characters.</span>
        </label>
        {error !== null && <ErrorBox error={error} />}
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className="muted small">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthLayout>
  );
}
