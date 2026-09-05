from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.accounting_brain.production_drafts.create_in_odoo import (
    create_reviewed_odoo_draft,
)
from plugins.accounting_brain.production_drafts.odoo_write import (
    OdooDraftWriteError,
    _validated_create_payload,
)


def _prediction() -> dict:
    return {
        "move_type": "in_invoice",
        "date": "2026-09-05",
        "reference": "INV-100",
        "journal": {"id": 3, "name": "Vendor Bills"},
        "partner": {"id": 9, "name": "Supplier"},
        "company": {"id": 1, "name": "Guardian"},
        "currency": {"id": 1, "name": "SAR"},
        "taxes": [],
        "journal_entry": [
            {
                "account_code": "510100",
                "debit": "100.00",
                "credit": "0.00",
                "tax_ids": [],
                "analytic_distribution": {},
            },
            {
                "account_code": "211000",
                "debit": "0.00",
                "credit": "100.00",
                "tax_ids": [],
                "analytic_distribution": {},
            },
        ],
    }


class FakeReader:
    def fields_get(self, model, *, attributes=None):
        if model in {"account.account", "account.journal", "account.tax"}:
            return {"id": {"type": "integer"}, "company_id": {"type": "many2one"}}
        return {"id": {"type": "integer"}}

    def search_read(
        self,
        model,
        domain,
        *,
        fields=None,
        limit=None,
        offset=0,
        order=None,
    ):
        if model == "res.company":
            return [{"id": 1, "name": "Guardian"}]
        if model == "account.account":
            code = next(value for field, operator, value in domain if field == "code")
            account_id = {"510100": 101, "211000": 201}.get(code)
            return [{"id": account_id, "code": code}] if account_id else []
        return []

    def read(self, model, ids, *, fields=None):
        record_id = int(ids[0])
        if model == "account.journal" and record_id == 3:
            return [{"id": 3, "company_id": [1, "Guardian"]}]
        if model == "res.currency" and record_id == 1:
            return [{"id": 1}]
        if model == "res.partner" and record_id == 9:
            return [{"id": 9}]
        if model == "account.move" and record_id == 77:
            return [
                {
                    "id": 77,
                    "name": "/",
                    "state": "draft",
                    "move_type": "in_invoice",
                    "journal_id": [3, "Vendor Bills"],
                    "company_id": [1, "Guardian"],
                }
            ]
        return []

    def search_count(self, model, domain):
        return 0

    def authenticate(self):
        return 1

    def version(self):
        return {"server_version": "19.0"}


class FakeWriter:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def create_draft_move(self, values: dict) -> int:
        self.payloads.append(values)
        assert values.get("state", "draft") == "draft"
        return 77


def test_reviewed_proposal_creates_and_verifies_draft_only(tmp_path: Path) -> None:
    proposal = {
        "stage": "READY_FOR_HUMAN_REVIEW",
        "production_mode": "draft_only",
        "prediction": _prediction(),
    }
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    writer = FakeWriter()

    result = create_reviewed_odoo_draft(
        proposal_path,
        permitted_root=tmp_path,
        reader=FakeReader(),
        writer=writer,
        requested_company_id=1,
    )

    assert result["ok"] is True
    assert result["stage"] == "ODOO_DRAFT_CREATED_VERIFIED"
    assert result["verification"]["state"] == "draft"
    assert result["safety"]["posted"] is False
    assert result["safety"]["write_methods_exposed"] == ["account.move.create"]
    assert len(writer.payloads) == 1
    assert writer.payloads[0]["date"] == "2026-09-05"
    assert len(writer.payloads[0]["line_ids"]) == 2


def test_create_only_adapter_rejects_non_draft_state() -> None:
    with pytest.raises(OdooDraftWriteError, match="Only draft"):
        _validated_create_payload(
            {
                "state": "posted",
                "line_ids": [(0, 0, {"account_id": 1, "debit": 1.0})],
            }
        )
