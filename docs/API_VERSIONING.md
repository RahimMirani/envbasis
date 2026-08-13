# API Versioning and Deprecation Policy

EnvBasis versions public HTTP APIs by major version in the URL. The current contract is `/api/v1`, and responses include `X-API-Version: 1`.

## Compatibility rules

The following changes may ship within `v1`:

- New optional request fields
- New response fields
- New endpoints and event types
- New optional headers
- Broader accepted input that does not change existing behavior
- Security fixes that reject previously unsafe input

The following require a new major version unless needed to close an urgent vulnerability:

- Removing or renaming fields or endpoints
- Changing field types or meanings
- Making an optional field required
- Changing authorization in a way that grants less functionality to an otherwise valid existing integration
- Changing response shapes, pagination models, or status-code meaning incompatibly

Clients should ignore unknown response fields and must not infer permissions from the frontend.

## Deprecation process

An endpoint scheduled for removal receives:

```text
Deprecation: true
Sunset: <HTTP date>
Link: <successor endpoint>; rel="successor-version"
```

EnvBasis should provide at least six months between public deprecation notice and removal unless an actively exploitable security issue requires faster action. Release notes and migration documentation must identify the replacement and behavioral differences.

The legacy runtime-token management and `/runtime/secrets` flows now emit these headers. Their successor is the machine-identity token exchange and `/machine/secrets` flow. The configured initial sunset is July 1, 2027; it may be extended but should not be moved earlier after publication.

## Pagination compatibility

Existing array-returning endpoints keep their array shape in `v1`. Pagination uses `limit` and `offset` query parameters plus `X-Total-Count`, `X-Limit`, and `X-Offset` headers. Cursor-based endpoints keep their documented cursor fields. Replacing arrays with response envelopes would require `v2` or a separately negotiated representation.

## Idempotency compatibility

`Idempotency-Key` is optional for supported `v1` create operations. A repeated key with an identical request must replay the original status and body during the retention window. A repeated key with different request data returns `409 Conflict`.
