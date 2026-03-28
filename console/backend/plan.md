# Envbasis MVP Plan

## 1. Product Summary

Envbasis is a developer-first platform for securely storing, sharing, pulling, and using `.env` secrets across teams. The initial focus is not enterprise vault complexity. The focus is a simple workflow for small teams, student builders, hackathons, and fast-moving projects that currently share secrets through Slack, Discord, email, or docs.

The product has three parts:

* **Dashboard** for project and token management
* **CLI** for developer workflows like push, pull, invite, and run
* **Runtime SDK/API** for apps to fetch secrets securely at startup

---

## 2. Core Problem

Most teams still share `.env` files manually. This creates several problems:

* no audit trail
* no per-user access control
* hard to revoke access when someone leaves
* easy accidental leaks into GitHub
* local, staging, and production envs drift out of sync
* enterprise tools are often too complex or expensive for small teams

Envbasis should sit between insecure `.env` sharing and heavy enterprise secret managers.

---

## 3. Positioning

**What Envbasis is:**

* simple secrets workflow for developers
* Git-like CLI for `.env` files
* owner-created runtime access tokens from CLI or dashboard
* secure sharing for teams and hackathons

**What Envbasis is not:**

* not a full HashiCorp Vault replacement
* not focused first on complex enterprise infra
* not an automatic rotator of all third-party API keys

---

## 4. Product Principles

1. **Simple first**: a developer should understand the product in minutes.
2. **Project-based storage**: secrets belong to projects and environments, not tokens.
3. **Tokens only control access**: tokens never contain the actual secrets.
4. **CLI-first for daily use**: terminal should be the main user workflow.
5. **Owner-restricted token management**: runtime token creation and revocation must be limited to project owners and enforced by the backend.
6. **Encrypted storage**: secrets must always be encrypted at rest.
7. **Good auditability**: every push, pull, token use, and membership change should be logged.

---

## 5. Mental Model

Think of the system like this:

* **Project** = locker
* **Secrets** = items inside locker
* **Runtime token** = temporary key to open locker
* **CLI / SDK** = the way developers or apps access the locker

This means:

* secrets are stored under the project and environment on the server
* runtime tokens only grant read access to those secrets
* if a new token is created, the secrets do not need to be re-uploaded

---

## 6. MVP Scope

### Human workflow

* sign up and log in
* create project
* create environments like `dev`, `staging`, `prod`
* push `.env` values to server
* pull `.env` values locally
* invite teammates
* revoke teammates
* view audit logs

### App/runtime workflow

* create runtime token from CLI or dashboard as project owner
* place runtime token in deployment env
* app fetches secrets at startup using token

### Excluded from MVP

* OS-level copy/paste tracking
* full secret rotation for third-party services like OpenAI or Stripe
* advanced policy engine
* GitHub-wide secret scanning on the open internet
* dynamic secrets like Vault
* zero-disk local secret mode

---

## 7. User Flows

### Flow A: Create project and upload secrets

1. User signs up in dashboard or CLI
2. User creates project: `my-ai-app`
3. User creates environment: `dev`
4. User runs:

   ```bash
   envbasis push
   ```
5. CLI reads local `.env`
6. CLI uploads keys to server
7. Server encrypts and stores them under project and environment

### Flow B: Teammate pulls secrets

1. Owner invites teammate by email
2. Teammate accepts invite and logs in
3. Teammate runs:

   ```bash
   envbasis pull --project my-ai-app --env dev
   ```
4. CLI downloads secrets and writes local `.env`
5. Audit log records who pulled secrets and when

### Flow C: Runtime token for production app

1. Admin opens the dashboard or uses the CLI
2. Admin creates runtime token under project and environment
3. Admin sets expiry and permissions
4. Token is shown once
5. Admin adds token to deployment environment:

   ```bash
   ENVSAFE_TOKEN=tok_prod_xxx
   ```
6. App starts and SDK fetches secrets from Envbasis
7. Secrets are loaded into memory for app runtime

### Flow D: Update env values

