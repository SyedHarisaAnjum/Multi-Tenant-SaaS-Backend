import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";

import { RoleBadge } from "../components/Badges";
import { Empty, ErrorBox, Loading } from "../components/States";
import { useAuth } from "../hooks/useAuth";
import { can, useMembers, useOrg } from "../hooks/useOrg";
import { invitations, members } from "../services/endpoints";
import { formatDate } from "../services/format";
import type { InvitationCreated, Role } from "../types/api";

const RANK: Record<Role, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };
const ASSIGNABLE: Role[] = ["admin", "member", "viewer"];

export function MembersPage() {
  const { orgId, org } = useOrg();
  const { user } = useAuth();
  const perms = can(org?.role);
  const queryClient = useQueryClient();
  const list = useMembers(orgId);
  const myRank = org ? RANK[org.role] : -1;
  // Mirrors the backend's ranking rule only to decide which controls to show.
  const grantable = ASSIGNABLE.filter((r) => perms.manage && RANK[r] < myRank);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["members", orgId] });
    void queryClient.invalidateQueries({ queryKey: ["summary", orgId] });
  };
  const changeRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) => members.changeRole(orgId, userId, role),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (userId: string) => members.remove(orgId, userId),
    onSuccess: refresh,
  });

  return (
    <div className="page">
      <h1>Members</h1>
      {perms.manage && <InviteMember orgId={orgId} roles={grantable} />}

      <section className="card">
        {list.isPending ? (
          <Loading />
        ) : list.isError ? (
          <ErrorBox error={list.error} onRetry={() => list.refetch()} />
        ) : (
          <>
            {(changeRole.isError || remove.isError) && <ErrorBox error={changeRole.error ?? remove.error} />}
            <table className="table">
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Role</th>
                  <th>Joined</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.data.map((m) => {
                  const isMe = m.user_id === user?.id;
                  const manageable = perms.manage && !isMe && RANK[m.role] < myRank;
                  return (
                    <tr key={m.user_id}>
                      <td>
                        <div>{m.full_name || m.email}</div>
                        {m.full_name && <div className="muted small">{m.email}</div>}
                      </td>
                      <td>
                        {manageable ? (
                          <select
                            aria-label={`Role for ${m.email}`}
                            value={m.role}
                            disabled={changeRole.isPending}
                            onChange={(e) => changeRole.mutate({ userId: m.user_id, role: e.target.value as Role })}
                          >
                            {[m.role, ...grantable.filter((r) => r !== m.role)].map((r) => (
                              <option key={r} value={r}>
                                {r}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <RoleBadge role={m.role} />
                        )}
                        {isMe && <span className="muted small"> (you)</span>}
                      </td>
                      <td className="muted">{formatDate(m.joined_at)}</td>
                      <td className="actions">
                        {manageable && (
                          <button
                            type="button"
                            className="btn btn-small btn-danger"
                            disabled={remove.isPending}
                            onClick={() => {
                              if (confirm(`Remove ${m.email} from ${org?.name}?`)) remove.mutate(m.user_id);
                            }}
                          >
                            Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}
      </section>

      {perms.manage && <PendingInvitations orgId={orgId} />}
    </div>
  );
}

function InviteMember({ orgId, roles }: { orgId: string; roles: Role[] }) {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [created, setCreated] = useState<InvitationCreated | null>(null);

  const invite = useMutation({
    mutationFn: () => invitations.create(orgId, { email, role }),
    onSuccess: (inv) => {
      setCreated(inv);
      setEmail("");
      void queryClient.invalidateQueries({ queryKey: ["invitations", orgId] });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    invite.mutate();
  };
  const link = created ? `${window.location.origin}/invitations/accept?token=${encodeURIComponent(created.token)}` : "";

  return (
    <section className="card">
      <h2>Invite someone</h2>
      <form className="inline-form" onSubmit={submit}>
        <input
          type="email"
          required
          placeholder="name@example.com"
          aria-label="Email to invite"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {roles.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <button type="submit" className="btn btn-primary" disabled={invite.isPending}>
          Send invitation
        </button>
      </form>
      {invite.isError && <ErrorBox error={invite.error} />}
      {created && (
        <div className="alert alert-info">
          <div>
            Invitation for <strong>{created.email}</strong> created. Email delivery isn't set up yet,
            so share this link with them. It's shown only once:
          </div>
          <div className="copy-row">
            <input readOnly value={link} aria-label="Invitation link" onFocus={(e) => e.target.select()} />
            <button type="button" className="btn btn-small" onClick={() => void navigator.clipboard?.writeText(link)}>
              Copy
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function PendingInvitations({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: ["invitations", orgId], queryFn: () => invitations.listPending(orgId) });
  const revoke = useMutation({
    mutationFn: (id: string) => invitations.revoke(orgId, id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["invitations", orgId] }),
  });

  return (
    <section className="card">
      <h2>Pending invitations</h2>
      {list.isPending ? (
        <Loading />
      ) : list.isError ? (
        <ErrorBox error={list.error} />
      ) : list.data.length === 0 ? (
        <Empty title="No pending invitations." />
      ) : (
        <>
          {revoke.isError && <ErrorBox error={revoke.error} />}
          <ul className="list">
            {list.data.map((inv) => (
              <li key={inv.id} className="list-row">
                <span>
                  {inv.email} <RoleBadge role={inv.role} />
                  <span className="muted small"> · expires {formatDate(inv.expires_at)}</span>
                </span>
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={revoke.isPending}
                  onClick={() => revoke.mutate(inv.id)}
                >
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
