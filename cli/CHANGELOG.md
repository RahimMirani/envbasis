# Changelog

EnvBasis CLI follows [Semantic Versioning](https://semver.org/). Releases use `MAJOR.MINOR.PATCH`: incompatible command or configuration changes increment MAJOR, backward-compatible features increment MINOR, and backward-compatible fixes increment PATCH.

## [0.2.0] - 2026-08-08

### Added

- Interactive, validated `envbasis init`
- Parent-directory configuration discovery for monorepos
- Configuration diagnostics, versioning, backups, and atomic migration
- In-memory `envbasis run -- <command>` process injection
- Development watch mode with debounce and safe restarts
- Dotenv, JSON, YAML, and shell export
- Filesystem, Git history, staged, uncommitted, and pre-commit scanning
- Stable automation exit codes and non-interactive behavior
- Cross-platform release artifact workflows

### Security

- Child commands execute without an intermediate shell
- Injected secret values are never written to temporary files or printed by the supervisor
- Scanner findings redact matched credentials
- Configuration files and migration backups use owner-only permissions

## [0.1.0] - 2026-08-07

### Added

- Initial authenticated CLI
- Project and environment selection
- Secret push, pull, listing, and CRUD
- Project member, runtime token, and audit commands
