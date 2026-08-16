# EnvBasis Agent Proxy

The Agent Proxy is a separate, stateless data-plane service. It accepts an EnvBasis short-lived machine access token, validates a supported OpenAI, Anthropic, or GitHub request, replaces the machine token with the provider credential, and forwards the request to a fixed provider host.

This first release intentionally has no policy or approval system. It validates request shape and applies a fixed safety boundary:

- Unknown provider paths are denied.
- OpenAI organization, administration, project, and API-key endpoints are blocked.
- Every GitHub `DELETE` request is blocked.
- GitHub GraphQL is blocked because destructive mutations use `POST`.
- GitHub secrets, tokens, collaborators, hooks, keys, and other administrative paths are blocked.
- Redirects are never followed.
- Incoming credentials are stripped and provider credentials are redacted from streamed responses.

## Run locally

The proxy and console backend must use the same machine JWT secret, issuer, and audience. Prefer platform-stored provider keys via the control-plane channel (`CONTROL_PLANE_URL` + `PROXY_SERVICE_TOKEN`). Local env vars remain a development fallback.

```bash
cd proxy
cp .env.example .env
python -m pip install -e '.[dev]'
uvicorn envbasis_proxy.main:app --reload --port 8080
```

Check the process:

```bash
curl http://localhost:8080/health
```

## Obtain a temporary machine token

Exchange the machine identity's long-lived client credential with the main EnvBasis backend:

```bash
export ENVBASIS_TOKEN="$(curl -sS \
  -X POST "$ENVBASIS_API_URL/machine-identities/token" \
  -H 'Content-Type: application/json' \
  -d "{\"client_id\":\"$ENVBASIS_CLIENT_ID\",\"client_secret\":\"$ENVBASIS_CLIENT_SECRET\"}" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
```

The client secret is used only for token exchange. Provider calls use the temporary token.

## OpenAI integration

OpenAI SDKs accept a custom base URL. Existing SDK code can use:

```bash
export OPENAI_API_KEY="$ENVBASIS_TOKEN"
export OPENAI_BASE_URL="http://localhost:8080/openai/v1"
```

```python
from openai import OpenAI

client = OpenAI()
response = client.responses.create(
    model="gpt-5.6-terra",
    input="Explain envelope encryption concisely.",
)
```

Supported OpenAI operations:

- `POST /openai/v1/responses`
- `GET /openai/v1/responses/{response_id}`
- `POST /openai/v1/responses/{response_id}/cancel`
- `GET /openai/v1/models`
- `POST /openai/v1/embeddings`

Streaming Responses requests are passed through as streamed responses.

## Anthropic integration

```bash
export ANTHROPIC_API_KEY="$ENVBASIS_TOKEN"
export ANTHROPIC_BASE_URL="http://localhost:8080/anthropic"
```

Supported Anthropic operations:

- `POST /anthropic/v1/messages`
- `GET /anthropic/v1/models`
- `GET /anthropic/v1/models/{model_id}`

## GitHub integration

Point GitHub REST calls at the proxy and use the machine token in place of the GitHub token:

```bash
curl \
  -H "Authorization: Bearer $ENVBASIS_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  http://localhost:8080/github/repos/acme/backend/issues
```

The proxy changes only the host and authorization credential:

```text
http://localhost:8080/github/repos/acme/backend/issues
                         ↓
https://api.github.com/repos/acme/backend/issues
```

The initial catalog covers repository, contents, issues, pull requests, commits, branches, Git references, checks, statuses, and workflow dispatches. Unsupported and destructive endpoints fail closed.

## Security boundary

Deploy the proxy separately from agent workloads. Agents should reach the proxy listener but must not have shell, filesystem, deployment, or environment access to the proxy process.

The current proxy validates JWT signature and expiry locally. Disabling or rotating a machine identity stops new token issuance, but an already-issued token remains usable until its short expiry. Online introspection and immediate revocation are planned control-plane integrations.

Provider keys should be stored in the EnvBasis console under **Provider keys**. The proxy resolves them through `POST /api/v1/internal/proxy/credentials/resolve` using `PROXY_SERVICE_TOKEN`. Process env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`) remain a local fallback when `CONTROL_PLANE_URL` is unset.

## Test

```bash
PYTHONPATH=src python -m pytest -q
```
