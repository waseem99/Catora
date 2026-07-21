# Authentication and workspace access

Catora uses server-side opaque sessions rather than browser-stored JWTs.

## First-run setup

1. Open `/setup` on a new installation.
2. Create the first organization, workspace and owner account.
3. The bootstrap endpoint permanently refuses additional initialization after the first user exists.

## Session model

- Passwords use Argon2id.
- The browser receives an HttpOnly session cookie and a readable CSRF cookie.
- Only HMAC-SHA256 token digests are persisted.
- Sessions expire, can be revoked, and are invalid when the user is disabled.
- Cookie-authenticated state changes require the `X-CSRF-Token` header.
- API clients may use a Bearer session token and do not use cookie CSRF protection.

## Roles

| Role | Main capabilities |
|---|---|
| Owner | Organization, members and all workspace operations |
| Admin | Members, sources, analysis, recommendations and reports |
| Analyst | Analysis, recommendations and reports |
| Reviewer | Review and approval |
| Viewer | Read-only access |

Administrators cannot create owners. The final owner cannot be demoted or removed.

## Invitations and password reset

Invitation and reset links contain one-time opaque tokens. Only token hashes are stored. Local email is delivered through Mailpit; production uses the configured SMTP relay.

## Production configuration

Set strong, independent secrets for:

- `CATORA_AUTH_TOKEN_PEPPER`
- `CATORA_S3_SECRET_KEY`

Enable `CATORA_TRUST_PROXY_HEADERS=true` only behind a trusted reverse proxy that overwrites forwarded headers.
