"""Approval-bound Odoo draft creation orchestration.

This is the production entrypoint for creating an Accounting Brain proposal in
Odoo. It proves that a human approval receipt still matches the exact proposal
bytes before delegating to the existing create-only, draft-only Odoo use case.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plugins.accounting_brain.odoo_discovery.contracts import OdooReadPort
from plugins.accounting_brain.production_drafts.approval import verify_draft_approval
from plugins.accounting_brain.production_drafts.create_in_odoo import (
    create_reviewed_odoo_draft,
)
from plugins.accounting_brain.production_drafts.odoo_write import OdooDraftWritePort


def create_approved_odoo_draft(
    proposal_path: Path,
    approval_path: Path,
    *,
    permitted_root: Path,
    reader: OdooReadPort,
    writer: OdooDraftWritePort,
    requested_company_id: int | None = None,
) -> dict[str, Any]:
    """Verify immutable human approval, then create and verify one Odoo draft."""

    approval = verify_draft_approval(
        approval_path,
        proposal_path,
        permitted_root=permitted_root,
    )
    result = create_reviewed_odoo_draft(
        proposal_path,
        permitted_root=permitted_root,
        reader=reader,
        writer=writer,
        requested_company_id=requested_company_id,
    )
    result["approval"] = {
        "approval_file": Path(approval_path).name,
        "reviewer": approval.get("reviewer"),
        "approved_at": approval.get("approved_at"),
        "proposal_sha256": approval.get("proposal_sha256"),
        "scope": approval.get("scope"),
    }
    result["safety"]["approval_receipt_verified"] = True
    result["safety"]["proposal_checksum_bound_to_approval"] = True
    return result
