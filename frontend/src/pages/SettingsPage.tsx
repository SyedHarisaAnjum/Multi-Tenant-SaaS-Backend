import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router";

import { ErrorBox } from "../components/States";
import { useAuth } from "../hooks/useAuth";
import { can, useMembers, useOrg } from "../hooks/useOrg";
import { members, organizations } from "../services/endpoints";
import type { Organization } from "../types/api";

export function SettingsPage() {
  const { org } = useOrg();
  if (!org) return null;
  const perms = can(org.role);
  return (
    <div className="page">
      <h1>Settings</h1>
      <OrganizationDetails org={org} editable={perms.manage} />
      {perms.own ? <TransferOwnership org={org} /> : <LeaveOrganization org={org} />}
    </div>
  );
}

function OrganizationDetails({ org, editable }: { org: Organization; editable: boolean }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(org.name);
  const [slug, setSlug] = useState(org.slug);
  const save = useMutation({
    mutationFn: () => organizations.update(org.id, { name, slug }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["org", org.id], updated);
      void queryClient.invalidateQueries({ queryKey: ["orgs"] });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  return (
    <section className="card">
      <h2>Organization details</h2>
      <form className="form" onSubmit={submit}>
        <fieldset disabled={!editable || save.isPending}>
          <label>
            Name
            <input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            URL slug
            <input
              required
              minLength={3}
              maxLength={100}
              pattern="[a-z0-9]+(-[a-z0-9]+)*"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
            />
          </label>
        </fieldset>
        {save.isError && <ErrorBox error={save.error} />}
        {save.isSuccess && <div className="alert alert-info">Saved.</div>}
        {editable ? (
          <div>
            <button type="submit" className="btn btn-primary" disabled={save.isPending}>
              Save
            </button>
          </div>
        ) : (
          <p className="muted small">Only owners and admins can change these settings.</p>
        )}
      </form>
    </section>
  );
}

function TransferOwnership({ org }: { org: Organization }) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const list = useMembers(org.id);
  const [target, setTarget] = useState("");
  const transfer = useMutation({
    mutationFn: () => organizations.transferOwnership(org.id, target),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["org", org.id] });
      void queryClient.invalidateQueries({ queryKey: ["members", org.id] });
      void queryClient.invalidateQueries({ queryKey: ["orgs"] });
    },
  });
  const candidates = list.data?.filter((m) => m.user_id !== user?.id) ?? [];
  return (
    <section className="card danger-zone">
      <h2>Transfer ownership</h2>
      <p className="muted small">The new owner gets full control. You become an admin.</p>
      <div className="inline-form">
        <select aria-label="New owner" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">Choose a member</option>
          {candidates.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.full_name || m.email} ({m.role})
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-danger"
          disabled={!target || transfer.isPending}
          onClick={() => {
            if (confirm("Transfer ownership? You can't undo this yourself.")) transfer.mutate();
          }}
        >
          Transfer
        </button>
      </div>
      {transfer.isError && <ErrorBox error={transfer.error} />}
    </section>
  );
}

function LeaveOrganization({ org }: { org: Organization }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const leave = useMutation({
    mutationFn: () => members.remove(org.id, user!.id),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["org", org.id] });
      void queryClient.invalidateQueries({ queryKey: ["orgs"] });
      navigate("/orgs", { replace: true });
    },
  });
  return (
    <section className="card danger-zone">
      <h2>Leave organization</h2>
      <p className="muted small">You'll lose access immediately. An admin can invite you again.</p>
      <button
        type="button"
        className="btn btn-danger"
        disabled={leave.isPending}
        onClick={() => {
          if (confirm(`Leave ${org.name}?`)) leave.mutate();
        }}
      >
        Leave {org.name}
      </button>
      {leave.isError && <ErrorBox error={leave.error} />}
    </section>
  );
}
