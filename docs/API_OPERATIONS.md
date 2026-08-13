# API Operations

EnvBasis uses shared Redis counters in production, structured request logs, Prometheus-compatible request metrics, and separate health probes.

## Shared rate limiting

Local development and tests default to the deterministic in-memory limiter. Production configuration requires Redis:

```dotenv
RATE_LIMIT_BACKEND=redis
REDIS_URL=rediss://default:<password>@<host>:6379/0
REDIS_KEY_PREFIX=envbasis
REDIS_SOCKET_TIMEOUT_SECONDS=1.0
```

The Redis implementation is a fixed-window counter. One Lua operation increments the counter, adds its expiry on the first request, and returns its remaining TTL. This makes increments atomic across all API processes. Keys contain a rule name and a SHA-256 subject digest; bearer credentials are never placed in Redis.

Authentication, CLI authentication, machine-token exchange, secret push/pull, runtime retrieval, and general traffic retain separate limits. Authenticated requests are grouped by a credential digest. Unauthenticated requests use the direct network peer address and never trust arbitrary `X-Forwarded-For` values.

Business endpoints fail closed with `503` if Redis is unavailable, preventing an outage from silently disabling brute-force and secret-access protection. `/health`, `/live`, `/ready`, and `/metrics` bypass rate limiting so operators can still diagnose the outage. Redis operations have a short configurable timeout.

## Structured logs

`LOG_JSON=true` emits one JSON object per log line. Request records contain:

- UTC timestamp and severity
- Logger and event name
- Request ID
- HTTP method and URL path without its query string
- Normalized route template
- Response status and duration
- Direct peer IP and selected rate-limit rule

Authorization headers, request bodies, query values, Redis URLs, and secret values are not logged. Client-supplied request IDs are restricted to safe characters and 128 characters before entering logs.

## Metrics

`GET /api/v1/metrics` exposes Prometheus text metrics:

- `envbasis_http_requests_total`
- `envbasis_http_request_duration_seconds_sum`
- `envbasis_http_request_duration_seconds_count`
- `envbasis_http_errors_total`

Metrics use normalized route templates instead of raw object IDs, preventing unbounded label cardinality. A production deployment should restrict the metrics endpoint at the load balancer or private network boundary.

## Probes

- `GET /api/v1/health` returns service identity and general status for compatibility.
- `GET /api/v1/live` confirms the API process is running and does not check dependencies.
- `GET /api/v1/ready` checks Postgres and the configured rate limiter. It returns `503` until both are available.
- `GET /api/v1/metrics` exposes operational counters and latency totals.

The liveness probe should determine whether a container is restarted. Readiness should determine whether it receives traffic.

## Safe errors

All route exceptions use a shared public response contract:

```json
{
  "detail": "A safe explanation.",
  "error": "error_category",
  "request_id": "request-uuid"
}
```

Validation responses may add a sanitized `errors` array. Database constraint errors return `409`, database availability errors return `503`, and unexpected exceptions return a generic `500`. Internal exception details remain in structured server logs associated with the request ID and are never returned to clients.

## Pagination

Collection endpoints accept:

```text
?limit=100&offset=0
```

They retain their existing JSON array shapes for dashboard compatibility and return:

```text
X-Total-Count
X-Limit
X-Offset
```

The maximum standard page size is 200. Existing cursor-based project-secret and unified-audit endpoints retain cursor pagination because their time-ordered datasets benefit from stable cursors.

## Idempotent creates

Sensitive creation endpoints accept an optional `Idempotency-Key` header containing 1–255 safe characters. The key is scoped to the authenticated credential, HTTP method and path. Reusing it with the same request returns the stored response with `Idempotency-Replayed: true`; using it with a different body returns `409`.

Supported operations include project, environment, secret, runtime-token, machine-identity, webhook, invitation and runtime-token-share creation, plus secret push.

Records are stored in Postgres so retries work across API instances and restarts. Response bodies—including one-time client secrets—are encrypted using the independent `API_IDEMPOTENCY_ENCRYPTION_KEY`; authorization headers and plaintext response bodies are never stored. In-progress duplicate requests return `409` with `Retry-After: 1`. Server failures release the key so a safe retry can execute again.

Generate the encryption key separately from other EnvBasis keys:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Versioning

The current major version remains `/api/v1`, and every response includes `X-API-Version: 1`. See [API_VERSIONING.md](API_VERSIONING.md) for compatibility and deprecation rules.
