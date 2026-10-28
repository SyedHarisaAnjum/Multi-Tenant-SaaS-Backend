import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { ErrorBox } from "../components/States";
import { useAuth } from "../hooks/useAuth";
import { AuthLayout } from "../layouts/AuthLayout";
import { invitations } from "../services/endpoints";

export function AcceptInvitationPage() {
  const [params] = useSearchParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [token, setToken] = useState(params.get("token") ?? "");

  const accept = useMutation({
    mutationFn: () => invitations.accept(token.trim()),
    onSuccess: (org) => {
      void queryClient.invalidateQueries({ queryKey: ["orgs"] });
      navigate(`/orgs/${org.id}`, { replace: true });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    accept.mutate();
  };

  return (
    <AuthLayout title="Accept an invitation">
      <p className="muted small">
        Signed in as <strong>{user?.email}</strong>. The invitation must have been sent to this
        address.
      </p>
      <form className="form" onSubmit={submit}>
        <label>
          Invitation token
          <input required value={token} onChange={(e) => setToken(e.target.value)} />
        </label>
        {accept.isError && <ErrorBox error={accept.error} />}
        <button type="submit" className="btn btn-primary" disabled={accept.isPending}>
          {accept.isPending ? "Joining…" : "Join organization"}
        </button>
      </form>
      <p className="small">
        <Link to="/orgs">Back to your organizations</Link>
      </p>
    </AuthLayout>
  );
}
