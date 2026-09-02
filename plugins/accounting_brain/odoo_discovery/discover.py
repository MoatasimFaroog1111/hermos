"""Odoo accounting schema discovery use case."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from plugins.accounting_brain.odoo_discovery.contracts import (
    CORE_ACCOUNTING_MODELS,
    OdooReadError,
    OdooReadPort,
)


_FIELD_ATTRIBUTES = (
    "string",
    "type",
    "relation",
    "required",
    "readonly",
    "store",
    "selection",
)


@dataclass(frozen=True)
class ModelSchemaSnapshot:
    model: str
    available: bool
    field_count: int
    fields: dict[str, dict[str, Any]]
    error: str | None = None


@dataclass(frozen=True)
class OdooSchemaReport:
    generated_at: str
    server_version: dict[str, Any]
    models: tuple[ModelSchemaSnapshot, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "server_version": self.server_version,
            "models": [asdict(item) for item in self.models],
        }


def discover_odoo_schema(
    reader: OdooReadPort,
    models: Iterable[str] = CORE_ACCOUNTING_MODELS,
) -> OdooSchemaReport:
    """Inspect actual Odoo metadata instead of assuming version-specific fields."""
    reader.authenticate()
    snapshots: list[ModelSchemaSnapshot] = []
    seen: set[str] = set()

    for raw_model in models:
        model = str(raw_model or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        try:
            fields = reader.fields_get(model, attributes=_FIELD_ATTRIBUTES)
        except OdooReadError as exc:
            snapshots.append(
                ModelSchemaSnapshot(
                    model=model,
                    available=False,
                    field_count=0,
                    fields={},
                    error=str(exc),
                )
            )
            continue

        normalized: dict[str, dict[str, Any]] = {}
        for field_name, metadata in sorted(fields.items()):
            clean = {
                key: value
                for key, value in dict(metadata or {}).items()
                if key in _FIELD_ATTRIBUTES and value not in (None, False, "")
            }
            normalized[str(field_name)] = clean

        snapshots.append(
            ModelSchemaSnapshot(
                model=model,
                available=True,
                field_count=len(normalized),
                fields=normalized,
            )
        )

    return OdooSchemaReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        server_version=reader.version(),
        models=tuple(snapshots),
    )
