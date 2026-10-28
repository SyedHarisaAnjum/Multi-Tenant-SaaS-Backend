import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { label, StatusBadge } from "../components/Badges";
import { Pagination } from "../components/Pagination";
import { Empty, ErrorBox, Loading } from "../components/States";
import { can, useOrg } from "../hooks/useOrg";
import { projects, workspaces } from "../services/endpoints";
import { formatDate } from "../services/format";
import { PROJECT_STATUSES } from "../types/api";
import type { ProjectStatus } from "../types/api";

const SORTS = [
  ["-created_at", "Newest"],
  ["name", "Name A–Z"],
  ["-updated_at", "Recently updated"],
  ["status", "Status"],
] as const;

export function ProjectsPage() {
  const { orgId, org } = useOrg();
  const perms = can(org?.role);
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();

  // Filters live in the URL, so they survive reloads and can be shared as links.
  const page = Number(params.get("page") ?? 1);
  const q = params.get("q") ?? "";
  const status = (params.get("status") ?? "") as ProjectStatus | "";
  const workspaceId = params.get("workspace_id") ?? "";
  const sort = params.get("sort") ?? "-created_at";
  const update = (changes: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    if (!("page" in changes)) next.delete("page");
    setParams(next, { replace: true });
  };

  const allWorkspaces = useQuery({
    queryKey: ["workspaces", orgId, { all: true }],
    queryFn: () => workspaces.list(orgId, { page_size: 100, sort: "name" }),
  });
  const workspaceName = new Map(allWorkspaces.data?.items.map((w) => [w.id, w.name]));

  const list = useQuery({
    queryKey: ["projects", orgId, { page, q, status, workspaceId, sort }],
    queryFn: () =>
      projects.list(orgId, { page, page_size: 20, q, status, workspace_id: workspaceId, sort }),
    placeholderData: keepPreviousData,
  });

  return (
    <div className="page">
      <div className="page-header">
        <h1>Projects</h1>
      </div>

      {perms.contribute && (
        <CreateProject
          orgId={orgId}
          workspaceOptions={allWorkspaces.data?.items ?? []}
          defaultWorkspace={workspaceId}
          onCreated={() => {
            void queryClient.invalidateQueries({ queryKey: ["projects", orgId] });
            void queryClient.invalidateQueries({ queryKey: ["summary", orgId] });
          }}
        />
      )}

      <section className="card">
        <div className="filters">
          <input
            type="search"
            placeholder="Search by name"
            aria-label="Search projects"
            value={q}
            onChange={(e) => update({ q: e.target.value })}
          />
          <select aria-label="Status" value={status} onChange={(e) => update({ status: e.target.value })}>
            <option value="">All statuses</option>
            {PROJECT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {label(s)}
              </option>
            ))}
          </select>
          <select
            aria-label="Workspace"
            value={workspaceId}
            onChange={(e) => update({ workspace_id: e.target.value })}
          >
            <option value="">All workspaces</option>
            {allWorkspaces.data?.items.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
          <select aria-label="Sort" value={sort} onChange={(e) => update({ sort: e.target.value })}>
            {SORTS.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        </div>

        {list.isPending ? (
          <Loading />
        ) : list.isError ? (
          <ErrorBox error={list.error} onRetry={() => list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <Empty title="No projects found.">
            {q || status || workspaceId ? "Try clearing the filters." : "Create the first project above."}
          </Empty>
        ) : (
          <>
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Workspace</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link to={p.id}>{p.name}</Link>
                    </td>
                    <td>
                      <StatusBadge status={p.status} />
                    </td>
                    <td className="muted">{workspaceName.get(p.workspace_id) ?? "—"}</td>
                    <td className="muted">{formatDate(p.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              page={list.data.page}
              totalPages={list.data.total_pages}
              total={list.data.total}
              onChange={(p) => update({ page: String(p) })}
            />
          </>
        )}
      </section>
    </div>
  );
}

interface CreateProjectProps {
  orgId: string;
  workspaceOptions: { id: string; name: string }[];
  defaultWorkspace: string;
  onCreated: () => void;
}

function CreateProject({ orgId, workspaceOptions, defaultWorkspace, onCreated }: CreateProjectProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [workspaceId, setWorkspaceId] = useState(defaultWorkspace);
  const [status, setStatus] = useState<ProjectStatus>("active");

  const create = useMutation({
    mutationFn: () =>
      projects.create(orgId, {
        workspace_id: workspaceId,
        name,
        description: description.trim() || null,
        status,
      }),
    onSuccess: () => {
      setName("");
      setDescription("");
      setOpen(false);
      onCreated();
    },
  });

  if (!open) {
    return (
      <div>
        <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}>
          New project
        </button>
      </div>
    );
  }
  if (workspaceOptions.length === 0) {
    return (
      <section className="card">
        <Empty title="Create a workspace first.">
          Projects live in workspaces. <Link to="../workspaces" relative="path">Go to workspaces</Link>
        </Empty>
      </section>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };
  return (
    <section className="card">
      <h2>New project</h2>
      <form className="form" onSubmit={submit}>
        <div className="grid-2">
          <label>
            Name
            <input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Workspace
            <select required value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
              <option value="" disabled>
                Choose a workspace
              </option>
              {workspaceOptions.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label>
          Description <span className="muted">(optional)</span>
          <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value as ProjectStatus)}>
            {PROJECT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {label(s)}
              </option>
            ))}
          </select>
        </label>
        {create.isError && <ErrorBox error={create.error} />}
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create project"}
          </button>
          <button type="button" className="btn" onClick={() => setOpen(false)}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
