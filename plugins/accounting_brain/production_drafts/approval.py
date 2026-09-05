"""Auditable human-approval receipts for Accounting Brain draft creation.

Approval is deliberately separated from both model inference and Odoo mutation.
A receipt is bound to the exact persisted proposal bytes by SHA-256. Any change
to the proposal after approval invalidates the receipt and blocks Odoo creation.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_APPROVAL_STAGE = "HUMAN_APPROVED_FOR_ODOO_DRAFT_CREATE"
_APPROVAL_SCOPE = "account.move.create:draft_only"


class DraftApprovalError(RuntimeError):
    """Raised when a draft approval cannot be created or verified safely."""


def approve_draft_proposal(
    proposal_path: Path,
    *,
    permitted_root: Path,
    output_root: Path,
    reviewer: str,
) -> dict[str, Any]:
    """Create a private approval receipt bound to one exact proposal file."""

    proposal_file = _resolve_private_file(proposal_path, permitted_root, "proposal")
    proposal = _load_json_object(proposal_file, "proposal")
    if proposal.get("stage") != "READY_FOR_HUMAN_REVIEW":
        raise DraftApprovalError("Proposal is not ready for human review")
    if proposal.get("production_mode") != "draft_only":
        raise DraftApprovalError("Proposal is not marked draft_only")
    validation = proposal.get("validation")
    if not isinstance(validation, dict) or validation.get("valid") is not True:
        raise DraftApprovalError("Proposal does not contain a passing deterministic validation")
    reviewer_name = str(reviewer or "").strip()
    if not reviewer_name:
        raise DraftApprovalError("Reviewer identity is required")

    proposal_sha256 = _sha256_file(proposal_file)
    receipt = {
        "ok": True,
        "stage": _APPROVAL_STAGE,
        "scope": _APPROVAL_SCOPE,
        "proposal_file": proposal_file.name,
        "proposal_sha256": proposal_sha256,
        "reviewer": reviewer_name[:200],
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "safety": {
            "odoo_write_performed": False,
            "posting_authorized": False,
            "draft_create_only": True,
            "proposal_mutation_after_approval_allowed": False,
        },
    }
    receipt_path = _write_private_receipt(output_root, permitted_root, receipt)
    receipt["approval_file"] = receipt_path.name
    return receipt


def verify_draft_approval(
    approval_path: Path,
    proposal_path: Path,
    *,
    permitted_root: Path,
) -> dict[str, Any]:
    """Verify approval stage, scope, reviewer, and proposal checksum binding."""

    approval_file = _resolve_private_file(approval_path, permitted_root, "approval")
    proposal_file = _resolve_private_file(proposal_path, permitted_root, "proposal")
    receipt = _load_json_object(approval_file, "approval")
    if receipt.get("stage") != _APPROVAL_STAGE:
        raise DraftApprovalError("Approval receipt has an invalid stage")
    if receipt.get("scope") != _APPROVAL_SCOPE:
        raise DraftApprovalError("Approval receipt does not authorize draft creation")
    if not str(receipt.get("reviewer") or "").strip():
        raise DraftApprovalError("Approval receipt has no reviewer identity")
    expected_name = str(receipt.get("proposal_file") or "").strip()
    if expected_name and expected_name != proposal_file.name:
        raise DraftApprovalError("Approval receipt belongs to a different proposal")
    expected_sha = str(receipt.get("proposal_sha256") or "").strip().lower()
    actual_sha = _sha256_file(proposal_file)
    if not expected_sha or expected_sha != actual_sha:
        raise DraftApprovalError("Proposal changed after human approval")
    return receipt


def _resolve_private_file(path: Path, permitted_root: Path, label: str) -> Path:
    root = Path(permitted_root).expanduser().resolve()
    candidate = Path(path).expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise DraftApprovalError(f"{label.capitalize()} file must stay inside Hermes private data") from exc
    if not candidate.is_file():
        raise DraftApprovalError(f"{label.capitalize()} file does not exist")
    return candidate


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DraftApprovalError(f"Invalid {label} JSON") from exc
    if not isinstance(value, dict):
        raise DraftApprovalError(f"{label.capitalize()} must be a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_private_receipt(
    output_root: Path,
    permitted_root: Path,
    receipt: dict[str, Any],
) -> Path:
    private_root = Path(permitted_root).expanduser().resolve()
    root = Path(output_root).expanduser().resolve()
    try:
        root.relative_to(private_root)
    except ValueError as exc:
        raise DraftApprovalError("Approval output must stay inside Hermes private data") from exc
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = root / f"draft-approval-{timestamp}.json"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