1. Developer edits local `.env`
2. Developer runs:

   ```bash
   envbasis push
   ```
3. Server stores a new version of changed secrets
4. Teammates can pull latest values later
5. Running apps only pick up new values after restart or refresh

---

## 8. Core Commands

### CLI commands for MVP

```bash
envbasis signup
envbasis login
envbasis init
envbasis push
envbasis pull
envbasis invite user@email.com --role member
envbasis revoke user@email.com
envbasis members list
envbasis token create --env prod --expires 24h
envbasis token list
envbasis token revoke <token_id>
envbasis whoami
envbasis projects list
envbasis env list
```

### Phase 2 commands

```bash
envbasis diff
envbasis history
envbasis rollback
envbasis run -- node app.js
envbasis status
envbasis scan
```

---

## 9. Dashboard Scope

The dashboard should handle sensitive or administrative actions:

* create and manage projects
* create environments
* invite and revoke users
* create runtime tokens
* revoke runtime tokens
* set token expiry
* audit logs
* view secret versions

### Important rule

Runtime tokens can be created from **both the CLI and the dashboard**, but **only project owners are allowed to create or revoke runtime tokens**. This prevents regular members from generating long-lived access to sensitive environments.

CLI example:

```bash
envbasis token create --env prod --expires 24h
```

The dashboard still allows owners to:

* view all tokens
* revoke tokens
* edit expiry
* inspect token usage
* share active runtime tokens with existing project members for testing or hackathon workflows

This keeps security-critical actions restricted while still allowing developers to work from the terminal.

---

## 10. Runtime Token Design

### What a runtime token is

A runtime token is a project-scoped, environment-scoped access credential that lets an app fetch secrets at startup.

### Token creation permissions

For MVP security:

* **Only project owners can create runtime tokens**
* Members cannot create runtime tokens
* Owners may share an active runtime token with an existing project member when collaboration requires it
* Members may only push and pull secrets if their role allows it

This prevents a basic member from creating long-lived production access keys.

### What token metadata should include

* token id
* project id
* environment id
* name
* created by
* expiry timestamp
* permissions such as `read:secrets`
* last used time
* revoked flag

### Important clarification

Tokens do **not** store the actual API keys.

Tokens only answer the question:

> Is this app allowed to fetch secrets for this project and environment right now?

### Runtime behavior

* app uses `ENVSAFE_TOKEN`
* SDK sends token to server
* server validates token
* server returns project secrets
* SDK loads secrets into memory
* token may expire later, but secrets already loaded in memory remain usable while the process is alive

---

## 11. Push and Pull Model

### `envbasis push`

Purpose:

* upload local `.env` values to server
* create or update secrets under the selected project/environment
* version changed values
* write audit logs

### `envbasis pull`

Purpose:

* fetch latest secrets from server
* generate local `.env`
* support onboarding and environment sync
* write audit logs

### Important design rule

The server should treat the project/environment as the source of truth. Tokens are not the source of truth.

---

## 12. Suggested Database Schema

### `users`

* id
* email
* Supabase-auth-backed identity
* created_at

### `projects`

* id
* name
* owner_id
* created_at

### `environments`

* id
* project_id
* name
* created_at

### `project_members`

* id
* project_id
* user_id
* role
* invited_by
* created_at

### `secrets`

* id
* environment_id
* key
* encrypted_value
* version
* updated_by
* updated_at

### `runtime_tokens`

* id
* project_id
* environment_id
* token_hash
* name
* expires_at
* created_by
* revoked_at
* last_used_at

### `audit_logs`

* id
* project_id
* environment_id
* user_id
* action
* metadata_json
* created_at

---

## 13. Security Model

### Baseline security

* HTTPS everywhere
* encrypt secrets at rest
* use Supabase Auth for password handling and session issuance
* store hashed runtime tokens for runtime validation
* store an encrypted copy of runtime tokens only when the backend needs authorized owner/member reveal or sharing
* runtime token reveal and sharing should remain restricted to authorized users
* short token expiry supported
* audit every push, pull, invite, revoke, token creation, and token usage

