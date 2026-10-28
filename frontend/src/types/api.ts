// Response shapes from the backend (only the fields the UI uses).

export type Role = "owner" | "admin" | "member" | "viewer";
export type ProjectStatus = "active" | "on_hold" | "completed" | "archived";
export type TaskStatus = "todo" | "in_progress" | "in_review" | "done";
export type TaskPriority = "low" | "medium" | "high" | "urgent";

export const ROLES: Role[] = ["owner", "admin", "member", "viewer"];
export const PROJECT_STATUSES: ProjectStatus[] = ["active", "on_hold", "completed", "archived"];
export const TASK_STATUSES: TaskStatus[] = ["todo", "in_progress", "in_review", "done"];
export const TASK_PRIORITIES: TaskPriority[] = ["low", "medium", "high", "urgent"];

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  role: Role;
  created_at: string;
  updated_at: string;
}

export interface OrganizationSummary {
  members: number;
  workspaces: number;
  projects: { total: number; by_status: Record<ProjectStatus, number> };
  tasks: { total: number; by_status: Record<TaskStatus, number>; overdue: number };
}

export interface Member {
  user_id: string;
  email: string;
  full_name: string | null;
  role: Role;
  joined_at: string;
}

export interface Invitation {
  id: string;
  organization_id: string;
  email: string;
  role: Role;
  invited_by_id: string | null;
  expires_at: string;
  created_at: string;
}

export interface InvitationCreated extends Invitation {
  token: string;
}

export interface Workspace {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  organization_id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  status: ProjectStatus;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: string;
  organization_id: string;
  project_id: string;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  assignee_id: string | null;
  created_by_id: string | null;
  due_date: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface ErrorDetail {
  field?: string;
  message?: string;
  allowed?: string[];
  current_version?: number;
}
