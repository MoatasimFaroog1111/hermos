from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.accounting_brain.production_drafts.approval import (
    DraftApprovalError,
    approve_draft_proposal,
)
from plugins.accounting_brain.production_drafts.approved_create import (
    create_approved_odoo_draft,
)


def _proposal() -> dict:
    return {
        "stage": "READY_FOR_HUMAN_REVIEW",
        "production_mode": "draft_only",
        "validation": {"valid": True},
        "prediction": {
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
        },
    }


class NeverCalledReader:
    def __getattr__(self, name):
        raise AssertionError(f"Odoo reader must not be called before approval verification: {name}")


class NeverCalledWriter:
    def create_draft_move(self, values):
        raise AssertionError("Odoo writer must not be called before approval verification")


def test_tampered_proposal_blocks_before_any_odoo_access(tmp_path: Path) -> None:
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(_proposal(), sort_keys=True), encoding="utf-8")
    approval = approve_draft_proposal(
        proposal_path,
        permitted_root=tmp_path,
        output_root=tmp_path / "approvals",
        reviewer="Finance Manager",
    )
    approval_path = tmp_path / "approvals" / approval["approval_file"]

    changed = _proposal()
    changed["prediction"]["reference"] = "TAMPERED"
    proposal_path.write_text(json.dumps(changed, sort_keys=True), encoding="utf-8")

    with pytest.raises(DraftApprovalError, match="changed after human approval"):
        create_approved_odoo_draft(
            proposal_path,
            approval_path,
            permitted_root=tmp_path,
            reader=NeverCalledReader(),
            writer=NeverCalledWriter(),
            requested_company_id=1,
        )
