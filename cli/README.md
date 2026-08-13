# EnvBasis CLI

EnvBasis CLI is a thin authenticated command-line client for the EnvBasis backend API. It gives teams a consistent way to sign in, select a project and environment, sync `.env` files, manage individual secrets, administer project access, and work with runtime tokens without talking directly to the database.

It is built with Python, Typer, `httpx`, `pydantic`, `rich`, `keyring`, and `python-dotenv`, and is packaged as the `envbasis` command.

## Feature Summary

- Keyring-backed CLI session handling
- Secure session storage in the OS keyring
- Interactive `envbasis init` setup with server, project, and environment validation
- In-memory process injection with `envbasis run -- <command>`
- Development watch mode with safe child-process restarts
- Dedicated dotenv, JSON, YAML, and shell exports
- Filesystem and Git secret scanning with redacted findings
- Project and environment selection stored in local working-directory config
- Automatic numbered project/environment selection when context is missing
- Simple `envbasis secret` name listing and `envbasis secrets pull` retrieval
- `.env` push and `secrets pull` workflows
- Single-secret CRUD commands for targeted updates
- Member listing, invitation, access management, and revoke flows
- Runtime token creation, reveal, revoke, share, and audit visibility
- Human-friendly table output and `--json` output for scripting

## What The CLI Does Today

The current CLI supports these areas:

- Authentication: `login`, `logout`, `whoami`
- Initialization: `init`
- Process injection: `run`
- Automation: `export`
- Secret scanning: `scan`
- Context inspection: `context`
- Project workflows: `project --select`, `projects list`, `project create`, `project show`, `project update`
- Environment workflows: `environment`, `env list`, `env create`
- Secret sync: `secret`, `push`, and `secrets pull`
- Secret management: `secrets stats`, `secrets set`, `secrets update`, `secrets delete`
- Member workflows: `members list`, `members access`, plus top-level `invite` and `revoke`
- Runtime tokens: `token list`, `token create`, `token reveal`, `token revoke`, `token share`, `token shares`
- Audit logs: `audit logs`

The normal everyday workflow is intentionally short:

- `envbasis secret` lists secret names for the selected context.
- `envbasis secrets pull` retrieves values and writes `.env` by default.
- If no project or environment is selected, interactive commands show numbered choices and save the answer.
- `invite` and `revoke` are top-level commands. Member listing and access toggles live under `members`.

## Install And Requirements

### Requirements

- Python 3.11 or newer
- Access to an EnvBasis API deployment
- A working OS keyring backend

### Install From PyPI

After the repository owner enables the included PyPI trusted-publishing workflow and creates the first release:

```bash
pipx install envbasis-cli
```

Upgrade later with `pipx upgrade envbasis-cli`.

### Install From This Repository

If you want an isolated user install from a checkout of this repo, run this from the repo root:

```bash
pipx install ./cli
```

If you prefer a standard Python install:

```bash
python -m pip install ./cli
```

After installation, the CLI is available as:

```bash
envbasis --help
envbasis --version
```

Shell completion is available for Bash, Zsh, and Fish through Typer's built-in installers:

```bash
envbasis --install-completion
envbasis --show-completion
```

## Authentication And Required Configuration

The CLI only needs your EnvBasis backend API URL and stores authenticated sessions in your OS keyring.

### Required Settings

Hosted users automatically use `https://api.envbasis.com/api/v1`. Self-hosted users can override the API URL during login or initialization.

The recommended setup is a local `.envbasis.toml`, so you can use the CLI directly without re-exporting values in every shell.

### Recommended Setup: Local Config File

The CLI searches the current directory and then its parents for the nearest `.envbasis.toml`. This lets every package in a monorepo inherit one repository-level configuration. If no file exists, `envbasis init` creates one in the current directory.

The `project_id`, `project_name`, and `environment` fields are optional. They are written automatically after an interactive choice, or manually with `envbasis project --select <name>` and `envbasis environment <name>`.