### Local machine behavior

For MVP:

* `envbasis pull` writes a real `.env` file
* CLI must never print secret values in logs
* CLI should warn if writing into a tracked Git repo and `.env` is not ignored

### Runtime behavior

* apps should use read-only runtime tokens
* runtime tokens should not support pushing or editing secrets
* apps fetch at startup, not every request, in MVP

---

## 14. Local Tracking and Secret Safety Features

This can become a strong differentiator because it makes the product more powerful than many secret managers.

### MVP-friendly tracking

1. **Audit pulls and pushes**

   * who uploaded secrets
   * who pulled secrets
   * when and for which environment

2. **Git safety check in CLI**

   * before `envbasis pull`, check if repo has `.gitignore`
   * warn if `.env` may be committed

3. **Secret detection before push to Git**

   * optional `envbasis scan`
   * detect known keys in tracked files
   * warn before commit or push

4. **Token usage logs**

   * track which runtime token fetched secrets
   * show last used machine or IP if possible

5. **Leak alerts later**

   * notify project owner or admin when a secret appears in a Git diff or suspicious place

### Important realism

True OS-level copy, move, or paste tracking is hard and should not be part of MVP. Start with Git-aware monitoring and audit logs.

---

## 15. Versioning Model

Every `envbasis push` should create a new version for any changed key.

Example:

* `OPENAI_API_KEY` version 1
* `OPENAI_API_KEY` version 2 after update

Benefits:

* auditability
* rollback later
* safer collaboration
* conflict visibility

### MVP conflict rule

* latest push wins
* version history preserved

Later you can add:

* diff preview
* push confirmation on conflict
* rollback to previous version

---

## 16. SDK / Runtime Loader

### MVP behavior

Simple startup loader.

Example conceptual usage in Node:

```js
import { loadEnvbasis } from "envbasis-sdk";
await loadEnvbasis();
```

Example conceptual usage in Python:

```python
from envbasis_sdk import load_envbasis
load_envbasis()
```

### What loader does

* reads `ENVSAFE_TOKEN`
* calls Envbasis API
* retrieves secrets
* sets them into process environment or memory

### MVP limitation

If secrets change after startup, the running app does not update automatically. App must restart or explicitly refresh later.

---

## 17. API Design Sketch

### Auth

* `GET /auth/me`
* sign up and log in handled by Supabase Auth clients

### Projects

* `POST /projects`
* `GET /projects`
* `POST /projects/:id/invite`
* `POST /projects/:id/revoke`

### Environments

* `POST /projects/:id/environments`
* `GET /projects/:id/environments`

### Secrets

* `POST /projects/:id/environments/:env_id/secrets/push`
* `GET /projects/:id/environments/:env_id/secrets/pull`

### Runtime tokens

* `POST /projects/:id/environments/:env_id/runtime-tokens`
* `POST /runtime-tokens/:id/revoke`
* `GET /projects/:id/runtime-tokens`

### Runtime fetch

* `POST /runtime/secrets`

### Audit

* `GET /projects/:id/audit-logs`

---

## 18. Recommended Tech Stack for MVP

### Backend

* **Python + FastAPI**
* FastAPI will handle auth verification, project logic, secret push/pull, runtime token validation, audit logs, and encryption/decryption
* Keep all secret reads and writes behind FastAPI

### Frontend

* **React** for the dashboard
* Use a simple dashboard-first UI with these views:

  * sign up / log in
  * projects list
  * create project
  * project detail
  * environments
  * members
  * secrets manager
  * runtime tokens
  * audit logs
* Frontend should never directly read raw secret values from the database

### Database and Auth

* **Supabase** is a good fit for MVP
* Use Supabase for:

  * Postgres database
  * Auth
  * Row Level Security as defense in depth
* FastAPI remains the main control plane for secret operations

### Recommended architecture with Supabase

* React handles user interface
* Supabase Auth handles user login and sessions
* React sends authenticated requests to FastAPI
* FastAPI validates the user and performs secret operations
* FastAPI stores encrypted secrets in Supabase Postgres
* Runtime fetch for apps also goes through FastAPI, not directly to Supabase

