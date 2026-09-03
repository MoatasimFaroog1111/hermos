"""Accounting Brain dashboard API.

Mounted by Hermes under ``/api/plugins/accounting_brain``. Every operation is
read-only against Odoo and delegates to the same discovery/audit/export use
cases used by the operator CLI. Credentials remain server-side environment
secrets and are never accepted from, or returned to, the browser.

Historical audit and dataset scope is fail-closed for multi-company databases.
The shared company-scope use case is also used by the CLI so no entrypoint can
silently mix accounting histories from different Odoo companies.
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
from plugins.accounting_brain.journal_training.export import export_training_pairs
from plugins.accounting_brain.journal_training.filesystem_dataset import (
    FilesystemTrainingDatasetSink,
)
from plugins.accounting_brain.journal_training.historical_journals import (
    JournalSelection,
    load_historical_journal_batch,
)
from plugins.accounting_brain.odoo_discovery.company_scope import (
    OdooCompanyScopeError,
    list_accessible_companies,
    resolve_company_scope,
)
from plugins.accounting_brain.odoo_discovery.contracts import (
    CORE_ACCOUNTING_MODELS,
    OdooConfigurationError,
    OdooCredentials,
    OdooReadError,
)
from plugins.accounting_brain.odoo_discovery.discover import discover_odoo_schema
from plugins.accounting_brain.odoo_discovery.xmlrpc_adapter import OdooXmlRpcReadAdapter

router = APIRouter()


class AuditRequest(BaseModel):
    """Bounded historical sample requested from the dashboard."""

    max_moves: int = Field(default=1000, ge=1, le=5000)
    date_from: date | None = None
    date_to: date | None = None
    company_id: int | None = Field(default=None, ge=1)


class ReadinessRequest(AuditRequest):
    """One-click read-only launch-readiness pipeline configuration."""

    include_silver: bool = False
    download_attachments: bool = False
    max_attachment_mb: int = Field(default=25, ge=1, le=100)


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
    _validate_dates(request)
    try:
        return await asyncio.to_thread(_audit_sync, request)
    except OdooCompanyScopeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OdooConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OdooReadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/readiness")
async def readiness(request: ReadinessRequest) -> dict[str, Any]:
    """Run the shortest safe path from live Odoo evidence to a Gold dataset.

    This endpoint never trains a model and never mutates Odoo. It proves the
    data layer needed before model work: connectivity, schema, one-company
    scope, historical audit, deterministic Gold/Silver/Rejected grading, and a
    private attachment-to-journal dataset manifest.
    """
    _validate_dates(request)
    try:
        return await asyncio.to_thread(_readiness_sync, request)
    except OdooCompanyScopeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OdooConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OdooReadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _validate_dates(request: AuditRequest) -> None:
    if request.date_from and request.date_to and request.date_from > request.date_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")


def _reader_from_environment() -> OdooXmlRpcReadAdapter:
    return OdooXmlRpcReadAdapter(OdooCredentials.from_environment())


def _status_sync() -> dict[str, Any]:
    reader = _reader_from_environment()
    uid = reader.authenticate()
    version = reader.version()
    companies = list_accessible_companies(reader)
    default_company_id = companies[0].id if len(companies) == 1 else None
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
        "companies": [company.to_dict() for company in companies],
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


def _selection_from_request(request: AuditRequest, company_id: int) -> JournalSelection:
    return JournalSelection(
        max_moves=request.max_moves,
        date_from=request.date_from.isoformat() if request.date_from else None,
        date_to=request.date_to.isoformat() if request.date_to else None,
        company_id=company_id,
    )


def _audit_sync(request: AuditRequest) -> dict[str, Any]:
    reader = _reader_from_environment()
    selected_company = resolve_company_scope(reader, request.company_id)
    selection = _selection_from_request(request, selected_company.id)
    batch = load_historical_journal_batch(reader, selection)
    report = build_training_audit(batch)
    report["selection_parameters"] = {
        "max_moves": selection.max_moves,
        "date_from": selection.date_from,
        "date_to": selection.date_to,
        "company_id": selection.company_id,
    }
    report["selected_company"] = selected_company.to_dict()
    output = _write_private_report("reports", "training-audit", report)
    return {
        "ok": True,
        "mode": "read_only",
        "report_file": output.name,
        "generated_at": report["generated_at"],
        "selected_company": selected_company.to_dict(),
        "selection": report["selection"],
        "quality": report["quality"],
        "taxonomy": report["taxonomy"],
    }


def _readiness_sync(request: ReadinessRequest) -> dict[str, Any]:
    reader = _reader_from_environment()

    uid = reader.authenticate()
    version = reader.version()
    selected_company = resolve_company_scope(reader, request.company_id)

    discovery_report = discover_odoo_schema(
        reader,
        models=CORE_ACCOUNTING_MODELS,
    ).to_dict()
    discovery_file = _write_private_report(
        "discovery",
        "odoo-schema",
        discovery_report,
    )

    selection = _selection_from_request(request, selected_company.id)
    batch = load_historical_journal_batch(reader, selection)
    audit_report = build_training_audit(batch)
    audit_report["selection_parameters"] = {
        "max_moves": selection.max_moves,
        "date_from": selection.date_from,
        "date_to": selection.date_to,
        "company_id": selection.company_id,
    }
    audit_report["selected_company"] = selected_company.to_dict()
    audit_file = _write_private_report("reports", "training-audit", audit_report)

    dataset_root = (
        get_hermes_home()
        / "accounting_brain"
        / "datasets"
        / f"golden-{_timestamp()}"
    )
    sink = FilesystemTrainingDatasetSink(dataset_root)
    export_report = export_training_pairs(
        reader,
        batch,
        sink,
        include_silver=request.include_silver,
        download_attachments=request.download_attachments,
        max_attachment_bytes=request.max_attachment_mb * 1024 * 1024,
    )
    export_report["selected_company"] = selected_company.to_dict()
    export_report["selection_parameters"] = audit_report["selection_parameters"]
    export_report["dataset_kind"] = "golden_manifest"
    sink.write_report("export-report.json", export_report)

    available_models = {
        item["model"]
        for item in discovery_report["models"]
        if item["available"]
    }
    sampled_moves = int(audit_report["selection"]["sampled_posted_moves"] or 0)
    exported_pairs = int(export_report["exported_pairs"] or 0)

    gates = {
        "odoo_connection": True,
        "read_only_mode": True,
        "single_company_scope": True,
        "core_schema_available": {
            "pass": {"account.move", "account.move.line"}.issubset(available_models),
            "required": ["account.move", "account.move.line"],
        },
        "historical_sample_available": sampled_moves > 0,
        "golden_dataset_created": exported_pairs > 0,
        "auto_post_disabled": True,
        "human_review_required": True,
        "model_training_enabled": False,
    }
    data_gate_passed = all(
        (
            gates["odoo_connection"],
            gates["read_only_mode"],
            gates["single_company_scope"],
            gates["core_schema_available"]["pass"],
            gates["historical_sample_available"],
            gates["golden_dataset_created"],
            gates["auto_post_disabled"],
            gates["human_review_required"],
            not gates["model_training_enabled"],
        )
    )

    readiness_report = {
        "ok": data_gate_passed,
        "mode": "read_only",
        "stage": (
            "DATA_READY_FOR_GOLDEN_REVIEW"
            if data_gate_passed
            else "BLOCKED_BY_DATA_GATE"
        ),
        "next_gate": "MODEL_EVALUATION_REQUIRED",
        "authenticated_user_id": uid,
        "server_version": version.get("server_version"),
        "selected_company": selected_company.to_dict(),
        "gates": gates,
        "discovery": {
            "report_file": discovery_file.name,
            "models_requested": len(discovery_report["models"]),
            "models_available": len(available_models),
        },
        "audit": {
            "report_file": audit_file.name,
            "selection": audit_report["selection"],
            "quality": audit_report["quality"],
            "taxonomy": audit_report["taxonomy"],
        },
        "golden_dataset": export_report,
        "safety": {
            "odoo_mutations": False,
            "training_performed": False,
            "auto_post": False,
            "secrets_exposed": False,
        },
    }
    readiness_file = _write_private_report(
        "reports",
        "launch-readiness",
        readiness_report,
    )
    readiness_report["report_file"] = readiness_file.name
    return readiness_report


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write_private_report(category: str, prefix: str, payload: dict[str, Any]) -> Path:
    """Persist private analysis under HERMES_HOME, which is a Railway volume."""
    root = (get_hermes_home() / "accounting_brain" / category).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass

    path = root / f"{prefix}-{_timestamp()}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