Example:

```toml
config_version = 1
api_base_url = "https://api.example.com/api/v1"
project_id = "proj_123"
project_name = "my-app"
environment = "dev"
```

The recommended setup flow is:

```bash
envbasis login
envbasis init
envbasis whoami
envbasis secret
envbasis secrets pull
envbasis push --file .env
envbasis run -- npm run dev
```

`envbasis init` validates the authenticated API connection, lists the projects and environments available to the current user, and saves the selected values only after every check succeeds.

For a self-hosted deployment:

```bash
envbasis --api-url https://secrets.company.com/api/v1 login
envbasis init
```

Validate the discovered configuration and its remote selections at any time:

```bash
envbasis config check
```

For scripts, prompts can be replaced with explicit selections:

```bash
envbasis init \
  --api-url https://secrets.company.com/api/v1 \
  --project my-app \
  --env dev \
  --no-input
```

### Optional Alternative: Environment Variables

If you do not want to keep a local `.envbasis.toml`, the CLI can also read these environment variables:

- `ENVBASIS_API_URL`

### Session Behavior

- Login stores the authenticated session in the OS keyring, not in `.envbasis.toml`.
- Expired sessions are cleared locally and you will need to log in again.

### Deployed Services And Universal Auth

For a deployed service, CI job, or agent, create a Machine Identity in the console and store its one-time client ID and client secret in the deployment platform. Exchange them at startup and expose only the short-lived token to CLI commands:

```bash
export ENVBASIS_TOKEN="$(envbasis login \
  --method universal-auth \
  --client-id "$ENVBASIS_CLIENT_ID" \
  --client-secret "$ENVBASIS_CLIENT_SECRET" \
  --plain)"

envbasis --project demo-api --env production secret
```

The client secret is never saved in `.envbasis.toml` or the OS keyring. `ENVBASIS_TOKEN` overrides an interactive keyring session for the lifetime of the process and expires according to the Machine Identity policy.

## How To Use It

### 1. Sign in

```bash
envbasis login
```

Verify the session:

```bash
envbasis whoami
```

### 2. Initialize the working directory

```bash
envbasis init
```

### 3. Create or change the selected project

```bash
envbasis project create --name my-app --description "Internal service"
envbasis projects list
envbasis project --select my-app
envbasis project show
```

### 4. Create or select an environment

```bash
envbasis env create dev
envbasis env create prod
envbasis environment dev
envbasis env list
```

### 5. Push a local `.env` file

```bash
envbasis push --file .env
```

Preview a masked diff before pushing:

```bash
envbasis push --file .env --review
envbasis push --file .env --review --yes
```

### 6. Pull secrets back into a file

```bash
envbasis secrets pull --file .env
```

To inspect what the CLI would pull without writing a file:

```bash
envbasis secrets pull --stdout
envbasis secrets pull --stdout --format json
```

### 7. Inspect the resolved CLI context

```bash
envbasis context
```

## Command Map

### Global Options

These options are available before any command:

- `--api-url`
- `--project`
- `--env`
- `--json`
- `--verbose`

### Root Commands

| Command | Purpose |
| --- | --- |
| `login` | Start the backend website-based device login flow |
| `logout` | Clear the stored session from keyring |
| `whoami` | Show the authenticated user |
| `init` | Validate the API and interactively configure a project and environment |
| `run` | Run a child process with remote secrets injected only into its environment |
| `export` | Export remote secrets to stdout or a file in automation-friendly formats |
| `scan` | Detect likely credentials in files, directories, and Git changes/history |
| `push` | Upload a dotenv file into the selected project and environment |
| `invite` | Invite a member to the selected project |
| `revoke` | Revoke a member from the selected project |
| `context` | Show the resolved API URL, project, environment, and output mode |

### Command Groups

