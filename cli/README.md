# EnvBasis CLI

EnvBasis CLI is a thin authenticated command-line client for the EnvBasis backend API. It gives teams a consistent way to sign in, select a project and environment, sync `.env` files, manage individual secrets, administer project access, and work with runtime tokens without talking directly to the database.

It is built with Python, Typer, `httpx`, `pydantic`, `rich`, `keyring`, and `python-dotenv`, and is packaged as the `envbasis` command.

## Feature Summary

- Keyring-backed CLI session handling
- Secure session storage in the OS keyring
- Project and environment selection stored in local working-directory config
- Top-level `.env` push and pull workflows
- Single-secret CRUD commands for targeted updates
- Member listing, invitation, access management, and revoke flows
- Runtime token creation, reveal, revoke, share, and audit visibility
- Human-friendly table output and `--json` output for scripting

## What The CLI Does Today

The current CLI supports these areas:

- Authentication: `login`, `logout`, `whoami`
- Context inspection: `context`
- Project workflows: `projects list`, `project create`, `project show`, `project use`, `project update`
- Environment workflows: `env list`, `env create`, `env use`
- Secret sync: top-level `push` and `pull`
- Secret CRUD: `secrets list`, `secrets stats`, `secrets set`, `secrets update`, `secrets delete`
- Member workflows: `members list`, `members access`, plus top-level `invite` and `revoke`
- Runtime tokens: `token list`, `token create`, `token reveal`, `token revoke`, `token share`, `token shares`
- Audit logs: `audit logs`

Two command layout details are easy to miss:

- `push` and `pull` are top-level commands. Individual secret CRUD lives under `secrets`.
- `invite` and `revoke` are top-level commands. Member listing and access toggles live under `members`.

## Install And Requirements

### Requirements

- Python 3.11 or newer
- Access to an EnvBasis API deployment
- A working OS keyring backend

### Install For Local Use

If you want an isolated user install from a checkout of this repo, run this from the repo root:

```bash
pipx install .
```

If you prefer a standard Python install:

```bash
python -m pip install .
```

After installation, the CLI is available as:

```bash
envbasis --help
```

## Authentication And Required Configuration

The CLI only needs your EnvBasis backend API URL and stores authenticated sessions in your OS keyring.

### Required Settings

Current requirements:

- An EnvBasis API base URL

The recommended setup is a local `.envbasis.toml`, so you can use the CLI directly without re-exporting values in every shell.

### Recommended Setup: Local Config File

The CLI reads and writes `.envbasis.toml` in the current working directory.

The `project_id`, `project_name`, and `environment` fields are optional. In normal use, they are usually written by `envbasis project use ...` and `envbasis env use ...`.

Example:

```toml
api_base_url = "https://api.example.com/api/v1"
project_id = "proj_123"
project_name = "my-app"
environment = "dev"
```

Once this file exists, the normal usage flow is:

```bash
envbasis login
envbasis whoami
envbasis projects list
envbasis project use my-app
envbasis env list
envbasis env use dev
envbasis push --file .env
```

### Optional Alternative: Environment Variables

If you do not want to keep a local `.envbasis.toml`, the CLI can also read these environment variables:

- `ENVBASIS_API_URL`

### Session Behavior

- Login stores the authenticated session in the OS keyring, not in `.envbasis.toml`.
- Expired sessions are cleared locally and you will need to log in again.

## How To Use It

### 1. Create `.envbasis.toml`

Create `.envbasis.toml` in the directory where you want to use the CLI, using the example shown above.

### 2. Sign in

```bash
envbasis login
```

Verify the session:

```bash
envbasis whoami
```

### 3. Create or select a project

```bash
envbasis project create --name my-app --description "Internal service"
envbasis projects list
envbasis project use my-app
envbasis project show
```

### 4. Create or select an environment

```bash
envbasis env create dev
envbasis env create prod
envbasis env use dev
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
envbasis pull --file .env
```

To inspect what the CLI would pull without writing a file:

```bash
envbasis pull --stdout
envbasis pull --stdout --format json
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
| `push` | Upload a dotenv file into the selected project and environment |
| `pull` | Download secrets into a file or stdout |
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
envbasis project use my-app
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

`project use` writes `project_id` and `project_name` into `.envbasis.toml` and clears any previously saved environment selection.

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
envbasis env use dev
```

Environment resolution behavior:

- If exactly one environment exists and none is selected, the CLI uses it automatically.
- If multiple environments exist and none is selected, commands that need an environment fail until you pass `--env` or run `envbasis env use <name>`.

### Secret Sync: `push` And `pull`

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
envbasis pull --file .env
```

Pull secrets as JSON to stdout:

```bash
envbasis pull --stdout --format json
```

Write JSON to a file instead of dotenv format:

```bash
envbasis pull --file secrets.json --format json --overwrite
```

Important behavior:

- `push` reads the specified dotenv file and uploads parsed key/value pairs.
- `push --review` compares the local dotenv payload with the current remote secrets and prints a masked Git-style diff before any push request is sent.
- `push --review --yes` prints the same diff and skips the confirmation prompt.
- `push --yes` is invalid unless you also pass `--review`.
- `push` fails if the file does not exist or contains no parsed keys.
- `pull` prompts before overwriting an existing file unless you pass `--overwrite`.
- `pull --stdout` skips file writes entirely.
- Before reading or writing a secret file, the CLI warns if that path is tracked by git or is not ignored.

### Secret CRUD

List secrets for the selected environment:

```bash
envbasis secrets list
```

Reveal raw values if the backend returns them:

```bash
envbasis secrets list --reveal
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

- `secrets list` hides secret values by default.
- `secrets list --reveal` only shows values if the backend response includes them.
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

## Local Config, Precedence, And Security Notes

### Resolution Order

API URL resolution:

1. `--api-url`
2. `ENVBASIS_API_URL`
3. `api_base_url` in `.envbasis.toml`

Project and environment resolution:

1. `--project` or `--env`
2. saved values in `.envbasis.toml`

For projects, the saved config can resolve through either `project_id` or `project_name`.

### What Gets Stored Where

- Session secrets live in the OS keyring.
- Local defaults live in `.envbasis.toml`.
- Your application secrets typically live in `.env` when using `push` and `pull`.

### Git Safety

This repo already ignores `.env` and `.envbasis.toml`.

If you use the CLI inside another project repository, you should ignore those files there as well. The CLI checks git status for the target secret file and warns when that file is tracked or not ignored.

### Current Working Directory Matters

Because `.envbasis.toml` is read from the current working directory, different repositories or folders can maintain different selected projects and environments.

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
envbasis pull --stdout --format json
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
envbasis project use my-app
envbasis env use dev
```

Or override per command:

```bash
envbasis --project my-app --env dev secrets list
```

## Additional Docs

- Backend contract baseline: [`docs/api-contract.md`](docs/api-contract.md)
