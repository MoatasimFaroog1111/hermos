"""Export attachment-to-journal training pairs from validated Odoo history."""

from __future__ import annotations

import base64
from collections import Counter
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from plugins.accounting_brain.journal_training.contracts import TrainingDatasetSink
from plugins.accounting_brain.journal_training.historical_journals import HistoricalJournalBatch
from plugins.accounting_brain.journal_training.models import (
    AttachmentEvidence,
    JournalLineTarget,
    JournalTrainingPair,
    TrainingGrade,
)
from plugins.accounting_brain.journal_training.quality import (
    accounting_lines,
    grade_training_example,
)
from plugins.accounting_brain.odoo_discovery.contracts import OdooReadError, OdooReadPort


TRAINING_CONTRACT_VERSION = "1.0"


def export_training_pairs(
    reader: OdooReadPort,
    batch: HistoricalJournalBatch,
    sink: TrainingDatasetSink,
    *,
    include_silver: bool = False,
    download_attachments: bool = False,
    max_attachment_bytes: int = 25 * 1024 * 1024,
) -> dict[str, Any]:
    """Export deterministic, traceable journal targets and source evidence.

    Attachment field discovery is done once per export, not once per file, so
    large Odoo datasets do not pay an avoidable metadata round-trip for every
    attachment.
    """
    grade_counts: Counter[str] = Counter()
    exported = 0
    skipped = 0
    attachment_status: Counter[str] = Counter()
    content_field = (
        _resolve_attachment_content_field(reader)
        if download_attachments
        else None
    )

    for move in batch.moves:
        move_id = int(move.get("id") or 0)
        lines = batch.lines_by_move.get(move_id, [])
        attachments = batch.attachments_by_move.get(move_id, [])
        decision = grade_training_example(move, lines, attachments)
        grade_counts[decision.grade.value] += 1

        if decision.grade is TrainingGrade.REJECTED:
            skipped += 1
            continue
        if decision.grade is TrainingGrade.SILVER and not include_silver:
            skipped += 1
            continue

        attachment_evidence: list[AttachmentEvidence] = []
        for attachment in attachments:
            evidence = _attachment_evidence(
                reader,
                sink,
                attachment,
                download=download_attachments,
                content_field=content_field,
                max_bytes=max_attachment_bytes,
            )
            attachment_status[evidence.content_status] += 1
            attachment_evidence.append(evidence)

        ledger_lines = accounting_lines(lines)
        target_lines = [
            _journal_line_target(line, batch.accounts_by_id)
            for line in ledger_lines
        ]
        tax_ids = sorted(
            {
                tax_id
                for line in ledger_lines
                for tax_id in _line_tax_ids(line)
            }
        )
        taxes = [
            {
                "id": tax_id,
                "name": batch.taxes_by_id.get(tax_id, {}).get("name"),
                "amount": batch.taxes_by_id.get(tax_id, {}).get("amount"),
                "amount_type": batch.taxes_by_id.get(tax_id, {}).get("amount_type"),
                "type_tax_use": batch.taxes_by_id.get(tax_id, {}).get("type_tax_use"),
            }
            for tax_id in tax_ids
        ]

        pair = JournalTrainingPair(
            source_move_id=move_id,
            source_move_name=_text_or_none(move.get("name")),
            grade=decision.grade,
            quality_reasons=decision.reasons,
            input={
                "contract_version": TRAINING_CONTRACT_VERSION,
                "source_system": "odoo",
                "document": {
                    "move_type": _text_or_none(move.get("move_type")),
                    "reference": _text_or_none(move.get("ref")),
                    "date": _text_or_none(move.get("date")),
                    "invoice_date": _text_or_none(move.get("invoice_date")),
                    "invoice_origin": _text_or_none(move.get("invoice_origin")),
                    "partner": _many2one_ref(move.get("partner_id")),
                    "journal": _many2one_ref(move.get("journal_id")),
                    "company": _many2one_ref(move.get("company_id")),
                    "currency": _many2one_ref(move.get("currency_id")),
                    "amount_untaxed": _money_string(move.get("amount_untaxed")),
                    "amount_tax": _money_string(move.get("amount_tax")),
                    "amount_total": _money_string(move.get("amount_total")),
                },
                "attachments": [asdict(item) for item in attachment_evidence],
            },
            target={
                "contract_version": TRAINING_CONTRACT_VERSION,
                "move_type": _text_or_none(move.get("move_type")),
                "date": _text_or_none(move.get("date")),
                "reference": _text_or_none(move.get("ref")),
                "partner": _many2one_ref(move.get("partner_id")),
                "journal": _many2one_ref(move.get("journal_id")),
                "company": _many2one_ref(move.get("company_id")),
                "currency": _many2one_ref(move.get("currency_id")),
                "taxes": taxes,
                "journal_entry": [asdict(item) for item in target_lines],
                "invariants": {
                    "total_debit": _money_string(sum(Decimal(item.debit) for item in target_lines)),
                    "total_credit": _money_string(sum(Decimal(item.credit) for item in target_lines)),
                    "balanced": True,
                },
            },
        )
        sink.write_pair(pair)
        exported += 1

    report = {
        "contract_version": TRAINING_CONTRACT_VERSION,
        "source": "odoo_read_only",
        "sampled_moves": len(batch.moves),
        "total_matching_posted_moves": batch.total_matching_posted_moves,
        "grade_counts": dict(sorted(grade_counts.items())),
        "exported_pairs": exported,
        "skipped_pairs": skipped,
        "include_silver": bool(include_silver),
        "download_attachments": bool(download_attachments),
        "attachment_content_status": dict(sorted(attachment_status.items())),
        "dataset_root": str(sink.root),
    }
    sink.write_report("export-report.json", report)
    return report


