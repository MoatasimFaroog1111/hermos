"""Accounting Brain dashboard API.

Mounted by Hermes under ``/api/plugins/accounting_brain``. Every operation is
read-only against Odoo and delegates to the same discovery/audit use cases used
by the operator CLI. Credentials remain server-side environment secrets and
are never accepted from, or returned to, the browser.

Historical audit scope is fail-closed for multi-company databases: a single
accessible company is selected automatically, while multiple accessible
companies require an explicit company selection before journal history can be
sampled. This prevents cross-company accounting history from being mixed into
one training/audit population by accident.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hermes_constants import get_hermes_home
from plugins.accounting_brain.journal_training.audit import build_training_audit
from plugins.accounting_brain.journal_training.historical_journals import (
    JournalSelection,
    load_historical_journal_batch,
)
from plugins.accounting_brain.odoo_discovery.contracts import (
    CORE_ACCOUNTING_MODELS,
    OdooConfigurationError,
    OdooCredentials,
    OdooReadError,
    OdooReadPort,
)
from plugins.accounting_brain.odoo_discovery.discover import discover_odoo_schema
from plugins.accounting_brain.odoo_discovery.xmlrpc_adapter import OdooXmlRpcReadAdapter

router = APIRouter()


class AccountingSelectionError(RuntimeError):
    """Raised when accounting evidence scope is missing or ambiguous."""


class AuditRequest(BaseModel):
    """Bounded historical sample requested from the dashboard."""

    max_moves: int = Field(default=1000, ge=1, le=5000)
    date_from: date | None = None
    date_to: date | None = None
    company_id: int | None = Field(default=None, ge=1)


@router.get("/status")
async def status() -> dict[str, Any]:
    """Return secret-safe connectivity and company-scope status."""
    try:
        return await asyncio.to_thread(_status_sync)
    except OdooConfigurationError as exc:
        return {
            "ok": False,
            "configured": False,
            "connected": False,
            "mode": "read_only",
            "message": str(exc),
            "secrets_exposed": False,
            "companies": [],
            "company_selection_required": False,
            "default_company_id": None,
        }
    except OdooReadError as exc:
        return {
            "ok": False,
            "configured": True,
            "connected": False,
            "mode": "read_only",
            "message": str(exc),
            "secrets_exposed": False,
            "companies": [],
            "company_selection_required": False,
            "default_company_id": None,
        }


@router.post("/discover")
async def discover() -> dict[str, Any]:
    """Discover the actual Odoo accounting schema and persist the full report."""
    try:
        return await asyncio.to_thread(_discover_sync)
    except OdooConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OdooReadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/audit")
async def audit(request: AuditRequest) -> dict[str, Any]:
    """Audit one company's bounded posted-journal sample for training fitness."""
    if request.date_from and request.date_to and request.date_from > request.date_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")
    try:
        return await asyncio.to_thread(_audit_sync, request)
    except AccountingSelectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OdooConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OdooReadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _reader_from_environment() -> OdooXmlRpcReadAdapter:
    return OdooXmlRpcReadAdapter(OdooCredentials.from_environment())


def _status_sync() -> dict[str, Any]:
    reader = _reader_from_environment()
    uid = reader.authenticate()
    version = reader.version()
    companies = _accessible_companies(reader)
    default_company_id = companies[0]["id"] if len(companies) == 1 else None
    return {
        "ok": True,
        "configured": True,
        "connected": True,
        "mode": "read_only",
        "authenticated_user_id": uid,
        "server_version": version.get("server_version"),
        "server_serie": version.get("server_serie"),
        "protocol": version.get("protocol_version"),
        "secrets_exposed": False,
        "companies": companies,
        "company_selection_required": len(companies) > 1,
        "default_company_id": default_company_id,
    }


def _discover_sync() -> dict[str, Any]:
    reader = _reader_from_environment()
    report = discover_odoo_schema(reader, models=CORE_ACCOUNTING_MODELS).to_dict()
    output = _write_private_report("discovery", "odoo-schema", report)

    models = report["models"]
    available = [item for item in models if item["available"]]
    unavailable = [item for item in models if not item["available"]]
    return {
        "ok": True,
        "mode": "read_only",
        "models_requested": len(models),
        "models_available": len(available),
        "models_unavailable": len(unavailable),
        "available_models": [
            {"model": item["model"], "field_count": item["field_count"]}
            for item in available
        ],
        "unavailable_models": [item["model"] for item in unavailable],
        "report_file": output.name,
        "generated_at": report["generated_at"],
    }


def _audit_sync(request: AuditRequest) -> dict[str, Any]:
    reader = _reader_from_environment()
    companies = _accessible_companies(reader)
    selected_company = _resolve_company_scope(companies, request.company_id)
    selection = JournalSelection(
        max_moves=request.max_moves,
        date_from=request.date_from.isoformat() if request.date_from else None,
        date_to=request.date_to.isoformat() if request.date_to else None,
        company_id=int(selected_company["id"]),
    )
    batch = load_historical_journal_batch(reader, selection)
    report = build_training_audit(batch)
    report["selection_parameters"] = {
        "max_moves": selection.max_moves,
        "date_from": selection.date_from,
        "date_to": selection.date_to,
        "company_id": selection.company_id,
    }
    report["selected_company"] = selected_company
    output = _write_private_report("reports", "training-audit", report)
    return {
        "ok": True,
        "mode": "read_only",
        "report_file": output.name,
        "generated_at": report["generated_at"],
        "selected_company": selected_company,
        "selection": report["selection"],
        "quality": report["quality"],
        "taxonomy": report["taxonomy"],
    }


def _accessible_companies(reader: OdooReadPort) -> list[dict[str, Any]]:
    """Return normalized companies the authenticated Odoo user can read."""
    rows = reader.search_read(
        "res.company",
        [],
        fields=("id", "name"),
        limit=100,
        order="id asc",
    )
    companies: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        try:
            company_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if company_id <= 0 or company_id in seen:
            continue
        seen.add(company_id)
        name = str(row.get("name") or f"Company {company_id}").strip()
        companies.append({"id": company_id, "name": name or f"Company {company_id}"})

    if not companies:
        raise OdooReadError("No accessible Odoo companies were returned")
    return companies


def _resolve_company_scope(
    companies: list[dict[str, Any]],
    requested_company_id: int | None,
) -> dict[str, Any]:
    """Resolve exactly one company or reject an ambiguous audit request."""
    normalized = {
        int(company["id"]): {"id": int(company["id"]), "name": str(company["name"])}
        for company in companies
        if company.get("id")
    }
    if not normalized:
        raise AccountingSelectionError("No accessible Odoo company is available")

    if requested_company_id is not None:
        selected = normalized.get(int(requested_company_id))
        if selected is None:
            raise AccountingSelectionError(
                "Selected Odoo company is not accessible to this connection"
            )
        return selected

    if len(normalized) == 1:
        return next(iter(normalized.values()))

    raise AccountingSelectionError(
        "Select one Odoo company before auditing historical journals"
    )


def _write_private_report(category: str, prefix: str, payload: dict[str, Any]) -> Path:
    """Persist private analysis under HERMES_HOME, which is a Railway volume."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = (get_hermes_home() / "accounting_brain" / category).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass

    path = root / f"{prefix}-{stamp}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
