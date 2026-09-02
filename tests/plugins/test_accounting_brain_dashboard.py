from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from hermes_cli.plugins import get_bundled_plugins_dir
from hermes_cli.required_dashboard_plugins import validate_bundled_dashboard_plugin
from plugins.accounting_brain.dashboard.plugin_api import (
    AccountingSelectionError,
    AuditRequest,
    _resolve_company_scope,
    status,
)


def test_accounting_dashboard_manifest_declares_valid_assets() -> None:
    manifest = validate_bundled_dashboard_plugin(
        get_bundled_plugins_dir(),
        "accounting_brain",
    )

    assert manifest["tab"]["path"] == "/accounting"
    assert manifest["api"] == "plugin_api.py"


def test_accounting_dashboard_status_is_secret_safe_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "ODOO_URL",
        "ODOO_DB",
        "ODOO_DATABASE",
        "ODOO_USERNAME",
        "ODOO_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    payload = asyncio.run(status())

    assert payload["ok"] is False
    assert payload["configured"] is False
    assert payload["connected"] is False
    assert payload["secrets_exposed"] is False
    assert payload["companies"] == []
    assert payload["company_selection_required"] is False
    assert "ODOO_API_KEY" in payload["message"]


def test_accounting_dashboard_audit_sample_is_bounded() -> None:
    with pytest.raises(ValidationError):
        AuditRequest(max_moves=5001)

    request = AuditRequest(max_moves=1000)
    assert request.max_moves == 1000


def test_single_company_scope_is_selected_automatically() -> None:
    selected = _resolve_company_scope(
        [{"id": 1, "name": "Guardian Technical Contracting"}],
        None,
    )

    assert selected == {"id": 1, "name": "Guardian Technical Contracting"}


def test_multi_company_scope_requires_explicit_selection() -> None:
    companies = [
        {"id": 1, "name": "Guardian Technical Contracting"},
        {"id": 2, "name": "Another Company"},
    ]

    with pytest.raises(
        AccountingSelectionError,
        match="Select one Odoo company",
    ):
        _resolve_company_scope(companies, None)


def test_multi_company_scope_accepts_only_accessible_company() -> None:
    companies = [
        {"id": 1, "name": "Guardian Technical Contracting"},
        {"id": 2, "name": "Another Company"},
    ]

    assert _resolve_company_scope(companies, 2) == {
        "id": 2,
        "name": "Another Company",
    }

    with pytest.raises(
        AccountingSelectionError,
        match="not accessible",
    ):
        _resolve_company_scope(companies, 99)