### Why this architecture is recommended

* faster MVP development
* managed Postgres and Auth out of the box
* easier team and user management
* better control over secret encryption and business logic
* prevents accidental exposure through direct frontend-to-database secret access

### Important rule

**Do not let the browser talk directly to secret tables for raw secret values.**
Use FastAPI as the only backend that can encrypt, decrypt, and return secrets.

### Encryption strategy

Recommended approach for MVP:

* store encrypted secret values in normal Postgres tables in Supabase
* perform encryption and decryption inside FastAPI using an app-controlled master key
* store only ciphertext in the database
* store token hashes, not plaintext tokens

Optional later:

* evaluate **Supabase Vault**, which is an official Supabase feature for encrypted secret storage in Postgres, but it is still marked as **Public Beta**

### Notes on Supabase usage

* Supabase Auth officially supports password-based auth and React integration
* Supabase Free projects with very low activity may be paused after 7 days, so move to Pro when testing seriously
* backups are limited on the Free plan

## 19. Frontend Product Plan

### Frontend goals

The dashboard should be simple enough that a user can understand the product quickly and complete core setup without reading docs.

### MVP pages

#### 1. Auth

* sign up
* log in
* forgot password later

#### 2. Projects page

* list projects
* create project
* open project

#### 3. Project overview

* project name
* available environments
* quick actions: push guide, invite teammate, create runtime token

#### 4. Environments page

* list environments such as `dev`, `staging`, `prod`
* add environment
* select current environment in dashboard

#### 5. Secrets page

* show key names only by default
* add secret manually
* bulk upload `.env`
* edit or delete secret
* show last updated time and version
* avoid exposing secret values by default

#### 6. Runtime tokens page

* create runtime token
* set token name
* set token environment
* set expiry
* show token once after creation
* revoke token
* show last used time

#### 7. Team page

* invite teammate by email
* list current members
* revoke member access
* roles can stay minimal in MVP

#### 8. Audit logs page

* show pushes
* pulls
* token creation
* token usage
* member invites and revocations

### Frontend UX principles

* do not overload the user with enterprise security concepts
* use very clear language like project, environment, member, token, push, pull
* show onboarding hints for CLI commands
* make token creation feel sensitive and deliberate
* show warnings when a token is displayed because it will only be shown once

### Frontend and CLI relationship

The dashboard handles:

* setup
* visibility
* administration
* token visibility and management

The CLI handles:

* daily dev workflow
* push
* pull
* owner-only token creation and revocation
* run
* scan later

That split should be consistent throughout the product.

## 20. Phased Build Roadmap

### Phase 1: Core MVP

Goal: secure push/pull for teams

* auth
* project creation
* environment creation
* `envbasis push`
* `envbasis pull`
* encrypted storage
* team invites
* revoke access
* audit logs
* owner token creation and revocation through shared backend APIs
* runtime secret fetch API

### Phase 2: Better developer experience

* `envbasis diff`
* `envbasis history`
* `envbasis rollback`
* `envbasis run`
* Git safety checks
* token usage dashboard

### Phase 3: Differentiation

* leak alerts
* suspicious usage notifications
* secret scanning in repo changes
* hackathon mode with temporary projects or expiring access
* scoped machine sessions

---

## 20. Hackathon Mode Opportunity

A strong wedge is short-lived secret sharing for hackathons and temporary teams.

Potential features later:

* fast project creation
* temporary team invites
* auto-expiring runtime tokens
* 24h or 72h project expiration options
* one-command bootstrap for teammates

This is a strong differentiator because many teams skip enterprise tools in hackathons and share `.env` files insecurely.

---

## 21. Biggest Risks

1. **Overbuilding too early**

   * do not start with enterprise complexity
2. **Weak auth model**

   * avoid shared project password model
3. **Confusing storage model**

   * secrets must live under projects, not tokens
4. **Trying to solve impossible local tracking too early**

   * do Git-aware detection first
5. **Poor DX**

   * CLI must be very simple

