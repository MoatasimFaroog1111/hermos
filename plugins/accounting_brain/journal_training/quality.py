"""Deterministic quality gate for Odoo journal-entry training examples."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from plugins.accounting_brain.journal_training.models import (
    QualityDecision,
    TrainingGrade,
)


_BALANCE_TOLERANCE = Decimal("0.01")
_PARTNER_REQUIRED_MOVE_TYPES = frozenset(
    {
        "out_invoice",
        "out_refund",
        "in_invoice",
        "in_refund",
        "out_receipt",
        "in_receipt",
    }
)


def accounting_lines(lines: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return posted accounting lines, excluding display-only rows.

    Odoo's ``display_type`` evolves across versions. ``account_id`` is the
    stronger invariant for whether a row participates in the ledger.
    """
    return [dict(line) for line in lines if _many2one_id(line.get("account_id"))]


def grade_training_example(
    move: dict[str, Any],
    lines: Iterable[dict[str, Any]],
    attachments: Iterable[dict[str, Any]],
) -> QualityDecision:
    """Classify historical evidence as gold, silver, or rejected.

    Gold means suitable as a supervised attachment -> journal-entry example.
    Silver is valid accounting history but lacks enough source evidence or has
    a condition that should be reviewed before training. Rejected examples
    violate hard accounting invariants or are not finalized history.
    """
    reasons: list[str] = []
    state = str(move.get("state") or "").strip().lower()
    if state != "posted":
        return QualityDecision(
            TrainingGrade.REJECTED,
            ("move_not_posted",),
        )

    ledger_lines = accounting_lines(lines)
    if not ledger_lines:
        return QualityDecision(
            TrainingGrade.REJECTED,
            ("no_accounting_lines",),
        )

    try:
        total_debit = sum((_money(line.get("debit")) for line in ledger_lines), Decimal("0"))
        total_credit = sum((_money(line.get("credit")) for line in ledger_lines), Decimal("0"))
    except (InvalidOperation, ValueError, TypeError):
        return QualityDecision(
            TrainingGrade.REJECTED,
            ("invalid_monetary_amount",),
        )

    if total_debit <= 0 or total_credit <= 0:
        return QualityDecision(
            TrainingGrade.REJECTED,
            ("zero_sided_entry",),
        )

    if abs(total_debit - total_credit) > _BALANCE_TOLERANCE:
        return QualityDecision(
            TrainingGrade.REJECTED,
            ("journal_not_balanced",),
        )

    if any(not _many2one_id(line.get("account_id")) for line in ledger_lines):
        return QualityDecision(
            TrainingGrade.REJECTED,
            ("missing_account",),
        )

    attachment_rows = [dict(item) for item in attachments]
    if not attachment_rows:
        reasons.append("no_source_attachment")

    move_type = str(move.get("move_type") or "entry").strip()
    if move_type in _PARTNER_REQUIRED_MOVE_TYPES and not _many2one_id(move.get("partner_id")):
        reasons.append("partner_missing_for_document_move")

    if _many2one_id(move.get("reversed_entry_id")):
        reasons.append("reversal_entry")

    if move.get("auto_post") not in (None, False, "no"):
        reasons.append("auto_posted_or_scheduled")

    if reasons:
        return QualityDecision(TrainingGrade.SILVER, tuple(sorted(set(reasons))))

    return QualityDecision(TrainingGrade.GOLD, ())


def _money(value: Any) -> Decimal:
    if value in (None, False, ""):
        return Decimal("0")
    return Decimal(str(value))


def _many2one_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(value[0])
        except (TypeError, ValueError):
            return None
    if isinstance(value, int):
        return value
    return None
