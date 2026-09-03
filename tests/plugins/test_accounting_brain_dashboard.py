from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from hermes_cli.plugins import get_bundled_plugins_dir
from hermes_cli.required_dashboard_plugins import validate_bundled_dashboard_plugin
from plugins.accounting_brain.dashboard import plugin_api
from plugins.accounting_brain.dashboard.plugin_api import (
    AuditRequest,
    ReadinessRequest,
    status,
)
from plugins.accounting_brain.odoo_discovery.company_scope import (
    OdooCompany,
    OdooCompanyScopeError,
    resolve_company_from_candidates,
)


def test_accounting_dashboard_manifest_declares_valid_assets() -> None:
    manifest = validate_bundled_dashboard_plugin(
        get_bundled_plugins_dir(),
        "accounting_brain",
    )

    assert manifest["tab"]["path"] == "/accounting"
    assert manifest["api"] == "plugin_api.py"


def test_accounting_dashboard_uses_readable_theme_tokens() -> None:
    css_path = (
        get_bundled_plugins_dir()
        / "accounting_brain"
        / "dashboard"
        / "dist"
        / "style.css"
    )
    css = css_path.read_text(encoding="utf-8")

    # Hermes intentionally gives --foreground alpha 0 in its default LENS_0
    # palette. Dashboard plugins must route visible text through --midground
    # (or a semantic alias derived from it) rather than consuming the
    # transparent raw token directly.
    assert "--ab-text: var(--midground" in css
    assert "--ab-primary: var(--midground" in css
    assert "var(--foreground)" not in css


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


def test_launch_readiness_request_defaults_are_conservative() -> None:
    request = ReadinessRequest(max_moves=1000, company_id=1)

    assert request.include_silver is False
    assert request.download_attachments is False
    assert request.max_attachment_mb == 25

    with pytest.raises(ValidationError):
        ReadinessRequest(max_moves=1000, company_id=1, max_attachment_mb=101)