---

## 22. Success Criteria for MVP

MVP is successful if a small team can:

* create a project in minutes
* push a `.env` file securely
* invite a teammate
* teammate can pull envs without Slack or Discord sharing
* production app can fetch envs at startup using runtime token
* project owner can see who accessed what

---

## 23. Sharp Product Summary

Envbasis is a developer-first secrets workflow for teams that still share `.env` files manually. It lets users securely push and pull environment variables, manage runtime access through owner-created temporary tokens from CLI or dashboard, and add auditability and Git-aware safety checks without the complexity of enterprise secrets infrastructure.

---

## 24. System Architecture and Communication Model

The system follows a simple three-layer architecture:

```
React Dashboard
        ↓
    FastAPI Backend
        ↓
   Supabase (Postgres + Auth)
```

In addition to the dashboard, two other clients communicate with the backend:

```
CLI  →  FastAPI Backend  →  Supabase
SDK  →  FastAPI Backend  →  Supabase
```

FastAPI acts as the **central control plane** of the system.

### Important Rules

* CLI never talks directly to Supabase
* Frontend never reads raw secret tables
* All encryption and decryption happens inside FastAPI
* Runtime token validation happens inside FastAPI

This ensures consistent security and permission checks.

---

## 25. Request Flow Examples

### CLI Push Flow

When a developer uploads secrets from their machine.

```
CLI
 ↓
POST /projects/:id/environments/:env_id/secrets/push
 ↓
FastAPI
 ↓
Encrypt secret values
 ↓
Store ciphertext
 ↓
Supabase Postgres
```

### CLI Pull Flow

When a developer retrieves secrets for local development.

```
CLI
 ↓
GET /projects/:id/environments/:env_id/secrets/pull
 ↓
FastAPI
 ↓
Read encrypted secrets
 ↓
Decrypt values
 ↓
Return plaintext
```

The CLI then writes the `.env` file locally.

### Runtime Secret Fetch Flow

When an application starts in production.

```
Application / SDK
 ↓
POST /runtime/secrets
Authorization: Bearer ENVSAFE_TOKEN
 ↓
FastAPI
 ↓
Validate runtime token
 ↓
Fetch encrypted secrets
 ↓
Decrypt
 ↓
Return secrets to application
```

The application stores the secrets in memory for the duration of the process.

### Dashboard Flow

Administrative actions are performed through the dashboard.

```
React Dashboard
 ↓
FastAPI
 ↓
Supabase
```

Example actions:

* create project
* invite team member
* create runtime token
* revoke token
* view audit logs

---

## 26. Why FastAPI Is the Control Plane

FastAPI performs all sensitive operations including:

* authentication verification
* project membership checks
* secret encryption before storage
* secret decryption when returned
* runtime token validation
* audit logging

Keeping these operations inside the backend prevents accidental exposure of secret data and ensures a consistent security model.

---

## 27. CLI Interaction Model

The CLI communicates directly with the backend API.

Typical CLI lifecycle:

```
envbasis login
envbasis push
envbasis pull
```

Example interaction:

```
CLI
 ↓
FastAPI
 ↓
Supabase
```

Responsibilities of the CLI:

* reading `.env` files locally
* sending secrets to the backend
* receiving secrets from the backend
* generating local `.env` files
* assisting developer workflows

The CLI never performs encryption logic directly against the database.

---

## 28. SDK Runtime Interaction Model

Applications use a lightweight SDK to fetch secrets at startup.

Example runtime flow:

```
App Start
 ↓
SDK reads ENVSAFE_TOKEN
 ↓
SDK calls backend
 ↓
Backend validates token
 ↓
Backend returns decrypted secrets
 ↓
SDK loads them into environment memory
```

Important behavior:

* secrets remain in memory while the process runs
* runtime token expiration only prevents future fetches
* already loaded secrets remain usable until process restart

---

## 29. Future Architecture Extensions

If the platform grows significantly, additional services may be introduced such as:

* event collector service
* telemetry processing
* leak detection pipeline
* secret scanning workers

