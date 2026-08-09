from __future__ import annotations

import fnmatch
import math
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


INLINE_IGNORE_MARKER = "envbasis:ignore"
DEFAULT_IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
}
MAX_FILE_BYTES = 1_000_000

PROVIDER_PATTERNS = [
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,255}\b")),
    ("openai-api-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,255}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,255}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]
GENERIC_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|password|passwd|client[_-]?secret)\s*[:=]\s*"
    r"['\"]?(?P<secret>[^\s'\"#,;]{8,})"
)
ENTROPY_CANDIDATE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_+/=-]{24,}(?![A-Za-z0-9])")


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    rule: str
    redacted: str
    source: str = "filesystem"

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "rule": self.rule,
            "redacted": self.redacted,
            "source": self.source,
        }


class IgnoreRules:
    def __init__(self, root: Path, patterns: list[str] | None = None) -> None:
        self.root = root.resolve()
        self.patterns = patterns or []

    @classmethod
    def load(cls, root: Path, ignore_file: Path | None = None) -> IgnoreRules:
        path = ignore_file or root / ".envbasisignore"
        patterns: list[str] = []
        if path.is_file():
            patterns = [
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
        return cls(root, patterns)

    def ignores(self, path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            relative = path.name
        parts = Path(relative).parts
        if any(part in DEFAULT_IGNORED_DIRECTORIES for part in parts):
            return True
        for pattern in self.patterns:
            normalized = pattern.lstrip("/")
            if pattern.endswith("/") and (relative == normalized.rstrip("/") or relative.startswith(normalized)):
                return True
            if fnmatch.fnmatch(relative, normalized) or fnmatch.fnmatch(path.name, normalized):
                return True
        return False


def scan_paths(paths: list[Path], *, root: Path, ignore_rules: IgnoreRules) -> list[Finding]:
    findings: list[Finding] = []
    for requested_path in paths:
        path = requested_path.expanduser().resolve()
        if path.is_file():
            findings.extend(scan_file(path, root=root, ignore_rules=ignore_rules))
            continue
        if not path.is_dir():
            raise FileNotFoundError(path)
        for candidate in sorted(path.rglob("*")):
            if candidate.is_file() and not ignore_rules.ignores(candidate):
                findings.extend(scan_file(candidate, root=root, ignore_rules=ignore_rules))
    return _deduplicate(findings)


def scan_file(path: Path, *, root: Path, ignore_rules: IgnoreRules) -> list[Finding]:
    if ignore_rules.ignores(path) or path.stat().st_size > MAX_FILE_BYTES:
        return []
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    if b"\x00" in raw:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []
    try:
        display_path = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        display_path = str(path)
    return scan_text(text, path=display_path)


def scan_text(text: str, *, path: str, source: str = "filesystem", start_line: int = 1) -> list[Finding]:
    findings: list[Finding] = []
    for offset, line in enumerate(text.splitlines(), start=start_line):
        if INLINE_IGNORE_MARKER in line.lower():
            continue
        provider_match = False
        for rule, pattern in PROVIDER_PATTERNS:
            for match in pattern.finditer(line):
                provider_match = True
                findings.append(Finding(path, offset, rule, redact(match.group(0)), source))
        for match in GENERIC_ASSIGNMENT.finditer(line):
            provider_match = True
            value = match.group("secret")
            findings.append(Finding(path, offset, "generic-secret", redact(value), source))
        if provider_match:
            continue
        for match in ENTROPY_CANDIDATE.finditer(line):
            value = match.group(0)
            if _shannon_entropy(value) >= 4.0:
                findings.append(Finding(path, offset, "high-entropy", redact(value), source))
    return findings


def scan_git_patch(patch: str, *, source: str) -> list[Finding]:
    findings: list[Finding] = []
    path = "unknown"
    line_number = 0
    current_source = source
    for line in patch.splitlines():
        if line.startswith("commit ") and source == "history":
            current_source = f"history:{line.split(maxsplit=1)[1][:12]}"
            continue
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            line_number = int(match.group(1)) if match else 0
            continue
        if line.startswith("+") and not line.startswith("+++"):
            findings.extend(
                scan_text(line[1:], path=path, source=current_source, start_line=max(line_number, 1))
            )
            line_number += 1
        elif not line.startswith("-") and not line.startswith("\\"):
            line_number += 1
    return _deduplicate(findings)


def scan_git(
    root: Path,
    *,
    history: bool,
    staged: bool,
    uncommitted: bool,
    ignore_rules: IgnoreRules | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    if history:
        findings.extend(
            scan_git_patch(
                _run_git(root, ["log", "-p", "--all", "--no-ext-diff", "--unified=0"]),
                source="history",
            )
        )
    if staged:
        findings.extend(
            scan_git_patch(
                _run_git(root, ["diff", "--cached", "--no-ext-diff", "--unified=0"]),
                source="staged",
            )
        )
    if uncommitted:
        findings.extend(
            scan_git_patch(
                _run_git(root, ["diff", "--no-ext-diff", "--unified=0"]),
                source="uncommitted",
            )
        )
        untracked_output = _run_git(root, ["ls-files", "--others", "--exclude-standard"])
        untracked_paths = [root / line for line in untracked_output.splitlines() if line.strip()]
        rules = ignore_rules or IgnoreRules.load(root)
        for finding in scan_paths(untracked_paths, root=root, ignore_rules=rules):
            findings.append(
                Finding(
                    path=finding.path,
                    line=finding.line,
                    rule=finding.rule,
                    redacted=finding.redacted,
                    source="uncommitted",
                )
            )
    return _deduplicate(findings)


def redact(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]}"


def _run_git(root: Path, arguments: list[str]) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "Git command failed."
        raise RuntimeError(message)
    return result.stdout


def _shannon_entropy(value: str) -> float:
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _deduplicate(findings: list[Finding]) -> list[Finding]:
    unique = {(finding.path, finding.line, finding.rule, finding.source): finding for finding in findings}
    return sorted(unique.values(), key=lambda finding: (finding.path, finding.line, finding.rule, finding.source))
