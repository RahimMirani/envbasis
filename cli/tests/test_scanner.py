from __future__ import annotations

import json
from types import SimpleNamespace

from typer.testing import CliRunner

from envbasis_cli.config import ConfigManager
from envbasis_cli.main import app
from envbasis_cli.scanner import IgnoreRules, scan_git_patch, scan_paths, scan_text


class FakeTokenStore:
    pass


def _wire(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("envbasis_cli.main.ConfigManager", lambda: ConfigManager(tmp_path / ".envbasis.toml"))
    monkeypatch.setattr("envbasis_cli.main.TokenStore", FakeTokenStore)


def test_scan_files_directories_ignore_rules_and_inline_suppression(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".envbasisignore").write_text("ignored.env\nfixtures/\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        'OPENAI_API_KEY="sk-proj-abcdefghijklmnopqrstuvwxyz123456"\n'
        'IGNORED_TOKEN="ghp_abcdefghijklmnopqrstuvwxyz123456"  # envbasis:ignore\n',
        encoding="utf-8",
    )
    (tmp_path / "ignored.env").write_text(
        "AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP\n",
        encoding="utf-8",
    )
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "secret.txt").write_text("token=abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "scan", str(tmp_path)])

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["count"] >= 1
    serialized = json.dumps(payload)
    assert "sk-proj-abcdefghijklmnopqrstuvwxyz123456" not in serialized
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in serialized
    assert "AKIAABCDEFGHIJKLMNOP" not in serialized
    assert all(finding["path"] == "app.py" for finding in payload["findings"])


def test_clean_scan_returns_success(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    clean = tmp_path / "clean.py"
    clean.write_text("answer = 42\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["scan", str(clean)])

    assert result.exit_code == 0
    assert "No actionable secrets found" in result.output


def test_scan_detects_high_entropy_without_returning_plaintext(tmp_path) -> None:
    value = "aB3dE5fG7hJ9kL2mN4pQ6rS8tV0xYz12"
    findings = scan_text(f'opaque = "{value}"', path="config.txt")

    assert any(finding.rule == "high-entropy" for finding in findings)
    assert all(finding.redacted != value for finding in findings)


def test_scan_git_patch_tracks_files_lines_and_commit_sources() -> None:
    patch = """commit abcdef1234567890
diff --git a/app.env b/app.env
--- a/app.env
+++ b/app.env
@@ -0,0 +4 @@
+OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456
"""

    findings = scan_git_patch(patch, source="history")

    assert findings
    assert findings[0].path == "app.env"
    assert findings[0].line == 4
    assert findings[0].source == "history:abcdef123456"
    assert "abcdefghijklmnopqrstuvwxyz" not in findings[0].redacted


def test_pre_commit_mode_scans_only_staged_patch(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    calls: list[list[str]] = []
    patch = """diff --git a/settings.env b/settings.env
--- a/settings.env
+++ b/settings.env
@@ -0,0 +1 @@
+GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz123456
"""

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=patch, stderr="")

    monkeypatch.setattr("envbasis_cli.scanner.subprocess.run", fake_run)
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "scan", "--pre-commit"])

    assert result.exit_code == 3
    assert calls == [["git", "diff", "--cached", "--no-ext-diff", "--unified=0"]]
    payload = json.loads(result.output)
    assert payload["findings"][0]["source"] == "staged"
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in result.output


def test_custom_ignore_file_is_applied_to_recursive_scan(tmp_path) -> None:
    ignored = tmp_path / "generated" / "credentials.txt"
    ignored.parent.mkdir()
    ignored.write_text("token=abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    ignore_file = tmp_path / "custom.ignore"
    ignore_file.write_text("generated/\n", encoding="utf-8")
    rules = IgnoreRules.load(tmp_path, ignore_file)

    assert scan_paths([tmp_path], root=tmp_path, ignore_rules=rules) == []


def test_uncommitted_mode_includes_untracked_files(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    untracked = tmp_path / "new.env"
    untracked.write_text("OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "ls-files" in command:
            return SimpleNamespace(returncode=0, stdout="new.env\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("envbasis_cli.scanner.subprocess.run", fake_run)
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "scan", "--uncommitted"])

    assert result.exit_code == 3
    assert calls == [
        ["git", "diff", "--no-ext-diff", "--unified=0"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    payload = json.loads(result.output)
    assert payload["findings"][0]["path"] == "new.env"
    assert payload["findings"][0]["source"] == "uncommitted"