However, **these are not required for the MVP**.

The MVP architecture should remain simple:

```
CLI / SDK / Dashboard
        ↓
      FastAPI
        ↓
     Supabase
```

This keeps the system easy to build, secure, and understandable for early users.

---

## 30. Pending Invitation Flow Later

Current limitation in the backend:

* member invite works only after the invited user has authenticated at least once
* there is no dedicated invitation table yet

Planned improvement:

* add a `project_invitations` table so owners can invite users before they sign up
* invitation should be created using email, project id, role, invited by, token, status, created at, and expires at
* invitation validity should be **15 days**
* if the user signs up within 15 days, they can accept the invitation and become a project member
* if the invitation expires before signup or acceptance, the owner must send a new invitation

Suggested `project_invitations` fields:

* id
* project_id
* email
* role
* invited_by
* invite_token_hash
* status such as `pending`, `accepted`, `expired`, `revoked`
* expires_at
* accepted_at
* created_at

Suggested flow:

1. Owner invites a user by email even if that user does not exist yet in `users`
2. Backend stores a pending invitation with a 15-day expiry
3. User signs up later
4. Backend matches the signed-up email to pending invitations
5. User accepts the invitation
6. Backend creates the `project_members` row
7. Invitation status moves to `accepted`

---

## 31. Shared Client TODO

The backend should remain client-agnostic.

This means:

* the CLI and the dashboard frontend both use the same FastAPI backend
* the backend is the shared control plane for auth, authorization, encryption, versioning, runtime token management, and audit logs
* secret or API key changes inside a project should be possible from both the CLI and the frontend

Current shape:

* CLI fits naturally with `push` and `pull`
* frontend can also use backend secret APIs
* backend must not assume one client type

Future improvement for frontend-friendly secret management:

* add single-secret create endpoint
* add single-secret update endpoint
* add single-secret delete endpoint
* add secret metadata list endpoint that returns key names, versions, and timestamps without returning secret values by default

Important rule:

* CLI and frontend should never bypass FastAPI for secret operations
* all secret reads and writes must go through the backend

---

## 32. Runtime Token Sharing TODO

Hackathon and testing workflows may require owners to share runtime tokens with members.

Rules:

* only project owners can create, revoke, and share runtime tokens
* members cannot create runtime tokens themselves
* owners may share only with existing project members
* shared members may view and use only the specific runtime tokens shared with them
* runtime token sharing must not grant project ownership or broader admin rights
* if a shared member is removed from the project, the share relationship for that member must be removed immediately
* removing a member must not automatically revoke the underlying runtime token unless the owner chooses to revoke or rotate it

Backend requirements:

* add a `runtime_token_shares` table
* keep runtime token hashes for runtime validation
* keep an encrypted token copy so authorized users can reveal a shared token when needed
* audit token share and token reveal actions
* when an owner removes a member who had shared runtime tokens, the backend should notify the owner or ask for confirmation about whether the underlying token should also be revoked or rotated

---

## 33. Member Push/Pull Access TODO

Project membership should explicitly control human secret access.

Rules:

* different projects can have different member lists
* members with project access may push and pull secrets for that project when their role allows it
* owners keep higher-level admin powers such as invite, revoke, token create, token share, and token revoke
* push and pull permission checks must be enforced in the backend for both CLI and frontend clients

Future improvement:

* if needed later, add finer-grained environment-level access such as allowing a member to access `dev` but not `prod`

---

## 34. Memory Safety Check Later

Temporary secret handling in backend memory is expected during normal operation.

Important points:

* plaintext secrets will exist briefly in backend RAM during encrypt, decrypt, push, and pull operations
* this should not become a long-lived in-memory secret cache
* this normal request-time memory use should not make the system heavy by itself because `.env` payloads are expected to stay small

Things to verify before release:

* confirm the backend is not retaining plaintext secrets in an application-level cache after request completion
* add reasonable request size limits for secret push and pull operations
* monitor process memory and response size during local and staging load tests
* review logs and error handling to ensure plaintext secret values are never written accidentally
