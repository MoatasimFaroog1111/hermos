"""Read historical posted journals and their source evidence from Odoo."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from plugins.accounting_brain.odoo_discovery.contracts import OdooReadPort


_MOVE_FIELDS = (
    "id",
    "name",
    "ref",
    "date",
    "invoice_date",
    "state",
    "move_type",
    "journal_id",
    "partner_id",
    "company_id",
    "currency_id",
    "amount_untaxed",
    "amount_tax",
    "amount_total",
    "invoice_origin",
    "reversed_entry_id",
    "auto_post",
)

_LINE_FIELDS = (
    "id",
    "move_id",
    "account_id",
    "partner_id",
    "name",
    "debit",
    "credit",
    "balance",
    "amount_currency",
    "currency_id",
    "tax_ids",
    "tax_line_id",
    "analytic_distribution",
    "display_type",
    "product_id",
    "quantity",
    "price_unit",
)

_ATTACHMENT_FIELDS = (
    "id",
    "name",
    "mimetype",
    "file_size",
    "checksum",
    "res_model",
    "res_id",
    "type",
    "url",
)

_ACCOUNT_FIELDS = (
    "id",
    "code",
    "name",
    "account_type",
    "reconcile",
)

_TAX_FIELDS = (
    "id",
    "name",
    "amount",
    "amount_type",
    "type_tax_use",
)


@dataclass(frozen=True)
class JournalSelection:
    max_moves: int = 1000
    date_from: str | None = None
    date_to: str | None = None
    company_id: int | None = None

    def domain(self) -> list[Any]:
        domain: list[Any] = [("state", "=", "posted")]
        if self.date_from:
            domain.append(("date", ">=", self.date_from))
        if self.date_to:
            domain.append(("date", "<=", self.date_to))
        if self.company_id:
            domain.append(("company_id", "=", int(self.company_id)))
        return domain


@dataclass
class HistoricalJournalBatch:
    moves: list[dict[str, Any]]
    lines_by_move: dict[int, list[dict[str, Any]]]
    attachments_by_move: dict[int, list[dict[str, Any]]]
    accounts_by_id: dict[int, dict[str, Any]]
    taxes_by_id: dict[int, dict[str, Any]]
    total_matching_posted_moves: int


def load_historical_journal_batch(
    reader: OdooReadPort,
    selection: JournalSelection,
) -> HistoricalJournalBatch:
    """Load a bounded historical sample without assuming optional Odoo fields."""
    move_fields = _existing_fields(reader, "account.move", _MOVE_FIELDS)
    line_fields = _existing_fields(reader, "account.move.line", _LINE_FIELDS)
    attachment_fields = _existing_fields(reader, "ir.attachment", _ATTACHMENT_FIELDS)
    account_fields = _existing_fields(reader, "account.account", _ACCOUNT_FIELDS)
    tax_fields = _existing_fields(reader, "account.tax", _TAX_FIELDS)

    domain = selection.domain()
    total_matching = reader.search_count("account.move", domain)
    max_moves = max(1, min(int(selection.max_moves), 100_000))
    moves = reader.search_read(
        "account.move",
        domain,
        fields=move_fields,
        limit=max_moves,
        order="date desc, id desc",
    )
    move_ids = [int(move["id"]) for move in moves if move.get("id")]
    if not move_ids:
        return HistoricalJournalBatch(
            moves=[],
            lines_by_move={},
            attachments_by_move={},
            accounts_by_id={},
            taxes_by_id={},
            total_matching_posted_moves=total_matching,
        )

    lines = _paged_search_read(
        reader,
        "account.move.line",
        [("move_id", "in", move_ids)],
        fields=line_fields,
        order="move_id asc, id asc",
    )
    attachments = _paged_search_read(
        reader,
        "ir.attachment",
        [("res_model", "=", "account.move"), ("res_id", "in", move_ids)],
        fields=attachment_fields,
        order="res_id asc, id asc",
    )

    lines_by_move: dict[int, list[dict[str, Any]]] = defaultdict(list)
    account_ids: set[int] = set()
    tax_ids: set[int] = set()
    for line in lines:
        move_id = _many2one_id(line.get("move_id"))
        if move_id is None:
            continue
        lines_by_move[move_id].append(line)
        account_id = _many2one_id(line.get("account_id"))
        if account_id is not None:
            account_ids.add(account_id)
        for tax_id in _many2many_ids(line.get("tax_ids")):
            tax_ids.add(tax_id)
        tax_line_id = _many2one_id(line.get("tax_line_id"))
        if tax_line_id is not None:
            tax_ids.add(tax_line_id)

    attachments_by_move: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for attachment in attachments:
        try:
            move_id = int(attachment.get("res_id") or 0)
        except (TypeError, ValueError):
            continue
        if move_id:
            attachments_by_move[move_id].append(attachment)

    accounts_by_id = _read_indexed(
        reader,
        "account.account",
        account_ids,
        fields=account_fields,
    )
    taxes_by_id = _read_indexed(
        reader,
        "account.tax",
        tax_ids,
        fields=tax_fields,
    )

    return HistoricalJournalBatch(
        moves=moves,
        lines_by_move=dict(lines_by_move),
        attachments_by_move=dict(attachments_by_move),
        accounts_by_id=accounts_by_id,
        taxes_by_id=taxes_by_id,
        total_matching_posted_moves=total_matching,
    )


def _existing_fields(
    reader: OdooReadPort,
    model: str,
    candidates: Sequence[str],
) -> list[str]:
    metadata = reader.fields_get(model, attributes=("type",))
    return [name for name in candidates if name in metadata]


def _paged_search_read(
    reader: OdooReadPort,
    model: str,
    domain: list[Any],
    *,
    fields: Sequence[str],
    order: str | None = None,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = reader.search_read(
            model,
            domain,
            fields=fields,
            limit=page_size,
            offset=offset,
            order=order,
        )
        if not page:
            break
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += len(page)
    return rows


def _read_indexed(
    reader: OdooReadPort,
    model: str,
    ids: Iterable[int],
    *,
    fields: Sequence[str],
    batch_size: int = 500,
) -> dict[int, dict[str, Any]]:
    ordered = sorted({int(item) for item in ids if int(item) > 0})
    result: dict[int, dict[str, Any]] = {}
    for start in range(0, len(ordered), batch_size):
        for row in reader.read(model, ordered[start : start + batch_size], fields=fields):
            if row.get("id"):
                result[int(row["id"])] = row
    return result


def _many2one_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(value[0])
        except (TypeError, ValueError):
            return None
    if isinstance(value, int):
        return value
    return None


def _many2many_ids(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    normalized: list[int] = []
    for item in value:
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            continue
    return tuple(normalized)