def test_launch_readiness_passes_only_data_gate_without_enabling_training(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeReader:
        def authenticate(self) -> int:
            return 7

        def version(self) -> dict[str, str]:
            return {"server_version": "19.0"}

    class FakeDiscovery:
        def to_dict(self) -> dict:
            return {
                "models": [
                    {"model": "account.move", "available": True},
                    {"model": "account.move.line", "available": True},
                ]
            }

    class FakeSink:
        def __init__(self, root: Path) -> None:
            self.root = root

        def write_report(self, name: str, payload: dict) -> Path:
            return self.root / name

    fake_batch = object()

    monkeypatch.setattr(plugin_api, "_reader_from_environment", lambda: FakeReader())
    monkeypatch.setattr(
        plugin_api,
        "resolve_company_scope",
        lambda reader, company_id: OdooCompany(id=1, name="Guardian Technical Contracting"),
    )
    monkeypatch.setattr(
        plugin_api,
        "discover_odoo_schema",
        lambda reader, models: FakeDiscovery(),
    )
    monkeypatch.setattr(
        plugin_api,
        "load_historical_journal_batch",
        lambda reader, selection: fake_batch,
    )
    monkeypatch.setattr(
        plugin_api,
        "build_training_audit",
        lambda batch: {
            "selection": {
                "sampled_posted_moves": 10,
                "total_matching_posted_moves": 10,
            },
            "quality": {
                "grades": {"gold": 10, "silver": 0, "rejected": 0},
                "gold_rate": 1.0,
                "attachment_coverage": 1.0,
            },
            "taxonomy": {},
        },
    )
    monkeypatch.setattr(plugin_api, "FilesystemTrainingDatasetSink", FakeSink)
    monkeypatch.setattr(
        plugin_api,
        "export_training_pairs",
        lambda reader, batch, sink, **kwargs: {
            "exported_pairs": 10,
            "skipped_pairs": 0,
            "dataset_root": str(sink.root),
        },
    )
    monkeypatch.setattr(
        plugin_api,
        "_write_private_report",
        lambda category, prefix, payload: Path(f"{prefix}.json"),
    )

    result = plugin_api._readiness_sync(
        ReadinessRequest(max_moves=10, company_id=1)
    )

    assert result["ok"] is True
    assert result["stage"] == "DATA_READY_FOR_GOLDEN_REVIEW"
    assert result["next_gate"] == "MODEL_EVALUATION_REQUIRED"
    assert result["gates"]["golden_dataset_created"] is True
    assert result["gates"]["model_training_enabled"] is False
    assert result["gates"]["auto_post_disabled"] is True
    assert result["gates"]["human_review_required"] is True
    assert result["safety"] == {
        "odoo_mutations": False,
        "training_performed": False,
        "auto_post": False,
        "secrets_exposed": False,
    }


def test_launch_readiness_blocks_when_no_gold_pairs_are_exported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeReader:
        def authenticate(self) -> int:
            return 7

        def version(self) -> dict[str, str]:
            return {"server_version": "19.0"}

    class FakeDiscovery:
        def to_dict(self) -> dict:
            return {
                "models": [
                    {"model": "account.move", "available": True},
                    {"model": "account.move.line", "available": True},
                ]
            }

    class FakeSink:
        def __init__(self, root: Path) -> None:
            self.root = root

        def write_report(self, name: str, payload: dict) -> Path:
            return self.root / name

    monkeypatch.setattr(plugin_api, "_reader_from_environment", lambda: FakeReader())
    monkeypatch.setattr(
        plugin_api,
        "resolve_company_scope",
        lambda reader, company_id: OdooCompany(id=1, name="Guardian Technical Contracting"),
    )
    monkeypatch.setattr(
        plugin_api,
        "discover_odoo_schema",
        lambda reader, models: FakeDiscovery(),
    )
    monkeypatch.setattr(
        plugin_api,
        "load_historical_journal_batch",
        lambda reader, selection: object(),
    )
    monkeypatch.setattr(
        plugin_api,
        "build_training_audit",
        lambda batch: {
            "selection": {
                "sampled_posted_moves": 10,
                "total_matching_posted_moves": 10,
            },
            "quality": {
                "grades": {"gold": 0, "silver": 0, "rejected": 10},
                "gold_rate": 0.0,
                "attachment_coverage": 0.0,
            },
            "taxonomy": {},
        },
    )
    monkeypatch.setattr(plugin_api, "FilesystemTrainingDatasetSink", FakeSink)
    monkeypatch.setattr(
        plugin_api,
        "export_training_pairs",
        lambda reader, batch, sink, **kwargs: {
            "exported_pairs": 0,
            "skipped_pairs": 10,
            "dataset_root": str(sink.root),
        },
    )
    monkeypatch.setattr(
        plugin_api,
        "_write_private_report",
        lambda category, prefix, payload: Path(f"{prefix}.json"),
    )

    result = plugin_api._readiness_sync(
        ReadinessRequest(max_moves=10, company_id=1)
    )

    assert result["ok"] is False
    assert result["stage"] == "BLOCKED_BY_DATA_GATE"
    assert result["gates"]["golden_dataset_created"] is False
    assert result["gates"]["model_training_enabled"] is False
    assert result["safety"]["auto_post"] is False


def test_single_company_scope_is_selected_automatically() -> None:
    selected = resolve_company_from_candidates(
        (OdooCompany(id=1, name="Guardian Technical Contracting"),),
        None,
    )

    assert selected == OdooCompany(id=1, name="Guardian Technical Contracting")


def test_multi_company_scope_requires_explicit_selection() -> None:
    companies = (
        OdooCompany(id=1, name="Guardian Technical Contracting"),
        OdooCompany(id=2, name="Another Company"),
    )

    with pytest.raises(
        OdooCompanyScopeError,
        match="Select one Odoo company",
    ):
        resolve_company_from_candidates(companies, None)


def test_multi_company_scope_accepts_only_accessible_company() -> None:
    companies = (
        OdooCompany(id=1, name="Guardian Technical Contracting"),
        OdooCompany(id=2, name="Another Company"),
    )

    assert resolve_company_from_candidates(companies, 2) == OdooCompany(
        id=2,
        name="Another Company",
    )

    with pytest.raises(
        OdooCompanyScopeError,
        match="not accessible",
    ):
        resolve_company_from_candidates(companies, 99)
