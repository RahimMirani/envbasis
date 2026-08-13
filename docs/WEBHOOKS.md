# Webhook Security and Durable Delivery

> Deferred from the current MVP. The implementation and migrations are retained, but `WEBHOOKS_ENABLED=false` removes the API surface and prevents event enqueueing until a delivery worker is deployed.

EnvBasis stores each webhook delivery in Postgres before the API transaction commits. A separate worker claims due rows, validates the destination, sends the signed request, and either completes the row or schedules its next attempt. API restarts therefore do not lose queued work.

## Run the worker

Run at least one worker process from `console/backend`:

```bash
python -m app.workers.webhooks
```

Multiple workers may run against the same Postgres database. They claim rows with `FOR UPDATE SKIP LOCKED`, preventing the same due delivery from being processed concurrently.

## Destination protection

Webhook creation and every delivery attempt perform destination validation:

- Production accepts only HTTPS.
- User information and URL fragments are rejected.
- Every IPv4 and IPv6 result must be public.
- Loopback, private, link-local, multicast, reserved, unspecified, and cloud metadata destinations are blocked.
- A hostname with mixed public and private DNS results is blocked completely.
- The HTTP connection is pinned to the validated address while preserving the original hostname for the Host header and TLS certificate verification.
- Redirects are never followed.

Resolving immediately before connection and pinning the checked IP closes the DNS-rebinding gap where a hostname changes from a public address to an internal address between validation and connection.

Application checks should be combined with infrastructure egress rules for the worker in production. The worker should not have network access to databases, cloud metadata, control planes, or other internal services it does not need.

## Retry behavior

EnvBasis retries network errors, timeouts, HTTP 408, HTTP 425, HTTP 429, and HTTP 5xx responses. Most other HTTP 4xx responses and blocked destinations fail permanently without retrying. Redirect responses also fail without being followed.

The delay is:

```text
min(WEBHOOK_RETRY_BASE_SECONDS * 2^(attempt - 1), WEBHOOK_RETRY_MAX_SECONDS)
```

The default is five total attempts, starting with a 30-second retry delay and capped at one hour. Each retry reuses the exact stored payload and logical delivery ID.

## Idempotency and attempt history

Each logical delivery has a stable UUID, returned as `id` by the API and sent as `X-EnvBasis-Delivery`. Every automatic retry and authorized manual redelivery uses that same ID and the exact original payload. Receivers should store processed delivery IDs and return success without repeating side effects when they see a duplicate.

Producer-side idempotency keys are unique per webhook. Enqueueing the same webhook event key again returns the existing delivery instead of creating another job. A database uniqueness constraint also prevents duplicate rows.

Every actual request creates a `webhook_delivery_attempts` row containing:

- Its monotonically increasing attempt number
- Start and completion timestamps
- Attempt status and HTTP response code
- A safe error message
- The next retry time, when applicable

The parent delivery retains the current and final status. Delivery-history responses include their ordered `attempts` array, and the worker sends `X-EnvBasis-Attempt` on every request.

## Manual redelivery

Project owners can requeue a completed delivery:

```text
POST /api/v1/projects/{project_id}/webhooks/{webhook_id}/deliveries/{delivery_id}/redeliver
```

The endpoint rejects a delivery that is already queued or retrying. It preserves the delivery ID, payload and previous attempts, starts a fresh automatic-retry budget, and records `webhook.redelivery_requested` in the project audit log.

## Configuration

```dotenv
WEBHOOK_REQUEST_TIMEOUT_SECONDS=10
WEBHOOK_MAX_ATTEMPTS=5
WEBHOOK_RETRY_BASE_SECONDS=30
WEBHOOK_RETRY_MAX_SECONDS=3600
WEBHOOK_WORKER_POLL_SECONDS=1.0
WEBHOOK_WORKER_BATCH_SIZE=25
```

## Console support

The project Webhooks page displays queued, retrying and final delivery states, stable delivery IDs, next retry times, every recorded request attempt, and safe attempt errors. Project owners can manually requeue completed deliveries from the activity dialog.

## Remaining hardening

The core Phase 0 webhook backend and console experience are complete. Retry jitter, `Retry-After`, dead-letter handling, signing-secret hardening, and infrastructure egress policies remain tracked as later hardening.
