# CLI Distribution

## Python package

`uv build` creates a wheel and source distribution. Tagged releases use PyPI Trusted Publishing through `.github/workflows/cli-release.yml`; the repository owner must first create the `pypi` GitHub environment and register this workflow as a trusted publisher for the `envbasis-cli` PyPI project.

## Standalone binaries

`.github/workflows/cli-ci.yml` builds and smoke-tests one-file PyInstaller executables on Linux, macOS, and Windows. These artifacts are an additional installation option; `pipx install envbasis-cli` remains the preferred installation because operating-system keyring integration is easier to update and diagnose.

## Homebrew decision

Homebrew distribution is intentionally deferred until the macOS standalone artifact is code-signed and releases have stable public download URLs and checksums. `homebrew/envbasis-cli.rb.template` records the intended formula so a tap can be added without redesigning packaging.
