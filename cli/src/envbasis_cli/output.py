from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table


class OutputManager:
    def __init__(self, *, output_json: bool = False, verbose: bool = False) -> None:
        self.output_json = output_json
        self.verbose = verbose
        self.console = Console()
        self.error_console = Console(stderr=True)

    def emit_json(self, payload: Any) -> None:
        self.console.print_json(json.dumps(payload, default=str))

    def success(self, message: str) -> None:
        self.console.print(f"[green]{message}[/green]")

    def info(self, message: str) -> None:
        self.console.print(message)

    def write(self, message: str, *, end: str = "\n") -> None:
        self.console.print(message, end=end, highlight=False, markup=False, soft_wrap=True)

    def write_styled(self, message: str, *, style: str | None = None, end: str = "\n") -> None:
        self.console.print(
            message,
            style=style,
            end=end,
            highlight=False,
            markup=False,
            soft_wrap=True,
        )

    def error(self, message: str) -> None:
        self.error_console.print(f"[red]{message}[/red]")

    def table(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        table = Table(title=title)
        for column in columns:
            table.add_column(column)
        for row in rows:
            table.add_row(*row)
        self.console.print(table)
