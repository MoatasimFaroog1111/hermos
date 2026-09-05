"""Create an explicitly approved Accounting Brain proposal as an Odoo draft.

The use case is intentionally separate from model inference. It requires a
previously persisted proposal that passed deterministic validation, resolves and
verifies every accounting reference through the read-only Odoo port, performs
one create-only mutation, then reads the resulting move back to prove it remains
a draft. Posting is not implemented anywhere in this workflow.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from plugins.accounting_brain.odoo_discovery.company_scope import (
    resolve_company_scope,
)
from plugins.accounting_brain.odoo_discovery.contracts import OdooReadPort
from plugins.accounting_brain.production_drafts.odoo_write import OdooDraftWritePort
from plugins.accounting_brain.production_drafts.validation import (
    validate_draft_prediction,
)


class ApprovedDraftError(RuntimeError):
    """Raised when a reviewed proposal cannot be safely created in Odoo."""


def create_reviewed_odoo_draft(
    proposal_path: Path,
    *,
    permitted_root: Path,
    reader: OdooReadPort,
    writer: OdooDraftWritePort,
    requested_company_id: int | None = None,
) -> dict[str, Any]:
    """Create one verified ``account.move`` draft from an approved proposal."""

    proposal = _load_private_proposal(proposal_path, permitted_root)
    if proposal.get("stage") != "READY_FOR_HUMAN_REVIEW":
        raise ApprovedDraftError("Proposal is not ready for human-approved creation")
    if proposal.get("production_mode") != "draft_only":
        raise ApprovedDraftError("Proposal is not marked draft_only")
    prediction = proposal.get("prediction")
    if not isinstance(prediction, dict):
        raise ApprovedDraftError("Proposal contains no structured prediction")

    validation = validate_draft_prediction(prediction)
    if validation.get("valid") is not True:
        raise ApprovedDraftError("Proposal no longer passes deterministic validation")

    company = resolve_company_scope(reader, requested_company_id)
    values = _resolve_create_values(reader, prediction, company.id)
    move_id = writer.create_draft_move(values)
    verification = _verify_created_draft(reader, move_id, company.id)

    return {
        "ok": True,
        "stage": "ODOO_DRAFT_CREATED_VERIFIED",
        "move_id": move_id,
        "selected_company": company.to_dict(),
        "verification": verification,
        "source_proposal": Path(proposal_path).name,
        "safety": {
            "created_state": "draft",
            "posted": False,
            "auto_post": False,
            "write_methods_exposed": ["account.move.create"],
            "human_approval_required_before_this_action": True,
        },
    }


def _resolve_create_values(
    reader: OdooReadPort,
    prediction: dict[str, Any],
    company_id: int,
) -> dict[str, Any]:
    journal_id = _required_reference_id(prediction.get("journal"), "journal")
    currency_id = _required_reference_id(prediction.get("currency"), "currency")
    partner_id = _optional_reference_id(prediction.get("partner"), "partner")

    _verify_company_record(
        reader,
        "account.journal",
        journal_id,
        company_id,
        label="journal",
    )
    _verify_existing(reader, "res.currency", currency_id, label="currency")
    if partner_id is not None:
        _verify_existing(reader, "res.partner", partner_id, label="partner")

    move_type = str(prediction.get("move_type") or "").strip()
    if not move_type:
        raise ApprovedDraftError("move_type is required")

    line_commands: list[tuple[int, int, dict[str, Any]]] = []
    for index, line in enumerate(prediction.get("journal_entry") or [], start=1):
        if not isinstance(line, dict):
            raise ApprovedDraftError(f"Journal line {index} is invalid")
        account_id = _resolve_account(reader, line, company_id)
        tax_ids = _verified_tax_ids(reader, line.get("tax_ids"), company_id)
        values: dict[str, Any] = {
            "account_id": account_id,
            "name": str(line.get("label") or line.get("account_name") or "/"),
            "debit": float(_decimal(line.get("debit"), f"line {index} debit")),
            "credit": float(_decimal(line.get("credit"), f"line {index} credit")),
        }
        line_partner_id = _optional_int(line.get("partner_id")) or partner_id
        if line_partner_id is not None:
            _verify_existing(reader, "res.partner", line_partner_id, label="line partner")
            values["partner_id"] = line_partner_id
        if tax_ids:
            values["tax_ids"] = [(6, 0, tax_ids)]
        analytic = line.get("analytic_distribution")
        if isinstance(analytic, dict) and analytic:
            values["analytic_distribution"] = dict(analytic)
        line_commands.append((0, 0, values))

    payload: dict[str, Any] = {
        "move_type": move_type,
        "journal_id": journal_id,
        "company_id": company_id,
        "currency_id": currency_id,
        "line_ids": line_commands,
    }
    if partner_id is not None:
        payload["partner_id"] = partner_id
    reference = prediction.get("reference")
    if reference not in (None, False, ""):
        payload["ref"] = str(reference)[:200]
    date_value = prediction.get("date")
    if date_value not in (None, False, ""):
        payload["date"] = str(date_value)[:10]
    return payload


def _resolve_account(
    reader: OdooReadPort,
    line: dict[str, Any],
    company_id: int,
) -> int:
    raw_id = _optional_int(line.get("account_id"))
    code = str(line.get("account_code") or "").strip()
    fields = reader.fields_get("account.account", attributes=("type",))
    company_field = "company_id" if "company_id" in fields else (
        "company_ids" if "company_ids" in fields else None
    )

    if raw_id is not None:
        rows = reader.read(
            "account.account",
            [raw_id],
            fields=tuple(
                field
                for field in ("id", "code", company_field)
                if field is not None
            ),
        )
        if len(rows) != 1:
            raise ApprovedDraftError(f"Account id {raw_id} does not exist")
        row = rows[0]
        if code and str(row.get("code") or "").strip() != code:
            raise ApprovedDraftError(
                f"Account id {raw_id} does not match predicted code {code}"
            )
        _verify_company_value(row.get(company_field), company_id, "account")
        return raw_id

    if not code:
        raise ApprovedDraftError("Journal line has neither account id nor code")
    domain: list[Any] = [("code", "=", code)]
    if company_field == "company_id":
        domain.append(("company_id", "=", company_id))
    elif company_field == "company_ids":
        domain.append(("company_ids", "in", [company_id]))
    rows = reader.search_read(
        "account.account",
        domain,
        fields=("id", "code"),
        limit=2,
    )
    if len(rows) != 1:
        raise ApprovedDraftError(
            f"Account code {code} must resolve to exactly one company account"
        )
    return int(rows[0]["id"])


def _verified_tax_ids(
    reader: OdooReadPort,
    raw_tax_ids: Any,
    company_id: int,
) -> list[int]:
    if raw_tax_ids in (None, False, []):
        return []
    if not isinstance(raw_tax_ids, list):
        raise ApprovedDraftError("tax_ids must be a list")
    result: list[int] = []
    for raw in raw_tax_ids:
        tax_id = _optional_int(raw)
        if tax_id is None:
            raise ApprovedDraftError("Invalid tax id")
        _verify_company_record(
            reader,
            "account.tax",
            tax_id,
            company_id,
            label="tax",
        )
        result.append(tax_id)
    return sorted(set(result))


def _verify_company_record(
    reader: OdooReadPort,
    model: str,
    record_id: int,
    company_id: int,
    *,
    label: str,
) -> None:
    fields = reader.fields_get(model, attributes=("type",))
    company_field = "company_id" if "company_id" in fields else (
        "company_ids" if "company_ids" in fields else None
    )
    requested_fields = tuple(
        field for field in ("id", company_field) if field is not None
    )
    rows = reader.read(model, [record_id], fields=requested_fields)
    if len(rows) != 1:
        raise ApprovedDraftError(f"Predicted {label} id {record_id} does not exist")
    if company_field is not None:
        _verify_company_value(rows[0].get(company_field), company_id, label)


def _verify_company_value(value: Any, company_id: int, label: str) -> None:
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[1], str):
            ids = {_optional_int(value[0])}
        else:
            ids = {_optional_int(item) for item in value}
        ids.discard(None)
        if company_id not in ids:
            raise ApprovedDraftError(f"Predicted {label} belongs to another company")
    elif value not in (None, False, ""):
        if _optional_int(value) != company_id:
            raise ApprovedDraftError(f"Predicted {label} belongs to another company")


def _verify_existing(
    reader: OdooReadPort,
    model: str,
    record_id: int,
    *,
    label: str,
) -> None:
    rows = reader.read(model, [record_id], fields=("id",))
    if len(rows) != 1:
        raise ApprovedDraftError(f"Predicted {label} id {record_id} does not exist")


def _verify_created_draft(
    reader: OdooReadPort,
    move_id: int,
    company_id: int,
) -> dict[str, Any]:
    rows = reader.read(
        "account.move",
        [move_id],
        fields=("id", "name", "state", "move_type", "journal_id", "company_id"),
    )
    if len(rows) != 1:
        raise ApprovedDraftError(
            "Odoo draft was created but could not be read back for verification"
        )
    row = rows[0]
    if row.get("state") != "draft":
        raise ApprovedDraftError(
            "Critical safety failure: created Odoo move is not in draft state"
        )
    _verify_company_value(row.get("company_id"), company_id, "created move")
    return {
        "id": int(row["id"]),
        "name": row.get("name"),
        "state": row.get("state"),
        "move_type": row.get("move_type"),
        "journal": row.get("journal_id"),
        "company": row.get("company_id"),
    }


def _load_private_proposal(path: Path, permitted_root: Path) -> dict[str, Any]:
    root = permitted_root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ApprovedDraftError("Proposal path is outside the private Hermes root") from exc
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApprovedDraftError("Proposal file cannot be read safely") from exc
    if not isinstance(value, dict):
        raise ApprovedDraftError("Proposal file must contain a JSON object")
    return value


def _required_reference_id(value: Any, label: str) -> int:
    identifier = _optional_reference_id(value, label)
    if identifier is None:
        raise ApprovedDraftError(f"Predicted {label} requires a verified Odoo id")
    return identifier


def _optional_reference_id(value: Any, label: str) -> int | None:
    if value in (None, False, ""):
        return None
    if not isinstance(value, dict):
        raise ApprovedDraftError(f"Predicted {label} reference is invalid")
    identifier = _optional_int(value.get("id"))
    if identifier is None:
        raise ApprovedDraftError(f"Predicted {label} has no Odoo id")
    return identifier


def _optional_int(value: Any) -> int | None:
    try:
        if value in (None, False, ""):
            return None
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value if value is not None else "0")).quantize(
            Decimal("0.01")
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ApprovedDraftError(f"{label} is invalid") from exc
    return result
