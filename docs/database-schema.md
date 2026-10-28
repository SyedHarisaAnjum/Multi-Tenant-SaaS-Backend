# Database schema

All primary keys are UUIDv4. All timestamps are `timestamptz`. Constraint names follow the convention in `app/db/base.py`, so migrations can reliably reference them.

```
users ─┬─< memberships >─── organizations ─┬─< invitations
       │                                   ├─< activity_logs
       │                                   └─< workspaces ──< projects ──< tasks
       ├─< refresh_tokens                                                  │
       └────────────── (assignee / created_by, SET NULL) ──────────────────┘
```

| Table | Key columns | Constraints & indexes |
| --- | --- | --- |
| `users` | email, password_hash, full_name, is_active | `uq(email)`; `ck: email = lower(btrim(email))` |
| `organizations` | name, slug | `uq(slug)` |
| `memberships` | organization_id, user_id, role | `uq(organization_id, user_id)`; `ix(user_id)`; role ∈ owner/admin/member/viewer; both FKs CASCADE; **partial unique `(organization_id) WHERE role = 'owner'`** (exactly one owner) |
| `workspaces` | organization_id, name, slug | `uq(organization_id, slug)`; `uq(id, organization_id)` (composite-FK target); projects reference it with **ON DELETE RESTRICT** |
| `projects` | organization_id, workspace_id, name, description, status, **version** | FK `(workspace_id, organization_id)` → workspaces (RESTRICT); `uq(workspace_id, name)`; `uq(id, organization_id)`; `ix(organization_id)`; `ix(organization_id, created_at)`; **GIN trigram on `name`**; status in active/on_hold/completed/archived |
| `tasks` | organization_id, project_id, title, description, status, priority, assignee_id, created_by_id, due_date, **version** | FK `(project_id, organization_id)` → projects (CASCADE); `ix(organization_id, project_id, status)`; `ix(organization_id, assignee_id, status)`; `ix(assignee_id)`; `ix(created_by_id)`; **GIN trigram on `title`**; status in todo/in_progress/in_review/done; priority in low/medium/high/urgent; user FKs SET NULL |
| `activity_logs` | organization_id, actor_id, action, entity_type, entity_id, details (JSONB) | append-only (no `updated_at`); `ix(organization_id, created_at)`; `ix(entity_type, entity_id)`; `ix(actor_id)` |
| `invitations` | organization_id, email, role, token_hash, invited_by_id, expires_at, accepted_at, accepted_by_id, revoked_at | `uq(token_hash)`; `ck: role <> 'owner'`; `ck: email normalized`; `ck: not both accepted and revoked`; **partial unique `(organization_id, email) WHERE accepted_at IS NULL AND revoked_at IS NULL`** (one open invite per email) |
| `refresh_tokens` | user_id, token_hash, family_id, expires_at, revoked_at, replaced_by_id | `uq(token_hash)`; `ix(user_id)`; `ix(family_id)` |

### Index rationale

- Every list query starts with `organization_id = ...`, so composite indexes lead with it.
- `(organization_id, assignee_id, status)` serves "my tasks" and assignee listings.
- Single-column indexes on user FKs (`assignee_id`, `created_by_id`, `actor_id`) keep `ON DELETE SET NULL` cheap when a user is deleted.
- `pg_trgm` GIN indexes let `ILIKE '%term%'` search on task titles and project names use an index (checked with `EXPLAIN`: Bitmap Index Scan).
- `version` columns support optimistic locking (SQLAlchemy `version_id_col`).

Enums are stored as `VARCHAR` with a `CHECK` constraint rather than native PG enums: adding a value is a simple constraint swap, and downgrades don't need to drop types.

Deleting an organization cascades to all its tenant data. Deleting a user removes their memberships and sessions, and nulls out their task/activity references.