def _resolve_attachment_content_field(reader: OdooReadPort) -> str | None:
    fields = reader.fields_get("ir.attachment", attributes=("type",))
    return "datas" if "datas" in fields else None


def _attachment_evidence(
    reader: OdooReadPort,
    sink: TrainingDatasetSink,
    attachment: dict[str, Any],
    *,
    download: bool,
    content_field: str | None,
    max_bytes: int,
) -> AttachmentEvidence:
    attachment_id = int(attachment.get("id") or 0)
    filename = str(attachment.get("name") or f"attachment-{attachment_id}")
    mimetype = _text_or_none(attachment.get("mimetype"))
    file_size = _int_or_none(attachment.get("file_size"))
    checksum = _text_or_none(attachment.get("checksum"))

    if not download:
        return AttachmentEvidence(
            attachment_id=attachment_id,
            filename=filename,
            mimetype=mimetype,
            file_size=file_size,
            checksum=checksum,
            content_status="metadata_only",
        )

    if content_field is None:
        return AttachmentEvidence(
            attachment_id=attachment_id,
            filename=filename,
            mimetype=mimetype,
            file_size=file_size,
            checksum=checksum,
            content_status="content_field_unavailable",
        )

    if file_size is not None and file_size > max_bytes:
        return AttachmentEvidence(
            attachment_id=attachment_id,
            filename=filename,
            mimetype=mimetype,
            file_size=file_size,
            checksum=checksum,
            content_status="skipped_too_large",
        )

    try:
        rows = reader.read("ir.attachment", [attachment_id], fields=(content_field,))
    except OdooReadError:
        return AttachmentEvidence(
            attachment_id=attachment_id,
            filename=filename,
            mimetype=mimetype,
            file_size=file_size,
            checksum=checksum,
            content_status="read_denied_or_unavailable",
        )

    raw_value = rows[0].get(content_field) if rows else None
    if not raw_value:
        return AttachmentEvidence(
            attachment_id=attachment_id,
            filename=filename,
            mimetype=mimetype,
            file_size=file_size,
            checksum=checksum,
            content_status="empty_content",
        )

    try:
        content = base64.b64decode(raw_value, validate=False)
    except (ValueError, TypeError):
        return AttachmentEvidence(
            attachment_id=attachment_id,
            filename=filename,
            mimetype=mimetype,
            file_size=file_size,
            checksum=checksum,
            content_status="invalid_base64",
        )

    if len(content) > max_bytes:
        return AttachmentEvidence(
            attachment_id=attachment_id,
            filename=filename,
            mimetype=mimetype,
            file_size=len(content),
            checksum=checksum,
            content_status="skipped_too_large",
        )

    relative_path, sha256 = sink.write_attachment(
        attachment_id=attachment_id,
        filename=filename,
        content=content,
    )
    return AttachmentEvidence(
        attachment_id=attachment_id,
        filename=filename,
        mimetype=mimetype,
        file_size=len(content),
        checksum=checksum,
        local_path=relative_path,
        content_sha256=sha256,
        content_status="downloaded",
    )


def _journal_line_target(
    line: dict[str, Any],
    accounts_by_id: dict[int, dict[str, Any]],
) -> JournalLineTarget:
    account_ref = _many2one_ref(line.get("account_id"))
    account_id = account_ref.get("id") if account_ref else None
    account = accounts_by_id.get(int(account_id or -1), {})
    partner_ref = _many2one_ref(line.get("partner_id"))
    currency_ref = _many2one_ref(line.get("currency_id"))
    analytic = line.get("analytic_distribution")
    return JournalLineTarget(
        account_id=int(account_id) if account_id else None,
        account_code=_text_or_none(account.get("code")),
        account_name=_text_or_none(account.get("name")) or (
            account_ref.get("name") if account_ref else None
        ),
        partner_id=int(partner_ref["id"]) if partner_ref and partner_ref.get("id") else None,
        partner_name=partner_ref.get("name") if partner_ref else None,
        label=_text_or_none(line.get("name")),
        debit=_money_string(line.get("debit")) or "0.00",
        credit=_money_string(line.get("credit")) or "0.00",
        balance=_money_string(line.get("balance")) or "0.00",
        amount_currency=_money_string(line.get("amount_currency")),
        currency_id=int(currency_ref["id"]) if currency_ref and currency_ref.get("id") else None,
        currency_name=currency_ref.get("name") if currency_ref else None,
        tax_ids=tuple(_many2many_ids(line.get("tax_ids"))),
        analytic_distribution=dict(analytic) if isinstance(analytic, dict) and analytic else None,
    )


def _line_tax_ids(line: dict[str, Any]) -> tuple[int, ...]:
    ids = set(_many2many_ids(line.get("tax_ids")))
    tax_line = _many2one_ref(line.get("tax_line_id"))
    if tax_line and tax_line.get("id"):
        ids.add(int(tax_line["id"]))
    return tuple(sorted(ids))


def _many2one_ref(value: Any) -> dict[str, Any] | None:
    if isinstance(value, (list, tuple)) and value:
        try:
            identifier = int(value[0])
        except (TypeError, ValueError):
            return None
        name = str(value[1]).strip() if len(value) > 1 and value[1] not in (None, False) else None
        return {"id": identifier, "name": name}
    if isinstance(value, int):
        return {"id": value, "name": None}
    return None


def _many2many_ids(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _money_string(value: Any) -> str | None:
    if value in (None, False, ""):
        return None
    return f"{Decimal(str(value)):.2f}"


def _text_or_none(value: Any) -> str | None:
    if value in (None, False, ""):
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, False, "") else None
    except (TypeError, ValueError):
        return None
