import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { label, PriorityBadge, StatusBadge } from "../components/Badges";
import { ErrorBox, Loading } from "../components/States";
import { useAuth } from "../hooks/useAuth";
import { can, useMembers, useOrg } from "../hooks/useOrg";
import { ApiError } from "../services/api";
import { tasks } from "../services/endpoints";
import type { TaskInput } from "../services/endpoints";
import { formatDate } from "../services/format";
import { TASK_PRIORITIES, TASK_STATUSES } from "../types/api";
import type { Task, TaskPriority, TaskStatus } from "../types/api";

interface Draft {
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  assignee_id: string;
  due_date: string;
}

function toDraft(task: Task): Draft {
  return {
    title: task.title,
    description: task.description ?? "",
    status: task.status,
    priority: task.priority,
    assignee_id: task.assignee_id ?? "",
    due_date: task.due_date ?? "",
  };
}

/** Only the fields the user actually changed: avoids touching what someone else edited. */
function changedFields(task: Task, draft: Draft): Partial<TaskInput> {
  const original = toDraft(task);
  const changes: Partial<TaskInput> = {};
  if (draft.title !== original.title) changes.title = draft.title;
  if (draft.description !== original.description) changes.description = draft.description.trim() || null;
  if (draft.status !== original.status) changes.status = draft.status;
  if (draft.priority !== original.priority) changes.priority = draft.priority;
  if (draft.assignee_id !== original.assignee_id) changes.assignee_id = draft.assignee_id || null;
  if (draft.due_date !== original.due_date) changes.due_date = draft.due_date || null;
  return changes;
}

export function TaskDetailsPage() {
  const { taskId = "" } = useParams();
  const { orgId, org } = useOrg();
  const { user } = useAuth();
  const perms = can(org?.role);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const members = useMembers(orgId);

  const task = useQuery({ queryKey: ["task", taskId], queryFn: () => tasks.get(taskId) });
  const [draft, setDraft] = useState<Draft | null>(null);
  useEffect(() => {
    if (task.data) setDraft(toDraft(task.data));
  }, [task.data]);

  const afterWrite = (updated?: Task) => {
    if (updated) queryClient.setQueryData(["task", taskId], updated);
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    void queryClient.invalidateQueries({ queryKey: ["summary", orgId] });
  };

  const save = useMutation({
    mutationFn: (current: Task) => tasks.update(current.id, { version: current.version, ...changedFields(current, draft!) }),
    onSuccess: (updated) => afterWrite(updated),
  });
  const remove = useMutation({
    mutationFn: () => tasks.remove(taskId),
    onSuccess: () => {
      afterWrite();
      navigate(task.data ? `/orgs/${orgId}/projects/${task.data.project_id}` : `/orgs/${orgId}`, { replace: true });
    },
  });

  if (task.isPending || (task.data && !draft)) return <Loading />;
  if (task.isError) {
    return (
      <div className="page">
        <ErrorBox error={task.error} />
        <Link to={`/orgs/${orgId}`}>Back to dashboard</Link>
      </div>
    );
  }
  const current = task.data;
  const form = draft!;
  const dirty = Object.keys(changedFields(current, form)).length > 0;
  const conflict = save.error instanceof ApiError && save.error.code === "VERSION_CONFLICT";
  const canEdit = perms.contribute;
  const canDelete = perms.manage || (perms.contribute && current.created_by_id === user?.id);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft({ ...form, [key]: value });

  const reload = async () => {
    save.reset();
    await task.refetch();
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate(current);
  };

  return (
    <div className="page">
      <p className="small">
        <Link to={`/orgs/${orgId}/projects/${current.project_id}`}>← Project</Link>
      </p>
      <section className="card">
        <div className="page-header">
          <h1>{current.title}</h1>
          <div className="row">
            <StatusBadge status={current.status} />
            <PriorityBadge priority={current.priority} />
          </div>
        </div>
        <p className="muted small">
          Created {formatDate(current.created_at)} · Updated {formatDate(current.updated_at)} · Version{" "}
          {current.version}
        </p>

        <form className="form" onSubmit={submit}>
          <fieldset disabled={!canEdit || save.isPending}>
            <label>
              Title
              <input required maxLength={300} value={form.title} onChange={(e) => set("title", e.target.value)} />
            </label>
            <label>
              Description
              <textarea rows={4} value={form.description} onChange={(e) => set("description", e.target.value)} />
            </label>
            <div className="grid-2">
              <label>
                Status
                <select value={form.status} onChange={(e) => set("status", e.target.value as TaskStatus)}>
                  {TASK_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {label(s)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Priority
                <select value={form.priority} onChange={(e) => set("priority", e.target.value as TaskPriority)}>
                  {TASK_PRIORITIES.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Assignee
                <select value={form.assignee_id} onChange={(e) => set("assignee_id", e.target.value)}>
                  <option value="">Unassigned</option>
                  {members.data?.map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.full_name || m.email}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Due date
                <input type="date" value={form.due_date} onChange={(e) => set("due_date", e.target.value)} />
              </label>
            </div>
          </fieldset>

          {save.isError && <ErrorBox error={save.error} />}
          {save.isSuccess && !dirty && <div className="alert alert-info">Saved.</div>}
          {!canEdit && <p className="muted small">Viewers can't edit tasks.</p>}

          <div className="row">
            {conflict ? (
              <button type="button" className="btn btn-primary" onClick={() => void reload()}>
                Load latest version (discards your changes)
              </button>
            ) : (
              canEdit && (
                <button type="submit" className="btn btn-primary" disabled={!dirty || save.isPending}>
                  {save.isPending ? "Saving…" : "Save changes"}
                </button>
              )
            )}
            {canDelete && (
              <button
                type="button"
                className="btn btn-danger"
                disabled={remove.isPending}
                onClick={() => {
                  if (confirm("Delete this task?")) remove.mutate();
                }}
              >
                Delete task
              </button>
            )}
          </div>
          {remove.isError && <ErrorBox error={remove.error} />}
        </form>
      </section>
    </div>
  );
}
