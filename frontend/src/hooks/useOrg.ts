import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";

import { members, organizations } from "../services/endpoints";
import type { Role } from "../types/api";

/** The organization in the URL, plus the caller's role in it. */
export function useOrg() {
  const { orgId = "" } = useParams();
  const query = useQuery({
    queryKey: ["org", orgId],
    queryFn: () => organizations.get(orgId),
    enabled: orgId !== "",
  });
  return { orgId, org: query.data, query };
}

/**
 * Role helpers decide what to *show*. They are UX only: hiding a button does not prevent
 * the call, and the backend enforces every rule independently.
 */
export function can(role: Role | undefined) {
  const manager = role === "owner" || role === "admin";
  return {
    manage: manager,
    contribute: manager || role === "member",
    own: role === "owner",
  };
}

export function useMembers(orgId: string) {
  return useQuery({
    queryKey: ["members", orgId],
    queryFn: () => members.list(orgId),
    enabled: orgId !== "",
  });
}
