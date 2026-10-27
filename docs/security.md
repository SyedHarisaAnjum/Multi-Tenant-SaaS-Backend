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

### Known limitations / TODO

- Access tokens stay valid until expiry after logout (≤15 min). Add a deny-list only if needed.
- No rate limiting on `/login` and `/register` yet. Add it before going public.
- Set `COOKIE_SECURE=true` (the default) everywhere except local http development.
- Configure CORS explicitly when the frontend is added (credentials + an exact allowed origin).
