"""Fail-closed Odoo company scope for accounting evidence operations.

Historical accounting data must never be mixed across companies implicitly.
This use case sits above the read-only Odoo port so every entrypoint (CLI,
dashboard, future jobs) shares the same company-selection rule.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from plugins.accounting_brain.odoo_discovery.contracts import (
    OdooReadError,
    OdooReadPort,
)


class OdooCompanyScopeError(RuntimeError):
    """Raised when accounting evidence cannot be scoped to exactly one company."""


@dataclass(frozen=True)
class OdooCompany:
    id: int
    name: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_accessible_companies(reader: OdooReadPort) -> tuple[OdooCompany, ...]:
    """Return normalized companies visible to the authenticated Odoo user."""
    rows = reader.search_read(
        "res.company",
        [],
        fields=("id", "name"),
        limit=100,
        order="id asc",
    )
    companies: list[OdooCompany] = []
    seen: set[int] = set()
    for row in rows:
        try:
            company_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if company_id <= 0 or company_id in seen:
            continue
        seen.add(company_id)
        raw_name = str(row.get("name") or "").strip()
        companies.append(
            OdooCompany(
                id=company_id,
                name=raw_name or f"Company {company_id}",
            )
        )

    if not companies:
        raise OdooReadError("No accessible Odoo companies were returned")
    return tuple(companies)


def resolve_company_scope(
    reader: OdooReadPort,
    requested_company_id: int | None,
) -> OdooCompany:
    """Resolve exactly one accessible company for an accounting operation."""
    return resolve_company_from_candidates(
        list_accessible_companies(reader),
        requested_company_id,
    )


def resolve_company_from_candidates(
    companies: Iterable[OdooCompany],
    requested_company_id: int | None,
) -> OdooCompany:
    """Pure company-selection rule shared by tests and production entrypoints."""
    normalized = {company.id: company for company in companies if company.id > 0}
    if not normalized:
        raise OdooCompanyScopeError("No accessible Odoo company is available")

    if requested_company_id is not None:
        selected = normalized.get(int(requested_company_id))
        if selected is None:
            raise OdooCompanyScopeError(
                "Selected Odoo company is not accessible to this connection"
            )
        return selected

    if len(normalized) == 1:
        return next(iter(normalized.values()))

    raise OdooCompanyScopeError(
        "Select one Odoo company before auditing or exporting accounting history"
    )
