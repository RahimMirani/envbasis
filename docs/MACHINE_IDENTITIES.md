# Machine Identities

Machine identities are the backend replacement for long-lived runtime tokens. A deployed service stores a client ID and client secret, exchanges them for a short-lived access token, and uses that access token to fetch only its allowed secrets.

## Credential flow

1. An authorized user creates a project-scoped or organization-scoped machine identity.
2. EnvBasis returns the client secret once and stores only its SHA-256 hash. The secret cannot be revealed later.
3. The machine sends its client ID and client secret to `POST /api/v1/machine-identities/token`.
4. EnvBasis verifies the credential, expiry, revocation status, and source IP, then returns a signed short-lived bearer token.
5. The machine sends that token to `GET /api/v1/machine/secrets`.
6. EnvBasis checks current identity, credential, role, environment, path, key-pattern, and IP policy again before returning secrets.

The client credential may be long-lived or have an administrator-selected expiry. The access token is deliberately short-lived; its lifetime is configurable per identity within the operator-defined minimum and maximum.

Agents should store only the client ID and client secret. Copy [`docs/snippets/envbasis_session.py`](snippets/envbasis_session.py) into the agent and call `envbasis_session.configure()` at startup. That helper exchanges credentials for a JWT and refreshes it before expiry so operators never mint tokens by hand.

## Scopes

Project identities have a fixed project and environment. Organization identities can be reused across projects in their organization, but receive no access until they are assigned a role in each project. Every identity can also be restricted by:

- An allowlist of actions; the first supported action is `secrets:read`
- Optional secret-key glob patterns, such as `DATABASE_*` or `OPENAI_API_KEY`
- Optional IPv4 or IPv6 CIDRs

An omitted secret-key list permits all keys allowed by the identity's roles. An empty list permits no keys. Role permissions can further restrict access by environment and folder path.

CIDR restrictions are checked during both credential exchange and secret retrieval. The backend uses the direct peer address. A trusted reverse proxy must therefore pass the real client address to the ASGI server through securely configured proxy-header handling; EnvBasis does not trust arbitrary forwarded headers itself.

## Management API

These endpoints require project ownership or `can_manage_runtime_tokens`:

- `GET /api/v1/projects/{project_id}/machine-identities`
- `POST /api/v1/projects/{project_id}/machine-identities`
- `PATCH /api/v1/projects/{project_id}/machine-identities/{identity_id}`
- `POST /api/v1/projects/{project_id}/machine-identities/{identity_id}/rotate-secret`
- `POST /api/v1/projects/{project_id}/machine-identities/{identity_id}/revoke`
- `POST /api/v1/projects/{project_id}/machine-identities/{identity_id}/credentials`
- `DELETE /api/v1/projects/{project_id}/machine-identities/{identity_id}/credentials/{credential_id}`
- `POST /api/v1/projects/{project_id}/machine-identities/{identity_id}/disable`
- `POST /api/v1/projects/{project_id}/machine-identities/{identity_id}/enable`
- `POST /api/v1/projects/{project_id}/machine-identities/{identity_id}/unlock`
- `GET /api/v1/projects/{project_id}/machine-identities/{identity_id}/auth-history`

Credential exchange and secret retrieval are machine-facing:

- `POST /api/v1/machine-identities/token`
- `GET /api/v1/machine/secrets`

Creation and rotation responses use `Cache-Control: no-store` and include the new client secret exactly once.

## Rotation and revocation

An identity can have multiple named Universal Auth credentials. Rotation creates a replacement and either revokes the selected credential immediately or keeps it valid for a configurable overlap window (up to seven days). Access tokens are bound to the exact credential that issued them, so credential revocation also invalidates its active tokens.

Revocation also increments the credential version and marks the identity revoked. It blocks both new token exchange and existing access tokens immediately. Updating an identity's environment, actions, key patterns, or CIDRs takes effect on the next request because secret retrieval reads the current database state rather than trusting token scopes alone.

Repeated failed client-secret checks lock the identity temporarily. Administrators can inspect authentication history, unlock it, or disable and enable it from the console. Successful exchange resets the failure counter.

## Configuration

Set a distinct signing secret in every deployed environment:

```dotenv
MACHINE_AUTH_JWT_SECRET=<long-random-secret>
MACHINE_AUTH_DEFAULT_ACCESS_TOKEN_TTL_SECONDS=3600
MACHINE_AUTH_MIN_ACCESS_TOKEN_TTL_SECONDS=300
MACHINE_AUTH_MAX_ACCESS_TOKEN_TTL_SECONDS=86400
MACHINE_AUTH_MAX_FAILED_ATTEMPTS=5
MACHINE_AUTH_LOCKOUT_SECONDS=900
MACHINE_AUTH_DEFAULT_ROTATION_OVERLAP_SECONDS=0
```

Production startup rejects a missing machine-token signing secret. The current signer uses HS256, so every API instance must share the same secret. A later asymmetric signing configuration can separate token issuance from verification.

## Migration status

The backend API, console management experience, and CLI Universal Auth workflow are complete. Existing runtime-token endpoints remain temporarily for compatibility and can enter a documented removal window after deployed users migrate.
