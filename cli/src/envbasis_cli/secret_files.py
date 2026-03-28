from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values


@dataclass(slots=True)
class SecretReviewLine:
    text: str
    style: str | None = None


@dataclass(slots=True)
class SecretReview:
    lines: list[SecretReviewLine] = field(default_factory=list)
    added_keys: list[str] = field(default_factory=list)
    changed_keys: list[str] = field(default_factory=list)
    unchanged_keys: list[str] = field(default_factory=list)
    remote_only_keys: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added_keys or self.changed_keys)


def load_dotenv_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise IsADirectoryError(path)

    raw_values = dotenv_values(path)
    return {
        key: "" if value is None else value
        for key, value in raw_values.items()
        if key is not None
    }


def render_secret_payload(secrets: Mapping[str, str], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(dict(secrets), indent=2, sort_keys=True) + "\n"
    if output_format == "dotenv":
        return render_dotenv(secrets)
    raise ValueError(f"Unsupported secret output format: {output_format}")


def build_secret_review(remote_secrets: Mapping[str, str], local_secrets: Mapping[str, str]) -> SecretReview:
    review = SecretReview(
        lines=[
            SecretReviewLine("--- remote", style="red"),
            SecretReviewLine("+++ local", style="green"),
        ]
    )

    for key in sorted(set(remote_secrets) | set(local_secrets)):
        has_remote = key in remote_secrets
        has_local = key in local_secrets

        if has_remote and has_local:
            if remote_secrets[key] == local_secrets[key]:
                review.unchanged_keys.append(key)
                review.lines.append(SecretReviewLine(f"  {key}=<unchanged hidden>", style="bright_black"))
            else:
                review.changed_keys.append(key)
                review.lines.append(SecretReviewLine(f"- {key}=<remote value hidden>", style="red"))
                review.lines.append(SecretReviewLine(f"+ {key}=<local value hidden>", style="green"))
            continue

        if has_local:
            review.added_keys.append(key)
            review.lines.append(SecretReviewLine(f"+ {key}=<local value hidden>", style="green"))
            continue

        review.remote_only_keys.append(key)
        review.lines.append(SecretReviewLine(f"- {key}=<remote-only, not deleted>", style="red"))

    return review


def write_secret_file(path: Path, secrets: Mapping[str, str], output_format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_secret_payload(secrets, output_format), encoding="utf-8")


def git_safety_warnings(path: Path) -> list[str]:
    repository = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    if repository.returncode != 0:
        return []

    repo_root = Path(repository.stdout.strip())
    try:
        relative_path = str(path.resolve().relative_to(repo_root))
    except ValueError:
        return []

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative_path],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    ignored = subprocess.run(
        ["git", "check-ignore", relative_path],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    warnings: list[str] = []
    if tracked.returncode == 0:
        warnings.append(f"{relative_path} is tracked by git.")
    elif ignored.returncode != 0:
        warnings.append(f"{relative_path} is not ignored by git.")
    return warnings


def render_dotenv(secrets: Mapping[str, str]) -> str:
    lines = []
    for key in sorted(secrets):
        lines.append(f"{key}={_format_dotenv_value(secrets[key])}")
    return "\n".join(lines) + ("\n" if lines else "")


def _format_dotenv_value(value: str) -> str:
    if value == "" or any(character in value for character in (' ', '\t', '\n', '\r', '#', '"', "'")):
        escaped = value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
        return f'"{escaped}"'
    return value
