from plugins.accounting_brain.model_evaluation.production_gate import (
    ProductionThresholds,
    evaluate_production_readiness,
)


def _ready_preparation() -> dict:
    return {
        "ok": True,
        "stage": "EVALUATION_DATA_READY",
        "gates": {
            "gold_only": True,
            "single_company_scope": True,
            "temporal_holdout": {"pass": True},
            "exact_attachment_checksum_leakage_removed": True,
            "model_input_target_leakage_blocked": True,
            "source_content_coverage": {"pass": True},
            "auto_post_disabled": True,
            "human_review_required": True,
        },
    }


def _passing_metrics() -> dict:
    return {
        "cases": 150,
        "strict_pass_rate": 0.97,
        "critical_rates": {
            "schema_valid": 1.0,
            "balanced": 1.0,
            "amount_invariance": 1.0,
            "debit_credit_direction_exact": 1.0,
            "account_amount_exact": 0.99,
            "tax_exact": 0.99,
            "move_type_exact": 0.99,
            "journal_exact": 0.99,
        },
        "secondary_rates": {
            "partner_exact": 0.97,
            "currency_exact": 1.0,
            "analytic_distribution_exact": 0.93,
        },
    }


def test_production_gate_passes_only_as_draft_only() -> None:
    result = evaluate_production_readiness(_ready_preparation(), _passing_metrics())

    assert result["ok"] is True
    assert result["stage"] == "PRODUCTION_READY_DRAFT_ONLY"
    assert result["production_mode"] == "draft_only"
    assert result["auto_post"] is False
    assert result["human_review_required"] is True
    assert result["failed_checks"] == []


def test_production_gate_rejects_unbalanced_evaluation() -> None:
    metrics = _passing_metrics()
    metrics["critical_rates"]["balanced"] = 0.99

    result = evaluate_production_readiness(_ready_preparation(), metrics)

    assert result["ok"] is False
    assert "critical_balanced" in result["failed_checks"]


def test_production_gate_rejects_insufficient_holdout_cases() -> None:
    metrics = _passing_metrics()
    metrics["cases"] = 99

    result = evaluate_production_readiness(_ready_preparation(), metrics)

    assert result["ok"] is False
    assert "minimum_evaluation_cases" in result["failed_checks"]


def test_production_gate_rejects_missing_leakage_control() -> None:
    preparation = _ready_preparation()
    preparation["gates"]["model_input_target_leakage_blocked"] = False

    result = evaluate_production_readiness(preparation, _passing_metrics())

    assert result["ok"] is False
    assert "preparation_model_input_target_leakage_blocked" in result["failed_checks"]


def test_production_gate_fails_closed_on_missing_metric() -> None:
    metrics = _passing_metrics()
    del metrics["critical_rates"]["tax_exact"]

    result = evaluate_production_readiness(_ready_preparation(), metrics)

    assert result["ok"] is False
    assert "critical_tax_exact" in result["failed_checks"]


def test_thresholds_can_be_tightened_without_changing_gate_logic() -> None:
    thresholds = ProductionThresholds(strict_pass_rate=0.99)

    result = evaluate_production_readiness(
        _ready_preparation(),
        _passing_metrics(),
        thresholds=thresholds,
    )

    assert result["ok"] is False
    assert "strict_pass_rate" in result["failed_checks"]
