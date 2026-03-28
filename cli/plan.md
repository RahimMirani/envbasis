Build the CLI as a thin authenticated client over the backend API. It should not talk directly to Supabase tables or the database. The backend already has the right surface for this: project/environment management, secret push/pull and single-secret CRUD, member management, audit logs, runtime token sharing, runtime fetch, and now token actions by name.

Recommended Stack
Use Python.

Typer for the CLI UX
httpx for API requests
pydantic for config and API models
rich for tables, prompts, status, and error output
keyring for storing the access token securely
python-dotenv for .env parsing/writing
tomli / tomllib for local project config
pytest + respx for tests
uv for dependency management and packaging
distribute with pipx
Why Python:

backend is already Python/FastAPI
easiest mapping of request/response models
best fit for .env workflows and local tooling
fastest path to a solid CLI
If you wanted a binary-first install story, Go is the second-best option. I would not choose Node here.

CLI Repo Shape
Use something like:

src/envbasis_cli/main.py
src/envbasis_cli/commands/auth.py
src/envbasis_cli/commands/projects.py
src/envbasis_cli/commands/environments.py
src/envbasis_cli/commands/secrets.py
src/envbasis_cli/commands/members.py
src/envbasis_cli/commands/tokens.py
src/envbasis_cli/commands/audit.py
src/envbasis_cli/client.py
src/envbasis_cli/config.py
src/envbasis_cli/output.py
Local CLI State
Store two things:

secure token in OS keychain
local config in .envbasis.toml
Suggested local config:

api_base_url = "https://api.yourdomain.com/api/v1"
project_id = "..."
project_name = "my-app"
environment = "dev"
Auth Plan
Right now backend expects a bearer token and exposes GET /auth/me, but it does not mint login tokens itself.

So CLI auth should be one of these:

envbasis login --token <access-token> for MVP
or later integrate Supabase email/password/device flow in CLI
For now, the simplest path is:

user gets Supabase access token
CLI stores it securely
CLI uses it for all backend calls
Commands:

envbasis login --token ...
envbasis logout
envbasis whoami
Core Command Plan
Phase 1 should be:

envbasis whoami

envbasis projects list

envbasis project create --name ... --description ...

envbasis project use <project-name|project-id>

envbasis project show

envbasis project update --name ... --description ...

envbasis env list

envbasis env create <name>

envbasis push

envbasis pull

envbasis secrets list

envbasis secrets stats

envbasis secrets set KEY VALUE

envbasis secrets update KEY VALUE

envbasis secrets delete KEY

envbasis members list

envbasis invite user@email.com

envbasis members access user@email.com --allow

envbasis members access user@email.com --deny

envbasis revoke user@email.com

envbasis token create --name cli-prod-api --env prod --expires 30d

envbasis token list

envbasis token reveal --name cli-prod-api

envbasis token revoke --name cli-prod-api

envbasis token share --name cli-prod-api --email member@email.com

envbasis token shares --name cli-prod-api

envbasis audit logs

How Each Command Maps
Examples:

envbasis env list
calls GET /projects/{project_id}/environments

envbasis env create dev
calls POST /projects/{project_id}/environments

envbasis secrets stats
calls GET /projects/{project_id}/secrets/stats
This is metadata-only and does not pollute audit logs.

envbasis project update
calls PATCH /projects/{project_id}

envbasis token reveal --name cli-prod-api
calls the backend by-name endpoint

envbasis token revoke --name cli-prod-api
calls the backend by-name endpoint
Revoke now means audit log + immediate deletion of the token row.

Secret Workflow UX
push:

read .env
parse key/value pairs
upload via push endpoint
show changed vs unchanged keys
pull:

fetch secrets for current environment
write .env
support --stdout
support --format dotenv|json
secrets set/update/delete:

use single-secret endpoints
do not require rewriting the whole .env
Important Git safety:

warn if .env is tracked or not ignored
ask for confirmation before overwriting an existing .env
Token UX
Use token names as the main human handle.

Rules:

token names must be unique among active tokens in a project
CLI should default to name-based token actions
if needed, still support --id
This is now aligned with the backend.

Output Style
Use rich tables for:

projects
environments
members
tokens
audit logs
Use clear one-line success messages for mutations:

Created environment dev
Updated 4 secrets, 12 unchanged
Revoked token cli-prod-api
Testing Plan
At minimum test:

auth token loading and storage
project/environment resolution
.env parse and write behavior
push/pull happy path
secret set/update/delete
token create/reveal/revoke by name
member revoke flow with shared-token confirmation errors
API error rendering
Best Build Order

auth/config/client layer
whoami
projects list + project use
env list
push
pull
secrets list/stats/set/update/delete
members
tokens
audit logs

Use this as the CLI spec for the separate repo.

Global Rules
Binary name:

envbasis
Global options:

--api-url
--project
--env
--json
--verbose
Resolution order:

explicit flag
local .envbasis.toml
fail with a clear message
Local config file:

.envbasis.toml
Example:

api_base_url = "https://api.example.com/api/v1"
project_id = "..."
project_name = "my-app"
environment = "dev"
Auth
envbasis login --token <access-token>

