import { Navigate, Route, Routes } from "react-router";

import { RequireAuth } from "./components/RequireAuth";
import { OrgLayout } from "./layouts/OrgLayout";
import { AcceptInvitationPage } from "./pages/AcceptInvitationPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { MembersPage } from "./pages/MembersPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OrgSelectorPage } from "./pages/OrgSelectorPage";
import { ProjectDetailsPage } from "./pages/ProjectDetailsPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { RegisterPage } from "./pages/RegisterPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TaskDetailsPage } from "./pages/TaskDetailsPage";
import { WorkspacesPage } from "./pages/WorkspacesPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      <Route path="/" element={<Navigate to="/orgs" replace />} />
      <Route
        path="/orgs"
        element={
          <RequireAuth>
            <OrgSelectorPage />
          </RequireAuth>
        }
      />
      <Route
        path="/invitations/accept"
        element={
          <RequireAuth>
            <AcceptInvitationPage />
          </RequireAuth>
        }
      />
      <Route
        path="/orgs/:orgId"
        element={
          <RequireAuth>
            <OrgLayout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="workspaces" element={<WorkspacesPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectDetailsPage />} />
        <Route path="tasks/:taskId" element={<TaskDetailsPage />} />
        <Route path="members" element={<MembersPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
