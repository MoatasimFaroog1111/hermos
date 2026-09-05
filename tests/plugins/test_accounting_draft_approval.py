from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.accounting_brain.production_drafts.approval import (
    DraftApprovalError,
    approve_draft_proposal,
    verify_draft_approval,
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


def test_approval_receipt_is_bound_to_exact_proposal_bytes(tmp_path: Path) -> None:
    proposal_path = tmp_path / "drafts" / "proposal.json"
    proposal_path.parent.mkdir()
    proposal_path.write_text(json.dumps(_proposal(), sort_keys=True), encoding="utf-8")

    result = approve_draft_proposal(
        proposal_path,
        permitted_root=tmp_path,
        output_root=tmp_path / "approvals",
        reviewer="Finance Manager",
    )

    approval_path = tmp_path / "approvals" / result["approval_file"]
    verified = verify_draft_approval(
        approval_path,
        proposal_path,
        permitted_root=tmp_path,
    )
    assert verified["reviewer"] == "Finance Manager"
    assert verified["scope"] == "account.move.create:draft_only"
    assert verified["safety"]["posting_authorized"] is False


def test_proposal_tampering_after_approval_is_rejected(tmp_path: Path) -> None:
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(_proposal(), sort_keys=True), encoding="utf-8")
    result = approve_draft_proposal(
        proposal_path,
        permitted_root=tmp_path,
        output_root=tmp_path / "approvals",
        reviewer="Finance Manager",
    )
    approval_path = tmp_path / "approvals" / result["approval_file"]

    changed = _proposal()
    changed["prediction"]["reference"] = "CHANGED-AFTER-APPROVAL"
    proposal_path.write_text(json.dumps(changed, sort_keys=True), encoding="utf-8")

    with pytest.raises(DraftApprovalError, match="changed after human approval"):
        verify_draft_approval(
            approval_path,
            proposal_path,
            permitted_root=tmp_path,
        )


def test_approval_rejects_unvalidated_proposal(tmp_path: Path) -> None:
    proposal = _proposal()
    proposal["validation"] = {"valid": False}
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    with pytest.raises(DraftApprovalError, match="passing deterministic validation"):
        approve_draft_proposal(
            proposal_path,
            permitted_root=tmp_path,
            output_root=tmp_path / "approvals",
            reviewer="Finance Manager",
        )