stores token in OS keychain
verifies with GET /auth/me
envbasis logout

removes stored token
envbasis whoami

calls GET /auth/me
shows user id and email
Example:

envbasis login --token eyJ...
envbasis whoami
Projects
envbasis projects list

GET /projects
show name, role, env count, member count, token count, last activity
envbasis project create --name <name> [--description <text>]

POST /projects
envbasis project show

GET /projects/{project_id}
envbasis project use <project-name-or-id>

resolves a project from projects list
stores it in .envbasis.toml
envbasis project update [--name <name>] [--description <text>]

PATCH /projects/{project_id}
envbasis project delete

DELETE /projects/{project_id}
require explicit confirmation
do not hide that this is destructive
Examples:

envbasis projects list
envbasis project create --name my-ai-app --description "Hackathon app"
envbasis project use my-ai-app
envbasis project update --description "Internal staging app"
Environments
envbasis env list

GET /projects/{project_id}/environments
envbasis env create <name>

POST /projects/{project_id}/environments
owner-only
Examples:

envbasis env list
envbasis env create dev
envbasis env create prod
Secrets
envbasis push [--file .env]

reads dotenv file
POST /projects/{project_id}/environments/{environment_id}/secrets/push
shows changed/unchanged counts
envbasis pull [--file .env] [--stdout] [--format dotenv|json]

GET /projects/{project_id}/environments/{environment_id}/secrets/pull
envbasis secrets list

GET /projects/{project_id}/environments/{environment_id}/secrets
show key, version, updated, updated by
default: do not print raw secret values unless --reveal
envbasis secrets stats

GET /projects/{project_id}/secrets/stats
show total count + per-env counts + last activity
envbasis secrets set <KEY> <VALUE>

POST /projects/{project_id}/environments/{environment_id}/secrets
envbasis secrets update <KEY> <VALUE>

PATCH /projects/{project_id}/environments/{environment_id}/secrets/{KEY}
envbasis secrets delete <KEY>

DELETE /projects/{project_id}/environments/{environment_id}/secrets/{KEY}
Useful flags:

--file
--reveal
--stdin for value input later
--yes for overwrite confirmation
Examples:

envbasis push --file .env
envbasis pull --file .env
envbasis pull --stdout
envbasis secrets list
envbasis secrets stats
envbasis secrets set OPENAI_API_KEY sk-...
envbasis secrets update OPENAI_API_KEY sk-new...
envbasis secrets delete OPENAI_API_KEY
Team
envbasis members list

GET /projects/{project_id}/members
envbasis invite <email>

POST /projects/{project_id}/invite
optional later: --no-secret-access
envbasis members access <email> --allow|--deny

POST /projects/{project_id}/members/access
envbasis revoke <email>

POST /projects/{project_id}/revoke
if backend returns token-share confirmation conflict, CLI should print details and require retry with:
--keep-shared-tokens
--revoke-shared-tokens
Examples:

envbasis members list
envbasis invite dev@team.com
envbasis members access dev@team.com --deny
envbasis revoke dev@team.com --keep-shared-tokens
Runtime Tokens
envbasis token list

GET /projects/{project_id}/runtime-tokens
envbasis token create --name <token-name> --env <env-name> [--expires 30d|90d|never]

resolve env name to env id
POST /projects/{project_id}/environments/{environment_id}/runtime-tokens
show plaintext token once
strongly warn user to copy it
envbasis token reveal --name <token-name>

POST /projects/{project_id}/runtime-tokens/reveal-by-name
envbasis token revoke --name <token-name>

POST /projects/{project_id}/runtime-tokens/revoke-by-name
note: revoke deletes token immediately after audit logging
envbasis token share --name <token-name> --email <email>

list tokens, resolve name to id
POST /runtime-tokens/{token_id}/share
envbasis token shares --name <token-name>

list tokens, resolve name to id
GET /runtime-tokens/{token_id}/shares
Examples:

envbasis token list
envbasis token create --name cli-prod-api --env prod --expires 90d
envbasis token reveal --name cli-prod-api
envbasis token share --name cli-prod-api --email member@team.com
envbasis token shares --name cli-prod-api
envbasis token revoke --name cli-prod-api
Audit Logs
envbasis audit logs

GET /projects/{project_id}/audit-logs
owner-only
show actor, action, environment, created at
Flags:

later add --limit
later add --action
later add --env
Example:

envbasis audit logs
Error Handling
CLI should normalize backend errors into readable messages.

Examples:

401 → “You are not logged in.”
403 → “You do not have permission for this action.”
404 → “Project/environment/token not found.”
409 → show backend conflict text directly
For member revoke special case:

print affected shared tokens
instruct user to retry with --keep-shared-tokens or --revoke-shared-tokens
Output Conventions
Default:

human-readable tables and short success messages
With --json:

raw machine-friendly JSON for scripting
Examples:

Created environment dev
Pushed 4 changed secrets, 12 unchanged
Revoked token cli-prod-api
Selected project my-ai-app
Good First Milestone
Implement these first:

login
whoami
projects list
project use
env list
push
pull
token list
token create
token reveal --name
token revoke --name
That will already make the CLI genuinely usable.