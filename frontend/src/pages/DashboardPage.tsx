import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { label, PriorityBadge, StatusBadge } from "../components/Badges";
import { Empty, ErrorBox, Loading } from "../components/States";
import { useOrg } from "../hooks/useOrg";
import { organizations, tasks } from "../services/endpoints";
import { formatDate, isOverdue } from "../services/format";
import { PROJECT_STATUSES, TASK_STATUSES } from "../types/api";

export function DashboardPage() {
  const { orgId, org } = useOrg();
  const summary = useQuery({
    queryKey: ["summary", orgId],
    queryFn: () => organizations.summary(orgId),
  });
  const myTasks = useQuery({
    queryKey: ["tasks", "org", orgId, { mine: true }],
    queryFn: () =>
      tasks.listForOrg(orgId, { assigned_to_me: true, sort: "due_date", page_size: 10 }),
  });

  return (
    <div className="page">
      <h1>{org?.name} dashboard</h1>

      {summary.isPending ? (
        <Loading />
      ) : summary.isError ? (
        <ErrorBox error={summary.error} onRetry={() => summary.refetch()} />
      ) : (
        <>
          <div className="stats">
            <Stat label="Members" value={summary.data.members} to="members" />
            <Stat label="Workspaces" value={summary.data.workspaces} to="workspaces" />
            <Stat label="Projects" value={summary.data.projects.total} to="projects" />
            <Stat label="Tasks" value={summary.data.tasks.total} />
            <Stat label="Overdue" value={summary.data.tasks.overdue} tone="danger" />
          </div>
          <div className="grid-2">
            <section className="card">
              <h2>Tasks by status</h2>
              <Bars
                rows={TASK_STATUSES.map((s) => [label(s), summary.data.tasks.by_status[s] ?? 0])}
              />
            </section>
            <section className="card">
              <h2>Projects by status</h2>
              <Bars
                rows={PROJECT_STATUSES.map((s) => [label(s), summary.data.projects.by_status[s] ?? 0])}
              />
            </section>
          </div>
        </>
      )}

      <section className="card">
        <h2>Assigned to me</h2>
        {myTasks.isPending ? (
          <Loading />
        ) : myTasks.isError ? (
          <ErrorBox error={myTasks.error} onRetry={() => myTasks.refetch()} />
        ) : myTasks.data.items.length === 0 ? (
          <Empty title="Nothing assigned to you.">Tasks assigned to you will show up here.</Empty>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Task</th>
                <th>Status</th>
                <th>Priority</th>
                <th>Due</th>
              </tr>
            </thead>
            <tbody>
              {myTasks.data.items.map((task) => (
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
                  <td className={isOverdue(task.due_date, task.status) ? "text-danger" : undefined}>
                    {formatDate(task.due_date)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value, to, tone }: { label: string; value: number; to?: string; tone?: "danger" }) {
  const body = (
    <>
      <div className={`stat-value${tone === "danger" && value > 0 ? " text-danger" : ""}`}>{value}</div>
      <div className="stat-label">{label}</div>
    </>
  );
  return to ? (
    <Link to={to} className="stat">
      {body}
    </Link>
  ) : (
    <div className="stat">{body}</div>
  );
}

function Bars({ rows }: { rows: [string, number][] }) {
  const max = Math.max(1, ...rows.map(([, n]) => n));
  return (
    <ul className="bars">
      {rows.map(([name, n]) => (
        <li key={name}>
          <span className="bar-label">{name}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${(n / max) * 100}%` }} />
          </span>
          <span className="bar-value">{n}</span>
        </li>
      ))}
    </ul>
  );
}
