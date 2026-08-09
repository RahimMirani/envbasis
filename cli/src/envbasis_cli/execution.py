from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


SecretFetcher = Callable[[], dict[str, str]]
ChangeReporter = Callable[[list[str]], None]


def build_child_environment(
    secrets: Mapping[str, str],
    *,
    parent_environment: Mapping[str, str] | None = None,
    precedence: str = "remote",
) -> dict[str, str]:
    environment = dict(parent_environment if parent_environment is not None else os.environ)
    if precedence == "remote":
        environment.update(secrets)
        return environment
    if precedence == "local":
        for key, value in secrets.items():
            environment.setdefault(key, value)
        return environment
    raise ValueError(f"Unsupported environment precedence: {precedence}")


def changed_secret_keys(previous: Mapping[str, str], current: Mapping[str, str]) -> list[str]:
    return sorted(
        key
        for key in set(previous) | set(current)
        if previous.get(key) != current.get(key) or (key in previous) != (key in current)
    )


def normalize_exit_code(return_code: int) -> int:
    if return_code >= 0:
        return return_code
    return 128 + abs(return_code)


@dataclass(slots=True)
class ProcessSupervisor:
    command: Sequence[str]
    precedence: str = "remote"
    shutdown_timeout: float = 5.0
    process_factory: Callable[..., subprocess.Popen] = subprocess.Popen
    process: subprocess.Popen | None = None

    def start(self, secrets: Mapping[str, str]) -> None:
        child_environment = build_child_environment(secrets, precedence=self.precedence)
        self.process = self.process_factory(list(self.command), env=child_environment, shell=False)

    def wait(self) -> int:
        if self.process is None:
            raise RuntimeError("Child process has not been started.")
        return normalize_exit_code(self.process.wait())

    def poll(self) -> int | None:
        if self.process is None:
            raise RuntimeError("Child process has not been started.")
        return self.process.poll()

    def forward_signal(self, signum: int) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.send_signal(signum)

    def restart(self, secrets: Mapping[str, str]) -> None:
        self.stop()
        self.start(secrets)

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=self.shutdown_timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


def supervise_process(
    supervisor: ProcessSupervisor,
    initial_secrets: dict[str, str],
    *,
    watch: bool,
    fetch_secrets: SecretFetcher | None = None,
    poll_interval: float = 5.0,
    debounce_seconds: float = 0.5,
    report_changes: ChangeReporter | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    current_secrets = initial_secrets
    supervisor.start(current_secrets)
    previous_handlers: dict[int, object] = {}

    def forward(signum, _frame) -> None:
        supervisor.forward_signal(signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, forward)
        except (OSError, ValueError):
            continue

    try:
        if not watch:
            return supervisor.wait()
        if fetch_secrets is None:
            raise ValueError("Watch mode requires a secret fetcher.")

        while True:
            return_code = supervisor.poll()
            if return_code is not None:
                return normalize_exit_code(return_code)

            sleep(poll_interval)
            observed = fetch_secrets()
            changed = changed_secret_keys(current_secrets, observed)
            if not changed:
                continue

            if debounce_seconds > 0:
                sleep(debounce_seconds)
                latest = fetch_secrets()
                changed = changed_secret_keys(current_secrets, latest)
                observed = latest
                if not changed:
                    continue

            if report_changes is not None:
                report_changes(changed)
            current_secrets = observed
            supervisor.restart(current_secrets)
    except KeyboardInterrupt:
        supervisor.forward_signal(signal.SIGINT)
        return supervisor.wait()
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)
        supervisor.stop()
