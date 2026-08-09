from __future__ import annotations

import signal
import subprocess

import httpx
from typer.testing import CliRunner

from envbasis_cli.config import ConfigManager
from envbasis_cli.execution import (
    ProcessSupervisor,
    build_child_environment,
    changed_secret_keys,
    normalize_exit_code,
    supervise_process,
)
from envbasis_cli.main import app


class FakeTokenStore:
    def get(self) -> str:
        return "run-token"


class FakeProcess:
    def __init__(self, return_code: int = 0) -> None:
        self.return_code = return_code
        self.signals: list[int] = []
        self.terminated = False
        self.killed = False
        self.wait_timeouts: list[float | None] = []

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        return self.return_code

    def poll(self):
        return None if not self.terminated and not self.killed else self.return_code

    def send_signal(self, signum):
        self.signals.append(signum)

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def test_child_environment_precedence_is_explicit() -> None:
    parent = {"SHARED": "local", "LOCAL_ONLY": "present"}
    secrets = {"SHARED": "remote", "REMOTE_ONLY": "secret"}

    remote_wins = build_child_environment(secrets, parent_environment=parent, precedence="remote")
    local_wins = build_child_environment(secrets, parent_environment=parent, precedence="local")

    assert remote_wins == {
        "SHARED": "remote",
        "LOCAL_ONLY": "present",
        "REMOTE_ONLY": "secret",
    }
    assert local_wins == {
        "SHARED": "local",
        "LOCAL_ONLY": "present",
        "REMOTE_ONLY": "secret",
    }


def test_process_supervisor_preserves_arguments_without_a_shell(monkeypatch) -> None:
    captured: dict[str, object] = {}
    process = FakeProcess(return_code=7)

    def process_factory(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return process

    monkeypatch.setenv("LOCAL_ONLY", "yes")
    supervisor = ProcessSupervisor(
        ["python", "-c", "print('$HOME; still an argument')"],
        process_factory=process_factory,
    )

    supervisor.start({"API_KEY": "secret-value"})

    assert captured["command"] == ["python", "-c", "print('$HOME; still an argument')"]
    assert captured["shell"] is False
    child_environment = captured["env"]
    assert child_environment["API_KEY"] == "secret-value"
    assert child_environment["LOCAL_ONLY"] == "yes"
    assert supervisor.wait() == 7


def test_process_supervisor_forwards_signals_and_escalates_shutdown() -> None:
    class SlowProcess(FakeProcess):
        def wait(self, timeout=None):
            self.wait_timeouts.append(timeout)
            if timeout is not None and not self.killed:
                raise subprocess.TimeoutExpired("child", timeout)
            return self.return_code

    process = SlowProcess()
    supervisor = ProcessSupervisor(["child"], shutdown_timeout=0.1, process_factory=lambda *a, **k: process)
    supervisor.start({})

    supervisor.forward_signal(signal.SIGINT)
    supervisor.stop()

    assert process.signals == [signal.SIGINT]
    assert process.terminated is True
    assert process.killed is True


def test_watch_restarts_only_when_secret_values_change() -> None:
    class StubSupervisor:
        def __init__(self) -> None:
            self.started: list[dict[str, str]] = []
            self.restarted: list[dict[str, str]] = []
            self.poll_results = [None, 0]
            self.stopped = False

        def start(self, secrets):
            self.started.append(dict(secrets))

        def poll(self):
            return self.poll_results.pop(0)

        def restart(self, secrets):
            self.restarted.append(dict(secrets))

        def forward_signal(self, signum):
            return None

        def wait(self):
            return 0

        def stop(self):
            self.stopped = True

    supervisor = StubSupervisor()
    reports: list[list[str]] = []

    exit_code = supervise_process(
        supervisor,
        {"API_KEY": "v1", "REMOVED": "old"},
        watch=True,
        fetch_secrets=lambda: {"API_KEY": "v2", "ADDED": "new"},
        poll_interval=0.1,
        debounce_seconds=0,
        report_changes=reports.append,
        sleep=lambda seconds: None,
    )

    assert exit_code == 0
    assert supervisor.started == [{"API_KEY": "v1", "REMOVED": "old"}]
    assert supervisor.restarted == [{"API_KEY": "v2", "ADDED": "new"}]
    assert reports == [["ADDED", "API_KEY", "REMOVED"]]
    assert supervisor.stopped is True


def test_change_detection_and_signal_exit_codes() -> None:
    assert changed_secret_keys({"A": "1", "B": "2"}, {"A": "1", "B": "3"}) == ["B"]
    assert normalize_exit_code(-signal.SIGTERM) == 143


def test_run_command_fetches_in_memory_and_returns_child_exit_code(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / ".envbasis.toml"
    config_path.write_text(
        'config_version = 1\napi_base_url = "https://api.example.com/api/v1"\n'
        'project_id = "proj_1"\nproject_name = "agent-api"\nenvironment = "dev"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("envbasis_cli.main.ConfigManager", lambda: ConfigManager(config_path))
    monkeypatch.setattr("envbasis_cli.main.TokenStore", FakeTokenStore)
    pending = [
        ("GET", "https://api.example.com/api/v1/projects", [{"id": "proj_1", "name": "agent-api"}]),
        (
            "GET",
            "https://api.example.com/api/v1/projects/proj_1/environments",
            [{"id": "env_1", "name": "dev"}],
        ),
        (
            "GET",
            "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/pull",
            {"secrets": {"API_KEY": "never-print-this"}},
        ),
    ]

    def fake_request(self, method, url, params=None, json=None, headers=None):
        expected_method, expected_url, payload = pending.pop(0)
        assert (method, url) == (expected_method, expected_url)
        if url.endswith("/secrets/pull"):
            assert params == {
                "path": "/",
                "recursive": False,
                "resolve": True,
                "include_imports": True,
            }
        request = httpx.Request(method, url, headers=headers)
        return httpx.Response(200, json=payload, request=request)

    captured: dict[str, object] = {}

    class StubSupervisor:
        def __init__(self, command, precedence="remote") -> None:
            captured["command"] = command
            captured["precedence"] = precedence

    def fake_supervise(supervisor, secrets, **kwargs):
        captured["secrets"] = secrets
        captured["watch"] = kwargs["watch"]
        return 23

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    monkeypatch.setattr("envbasis_cli.commands.run.ProcessSupervisor", StubSupervisor)
    monkeypatch.setattr("envbasis_cli.commands.run.supervise_process", fake_supervise)
    runner = CliRunner()

    result = runner.invoke(app, ["run", "--", "node", "script.js", "--literal=$HOME;echo"])

    assert result.exit_code == 23
    assert not pending
    assert captured["command"] == ["node", "script.js", "--literal=$HOME;echo"]
    assert captured["secrets"] == {"API_KEY": "never-print-this"}
    assert "never-print-this" not in result.output
    assert captured["watch"] is False
