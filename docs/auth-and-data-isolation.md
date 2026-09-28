# Authentication And Data Isolation

## Ownership model

`User -> Project` is the tenancy boundary. All business records remain linked to
`project_id`; requests first resolve the current cookie session, then resolve the
project through `owner_user_id`. Missing ownership is returned as `404` to avoid
resource enumeration.

The protected resource set includes uploaded CSV files, analysis reports,
conversations, answer versions, revision lessons, correction proposals, agent
traces, location analyses, and external-context snapshots.

## Sessions

Passwords are stored as salted `scrypt` hashes. Login and registration create a
random 256-bit opaque token; only its SHA-256 digest is stored in `auth_sessions`.
The browser receives the token as an `HttpOnly` cookie plus a readable CSRF
cookie. Every state-changing authenticated request must send that CSRF value in
`X-CSRF-Token`; logout revokes the database session and clears both cookies.

`AUTH_COOKIE_SECURE=true` is required when the API is served through HTTPS.
For a Vercel frontend and a different API site, set `AUTH_COOKIE_SAMESITE=none`
as well; the double-submit CSRF check remains mandatory.
`AUTH_DISABLED` exists only for isolated legacy tests and must not be enabled in
any runnable environment.

## Data classes

| Class | Scope | Rule |
| --- | --- | --- |
| Orders, menu costs, reviews, reports, memory | Private | Stored and queried through the owning project only. |
| Raw CSV | Private | Stored below `storage/uploads/{user_id}/{project_id}` and never served as a static asset. |
| Map analysis and snapshots | Private | Public POI facts may be reused later, but a user's address, scoring inputs and result stay project-scoped. |
| Curated RAG sources | Public | Only operator-reviewed public documents enter the shared collection. |

User-provided documents must not enter the shared Qdrant collection. A future
private knowledge base needs a separate `project` scope and a server-derived
Qdrant filter; clients and LLM plans must never supply that scope themselves.