| Group | Commands |
| --- | --- |
| `projects` | `list` |
| `project` | `create`, `show`, `use`, `update` |
| `env` | `list`, `create`, `use` |
| `secrets` | `list`, `stats`, `set`, `update`, `delete` |
| `members` | `list`, `access` |
| `token` | `list`, `create`, `reveal`, `revoke`, `share`, `shares` |
| `audit` | `logs` |
| `config` | `check`, `migrate` |

## Detailed Usage

### Authentication

Login uses a backend-issued device flow:

```bash
envbasis login
```

The CLI prints:

- a short `user_code`
- the approval URL returned by the backend

It may try to open that URL in your browser, but browser launch is best-effort only and never required.

Show the authenticated identity:

```bash
envbasis whoami
```

Clear the stored session:

```bash
envbasis logout
```

### Projects

List projects:

```bash
envbasis projects list
```

Create a project:

```bash
envbasis project create --name my-app --description "Internal service"
```

Select the active project by name or ID:

```bash
envbasis project --select my-app
```

Show the selected project:

```bash
envbasis project show
```

Update the selected project:

```bash
envbasis project update --name my-renamed-app
envbasis project update --description "New description"
```

`project --select` writes `project_id` and `project_name` into `.envbasis.toml` and clears any previously saved environment selection.

### Environments

List environments for the selected project:

```bash
envbasis env list
```

Create an environment:

```bash
envbasis env create dev
```

Select the active environment by name or ID:

```bash
envbasis environment dev
```

Environment resolution behavior:

- If exactly one environment exists and none is selected, the CLI uses it automatically.
- If multiple environments exist and none is selected, interactive commands show numbered choices and save the selection.
- JSON automation never prompts; pass `--project` and `--env` explicitly.

### Simple Secret Commands

List only secret names:

```bash
envbasis secret
```

Pull secrets into `.env`:

```bash
envbasis secrets pull
```

Print pulled values as JSON when you explicitly need stdout:

```bash
envbasis secrets pull --stdout --format json
```

### Secret Sync: `push` And `secrets pull`

Push a dotenv file into the selected environment:

```bash
envbasis push --file .env
```

Preview a masked diff, then confirm before pushing:

```bash
envbasis push --file .env --review
```

Show the same review diff but skip the confirmation prompt:

```bash
envbasis push --file .env --review --yes
```

Pull secrets into a dotenv file:

```bash
envbasis secrets pull --file .env
```

Pull secrets as JSON to stdout:

```bash
envbasis secrets pull --stdout --format json
```

Write JSON to a file instead of dotenv format:

```bash
envbasis secrets pull --file secrets.json --format json --overwrite
```

Important behavior:

- `push` reads the specified dotenv file and uploads parsed key/value pairs.
- `push --review` compares the local dotenv payload with the current remote secrets and prints a masked Git-style diff before any push request is sent.
- `push --review --yes` prints the same diff and skips the confirmation prompt.
- `push --yes` is invalid unless you also pass `--review`.
- `push` fails if the file does not exist or contains no parsed keys.
- `secrets pull` prompts before overwriting an existing file unless you pass `--overwrite`.
- `secrets pull --stdout` skips file writes entirely.
- Before reading or writing a secret file, the CLI warns if that path is tracked by git or is not ignored.

### Secret CRUD

List secret names for the selected environment:

```bash
envbasis secret
```

Show project-level secret statistics:

```bash
envbasis secrets stats
```

Create a single secret:

```bash
envbasis secrets set OPENAI_API_KEY sk-test
```

Update a single secret:

```bash
envbasis secrets update OPENAI_API_KEY sk-new
```

Delete a single secret:

```bash
envbasis secrets delete OPENAI_API_KEY
```

Important behavior:

- `secret` lists names only; use `secrets pull` when values are required.
- Single-secret commands operate on the currently resolved project and environment and do not rewrite the whole `.env` file.

### Members, Invitations, And Revoke Flows

List members:

```bash
envbasis members list
```

