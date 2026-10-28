import type {
  Invitation,
  InvitationCreated,
  Member,
  Organization,
  OrganizationSummary,
  Page,
  Project,
  ProjectStatus,
  Role,
  Task,
  TaskPriority,
  TaskStatus,
  TokenResponse,
  User,
  Workspace,
} from "../types/api";
import { api } from "./api";

export interface ListParams {
  page?: number;
  page_size?: number;
  sort?: string;
  q?: string;
}

// --- auth ---------------------------------------------------------------------------

export const auth = {
  register: (body: { email: string; password: string; full_name?: string }) =>
    api<User>("/auth/register", { method: "POST", body, auth: false }),
  login: (body: { email: string; password: string }) =>
    api<TokenResponse>("/auth/login", { method: "POST", body, auth: false }),
  logout: () => api<void>("/auth/logout", { method: "POST", auth: false }),
  me: () => api<User>("/auth/me"),
};

// --- organizations, members, invitations -------------------------------------------

export const organizations = {
  list: () => api<Organization[]>("/organizations"),
  get: (orgId: string) => api<Organization>(`/organizations/${orgId}`),
  create: (body: { name: string; slug: string }) =>
    api<Organization>("/organizations", { method: "POST", body }),
  update: (orgId: string, body: { name?: string; slug?: string }) =>
    api<Organization>(`/organizations/${orgId}`, { method: "PATCH", body }),
  summary: (orgId: string) => api<OrganizationSummary>(`/organizations/${orgId}/summary`),
  transferOwnership: (orgId: string, userId: string) =>
    api<void>(`/organizations/${orgId}/transfer-ownership`, {
      method: "POST",
      body: { user_id: userId },
    }),
};

export const members = {
  list: (orgId: string) => api<Member[]>(`/organizations/${orgId}/members`),
  changeRole: (orgId: string, userId: string, role: Role) =>
    api<Member>(`/organizations/${orgId}/members/${userId}`, { method: "PATCH", body: { role } }),
  remove: (orgId: string, userId: string) =>
    api<void>(`/organizations/${orgId}/members/${userId}`, { method: "DELETE" }),
};

export const invitations = {
  listPending: (orgId: string) => api<Invitation[]>(`/organizations/${orgId}/invitations`),
  create: (orgId: string, body: { email: string; role: Role }) =>
    api<InvitationCreated>(`/organizations/${orgId}/invitations`, { method: "POST", body }),
  revoke: (orgId: string, invitationId: string) =>
    api<void>(`/organizations/${orgId}/invitations/${invitationId}`, { method: "DELETE" }),
  accept: (token: string) =>
    api<Organization>("/invitations/accept", { method: "POST", body: { token } }),
};

// --- workspaces, projects, tasks ----------------------------------------------------

export const workspaces = {
  list: (orgId: string, params: ListParams = {}) =>
    api<Page<Workspace>>(`/organizations/${orgId}/workspaces`, { query: { ...params } }),
  create: (orgId: string, body: { name: string; slug: string }) =>
    api<Workspace>(`/organizations/${orgId}/workspaces`, { method: "POST", body }),
  remove: (orgId: string, workspaceId: string) =>
    api<void>(`/organizations/${orgId}/workspaces/${workspaceId}`, { method: "DELETE" }),
};

export interface ProjectFilters extends ListParams {
  status?: ProjectStatus | "";
  workspace_id?: string;
}

export interface ProjectInput {
  workspace_id: string;
  name: string;
  description?: string | null;
  status?: ProjectStatus;
}

export const projects = {
  list: (orgId: string, params: ProjectFilters = {}) =>
    api<Page<Project>>(`/organizations/${orgId}/projects`, { query: { ...params } }),
  get: (projectId: string) => api<Project>(`/projects/${projectId}`),
  create: (orgId: string, body: ProjectInput) =>
    api<Project>(`/organizations/${orgId}/projects`, { method: "POST", body }),
  update: (projectId: string, body: Partial<ProjectInput> & { version: number }) =>
    api<Project>(`/projects/${projectId}`, { method: "PATCH", body }),
  remove: (projectId: string) => api<void>(`/projects/${projectId}`, { method: "DELETE" }),
};

export interface TaskFilters extends ListParams {
  status?: TaskStatus | "";
  priority?: TaskPriority | "";
  assignee_id?: string;
  assigned_to_me?: boolean;
}

export interface TaskInput {
  title: string;
  description?: string | null;
  status?: TaskStatus;
  priority?: TaskPriority;
  assignee_id?: string | null;
  due_date?: string | null;
}

export const tasks = {
  listForProject: (projectId: string, params: TaskFilters = {}) =>
    api<Page<Task>>(`/projects/${projectId}/tasks`, { query: { ...params } }),
  listForOrg: (orgId: string, params: TaskFilters = {}) =>
    api<Page<Task>>(`/organizations/${orgId}/tasks`, { query: { ...params } }),
  get: (taskId: string) => api<Task>(`/tasks/${taskId}`),
  create: (projectId: string, body: TaskInput) =>
    api<Task>(`/projects/${projectId}/tasks`, { method: "POST", body }),
  update: (taskId: string, body: Partial<TaskInput> & { version: number }) =>
    api<Task>(`/tasks/${taskId}`, { method: "PATCH", body }),
  remove: (taskId: string) => api<void>(`/tasks/${taskId}`, { method: "DELETE" }),
};
