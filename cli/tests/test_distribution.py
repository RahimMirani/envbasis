from __future__ import annotations

import json
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from envbasis_cli import __version__
from envbasis_cli.main import app


CLI_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = CLI_ROOT.parent


def test_package_version_is_consistent_and_semantic() -> None:
    metadata = tomllib.loads((CLI_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = metadata["project"]["version"]

    assert version == __version__
    assert version.split(".") == ["0", "2", "0"]


def test_version_and_shell_completion_are_exposed() -> None:
    runner = CliRunner()

    version_result = runner.invoke(app, ["--version"])
    help_result = runner.invoke(app, ["--help"])

    assert version_result.exit_code == 0
    assert version_result.output.strip() == f"envbasis {__version__}"
    assert "--install-completion" in help_result.output
    assert "--show-completion" in help_result.output


def test_json_mode_emits_machine_readable_errors_and_stable_usage_code() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "run"])

    assert result.exit_code == 2
    assert json.loads(result.output) == {
        "error": "No child command provided. Use: envbasis run -- <command>"
    }


def test_removed_legacy_selection_and_secret_commands_stay_unavailable() -> None:
    runner = CliRunner()

    for arguments in (
        ["pull", "--help"],
        ["secrets", "list", "--help"],
        ["project", "use", "--help"],
        ["env", "use", "--help"],
    ):
        result = runner.invoke(app, arguments)
        assert result.exit_code == 2
        assert "No such command" in result.output


def test_changelog_contains_current_release() -> None:
    changelog = (CLI_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert f"## [{__version__}]" in changelog
    assert "Semantic Versioning" in changelog


def test_ci_and_release_workflows_cover_tests_artifacts_and_trusted_publishing() -> None:
    ci = (REPOSITORY_ROOT / ".github/workflows/cli-ci.yml").read_text(encoding="utf-8")
    release = (REPOSITORY_ROOT / ".github/workflows/cli-release.yml").read_text(encoding="utf-8")

    assert "ubuntu-latest, macos-latest, windows-latest" in ci
    assert "uv run pytest -q" in ci
    assert "pyinstaller --onefile" in ci
    assert "actions/upload-artifact@v7" in ci
    assert "id-token: write" in release
    assert "pypa/gh-action-pypi-publish@release/v1" in release
