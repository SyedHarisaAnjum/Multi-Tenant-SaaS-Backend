import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { RoleBadge } from "../components/Badges";
import { Empty, ErrorBox, Loading } from "../components/States";
import { useAuth } from "../hooks/useAuth";
import { organizations } from "../services/endpoints";
import { slugify } from "../services/format";

export function OrgSelectorPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const orgs = useQuery({ queryKey: ["orgs"], queryFn: organizations.list });

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);

  const create = useMutation({
    mutationFn: () => organizations.create({ name, slug }),
    onSuccess: (org) => {
      void queryClient.invalidateQueries({ queryKey: ["orgs"] });
      navigate(`/orgs/${org.id}`);
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };

  return (
    <main className="narrow-shell">
      <header className="topbar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={24} height={24} />
          TeamFlow
        </div>
        <div className="row">
          <span className="muted small">{user?.email}</span>
          <button type="button" className="btn btn-small" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      </header>

      <section className="card">
        <h1>Your organizations</h1>
        {orgs.isPending ? (
          <Loading />
        ) : orgs.isError ? (
          <ErrorBox error={orgs.error} onRetry={() => orgs.refetch()} />
        ) : orgs.data.length === 0 ? (
          <Empty title="You're not in any organization yet.">
            Create one below, or <Link to="/invitations/accept">accept an invitation</Link>.
          </Empty>
        ) : (
          <ul className="list">
            {orgs.data.map((org) => (
              <li key={org.id}>
                <Link to={`/orgs/${org.id}`} className="list-link">
                  <span>
                    <strong>{org.name}</strong> <span className="muted small">/{org.slug}</span>
                  </span>
                  <RoleBadge role={org.role} />
                </Link>
              </li>
            ))}
          </ul>
        )}
        <p className="small">
          Have an invitation? <Link to="/invitations/accept">Accept it here</Link>
        </p>
      </section>

      <section className="card">
        <h2>Create an organization</h2>
        <form className="form" onSubmit={submit}>
          <label>
            Name
            <input
              required
              maxLength={200}
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (!slugEdited) setSlug(slugify(e.target.value));
              }}
            />
          </label>
          <label>
            URL slug
            <input
              required
              minLength={3}
              maxLength={100}
              pattern="[a-z0-9]+(-[a-z0-9]+)*"
              value={slug}
              onChange={(e) => {
                setSlug(e.target.value);
                setSlugEdited(true);
              }}
            />
            <span className="hint">Lowercase letters, digits and single hyphens.</span>
          </label>
          {create.isError && <ErrorBox error={create.error} />}
          <button type="submit" className="btn btn-primary" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create organization"}
          </button>
        </form>
      </section>
    </main>
  );
}
