from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from envbasis_cli.context import require_app_context
from envbasis_cli.exit_codes import GENERAL_ERROR, SCAN_FINDINGS
from envbasis_cli.scanner import IgnoreRules, scan_git, scan_paths


def register(root_app: typer.Typer) -> None:
    @root_app.command("scan")
    def scan_command(
        ctx: typer.Context,
        paths: Annotated[
            list[Path] | None,
            typer.Argument(help="Files or directories to scan. Defaults to the current directory."),
        ] = None,
        git_history: Annotated[
            bool,
            typer.Option("--git-history", help="Scan additions across Git history."),
        ] = False,
        staged: Annotated[
            bool,
            typer.Option("--staged", help="Scan staged Git changes."),
        ] = False,
        uncommitted: Annotated[
            bool,
            typer.Option("--uncommitted", help="Scan unstaged Git changes."),
        ] = False,
        pre_commit: Annotated[
            bool,
            typer.Option("--pre-commit", help="Pre-commit mode: scan only staged changes."),
        ] = False,
        ignore_file: Annotated[
            Path | None,
            typer.Option("--ignore-file", help="Custom ignore file; defaults to .envbasisignore."),
        ] = None,
    ) -> None:
        app_context = require_app_context(ctx)
        root = Path.cwd().resolve()
        requested_paths = [path for path in (paths or [])]
        if not requested_paths and not any((git_history, staged, uncommitted, pre_commit)):
            requested_paths = [root]

        try:
            rules = IgnoreRules.load(root, ignore_file.expanduser().resolve() if ignore_file else None)
            findings = scan_paths(requested_paths, root=root, ignore_rules=rules) if requested_paths else []
            findings.extend(
                scan_git(
                    root,
                    history=git_history,
                    staged=staged or pre_commit,
                    uncommitted=uncommitted,
                    ignore_rules=rules,
                )
            )
            findings = list(
                {
                    (finding.path, finding.line, finding.rule, finding.source): finding
                    for finding in findings
                }.values()
            )
            findings.sort(key=lambda finding: (finding.path, finding.line, finding.rule, finding.source))
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            app_context.output.error(str(exc))
            raise typer.Exit(code=GENERAL_ERROR) from exc

        payload = {
            "findings": [finding.to_dict() for finding in findings],
            "count": len(findings),
            "actionable": bool(findings),
        }
        if app_context.options.output_json:
            app_context.output.emit_json(payload)
        elif not findings:
            app_context.output.success("No actionable secrets found.")
        else:
            app_context.output.table(
                "Potential Secrets",
                ["Source", "Path", "Line", "Rule", "Redacted Match"],
                [
                    [finding.source, finding.path, str(finding.line), finding.rule, finding.redacted]
                    for finding in findings
                ],
            )

        if findings:
            raise typer.Exit(code=SCAN_FINDINGS)
