"""Data-quality audit for historical Odoo journal training candidates."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from plugins.accounting_brain.journal_training.historical_journals import (
    HistoricalJournalBatch,
)
from plugins.accounting_brain.journal_training.quality import (
    accounting_lines,
    grade_training_example,
)


def build_training_audit(batch: HistoricalJournalBatch) -> dict[str, Any]:
    grade_counts: Counter[str] = Counter()
    move_type_counts: Counter[str] = Counter()
    journal_counts: Counter[str] = Counter()
    attachment_mimetypes: Counter[str] = Counter()
    account_usage: Counter[str] = Counter()

    moves_with_attachments = 0
    moves_with_partner = 0
    moves_with_tax = 0
    moves_with_analytic = 0
    accounting_line_count = 0

    for move in batch.moves:
        move_id = int(move.get("id") or 0)
        lines = batch.lines_by_move.get(move_id, [])
        attachments = batch.attachments_by_move.get(move_id, [])
        decision = grade_training_example(move, lines, attachments)
        grade_counts[decision.grade.value] += 1

        move_type_counts[str(move.get("move_type") or "unknown")] += 1
        journal_counts[_many2one_name(move.get("journal_id")) or "unknown"] += 1

        if attachments:
            moves_with_attachments += 1
            for attachment in attachments:
                attachment_mimetypes[
                    str(attachment.get("mimetype") or "unknown")
                ] += 1

        if _many2one_id(move.get("partner_id")):
            moves_with_partner += 1

        ledger_lines = accounting_lines(lines)
        accounting_line_count += len(ledger_lines)
        has_tax = False
        has_analytic = False
        for line in ledger_lines:
            account_id = _many2one_id(line.get("account_id"))
            account = batch.accounts_by_id.get(account_id or -1, {})
            account_label = " ".join(
                part
                for part in (
                    str(account.get("code") or "").strip(),
                    str(account.get("name") or _many2one_name(line.get("account_id")) or "").strip(),
                )
                if part
            ) or "unknown"
            account_usage[account_label] += 1

            tax_ids = line.get("tax_ids")
            if isinstance(tax_ids, (list, tuple)) and tax_ids:
                has_tax = True
            if _many2one_id(line.get("tax_line_id")):
                has_tax = True
            analytic = line.get("analytic_distribution")
            if isinstance(analytic, dict) and analytic:
                has_analytic = True

        if has_tax:
            moves_with_tax += 1
        if has_analytic:
            moves_with_analytic += 1

    sampled = len(batch.moves)
    denominator = sampled or 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection": {
            "sampled_posted_moves": sampled,
            "total_matching_posted_moves": batch.total_matching_posted_moves,
        },
        "quality": {
            "grades": dict(sorted(grade_counts.items())),
            "gold_rate": round(grade_counts.get("gold", 0) / denominator, 4),
            "attachment_coverage": round(moves_with_attachments / denominator, 4),
            "partner_coverage": round(moves_with_partner / denominator, 4),
            "tax_evidence_coverage": round(moves_with_tax / denominator, 4),
            "analytic_distribution_coverage": round(moves_with_analytic / denominator, 4),
            "accounting_line_count": accounting_line_count,
            "average_accounting_lines_per_move": round(accounting_line_count / denominator, 2),
        },
        "taxonomy": {
            "move_types": dict(move_type_counts.most_common()),
            "journals": dict(journal_counts.most_common()),
            "attachment_mimetypes": dict(attachment_mimetypes.most_common()),
            "top_accounts_by_line_usage": dict(account_usage.most_common(50)),
            "unique_accounts_in_sample": len(account_usage),
            "known_tax_records_in_sample": len(batch.taxes_by_id),
        },
    }


def _many2one_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(value[0])
        except (TypeError, ValueError):
            return None
    if isinstance(value, int):
        return value
    return None


def _many2one_name(value: Any) -> str | None:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        text = str(value[1] or "").strip()
        return text or None
    return None
