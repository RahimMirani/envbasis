# EnvBasis

**Open-source secret management built for AI agents.**

EnvBasis lets you store API keys and configuration once, then hand your agent (or backend, or CLI) a single short-lived runtime token to fetch what it needs at startup. Rotate, revoke, and audit access without rebuilding or redeploying.

---

## Why agents-first?

Modern agents juggle a lot of high-value credentials — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, vector-DB tokens, tool-use webhooks, search APIs, payment keys. The usual options are bad:

- **Baking keys into the build** ships secrets with your container image and every redeploy.
- **Plain `.env` files** sprawl across laptops, CI, and chat threads with no audit trail.
- **Generic secret managers** (Vault, AWS SM, Doppler, etc.) are powerful but optimized for human ops teams, not for an agent that boots, fetches a credential bundle, and gets to work.

EnvBasis is built for the agent shape:

- **One runtime token per environment.** Drop it into your deploy env. Your agent makes a single call at startup to load everything it needs into memory.
- **Per-environment isolation.** `dev`, `staging`, `prod`, and per-agent envs each get their own token and their own audit stream.
- **Rotation without redeploys.** Revoke a leaked key in the dashboard; the next agent boot picks up the new value. No image rebuild.
- **Audit by default.** Every reveal, push, and runtime fetch is logged with actor, project, and environment.
- **Webhooks for downstream automation.** React to `secret.updated`, `runtime_token.revoked`, etc. with HMAC-signed deliveries.

---

## What's in this repo

| Path | What it is |
|---|---|
| [`console/`](./console) | The web dashboard (React + Vite) and the FastAPI backend that serves both the dashboard and the runtime API. |
| [`cli/`](./cli) | The `envbasis` Python CLI — sign in, push/pull `.env` files, manage secrets, runtime tokens, and members from your terminal. |

Each subproject has its own README with setup instructions:

- **Dashboard + backend setup:** [`console/README.md`](./console/README.md)
- **CLI usage and commands:** [`cli/README.md`](./cli/README.md)

---

## The 60-second mental model

```
┌──────────────┐    sign in / manage      ┌────────────────┐
│  Dashboard   │ ───────────────────────▶ │                │
│   (React)    │                          │                │
└──────────────┘                          │   EnvBasis     │
                                          │    Backend     │
┌──────────────┐    push / pull .env      │   (FastAPI)    │
│  envbasis    │ ───────────────────────▶ │                │
│     CLI      │                          │   Postgres     │
└──────────────┘                          │   (Supabase)   │
                                          │                │
┌──────────────┐    runtime token         │                │
│  Your agent  │ ───────────────────────▶ │                │
│  / backend   │  (fetch secrets at boot) │                │
└──────────────┘                          └────────────────┘
```

1. A human signs in to the dashboard, creates a project and a few environments (`dev`, `prod`, …), and uploads secrets — either through the UI or by `envbasis push` from the CLI.
2. For each environment that an agent will run in, the human creates a **runtime token** and copies it into the agent's deploy environment (Fly secret, Render env var, Kubernetes Secret, etc.).
3. At startup, the agent makes one `POST /api/v1/runtime/secrets` call with the runtime token and loads the returned secrets into memory.
4. If a key leaks or rotates, the human revokes/updates it in the dashboard. The next agent restart picks up the new value.

---

## Quick start (for product users)

The fastest path is the dashboard:

1. Open the deployed dashboard and sign in with Google.
2. Create a project — e.g. `support-agent`.
3. Add an environment — e.g. `prod`.
4. Open **Secrets** → `Upload .env` to bulk-import, or `Add Secret` one at a time.
5. Open **Runtime Tokens** → create a token for `prod` and copy it.
6. Put that token into your agent's deploy environment as `ENVBASIS_RUNTIME_TOKEN`.
7. At boot, your agent calls the runtime endpoint and loads the secrets.

For CLI-driven workflows (e.g. syncing a local `.env` into an environment), see [`cli/README.md`](./cli/README.md).

For self-hosting the dashboard + backend (Supabase Postgres, Google OAuth, Fernet master key), see [`console/README.md`](./console/README.md).

---

## Project status

EnvBasis is open-source and under active development. The core flows — project/environment management, secret CRUD, runtime tokens, member invitations, audit logs, webhooks, and CLI sign-in — are shipping. Features still on the roadmap (multi-region, SDKs, additional OAuth providers, fine-grained RBAC) are tracked as issues.

Contributions, bug reports, and feature requests are welcome via GitHub issues and pull requests.