Grant secret access:

```bash
envbasis members access teammate@example.com --allow
```

Deny secret access:

```bash
envbasis members access teammate@example.com --deny
```

Invite a member:

```bash
envbasis invite teammate@example.com
```

Revoke a member:

```bash
envbasis revoke teammate@example.com
```

Control revoke behavior when shared runtime tokens exist:

```bash
envbasis revoke teammate@example.com --keep-shared-tokens
envbasis revoke teammate@example.com --revoke-shared-tokens
```

Important behavior:

- `members access` requires exactly one of `--allow` or `--deny`.
- `revoke` is a top-level command, not `members revoke`.
- If revoke returns a conflict because the member owns shared runtime tokens and you did not pass a handling flag, the CLI prompts you to choose whether to keep or revoke those shared tokens.

### Runtime Tokens

List tokens for the selected project:

```bash
envbasis token list
```

Create a token for a specific environment:

```bash
envbasis token create --name cli-prod-api --env prod --expires 90d
```

Reveal a token by name:

```bash
envbasis token reveal --name cli-prod-api
```

Revoke a token by name:

```bash
envbasis token revoke --name cli-prod-api
```

Share a token with a member:

```bash
envbasis token share --name cli-prod-api --email teammate@example.com
```

List token shares:

```bash
envbasis token shares --name cli-prod-api
```

Important behavior:

- `token create` prompts you to choose an environment if the project has multiple environments and you did not pass `--env`.
- If the project has exactly one environment, `token create` uses it automatically.
- On successful creation, the CLI prints the plaintext runtime token and tells you to copy it immediately.
- Reveal and revoke flows are name-based at the CLI level.

### Audit Logs

Show audit logs for the selected project:

```bash
envbasis audit logs
```

### Context Inspection

Show the currently resolved execution context:

```bash
envbasis context
```

This includes:

- resolved API URL
- resolved project reference
- resolved environment
- JSON mode status
- verbose mode status

### Configuration Diagnostics And Migration

Validate the discovered file, format version, API connection, authenticated session, project, and environment:

```bash
envbasis config check
```

Legacy files without `config_version` continue to load as version 0. Upgrade them safely with:

```bash
envbasis config migrate
```

Migration validates the legacy file, creates a `.bak` copy, and atomically replaces the active file. New configuration files use `config_version = 1`.

### Process Secret Injection

Run any command with the selected environment's secrets injected into only that child process:

```bash
envbasis run -- npm run dev
envbasis run -- python worker.py --queue emails
```

Remote values override variables inherited from the current shell by default. Preserve existing local values instead with `--precedence local`:

```bash
envbasis run --precedence local -- npm test
```

The CLI passes an argument array directly to the operating system without an intermediate shell. It does not write injected secrets to a file or print their values.

Project and environment can use the global `--project` and `--env` options. Secret path and tag selectors are available directly on `run`. Paths are normalized to values such as `/` and `/backend`; repeated tags use AND matching, so every requested tag must be present:

```bash
envbasis --project demo-api --env dev run --path /backend --tag api -- npm run dev
```

Assign selectors when pushing or setting secrets:

```bash
envbasis push --file .env --path /backend --tag api --tag shared
envbasis secrets set DATABASE_URL postgres://db --path /backend --tag database
```

Watch mode polls for relevant remote changes, debounces bursts, prints only changed key names, and safely restarts the child:

```bash
envbasis run --watch --watch-interval 5 -- npm run dev
```

Watch mode is intended for local development. Production supervisors should perform controlled deployments instead of automatically restarting on secret changes.

### Export And Automation

Export raw data to stdout without status messages:

```bash
envbasis export --format dotenv
envbasis export --format json
envbasis export --format yaml
envbasis export --format shell
```

Write to a file with an explicit non-interactive overwrite policy:

```bash
envbasis export --format json --output secrets.json --overwrite --no-input
```

