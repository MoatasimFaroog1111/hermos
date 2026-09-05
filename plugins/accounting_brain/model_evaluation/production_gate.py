"""Deterministic production-readiness gate for the Accounting Brain.

The gate consumes only already-produced evaluation evidence and deterministic
aggregate metrics. It never calls a model, never mutates Odoo, and never trusts
a model to grade itself.

Production in this phase means *draft-only accounting assistance*: predictions
may be prepared for human review, but automatic posting remains prohibited.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ProductionThresholds:
    """Minimum acceptance thresholds for draft-only production use."""

    minimum_cases: int = 100
    strict_pass_rate: float = 0.95
    schema_valid: float = 1.0
    balanced: float = 1.0
    amount_invariance: float = 1.0
    debit_credit_direction_exact: float = 1.0
    account_amount_exact: float = 0.98
    tax_exact: float = 0.98
    move_type_exact: float = 0.98
    journal_exact: float = 0.98
    partner_exact: float = 0.95
    currency_exact: float = 0.99
    analytic_distribution_exact: float = 0.90


_REQUIRED_PREPARATION_GATES = (
    "gold_only",
    "single_company_scope",
    "exact_attachment_checksum_leakage_removed",
    "model_input_target_leakage_blocked",
    "auto_post_disabled",
    "human_review_required",
)


def evaluate_production_readiness(
    evaluation_preparation: dict[str, Any],
    aggregate_metrics: dict[str, Any],
    *,
    thresholds: ProductionThresholds | None = None,
) -> dict[str, Any]:
    """Evaluate whether the Accounting Brain may enter draft-only production.

    This is deliberately fail-closed. Missing fields, malformed rates, a stale
    evaluation-preparation stage, insufficient holdout cases, or any failed
    accounting invariant blocks production readiness.
    """

    limits = thresholds or ProductionThresholds()
    prep_gates = evaluation_preparation.get("gates") or {}
    critical = aggregate_metrics.get("critical_rates") or {}
    secondary = aggregate_metrics.get("secondary_rates") or {}

    checks: dict[str, dict[str, Any]] = {}

    checks["evaluation_data_ready"] = _boolean_check(
        evaluation_preparation.get("ok") is True
        and evaluation_preparation.get("stage") == "EVALUATION_DATA_READY",
        actual=evaluation_preparation.get("stage"),
        required="EVALUATION_DATA_READY",
    )

    for gate_name in _REQUIRED_PREPARATION_GATES:
        checks[f"preparation_{gate_name}"] = _boolean_check(
            _gate_passed(prep_gates.get(gate_name)),
            actual=prep_gates.get(gate_name),
            required=True,
        )

    checks["temporal_holdout"] = _boolean_check(
        _gate_passed(prep_gates.get("temporal_holdout")),
        actual=prep_gates.get("temporal_holdout"),
        required=True,
    )
    checks["source_content_coverage"] = _boolean_check(
        _gate_passed(prep_gates.get("source_content_coverage")),
        actual=prep_gates.get("source_content_coverage"),
        required=True,
    )

    cases = _integer(aggregate_metrics.get("cases"))
    checks["minimum_evaluation_cases"] = _rate_check(
        cases,
        limits.minimum_cases,
        comparator=">=",
    )
    checks["strict_pass_rate"] = _rate_check(
        _rate(aggregate_metrics.get("strict_pass_rate")),
        limits.strict_pass_rate,
    )

    critical_thresholds = {
        "schema_valid": limits.schema_valid,
        "balanced": limits.balanced,
        "amount_invariance": limits.amount_invariance,
        "debit_credit_direction_exact": limits.debit_credit_direction_exact,
        "account_amount_exact": limits.account_amount_exact,
        "tax_exact": limits.tax_exact,
        "move_type_exact": limits.move_type_exact,
        "journal_exact": limits.journal_exact,
    }
    for key, minimum in critical_thresholds.items():
        checks[f"critical_{key}"] = _rate_check(_rate(critical.get(key)), minimum)

    secondary_thresholds = {
        "partner_exact": limits.partner_exact,
        "currency_exact": limits.currency_exact,
        "analytic_distribution_exact": limits.analytic_distribution_exact,
    }
    for key, minimum in secondary_thresholds.items():
        checks[f"secondary_{key}"] = _rate_check(_rate(secondary.get(key)), minimum)

    passed = all(item["pass"] for item in checks.values())
    failed_checks = [name for name, result in checks.items() if not result["pass"]]

    return {
        "ok": passed,
        "stage": "PRODUCTION_READY_DRAFT_ONLY" if passed else "BLOCKED_BY_PRODUCTION_GATE",
        "production_mode": "draft_only",
        "auto_post": False,
        "human_review_required": True,
        "thresholds": asdict(limits),
        "checks": checks,
        "failed_checks": failed_checks,
        "next_action": (
            "ENABLE_DRAFT_ONLY_ACCOUNTING_WORKFLOW"
            if passed
            else "IMPROVE_MODEL_OR_EVIDENCE_AND_REEVALUATE"
        ),
        "safety": {
            "odoo_auto_post": False,
            "model_self_grading": False,
            "deterministic_scoring_required": True,
            "human_review_required": True,
        },
    }


def _gate_passed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return value.get("pass") is True
    return False


def _boolean_check(passed: bool, *, actual: Any, required: Any) -> dict[str, Any]:
    return {"pass": bool(passed), "actual": actual, "required": required}


def _rate_check(actual: float | int | None, required: float | int, *, comparator: str = ">=") -> dict[str, Any]:
    passed = actual is not None and actual >= required
    return {
        "pass": bool(passed),
        "actual": actual,
        "required": required,
        "comparator": comparator,
    }


def _rate(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0.0 or number > 1.0:
        return None
    return number


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None
