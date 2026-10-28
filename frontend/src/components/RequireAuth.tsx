import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { useAuth } from "../hooks/useAuth";
import { Loading } from "./States";

/** Route guard: anonymous visitors are sent to /login and brought back afterwards. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") return <Loading label="Restoring your session…" />;
  if (status === "anonymous") {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}