Automation uses stable exit codes: `0` for success, `1` for operational errors, `2` for invalid command usage, `3` for actionable scanner findings, `127` when a child command cannot be started, and the child's own exit code for `envbasis run`.

### Secret Scanning

Scan files and directories. Findings show only redacted matches:

```bash
envbasis scan .
envbasis scan src config/settings.py
envbasis scan --git-history
envbasis scan --staged
envbasis scan --uncommitted
envbasis scan --pre-commit
```

The scanner detects common AWS, GitHub, OpenAI, Slack, Google, private-key, generic credential, and high-entropy patterns. Add repository-relative patterns to `.envbasisignore`, or add `envbasis:ignore` on a line to suppress an intentional match.

## Local Config, Precedence, And Security Notes

### Resolution Order

API URL resolution:

1. `--api-url`
2. `ENVBASIS_API_URL`
3. `api_base_url` in `.envbasis.toml`
4. the hosted EnvBasis API default

Project and environment resolution:

1. `--project` or `--env`
2. saved values in `.envbasis.toml`

For projects, the saved config can resolve through either `project_id` or `project_name`.

### What Gets Stored Where

- Session secrets live in the OS keyring.
- Local defaults live in `.envbasis.toml`.
- Your application secrets typically live in `.env` when using `push` and `secrets pull`.

### Git Safety

This repo already ignores `.env` and `.envbasis.toml`.

If you use the CLI inside another project repository, you should ignore those files there as well. The CLI checks git status for the target secret file and warns when that file is tracked or not ignored.

### Repository And Monorepo Lookup

EnvBasis starts in the current working directory and walks upward until it finds `.envbasis.toml`. The nearest file wins, so a nested application can override a repository-level configuration while sibling packages continue sharing the root file.

## JSON And Scripting Usage

Every command can be switched into machine-readable mode with the global `--json` flag.

Examples:

```bash
envbasis --json whoami
envbasis --json projects list
envbasis --json env list
envbasis --json secrets stats
envbasis --json token shares --name cli-prod-api
envbasis --json context
```

You can combine `--json` with shell tools:

```bash
envbasis --json whoami
envbasis secrets pull --stdout --format json
```

Notes:

- `--json` is a global flag, so place it before the command group or root command.
- Human-readable table output is the default when `--json` is not set.
- `push --review` is terminal-oriented and is not available with `--json`.

## Development And Testing

### Canonical Local Workflow

Create or reuse a Python 3.11 virtual environment and install the project in editable mode:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Run the test suite:

```bash
.venv/bin/pytest -q
```

Inspect CLI help:

```bash
.venv/bin/envbasis --help
```

Run individual examples from the repo checkout:

```bash
.venv/bin/envbasis --help
.venv/bin/envbasis project --help
.venv/bin/envbasis secrets --help
```

### Repo Layout

| Path | Purpose |
| --- | --- |
| `src/envbasis_cli/` | CLI implementation |
| `src/envbasis_cli/commands/` | Command groups and root command registrations |
| `tests/` | CLI and client behavior tests |
| `docs/api-contract.md` | Backend API contract baseline |
| `pyproject.toml` | Packaging and dependency metadata |

## Troubleshooting

### `API base URL is not set`

Provide one of:

- `--api-url`
- `ENVBASIS_API_URL`
- `api_base_url` in `.envbasis.toml`

### `You are not logged in`

Run:

```bash
envbasis login
```

If you were previously logged in, the stored session may have expired and been cleared.

### Keyring errors

If login fails while saving or loading the session, your machine may not have a usable keyring backend configured. Fix the system keyring setup first, then retry login.

### Project or environment resolution errors

Use explicit selection when needed:

```bash
envbasis project --select my-app
envbasis environment dev
```

Or override per command:

```bash
envbasis --project my-app --env dev secret
```

## Additional Docs

- Backend contract baseline: [`docs/api-contract.md`](docs/api-contract.md)
