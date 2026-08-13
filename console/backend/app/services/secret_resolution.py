from __future__ import annotations

from dataclasses import dataclass
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.secret import Secret
from app.models.secret_import import SecretImport
from app.services.project_encryption import decrypt_project_secret
from app.services.secret_structure import normalize_secret_path, path_is_within
from app.services.secrets import get_latest_secret_rows

REFERENCE_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class SecretReferenceCycleError(ValueError):
    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(f"Secret reference cycle detected: {' -> '.join(cycle)}")


@dataclass(frozen=True)
class ResolvedSecretValue:
    key: str
    value: str
    version: int
    source: str
    source_environment_id: uuid.UUID
    source_path: str
    value_kind: str
    referenced_keys: list[str]
    resolved: bool
    error: str | None = None


def referenced_keys(value: str) -> list[str]:
    return list(dict.fromkeys(REFERENCE_PATTERN.findall(value)))


def contains_reference(value: str) -> bool:
    return bool(REFERENCE_PATTERN.search(value))


def _decrypt_row(db: Session, *, project_id: uuid.UUID, row: Secret) -> str:
    return decrypt_project_secret(
        db,
        project_id=project_id,
        encrypted_value=row.encrypted_value,
        encryption_key_version=row.encryption_key_version,
    )


def _select_flat_rows(rows: list[Secret], *, selected_path: str) -> list[Secret]:
    ordered = sorted(
        rows,
        key=lambda row: (
            row.path.count("/") - selected_path.count("/"),
            row.path,
            row.key,
        ),
    )
    selected: dict[str, Secret] = {}
    for row in ordered:
        selected.setdefault(row.key, row)
    return list(selected.values())


def resolve_secret_values(
    db: Session,
    *,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    path: str = "/",
    recursive: bool = False,
    include_imports: bool = True,
    resolve_references: bool = True,
    tags: list[str] | None = None,
) -> list[ResolvedSecretValue]:
    selected_path = normalize_secret_path(path)
    local_rows = _select_flat_rows(
        get_latest_secret_rows(
            db,
            environment_id=environment_id,
            path=selected_path,
            recursive=recursive,
            tags=tags,
        ),
        selected_path=selected_path,
    )

    values: dict[str, tuple[str, Secret, str, uuid.UUID, str]] = {}
    for row in local_rows:
        values[row.key] = (
            _decrypt_row(db, project_id=project_id, row=row),
            row,
            "local",
            environment_id,
            row.path,
        )

    if include_imports:
        rules = list(
            db.scalars(
                select(SecretImport)
                .where(
                    SecretImport.project_id == project_id,
                    SecretImport.target_environment_id == environment_id,
                    SecretImport.enabled.is_(True),
                )
                .order_by(
                    SecretImport.priority.desc(),
                    SecretImport.created_at.asc(),
                    SecretImport.id.asc(),
                )
            ).all()
        )
        applicable_rules = [
            rule
            for rule in rules
            if rule.target_path == selected_path
            or (recursive and path_is_within(rule.target_path, selected_path))
        ]
        for rule in applicable_rules:
            imported_rows = _select_flat_rows(
                get_latest_secret_rows(
                    db,
                    environment_id=rule.source_environment_id,
                    path=rule.source_path,
                    recursive=rule.recursive,
                    tags=tags,
                ),
                selected_path=rule.source_path,
            )
            for row in imported_rows:
                if row.key in values:
                    continue
                values[row.key] = (
                    _decrypt_row(db, project_id=project_id, row=row),
                    row,
                    "imported",
                    rule.source_environment_id,
                    row.path,
                )

    raw_values = {key: entry[0] for key, entry in values.items()}
    resolved_cache: dict[str, tuple[str, bool, str | None]] = {}

    def resolve_key(key: str, stack: list[str]) -> tuple[str, bool, str | None]:
        if key in resolved_cache:
            return resolved_cache[key]
        if key in stack:
            start = stack.index(key)
            raise SecretReferenceCycleError([*stack[start:], key])
        raw = raw_values[key]
        dependencies = referenced_keys(raw)
        if not resolve_references or not dependencies:
            result = (raw, not dependencies, None)
            resolved_cache[key] = result
            return result

        rendered = raw
        errors: list[str] = []
        for dependency in dependencies:
            if dependency not in raw_values:
                errors.append(f"Missing referenced secret: {dependency}")
                continue
            dependency_value, dependency_resolved, dependency_error = resolve_key(
                dependency, [*stack, key]
            )
            if not dependency_resolved:
                errors.append(dependency_error or f"Could not resolve {dependency}")
                continue
            rendered = rendered.replace(f"${{{dependency}}}", dependency_value)
        result = (rendered, not errors, "; ".join(errors) if errors else None)
        resolved_cache[key] = result
        return result

    output: list[ResolvedSecretValue] = []
    for key in sorted(values):
        raw, row, source, source_environment_id, source_path = values[key]
        value, resolved, error = resolve_key(key, [])
        dependencies = referenced_keys(raw)
        output.append(
            ResolvedSecretValue(
                key=key,
                value=value,
                version=row.version,
                source=source,
                source_environment_id=source_environment_id,
                source_path=source_path,
                value_kind="reference" if dependencies else "literal",
                referenced_keys=dependencies,
                resolved=resolved,
                error=error,
            )
        )
    return output


def validate_reference_cycles(
    db: Session,
    *,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    path: str,
) -> None:
    rows = get_latest_secret_rows(db, environment_id=environment_id, path=path)
    raw_values = {
        row.key: _decrypt_row(db, project_id=project_id, row=row)
        for row in rows
    }
    visited: set[str] = set()

    def visit(key: str, stack: list[str]) -> None:
        if key in stack:
            start = stack.index(key)
            raise SecretReferenceCycleError([*stack[start:], key])
        if key in visited:
            return
        for dependency in referenced_keys(raw_values[key]):
            if dependency in raw_values:
                visit(dependency, [*stack, key])
        visited.add(key)

    for key in raw_values:
        visit(key, [])
