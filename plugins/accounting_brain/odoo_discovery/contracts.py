"""Contracts for read-only Odoo discovery.

The Accounting Brain starts from evidence. This port intentionally exposes only
read operations; mutation methods do not exist on the interface.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol, Sequence


class OdooConfigurationError(RuntimeError):
    """Raised when required Odoo connection settings are missing."""


class OdooReadError(RuntimeError):
    """Raised when a read-only Odoo operation fails."""


@dataclass(frozen=True)
class OdooCredentials:
    url: str
    database: str
    username: str
    api_key: str

    @classmethod
    def from_environment(cls) -> "OdooCredentials":
        """Load credentials without logging or exposing secret values.

        ``ODOO_DB`` is the preferred Hermes skill name. ``ODOO_DATABASE`` is
        accepted for compatibility with existing deployments.
        """
        values = {
            "url": (os.environ.get("ODOO_URL") or "").strip(),
            "database": (
                os.environ.get("ODOO_DB")
                or os.environ.get("ODOO_DATABASE")
                or ""
            ).strip(),
            "username": (os.environ.get("ODOO_USERNAME") or "").strip(),
            "api_key": (os.environ.get("ODOO_API_KEY") or "").strip(),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            display = {
                "url": "ODOO_URL",
                "database": "ODOO_DB (or ODOO_DATABASE)",
                "username": "ODOO_USERNAME",
                "api_key": "ODOO_API_KEY",
            }
            raise OdooConfigurationError(
                "Missing Odoo secret(s): "
                + ", ".join(display[name] for name in missing)
            )
        return cls(**values)


class OdooReadPort(Protocol):
    """Read-only boundary consumed by accounting discovery use cases."""

    def authenticate(self) -> int:
        """Return the authenticated Odoo user id."""

    def version(self) -> dict[str, Any]:
        """Return server version metadata available from Odoo common API."""

    def fields_get(
        self,
        model: str,
        *,
        attributes: Sequence[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Read model field metadata."""

    def search_read(
        self,
        model: str,
        domain: list[Any],
        *,
        fields: Sequence[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search records and return selected fields."""

    def read(
        self,
        model: str,
        ids: Sequence[int],
        *,
        fields: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read known records by id."""

    def search_count(self, model: str, domain: list[Any]) -> int:
        """Count matching records."""


CORE_ACCOUNTING_MODELS: tuple[str, ...] = (
    "account.move",
    "account.move.line",
    "account.account",
    "account.journal",
    "account.tax",
    "res.partner",
    "res.company",
    "res.currency",
    "account.analytic.account",
    "ir.attachment",
)
