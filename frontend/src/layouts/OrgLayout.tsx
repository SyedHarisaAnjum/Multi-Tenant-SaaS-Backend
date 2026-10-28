import { Link, NavLink, Outlet, useNavigate } from "react-router";

import { RoleBadge } from "../components/Badges";
import { ErrorBox, Loading } from "../components/States";
import { useAuth } from "../hooks/useAuth";
import { useOrg } from "../hooks/useOrg";
import { ApiError } from "../services/api";

const NAV = [
  { to: "", label: "Dashboard", end: true },
  { to: "workspaces", label: "Workspaces" },
  { to: "projects", label: "Projects" },
  { to: "members", label: "Members" },
  { to: "settings", label: "Settings" },
];

export function OrgLayout() {
  const { org, query } = useOrg();
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const signOut = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link to="/orgs" className="brand">
          <img src="/favicon.svg" alt="" width={24} height={24} />
          TeamFlow
        </Link>
        {org && (
          <div className="org-card">
            <div className="org-name">{org.name}</div>
            <RoleBadge role={org.role} />
            <Link to="/orgs" className="small">
              Switch organization
            </Link>
          </div>
        )}
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink key={item.label} to={item.to} end={item.end}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="small muted" title={user?.email}>
            {user?.full_name || user?.email}
          </div>
          <button type="button" className="btn btn-small" onClick={signOut}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="content">
        {query.isPending ? (
          <Loading />
        ) : query.isError ? (
          query.error instanceof ApiError && query.error.status === 404 ? (
            <div className="page">
              <h1>Organization not found</h1>
              <p className="muted">It doesn't exist, or you're no longer a member.</p>
              <Link to="/orgs" className="btn">
                Choose another organization
              </Link>
            </div>
          ) : (
            <ErrorBox error={query.error} onRetry={() => query.refetch()} />
          )
        ) : (
          <Outlet />
        )}
      </main>
    </div>
  );
}
