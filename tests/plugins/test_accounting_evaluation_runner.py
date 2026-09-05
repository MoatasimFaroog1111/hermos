import json
from pathlib import Path

import pytest

from plugins.accounting_brain.model_evaluation.evaluate import (
    EvaluationRunError,
    score_latest_evaluation,
)
from plugins.accounting_brain.model_evaluation.production_gate import (
    ProductionThresholds,
)


def _manifest() -> dict:
    return {
        "ok": True,
        "stage": "EVALUATION_DATA_READY",
        "contract_version": "1.0",
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


def _target() -> dict:
    return {
        "move_type": "in_invoice",
        "journal": {"id": 3, "name": "Vendor Bills"},
        "partner": {"id": 9, "name": "Supplier"},
        "currency": {"id": 1, "name": "SAR"},
        "taxes": [{"id": 15}],
        "journal_entry": [
            {
                "account_id": 101,
                "account_code": "510000",
                "debit": "100.00",
                "credit": "0.00",
                "tax_ids": [15],
                "analytic_distribution": {},
            },
            {
                "account_id": 201,
                "account_code": "211000",
                "debit": "0.00",
                "credit": "100.00",
                "tax_ids": [],
                "analytic_distribution": {},
            },
        ],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _evaluation_root(tmp_path: Path) -> Path:
    root = tmp_path / "golden-20260905T000000Z" / "evaluation"
    root.mkdir(parents=True)
    _write_json(root / "evaluation-manifest.json", _manifest())
    _write_jsonl(
        root / "evaluation-ground-truth.jsonl",
        [
            {
                "contract_version": "1.0",
                "case_id": "case-1",
                "target": _target(),
            }
        ],
    )
    return root


def test_scores_exact_predictions_and_opens_draft_only_gate(tmp_path: Path) -> None:
    root = _evaluation_root(tmp_path)
    _write_jsonl(
        root / "evaluation-predictions.jsonl",
        [
            {
                "contract_version": "1.0",
                "case_id": "case-1",
                "prediction": _target(),
            }
        ],
    )

    result = score_latest_evaluation(
        tmp_path,
        thresholds=ProductionThresholds(minimum_cases=1),
    )

    assert result["ok"] is True
    assert result["stage"] == "PRODUCTION_READY_DRAFT_ONLY"
    assert result["aggregate"]["strict_pass_rate"] == 1.0
    assert (root / "evaluation-case-scores.jsonl").is_file()
    assert (root / "evaluation-score-report.json").is_file()


def test_rejects_missing_prediction_case(tmp_path: Path) -> None:
    root = _evaluation_root(tmp_path)
    _write_jsonl(root / "evaluation-predictions.jsonl", [])

    with pytest.raises(EvaluationRunError, match="predictions contain no cases"):
        score_latest_evaluation(tmp_path)


def test_rejects_extra_prediction_case(tmp_path: Path) -> None:
    root = _evaluation_root(tmp_path)
    prediction = {
        "contract_version": "1.0",
        "prediction": _target(),
    }
    _write_jsonl(
        root / "evaluation-predictions.jsonl",
        [
            {**prediction, "case_id": "case-1"},
            {**prediction, "case_id": "case-2"},
        ],
    )

    with pytest.raises(EvaluationRunError, match="exactly match the holdout"):
        score_latest_evaluation(tmp_path)


def test_rejects_contract_version_mismatch(tmp_path: Path) -> None:
    root = _evaluation_root(tmp_path)
    _write_jsonl(
        root / "evaluation-predictions.jsonl",
        [
            {
                "contract_version": "2.0",
                "case_id": "case-1",
                "prediction": _target(),
            }
        ],
    )

    with pytest.raises(EvaluationRunError, match="Prediction contract mismatch"):
        score_latest_evaluation(tmp_path)
