import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { label, PriorityBadge, StatusBadge } from "../components/Badges";
import { Pagination } from "../components/Pagination";
import { Empty, ErrorBox, Loading } from "../components/States";
import { can, useMembers, useOrg } from "../hooks/useOrg";
import { ApiError } from "../services/api";
import { projects, tasks } from "../services/endpoints";
import { formatDate, isOverdue } from "../services/format";
import { PROJECT_STATUSES, TASK_PRIORITIES, TASK_STATUSES } from "../types/api";
import type { Project, ProjectStatus, TaskPriority, TaskStatus } from "../types/api";

export function ProjectDetailsPage() {
  const { projectId = "" } = useParams();
  const { orgId, org } = useOrg();
  const perms = can(org?.role);
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => projects.get(projectId) });

  if (project.isPending) return <Loading />;
  if (project.isError) {
    return (
      <div className="page">
        <ErrorBox error={project.error} />
        <Link to={`/orgs/${orgId}/projects`}>Back to projects</Link>
      </div>
    );
  }
  return (
    <div className="page">
      <p className="small">
        <Link to={`/orgs/${orgId}/projects`}>← Projects</Link>
      </p>
      <ProjectHeader project={project.data} canEdit={perms.contribute} canDelete={perms.manage} />
      <ProjectTasks orgId={orgId} projectId={projectId} canCreate={perms.contribute} />
    </div>
  );
}

function ProjectHeader({ project, canEdit, canDelete }: { project: Project; canEdit: boolean; canDelete: boolean }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [status, setStatus] = useState<ProjectStatus>(project.status);

  const save = useMutation({
    mutationFn: () =>
      projects.update(project.id, {
        version: project.version,
        name,
        description: description.trim() || null,
        status,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["project", project.id], updated);
      void queryClient.invalidateQueries({ queryKey: ["projects", project.organization_id] });
      void queryClient.invalidateQueries({ queryKey: ["summary", project.organization_id] });
      setEditing(false);
    },
  });
  const remove = useMutation({
    mutationFn: () => projects.remove(project.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects", project.organization_id] });
      void queryClient.invalidateQueries({ queryKey: ["summary", project.organization_id] });
      navigate(`/orgs/${project.organization_id}/projects`, { replace: true });
    },
  });
  const conflict = save.error instanceof ApiError && save.error.code === "VERSION_CONFLICT";

  const reload = async () => {
    const fresh = await queryClient.fetchQuery({
      queryKey: ["project", project.id],
      queryFn: () => projects.get(project.id),
      staleTime: 0,
    });
    setName(fresh.name);
    setDescription(fresh.description ?? "");
    setStatus(fresh.status);
    save.reset();
  };

  if (!editing) {
    return (
      <section className="card">
        <div className="page-header">
          <h1>
            {project.name} <StatusBadge status={project.status} />
          </h1>
          <div className="row">
            {canEdit && (
              <button type="button" className="btn" onClick={() => setEditing(true)}>
                Edit
              </button>
            )}
            {canDelete && (
              <button
                type="button"
                className="btn btn-danger"
                disabled={remove.isPending}
                onClick={() => {
                  if (confirm(`Delete "${project.name}" and all its tasks?`)) remove.mutate();
                }}
              >
                Delete
              </button>
            )}
          </div>
        </div>
        {project.description ? <p>{project.description}</p> : <p className="muted">No description.</p>}
        {remove.isError && <ErrorBox error={remove.error} />}
      </section>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  return (
    <section className="card">
      <form className="form" onSubmit={submit}>
        <label>
          Name
          <input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Description
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
        {save.isError && <ErrorBox error={save.error} />}
        <div className="row">
          {conflict ? (
            <button type="button" className="btn btn-primary" onClick={() => void reload()}>
              Load latest version
            </button>
          ) : (
            <button type="submit" className="btn btn-primary" disabled={save.isPending}>
              Save
            </button>
          )}
          <button type="button" className="btn" onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

function ProjectTasks({ orgId, projectId, canCreate }: { orgId: string; projectId: string; canCreate: boolean }) {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<TaskStatus | "">("");
  const [priority, setPriority] = useState<TaskPriority | "">("");
  const [sort, setSort] = useState("-created_at");
  const members = useMembers(orgId);
  const memberName = new Map(members.data?.map((m) => [m.user_id, m.full_name || m.email]));

  const list = useQuery({
    queryKey: ["tasks", "project", projectId, { page, q, status, priority, sort }],
    queryFn: () => tasks.listForProject(projectId, { page, page_size: 20, q, status, priority, sort }),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      {canCreate && <CreateTask orgId={orgId} projectId={projectId} />}
      <section className="card">
        <h2>Tasks</h2>
        <div className="filters">
          <input
            type="search"
            placeholder="Search titles"
            aria-label="Search tasks"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
          <select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value as TaskStatus | ""); setPage(1); }}>
            <option value="">All statuses</option>
            {TASK_STATUSES.map((s) => (
              <option key={s} value={s}>
                {label(s)}
              </option>
            ))}
          </select>
          <select aria-label="Priority" value={priority} onChange={(e) => { setPriority(e.target.value as TaskPriority | ""); setPage(1); }}>
            <option value="">All priorities</option>
            {TASK_PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="-created_at">Newest</option>
            <option value="-priority">Priority</option>
            <option value="due_date">Due date</option>
            <option value="title">Title</option>
          </select>
        </div>
        {list.isPending ? (
          <Loading />
        ) : list.isError ? (
          <ErrorBox error={list.error} onRetry={() => list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <Empty title="No tasks found.">{q || status || priority ? "Try clearing the filters." : null}</Empty>
        ) : (
          <>
            <table className="table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Priority</th>
                  <th>Assignee</th>
                  <th>Due</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((task) => (
                  <tr key={task.id}>
                    <td>
                      <Link to={`/orgs/${orgId}/tasks/${task.id}`}>{task.title}</Link>
                    </td>
                    <td>
                      <StatusBadge status={task.status} />
                    </td>
                    <td>
                      <PriorityBadge priority={task.priority} />
                    </td>
                    <td className="muted">{task.assignee_id ? (memberName.get(task.assignee_id) ?? "—") : "Unassigned"}</td>
                    <td className={isOverdue(task.due_date, task.status) ? "text-danger" : "muted"}>
                      {formatDate(task.due_date)}
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
    </>
  );
}

function CreateTask({ orgId, projectId }: { orgId: string; projectId: string }) {
  const queryClient = useQueryClient();
  const members = useMembers(orgId);
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("medium");
  const [assignee, setAssignee] = useState("");
  const [due, setDue] = useState("");

  const create = useMutation({
    mutationFn: () =>
      tasks.create(projectId, {
        title,
        priority,
        assignee_id: assignee || null,
        due_date: due || null,
      }),
    onSuccess: () => {
      setTitle("");
      setAssignee("");
      setDue("");
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["summary", orgId] });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };
  return (
    <section className="card">
      <form className="inline-form wrap" onSubmit={submit}>
        <input
          required
          maxLength={300}
          placeholder="New task title"
          aria-label="New task title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <select aria-label="Priority" value={priority} onChange={(e) => setPriority(e.target.value as TaskPriority)}>
          {TASK_PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select aria-label="Assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
          <option value="">Unassigned</option>
          {members.data?.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.full_name || m.email}
            </option>
          ))}
        </select>
        <input type="date" aria-label="Due date" value={due} onChange={(e) => setDue(e.target.value)} />
        <button type="submit" className="btn btn-primary" disabled={create.isPending}>
          Add task
        </button>
      </form>
      {create.isError && <ErrorBox error={create.error} />}
    </section>
  );
}
