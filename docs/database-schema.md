# Database schema

All primary keys are UUIDv4. All timestamps are `timestamptz`. Constraint names follow the convention in `app/db/base.py`, so migrations can reliably reference them.

```
users ─┬─< memberships >─── organizations ──< workspaces ──< projects ──< tasks
       │                          │                                        │
       ├─< refresh_tokens         └──< activity_logs                       │
       └──────────── (assignee / created_by, SET NULL) ────────────────────┘
```

| Table | Key columns | Constraints & indexes |
| --- | --- | --- |
| `users` | email, password_hash, full_name, is_active | `uq(email)`; `ck: email = lower(btrim(email))` |
| `organizations` | name, slug | `uq(slug)` |
| `memberships` | organization_id, user_id, role | `uq(organization_id, user_id)`; `ix(user_id)`; role ∈ owner/admin/member/viewer; both FKs CASCADE |
| `workspaces` | organization_id, name, slug | `uq(organization_id, slug)`; `uq(id, organization_id)` (composite-FK target) |
| `projects` | organization_id, workspace_id, name, description | FK `(workspace_id, organization_id)` → workspaces; `uq(workspace_id, name)`; `uq(id, organization_id)`; `ix(organization_id)` |
| `tasks` | organization_id, project_id, title, status, priority, assignee_id, created_by_id, due_date | FK `(project_id, organization_id)` → projects; `ix(organization_id, project_id, status)`; `ix(assignee_id)`; user FKs SET NULL |
| `activity_logs` | organization_id, actor_id, action, entity_type, entity_id, details (JSONB) | append-only (no `updated_at`); `ix(organization_id, created_at)`; `ix(entity_type, entity_id)` |
| `refresh_tokens` | user_id, token_hash, family_id, expires_at, revoked_at, replaced_by_id | `uq(token_hash)`; `ix(user_id)`; `ix(family_id)` |

Enums are stored as `VARCHAR` with a `CHECK` constraint rather than native PG enums: adding a value is a simple constraint swap, and downgrades don't need to drop types.

Deleting an organization cascades to all its tenant data. Deleting a user removes their memberships and sessions, and nulls out their task/activity references.
