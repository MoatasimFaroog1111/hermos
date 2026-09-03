"""Deterministic scoring for accounting-model predictions.

No language model is trusted to grade itself. Predictions are compared with the
historical Gold target using exact accounting invariants and normalized ledger
signatures. The scorer is deliberately strict: a balanced but wrongly
classified journal entry does not pass.
"""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any


def score_journal_prediction(
    expected: dict[str, Any],
    predicted: dict[str, Any],
) -> dict[str, Any]:
    """Return exact, deterministic metrics for one predicted journal entry."""
    expected_lines = _lines(expected)
    predicted_lines = _lines(predicted)
    schema_valid = isinstance(predicted, dict) and isinstance(
        predicted.get("journal_entry"), list
    )

    expected_totals = _totals(expected_lines)
    predicted_totals = _totals(predicted_lines)
    predicted_balanced = predicted_totals[0] == predicted_totals[1]
    amount_invariance = predicted_totals == expected_totals

    account_amount_exact = _line_signature_counter(predicted_lines) == _line_signature_counter(
        expected_lines
    )
    direction_exact = _direction_counter(predicted_lines) == _direction_counter(
        expected_lines
    )
    tax_exact = _tax_ids(predicted) == _tax_ids(expected)
    analytic_exact = _analytic_counter(predicted_lines) == _analytic_counter(expected_lines)
    move_type_exact = _text(predicted.get("move_type")) == _text(expected.get("move_type"))
    journal_exact = _reference_key(predicted.get("journal")) == _reference_key(
        expected.get("journal")
    )
    partner_exact = _reference_key(predicted.get("partner")) == _reference_key(
        expected.get("partner")
    )
    currency_exact = _reference_key(predicted.get("currency")) == _reference_key(
        expected.get("currency")
    )

    critical = {
        "schema_valid": schema_valid,
        "balanced": predicted_balanced,
        "amount_invariance": amount_invariance,
        "account_amount_exact": account_amount_exact,
        "debit_credit_direction_exact": direction_exact,
        "tax_exact": tax_exact,
        "move_type_exact": move_type_exact,
        "journal_exact": journal_exact,
    }
    return {
        "pass": all(critical.values()),
        "critical": critical,
        "secondary": {
            "partner_exact": partner_exact,
            "currency_exact": currency_exact,
            "analytic_distribution_exact": analytic_exact,
        },
        "expected": {
            "line_count": len(expected_lines),
            "total_debit": _money(expected_totals[0]),
            "total_credit": _money(expected_totals[1]),
        },
        "predicted": {
            "line_count": len(predicted_lines),
            "total_debit": _money(predicted_totals[0]),
            "total_credit": _money(predicted_totals[1]),
        },
    }


def aggregate_evaluation_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate case-level deterministic scores without hiding failures."""
    total = len(scores)
    if total == 0:
        return {
            "cases": 0,
            "strict_pass_rate": 0.0,
            "critical_rates": {},
            "secondary_rates": {},
        }

    critical_keys = sorted(
        {
            key
            for score in scores
            for key in (score.get("critical") or {}).keys()
        }
    )
    secondary_keys = sorted(
        {
            key
            for score in scores
            for key in (score.get("secondary") or {}).keys()
        }
    )
    return {
        "cases": total,
        "strict_pass_rate": round(
            sum(bool(score.get("pass")) for score in scores) / total,
            4,
        ),
        "critical_rates": {
            key: round(
                sum(bool((score.get("critical") or {}).get(key)) for score in scores)
                / total,
                4,
            )
            for key in critical_keys
        },
        "secondary_rates": {
            key: round(
                sum(bool((score.get("secondary") or {}).get(key)) for score in scores)
                / total,
                4,
            )
            for key in secondary_keys
        },
    }


def _lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("journal_entry") if isinstance(payload, dict) else None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _totals(lines: list[dict[str, Any]]) -> tuple[Decimal, Decimal]:
    return (
        sum((_decimal(line.get("debit")) for line in lines), Decimal("0.00")),
        sum((_decimal(line.get("credit")) for line in lines), Decimal("0.00")),
    )


def _account_key(line: dict[str, Any]) -> str:
    code = _text(line.get("account_code"))
    if code:
        return f"code:{code}"
    account_id = line.get("account_id")
    if account_id not in (None, False, ""):
        return f"id:{account_id}"
    return "missing"


def _line_signature_counter(lines: list[dict[str, Any]]) -> Counter[tuple[str, str, str]]:
    return Counter(
        (
            _account_key(line),
            _money(_decimal(line.get("debit"))),
            _money(_decimal(line.get("credit"))),
        )
        for line in lines
    )


def _direction_counter(lines: list[dict[str, Any]]) -> Counter[tuple[str, str]]:
    signatures: Counter[tuple[str, str]] = Counter()
    for line in lines:
        debit = _decimal(line.get("debit"))
        credit = _decimal(line.get("credit"))
        direction = "debit" if debit > 0 else "credit" if credit > 0 else "zero"
        signatures[(_account_key(line), direction)] += 1
    return signatures


def _tax_ids(payload: dict[str, Any]) -> tuple[int, ...]:
    result: set[int] = set()
    taxes = payload.get("taxes") if isinstance(payload, dict) else None
    if isinstance(taxes, list):
        for tax in taxes:
            if isinstance(tax, dict):
                raw = tax.get("id")
            else:
                raw = tax
            try:
                if raw not in (None, False, ""):
                    result.add(int(raw))
            except (TypeError, ValueError):
                continue
    for line in _lines(payload):
        raw_ids = line.get("tax_ids")
        if not isinstance(raw_ids, (list, tuple)):
            continue
        for raw in raw_ids:
            try:
                result.add(int(raw))
            except (TypeError, ValueError):
                continue
    return tuple(sorted(result))


def _analytic_counter(lines: list[dict[str, Any]]) -> Counter[tuple[str, str]]:
    return Counter(
        (
            _account_key(line),
            json.dumps(
                line.get("analytic_distribution") or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        for line in lines
    )


def _reference_key(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    identifier = value.get("id")
    if identifier not in (None, False, ""):
        return f"id:{identifier}"
    name = _text(value.get("name"))
    return f"name:{name.casefold()}" if name else None


def _text(value: Any) -> str | None:
    if value in (None, False, ""):
        return None
    text = str(value).strip()
    return text or None
