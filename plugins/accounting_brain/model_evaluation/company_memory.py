"""Leakage-safe deterministic GITC accounting memory from Gold reference history.

The memory layer consumes only ``evaluation-reference.jsonl`` (or the equivalent
validated production Gold references). It never reads holdout ground truth and
never stores source move IDs, checksums, or monetary amounts.

The purpose is to expose company-specific Odoo semantics that a generic LLM
cannot know reliably: exact entity IDs, chart-of-account codes/names,
journal/move-type conventions, debit/credit direction priors, currencies,
taxes, recurring partners, and analytic-distribution patterns.
"""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any


class CompanyMemoryError(RuntimeError):
    """Raised when a safe company memory cannot be derived."""


class CompanyMemory:
    """Compact deterministic memory derived exclusively from validated history."""

    def __init__(
        self,
        *,
        company_name: str = "GITC Reference Derived",
        contract_version: str = "1.0",
    ) -> None:
        self.company_name = company_name
        self.contract_version = contract_version
        self.total_reference_cases = 0
        self.account_catalog: dict[str, dict[str, Any]] = {}
        self.journal_catalog: dict[str, dict[str, Any]] = {}
        self.currency_catalog: dict[str, dict[str, Any]] = {}
        self.tax_catalog: dict[str, dict[str, Any]] = {}
        self.partner_catalog: dict[str, dict[str, Any]] = {}
        self.journal_move_type_pairs: Counter[tuple[str, str]] = Counter()
        self.move_type_journal_pairs: Counter[tuple[str, str]] = Counter()
        self.journals: Counter[str] = Counter()
        self.move_types: Counter[str] = Counter()
        self.currency_counter: Counter[str] = Counter()
        self.tax_counter: Counter[str] = Counter()
        self.account_debit_count: Counter[str] = Counter()
        self.account_credit_count: Counter[str] = Counter()
        self.move_type_debit_count: Counter[str] = Counter()
        self.move_type_credit_count: Counter[str] = Counter()
        self.partner_presence = 0
        self.analytic_presence = 0
        self.line_counts: list[int] = []
        self.analytic_patterns: Counter[str] = Counter()
        self.account_analytic_patterns: dict[str, Counter[str]] = {}

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot with no source or amount evidence."""
        return {
            "company_name": self.company_name,
            "contract_version": self.contract_version,
            "total_reference_cases": self.total_reference_cases,
            "account_catalog": self.account_catalog,
            "journal_catalog": self.journal_catalog,
            "currency_catalog": self.currency_catalog,
            "tax_catalog": self.tax_catalog,
            "partner_catalog": self.partner_catalog,
            "journal_move_type_pairs": {
                _pair_key(a, b): count
                for (a, b), count in self.journal_move_type_pairs.items()
            },
            "move_type_journal_pairs": {
                _pair_key(a, b): count
                for (a, b), count in self.move_type_journal_pairs.items()
            },
            "journals": dict(self.journals),
            "move_types": dict(self.move_types),
            "currency_counter": dict(self.currency_counter),
            "tax_counter": dict(self.tax_counter),
            "account_debit_count": dict(self.account_debit_count),
            "account_credit_count": dict(self.account_credit_count),
            "move_type_debit_count": dict(self.move_type_debit_count),
            "move_type_credit_count": dict(self.move_type_credit_count),
            "partner_presence": self.partner_presence,
            "analytic_presence": self.analytic_presence,
            "line_count_distribution": list(self.line_counts),
            "analytic_patterns": dict(self.analytic_patterns),
            "account_analytic_patterns": {
                code: dict(counter)
                for code, counter in self.account_analytic_patterns.items()
            },
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CompanyMemory":
        memory = CompanyMemory(
            company_name=str(data.get("company_name") or "GITC Reference Derived"),
            contract_version=str(data.get("contract_version") or "1.0"),
        )
        memory.total_reference_cases = int(data.get("total_reference_cases") or 0)
        memory.account_catalog = dict(data.get("account_catalog") or {})
        memory.journal_catalog = dict(data.get("journal_catalog") or {})
        memory.currency_catalog = dict(data.get("currency_catalog") or {})
        memory.tax_catalog = dict(data.get("tax_catalog") or {})
        memory.partner_catalog = dict(data.get("partner_catalog") or {})
        memory.journal_move_type_pairs = _pairs_from_dict(
            data.get("journal_move_type_pairs")
        )
        memory.move_type_journal_pairs = _pairs_from_dict(
            data.get("move_type_journal_pairs")
        )
        memory.journals = Counter(data.get("journals") or {})
        memory.move_types = Counter(data.get("move_types") or {})
        memory.currency_counter = Counter(data.get("currency_counter") or {})
        memory.tax_counter = Counter(data.get("tax_counter") or {})
        memory.account_debit_count = Counter(data.get("account_debit_count") or {})
        memory.account_credit_count = Counter(data.get("account_credit_count") or {})
        memory.move_type_debit_count = Counter(data.get("move_type_debit_count") or {})
        memory.move_type_credit_count = Counter(data.get("move_type_credit_count") or {})
        memory.partner_presence = int(data.get("partner_presence") or 0)
        memory.analytic_presence = int(data.get("analytic_presence") or 0)
        memory.line_counts = [int(value) for value in data.get("line_count_distribution") or []]
        memory.analytic_patterns = Counter(data.get("analytic_patterns") or {})
        memory.account_analytic_patterns = {
            str(code): Counter(values)
            for code, values in (data.get("account_analytic_patterns") or {}).items()
            if isinstance(values, dict)
        }
        return memory


def derive_company_memory(reference_rows: list[dict[str, Any]]) -> CompanyMemory:
    """Derive exact GITC conventions from non-holdout Gold references only."""
    if not reference_rows:
        raise CompanyMemoryError("Reference pool is empty")

    memory = CompanyMemory(contract_version=_contract_version(reference_rows))
    valid_targets = 0

    for row in reference_rows:
        target = row.get("target")
        if not isinstance(target, dict) or not target:
            continue
        valid_targets += 1

        move_type = _text(target.get("move_type"))
        if move_type:
            memory.move_types[move_type] += 1

        journal = target.get("journal")
        journal_key = _catalog_entity(memory.journal_catalog, journal)
        journal_label = _entity_label(journal)
        if journal_label:
            memory.journals[journal_label] += 1
        if journal_key and move_type:
            memory.journal_catalog[journal_key]["move_type_usage"][move_type] = (
                int(memory.journal_catalog[journal_key]["move_type_usage"].get(move_type, 0))
                + 1
            )
            memory.journal_move_type_pairs[(journal_key, move_type)] += 1
            memory.move_type_journal_pairs[(move_type, journal_key)] += 1

        partner = target.get("partner")
        if isinstance(partner, dict) and partner:
            memory.partner_presence += 1
            _catalog_entity(memory.partner_catalog, partner)

        currency = target.get("currency")
        currency_key = _catalog_entity(memory.currency_catalog, currency)
        currency_label = _entity_label(currency)
        if currency_label:
            memory.currency_counter[currency_label] += 1
        if currency_key:
            memory.currency_catalog[currency_key]["count"] = int(
                memory.currency_catalog[currency_key].get("count", 0)
            )

        taxes = target.get("taxes")
        if isinstance(taxes, list):
            for tax in taxes:
                if not isinstance(tax, dict):
                    continue
                _catalog_entity(memory.tax_catalog, tax)
                label = _entity_label(tax)
                if label:
                    memory.tax_counter[label] += 1

        lines = target.get("journal_entry")
        if not isinstance(lines, list):
            continue
        memory.line_counts.append(len(lines))
        case_has_analytic = False

        for line in lines:
            if not isinstance(line, dict):
                continue
            code = _text(line.get("account_code"))
            if not code:
                continue
            entry = memory.account_catalog.setdefault(
                code,
                {
                    "code": code,
                    "id_counts": {},
                    "name_counts": {},
                    "debit_count": 0,
                    "credit_count": 0,
                    "move_type_usage": {},
                },
            )
            _count_value(entry["id_counts"], _int_or_none(line.get("account_id")))
            _count_value(entry["name_counts"], _text(line.get("account_name")))

            debit = _decimal(line.get("debit"))
            credit = _decimal(line.get("credit"))
            if debit > 0:
                entry["debit_count"] += 1
                memory.account_debit_count[code] += 1
                if move_type:
                    memory.move_type_debit_count[move_type] += 1
            if credit > 0:
                entry["credit_count"] += 1
                memory.account_credit_count[code] += 1
                if move_type:
                    memory.move_type_credit_count[move_type] += 1
            if move_type:
                entry["move_type_usage"][move_type] = int(
                    entry["move_type_usage"].get(move_type, 0)
                ) + 1

            analytic = line.get("analytic_distribution")
            if isinstance(analytic, dict) and analytic:
                case_has_analytic = True
                pattern = json.dumps(
                    analytic,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                memory.analytic_patterns[pattern] += 1
                memory.account_analytic_patterns.setdefault(code, Counter())[pattern] += 1

        if case_has_analytic:
            memory.analytic_presence += 1

    if valid_targets == 0:
        raise CompanyMemoryError("Reference pool contains no usable Gold targets")
    memory.total_reference_cases = valid_targets
    return memory


def build_memory_hints(
    memory: CompanyMemory,
    *,
    max_accounts: int = 40,
    max_partners: int = 15,
) -> str:
    """Render company rules for LLM context without historical monetary amounts."""
    lines: list[str] = [
        "GITC ACCOUNTING MEMORY — derived only from earlier validated Gold history.",
        "When the current document matches a listed entity, preserve the exact Odoo ID; exact IDs matter.",
        "Never copy a historical monetary amount. Monetary amounts must come from the current document.",
    ]

    journals = sorted(
        memory.journal_catalog.values(),
        key=lambda item: (-int(item.get("count", 0)), _entity_sort(item)),
    )
    if journals:
        rendered = []
        for item in journals[:20]:
            usage = item.get("move_type_usage") or {}
            rendered.append(
                _entity_text(item)
                + (f" move_types={_counter_text(usage, limit=4)}" if usage else "")
            )
        lines.append("JOURNALS: " + "; ".join(rendered))

    currencies = sorted(
        memory.currency_catalog.values(),
        key=lambda item: (-int(item.get("count", 0)), _entity_sort(item)),
    )
    if currencies:
        lines.append(
            "CURRENCIES: " + "; ".join(_entity_text(item) for item in currencies[:10])
        )

    taxes = sorted(
        memory.tax_catalog.values(),
        key=lambda item: (-int(item.get("count", 0)), _entity_sort(item)),
    )
    if taxes:
        lines.append("TAXES: " + "; ".join(_entity_text(item) for item in taxes[:20]))

    accounts = sorted(
        memory.account_catalog.values(),
        key=lambda item: (
            -(int(item.get("debit_count", 0)) + int(item.get("credit_count", 0))),
            str(item.get("code") or ""),
        ),
    )
    if accounts:
        rendered_accounts: list[str] = []
        for item in accounts[: max(1, max_accounts)]:
            code = str(item.get("code") or "")
            account_id = _most_common_key(item.get("id_counts") or {})
            name = _most_common_key(item.get("name_counts") or {})
            debit = int(item.get("debit_count", 0))
            credit = int(item.get("credit_count", 0))
            total = debit + credit
            direction = "mixed"
            if total:
                debit_rate = debit / total
                if debit_rate >= 0.80:
                    direction = f"debit-prior={debit_rate:.2f}"
                elif debit_rate <= 0.20:
                    direction = f"credit-prior={1.0 - debit_rate:.2f}"
            text = f"code={code}"
            if account_id:
                text += f" id={account_id}"
            if name:
                text += f" name={name}"
            text += f" {direction}"
            usage = item.get("move_type_usage") or {}
            if usage:
                text += f" move_types={_counter_text(usage, limit=4)}"
            analytic_counter = memory.account_analytic_patterns.get(code)
            if analytic_counter:
                text += f" analytics={analytic_counter.most_common(2)}"
            rendered_accounts.append(text)
        lines.append("ACCOUNTS: " + "; ".join(rendered_accounts))

    partners = sorted(
        memory.partner_catalog.values(),
        key=lambda item: (-int(item.get("count", 0)), _entity_sort(item)),
    )
    if partners:
        lines.append(
            "RECURRING PARTNERS: "
            + "; ".join(_entity_text(item) for item in partners[: max(1, max_partners)])
        )

    if memory.analytic_patterns:
        lines.append(
            "COMMON ANALYTIC DISTRIBUTIONS: "
            + "; ".join(
                f"{pattern} x{count}"
                for pattern, count in memory.analytic_patterns.most_common(8)
            )
        )

    if memory.line_counts:
        ordered = sorted(memory.line_counts)
        median = ordered[len(ordered) // 2]
        lines.append(
            f"ENTRY LINE COUNT: min={ordered[0]} median={median} max={ordered[-1]}."
        )

    total = max(1, memory.total_reference_cases)
    lines.append(
        "PRESENCE RATES: "
        f"partner={memory.partner_presence / total:.2f}, "
        f"analytic={memory.analytic_presence / total:.2f}."
    )
    return "\n".join(lines)


def _catalog_entity(catalog: dict[str, dict[str, Any]], value: Any) -> str | None:
    if not isinstance(value, dict) or not value:
        return None
    identifier = _int_or_none(value.get("id"))
    code = _text(value.get("code"))
    name = _text(value.get("name"))
    key = (
        f"id:{identifier}"
        if identifier is not None
        else f"code:{code.casefold()}"
        if code
        else f"name:{name.casefold()}"
        if name
        else None
    )
    if key is None:
        return None
    entry = catalog.setdefault(
        key,
        {
            "id": identifier,
            "code": code,
            "name": name,
            "count": 0,
        },
    )
    entry["count"] = int(entry.get("count", 0)) + 1
    if entry.get("id") is None and identifier is not None:
        entry["id"] = identifier
    if not entry.get("code") and code:
        entry["code"] = code
    if not entry.get("name") and name:
        entry["name"] = name
    return key


def _entity_label(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    return _text(value.get("code")) or _text(value.get("name"))


def _entity_text(item: dict[str, Any]) -> str:
    parts = []
    if item.get("id") not in (None, False, ""):
        parts.append(f"id={item['id']}")
    if item.get("code"):
        parts.append(f"code={item['code']}")
    if item.get("name"):
        parts.append(f"name={item['name']}")
    parts.append(f"seen={int(item.get('count', 0))}")
    return "{" + ", ".join(parts) + "}"


def _entity_sort(item: dict[str, Any]) -> str:
    return "|".join(
        str(item.get(key) or "") for key in ("code", "name", "id")
    ).casefold()


def _counter_text(values: dict[str, Any], *, limit: int) -> str:
    ordered = sorted(values.items(), key=lambda item: (-int(item[1]), str(item[0])))
    return ",".join(f"{name}:{count}" for name, count in ordered[:limit])


def _count_value(counter: dict[str, int], value: Any) -> None:
    if value in (None, False, ""):
        return
    key = str(value)
    counter[key] = int(counter.get(key, 0)) + 1


def _most_common_key(counter: dict[str, Any]) -> str | None:
    if not counter:
        return None
    return sorted(counter.items(), key=lambda item: (-int(item[1]), str(item[0])))[0][0]


def _pair_key(first: str, second: str) -> str:
    return json.dumps([first, second], ensure_ascii=False, separators=(",", ":"))


def _pairs_from_dict(value: Any) -> Counter[tuple[str, str]]:
    result: Counter[tuple[str, str]] = Counter()
    if not isinstance(value, dict):
        return result
    for key, count in value.items():
        try:
            pair = json.loads(str(key))
        except json.JSONDecodeError:
            continue
        if isinstance(pair, list) and len(pair) == 2:
            result[(str(pair[0]), str(pair[1]))] = int(count)
    return result


def _contract_version(rows: list[dict[str, Any]]) -> str:
    versions = {
        str(row.get("contract_version") or "").strip()
        for row in rows
        if str(row.get("contract_version") or "").strip()
    }
    if len(versions) > 1:
        raise CompanyMemoryError("Reference pool contains multiple contract versions")
    return next(iter(versions), "1.0")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _int_or_none(value: Any) -> int | None:
    try:
        if value in (None, False, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value in (None, False, ""):
        return None
    text = str(value).strip()
    return text or None


MemoryType = CompanyMemory
