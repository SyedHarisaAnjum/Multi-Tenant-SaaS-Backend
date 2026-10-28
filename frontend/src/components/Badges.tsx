import type { ProjectStatus, Role, TaskPriority, TaskStatus } from "../types/api";

export function label(value: string): string {
  return value.replace(/_/g, " ");
}

export function StatusBadge({ status }: { status: TaskStatus | ProjectStatus }) {
  return <span className={`badge badge-status-${status}`}>{label(status)}</span>;
}

export function PriorityBadge({ priority }: { priority: TaskPriority }) {
  return <span className={`badge badge-priority-${priority}`}>{priority}</span>;
}

export function RoleBadge({ role }: { role: Role }) {
  return <span className={`badge badge-role-${role}`}>{role}</span>;
}
