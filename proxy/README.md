# EnvBasis Agent Proxy

The Agent Proxy is a separate, stateless data-plane service. It accepts an EnvBasis short-lived machine access token, validates a supported OpenAI, Anthropic, or GitHub request, replaces the machine token with the provider credential stored in the console, and forwards the request to a fixed provider host.

This first release intentionally has no policy or approval system. It validates request shape and applies a fixed safety boundary:

- Unknown provider paths are denied.
- OpenAI organization, administration, project, and API-key endpoints are blocked.
- Every GitHub `DELETE` request is blocked.
- GitHub GraphQL is blocked because destructive mutations use `POST`.
- GitHub secrets, tokens, collaborators, hooks, keys, and other administrative paths are blocked.
- Redirects are never followed.
- Incoming credentials are stripped and provider credentials are redacted from streamed responses.

## Run locally

The proxy and console backend must use the same machine JWT secret, issuer, and audience. Provider API keys are stored in the console **Provider keys** page, not in `proxy/.env`. The proxy authenticates to the control plane with `PROXY_SERVICE_TOKEN`.

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

## Agent setup (recommended)

Copy [`docs/snippets/envbasis_session.py`](../docs/snippets/envbasis_session.py) into the agent. Set only machine credentials:

```bash
export ENVBASIS_API_URL=http://127.0.0.1:8000/api/v1
export ENVBASIS_PROXY_URL=http://localhost:8080
export ENVBASIS_CLIENT_ID=envb_mi_...
export ENVBASIS_CLIENT_SECRET=envb_mis_...
```

```python
import envbasis_session
envbasis_session.configure()

from openai import OpenAI
client = OpenAI(
    api_key=envbasis_session.api_key,
    base_url=envbasis_session.openai_base_url,
)
```

## OpenAI integration

Supported OpenAI operations:

- `POST /openai/v1/responses`
- `GET /openai/v1/responses/{response_id}`
- `POST /openai/v1/responses/{response_id}/cancel`
- `POST /openai/v1/chat/completions`
- `GET /openai/v1/models`
- `POST /openai/v1/embeddings`

Streaming Responses requests are passed through as streamed responses.

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

The current proxy validates JWT signature and expiry locally. Disabling or rotating a machine identity stops new token issuance, but an already-issued token remains usable until its short expiry.

Provider keys are stored encrypted in the console per project environment. The proxy resolves them through `POST /api/v1/internal/proxy/credentials/resolve` using `PROXY_SERVICE_TOKEN`. Env-var fallback (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`) is only for tests when `CONTROL_PLANE_URL` is unset.

## Test

```bash
PYTHONPATH=src python -m pytest -q
```
