import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router";

import { Pagination } from "../components/Pagination";
import { Empty, ErrorBox, Loading } from "../components/States";
import { can, useOrg } from "../hooks/useOrg";
import { workspaces } from "../services/endpoints";
import { formatDate, slugify } from "../services/format";

export function WorkspacesPage() {
  const { orgId, org } = useOrg();
  const perms = can(org?.role);
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");

  const list = useQuery({
    queryKey: ["workspaces", orgId, { page, q }],
    queryFn: () => workspaces.list(orgId, { page, q, page_size: 20 }),
    placeholderData: keepPreviousData,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["workspaces", orgId] });
    void queryClient.invalidateQueries({ queryKey: ["summary", orgId] });
  };

  const remove = useMutation({
    mutationFn: (id: string) => workspaces.remove(orgId, id),
    onSuccess: invalidate,
  });

  return (
    <div className="page">
      <div className="page-header">
        <h1>Workspaces</h1>
        <input
          type="search"
          placeholder="Search workspaces"
          aria-label="Search workspaces"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
      </div>

      {perms.manage && <CreateWorkspace orgId={orgId} onCreated={invalidate} />}

      <section className="card">
        {list.isPending ? (
          <Loading />
        ) : list.isError ? (
          <ErrorBox error={list.error} onRetry={() => list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <Empty title={q ? "No workspaces match your search." : "No workspaces yet."}>
            {perms.manage && !q && "Create the first one above."}
          </Empty>
        ) : (
          <>
            {remove.isError && <ErrorBox error={remove.error} />}
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Slug</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((ws) => (
                  <tr key={ws.id}>
                    <td>
                      <Link to={`../projects?workspace_id=${ws.id}`} relative="path">
                        {ws.name}
                      </Link>
                    </td>
                    <td className="muted">{ws.slug}</td>
                    <td className="muted">{formatDate(ws.created_at)}</td>
                    <td className="actions">
                      {perms.manage && (
                        <button
                          type="button"
                          className="btn btn-small btn-danger"
                          disabled={remove.isPending}
                          onClick={() => {
                            if (confirm(`Delete workspace "${ws.name}"?`)) remove.mutate(ws.id);
                          }}
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              page={list.data.page}
              totalPages={list.data.total_pages}
              total={list.data.total}
              onChange={setPage}
            />
          </>
        )}
      </section>
    </div>
  );
}

function CreateWorkspace({ orgId, onCreated }: { orgId: string; onCreated: () => void }) {
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => workspaces.create(orgId, { name, slug: slugify(name) }),
    onSuccess: () => {
      setName("");
      onCreated();
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };
  return (
    <section className="card">
      <form className="inline-form" onSubmit={submit}>
        <input
          required
          maxLength={200}
          placeholder="New workspace name"
          aria-label="New workspace name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button type="submit" className="btn btn-primary" disabled={create.isPending || slugify(name).length < 3}>
          Create workspace
        </button>
      </form>
      {create.isError && <ErrorBox error={create.error} />}
    </section>
  );
}
