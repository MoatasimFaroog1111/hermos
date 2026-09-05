"""Deterministic safety validation for proposed accounting drafts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


class DraftValidationError(RuntimeError):
    """Raised when a proposed journal is structurally unsafe."""


_PARTNER_REQUIRED_MOVE_TYPES = {
    "in_invoice",
    "in_refund",
    "out_invoice",
    "out_refund",
    "out_receipt",
    "in_receipt",
}


def validate_draft_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    """Fail closed unless a proposed journal satisfies core invariants."""

    lines = prediction.get("journal_entry") if isinstance(prediction, dict) else None
    errors: list[str] = []
    if not isinstance(lines, list) or len(lines) < 2:
        return _result(False, ["journal_entry must contain at least two lines"])

    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    validated_lines = 0
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            errors.append(f"line {index} must be an object")
            continue
        debit = _money(line.get("debit"), errors, f"line {index} debit")
        credit = _money(line.get("credit"), errors, f"line {index} credit")
        if debit is None or credit is None:
            continue
        if debit < 0 or credit < 0:
            errors.append(f"line {index} contains a negative debit or credit")
        if debit > 0 and credit > 0:
            errors.append(f"line {index} has both debit and credit")
        if debit == 0 and credit == 0:
            errors.append(f"line {index} is a zero-value line")
        if not _account_present(line):
            errors.append(f"line {index} has no account code or account id")
        tax_ids = line.get("tax_ids", [])
        if not isinstance(tax_ids, list):
            errors.append(f"line {index} tax_ids must be a list")
        else:
            for raw in tax_ids:
                if _positive_int(raw) is None:
                    errors.append(f"line {index} contains an invalid tax id")
                    break
        analytic = line.get("analytic_distribution")
        if analytic is not None and not isinstance(analytic, dict):
            errors.append(f"line {index} analytic_distribution must be an object or null")
        total_debit += debit
        total_credit += credit
        validated_lines += 1

    if validated_lines != len(lines):
        errors.append("not all journal lines could be validated")
    if total_debit <= 0 or total_credit <= 0:
        errors.append("journal totals must be greater than zero")
    if total_debit != total_credit:
        errors.append("journal entry is not balanced")

    move_type = str(prediction.get("move_type") or "").strip()
    if not move_type:
        errors.append("move_type is required")
    _validate_date(prediction.get("date"), errors)
    for field in ("journal", "company", "currency"):
        _validate_reference(prediction.get(field), field, errors)
    if move_type in _PARTNER_REQUIRED_MOVE_TYPES:
        _validate_reference(prediction.get("partner"), "partner", errors)
    elif prediction.get("partner") not in (None, False, ""):
        _validate_reference(prediction.get("partner"), "partner", errors)

    return _result(
        not errors,
        errors,
        total_debit=total_debit,
        total_credit=total_credit,
    )


def _account_present(line: dict[str, Any]) -> bool:
    return line.get("account_code") not in (None, False, "") or _positive_int(
        line.get("account_id")
    ) is not None


def _validate_reference(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, dict) or _positive_int(value.get("id")) is None:
        errors.append(f"{label} requires a positive Odoo id")


def _validate_date(value: Any, errors: list[str]) -> None:
    raw = str(value or "").strip()
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        errors.append("date must be a valid YYYY-MM-DD accounting date")
        return
    if parsed.year < 2000 or parsed.year > 2100:
        errors.append("date is outside the accepted accounting date range")


def _positive_int(value: Any) -> int | None:
    try:
        if value in (None, False, ""):
            return None
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _money(value: Any, errors: list[str], label: str) -> Decimal | None:
    try:
        number = Decimal(str(value if value is not None else "0")).quantize(
            Decimal("0.01")
        )
    except (InvalidOperation, TypeError, ValueError):
        errors.append(f"{label} is not a valid decimal amount")
        return None
    return number


def _result(
    valid: bool,
    errors: list[str],
    *,
    total_debit: Decimal = Decimal("0.00"),
    total_credit: Decimal = Decimal("0.00"),
) -> dict[str, Any]:
    return {
        "valid": bool(valid),
        "errors": errors,
        "total_debit": f"{total_debit:.2f}",
        "total_credit": f"{total_credit:.2f}",
        "balanced": total_debit == total_credit and total_debit > 0,
        "auto_post_allowed": False,
        "human_review_required": True,
    }
