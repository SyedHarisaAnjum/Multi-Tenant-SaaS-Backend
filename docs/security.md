# Security

## Passwords

- Hashed with **Argon2id** (`argon2-cffi`, RFC 9106 low-memory profile). Only the hash is stored.
- Hashes are upgraded transparently on login when parameters change (`check_needs_rehash`).
- Registration requires 12–128 characters. The upper bound caps hashing cost.
- Login always runs a hash verification, even for unknown emails, and returns the same error either way. This prevents user enumeration via timing or messages on login.
  (Registration does return 409 for a taken email; revisit with email verification later.)

## Emails

Trimmed and lower-cased in the request schemas. A database `CHECK` constraint guarantees no un-normalized email is ever stored.

## Tokens

| | Access token | Refresh token |
| --- | --- | --- |
| Format | JWT, HS256 | 384-bit random opaque string |
| Lifetime | 15 min (`ACCESS_TOKEN_EXPIRE_MINUTES`) | 7 days (`REFRESH_TOKEN_EXPIRE_DAYS`) |
| Transport | JSON body → client keeps it **in memory** and sends `Authorization: Bearer` | `HttpOnly; SameSite=Strict; Secure; Path=/api/v1/auth` cookie |
| Server storage | none (stateless) | SHA-256 hash in `refresh_tokens` |

- JWT decoding pins the algorithm (`alg: none` and key confusion are rejected) and requires `sub`, `exp`, `iat` and `type=access`.
- Each request re-loads the user, so deactivated users are rejected immediately.

### Rotation and reuse detection

Every `/refresh` revokes the presented token and issues a successor in the same **family** (one family = one login session). The row is locked with `SELECT … FOR UPDATE`, so concurrent refreshes cannot both succeed.

If an already-revoked token is presented, it was copied by someone, so the **entire family is revoked**. Both the attacker and the legitimate client must log in again.

`/logout` revokes only the current session's family; other devices stay logged in.

### CSRF

The refresh cookie is `SameSite=Strict` and scoped to `/api/v1/auth`, so browsers won't attach it to cross-site requests. `/refresh` returns the new access token in the response body, which a cross-origin page cannot read. All other endpoints authenticate with the bearer header, which browsers never attach automatically.

## Authorization and tenant isolation

- **Membership is re-checked on every request.** Access tokens carry only the user id, never roles or orgs. Removing a member or changing a role takes effect on their next request, even though their access token stays valid until it expires.
- **Non-members get 404**, identical to a non-existent org, so organization and resource ids can't be probed.
- **Tenant data is always queried with the caller's organization id.** Composite foreign keys also stop a row from pointing at another tenant's parent.
- **Role changes:** strict ranking (owner > admin > member > viewer). Nobody changes their own role. Nobody grants a role at or above their own. Ownership is transferred only by the owner, and the DB enforces exactly one owner.
- **Audit trail:** org creation and updates, role changes, removals, invitations and ownership transfers are written to `activity_logs` in the same transaction.

## Invitations

- 256-bit random token; only its SHA-256 hash is stored. Valid for `INVITATION_EXPIRE_HOURS` (default 72).
- Accepting locks the row (`FOR UPDATE`) and checks, in order: token exists → caller's email matches → not revoked → not already used → not expired → not already a member.
- Single use: `accepted_at` is set in the same transaction as the membership insert. Re-inviting an email revokes the previous link.
- Admins can only invite (and revoke invitations for) roles below admin. The owner role can never be invited.
- **Until email sending exists**, the create endpoint returns the raw token once so it can be shared out-of-band.

## Errors and logging

- Clients only ever get `{"error": {code, message, request_id}}`. Stack traces, SQL, constraint names and submitted values (including passwords in validation errors) are never returned. They go to the logs, tagged with the request id.
- A client-supplied `X-Request-ID` is accepted only if it matches `[A-Za-z0-9._-]{1,64}` (this prevents log injection). Otherwise a fresh id is generated.

## Tenant scope in request bodies

Request bodies reject unknown fields (422), so a client cannot submit an `organization_id`. The tenant always comes from the URL (verified membership) or the stored resource. References in bodies are checked against the caller's organization:
- `workspace_id`: a workspace in another organization looks the same as a missing one.
- `assignee_id`: must be an active member.

## Caching

- Only responses that are identical for every member are cached, and authorization runs *before* the cache lookup. A removed member's token never reaches a cached page.
- Keys always include the organization id. If a future response depends on the caller's role or identity, include that in the key or don't cache it.

## Rate limiting

See [architecture.md](architecture.md#rate-limiting-appcorerate_limitpy). Limits are per IP, per account and per user or organization, so neither a shared IP nor a distributed attacker can get around them alone. Login attempts count whether or not they succeed, so a correct guess after the limit is still refused.

## Frontend and deployment

- The access token is kept in memory only, never in localStorage. The refresh token stays in an HttpOnly, SameSite=Strict cookie scoped to `/api/v1/auth`. The SPA and API share one origin, so no CORS is configured at all.
- The UI hides controls by role for usability only; the API enforces every rule.
- `?next=` after login only accepts same-app paths (no open redirect).
- nginx: CSP `default-src 'self'` (no inline scripts), `X-Frame-Options: DENY`, `nosniff`, a strict referrer policy and `server_tokens off`. It overwrites `X-Forwarded-For`, and the backend is not reachable except through nginx.

## Production hardening

- **Unsafe production settings stop the app at start-up:** `COOKIE_SECURE=false`, a short or placeholder JWT secret (production needs 64+ characters), or rate limiting turned off. Config errors never print input values.
- **API docs and the OpenAPI schema are off in production** (`DOCS_ENABLED` can override this).
- **TLS:** Caddy terminates it, sends HSTS (1 year) and redirects HTTP. Only Caddy publishes ports. PostgreSQL and Redis are reachable only on the internal Docker network, and Redis also requires a password.
- **Containers:** they run as non-root where possible, with a read-only root filesystem, `cap_drop: ALL` (nginx keeps only what it needs to bind :80 and drop privileges), `no-new-privileges`, and memory limits.
- **Python dependencies are pinned in `requirements.lock`,** so every image build installs exactly the versions CI tested. Dependabot tracks npm packages, base images and Actions; regenerate the Python lock deliberately.

### Known limitations / TODO

- Access tokens stay valid until expiry after logout (≤15 min). Add a deny-list only if needed.
- Fixed-window limits allow a burst of up to 2x the limit across a window boundary. Switch to a sliding window if that matters.
- Per-account login limits let an attacker lock a known account out for 15 minutes (the usual trade-off). Consider CAPTCHA or step-up checks instead of hard blocks later.
- **No email verification yet.** Invitation acceptance trusts the account's email, so someone could register an invitee's address first. They would still need the invitation token, which is sent to that inbox. Add email verification before relying on this in production.
- Set `COOKIE_SECURE=true` (the default) everywhere except local http development.
- The SPA and API share one origin, so there is no CORS. If the frontend ever moves to another origin, allow exactly that origin with credentials.
- **Email verification** must be added before production, together with email delivery (the planned worker).
