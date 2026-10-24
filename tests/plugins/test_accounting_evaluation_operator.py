from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.accounting_brain.model_evaluation.operator import (
    EvaluationOperatorError,
    score_prediction_file,
)


def _target() -> dict:
    return {
        "move_type": "in_invoice",
        "partner": {"id": 44, "name": "Vendor"},
        "journal": {"id": 9, "name": "Vendor Bills"},
        "company": {"id": 1, "name": "Company"},
        "currency": {"id": 1, "name": "SAR"},
        "taxes": [{"id": 3, "name": "VAT 15%"}],
        "journal_entry": [
            {
                "account_id": 501,
                "account_code": "500100",
                "debit": "100.00",
                "credit": "0.00",
                "tax_ids": [3],
                "analytic_distribution": None,
            },
            {
                "account_id": 202,
                "account_code": "202000",
                "debit": "15.00",
                "credit": "0.00",
                "tax_ids": [],
                "analytic_distribution": None,
            },
            {
                "account_id": 401,
                "account_code": "401000",
                "debit": "0.00",
                "credit": "115.00",
                "tax_ids": [],
                "analytic_distribution": None,
            },
        ],
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _prepared_dataset(root: Path) -> Path:
    dataset = root / "golden-20260904T000000000000Z"
    evaluation = dataset / "evaluation"
    evaluation.mkdir(parents=True)
    _write_jsonl(dataset / "pairs.jsonl", [{"grade": "gold"}])
    _write_jsonl(
        evaluation / "evaluation-inputs.jsonl",
        [
            {"case_id": "acct-a", "source": {"attachments": []}},
            {"case_id": "acct-b", "source": {"attachments": []}},
        ],
    )
    _write_jsonl(
        evaluation / "evaluation-ground-truth.jsonl",
        [
            {"case_id": "acct-a", "target": _target()},
            {"case_id": "acct-b", "target": _target()},
        ],
    )
    (evaluation / "evaluation-manifest.json").write_text(
        json.dumps({"ok": True, "stage": "EVALUATION_DATA_READY"}),
        encoding="utf-8",
    )
    return dataset


def test_score_prediction_file_requires_exact_case_coverage(tmp_path: Path) -> None:
    _prepared_dataset(tmp_path)
    predictions = tmp_path / "predictions.jsonl"
    _write_jsonl(
        predictions,
        [{"case_id": "acct-a", "prediction": _target()}],
    )

    with pytest.raises(EvaluationOperatorError, match="exactly match the holdout"):
        score_prediction_file(tmp_path, predictions)


def test_score_prediction_file_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    _prepared_dataset(tmp_path)
    predictions = tmp_path / "predictions.jsonl"
    _write_jsonl(
        predictions,
        [
            {"case_id": "acct-a", "prediction": _target()},
            {"case_id": "acct-a", "prediction": _target()},
        ],
    )

    with pytest.raises(EvaluationOperatorError, match="Duplicate case_id"):
        score_prediction_file(tmp_path, predictions)


def test_score_prediction_file_writes_private_deterministic_report(tmp_path: Path) -> None:
    dataset = _prepared_dataset(tmp_path)
    wrong = json.loads(json.dumps(_target()))
    wrong["journal_entry"][0]["account_code"] = "999999"
    predictions = tmp_path / "predictions.jsonl"
    _write_jsonl(
        predictions,
        [
            {"case_id": "acct-a", "prediction": _target()},
            {"case_id": "acct-b", "prediction": wrong},
        ],
    )

    result = score_prediction_file(tmp_path, predictions)

    assert result["ok"] is True
    assert result["stage"] == "BASELINE_EVALUATION_SCORED"
    assert result["next_action"] == "REVIEW_BASELINE_METRICS_BEFORE_MODEL_SELECTION"
    assert result["coverage"]["exact_case_coverage"] is True
    assert result["metrics"]["cases"] == 2
    assert result["metrics"]["strict_pass_rate"] == 0.5
    assert result["metrics"]["critical_rates"]["balanced"] == 1.0
    assert result["metrics"]["critical_rates"]["account_amount_exact"] == 0.5
    assert result["safety"]["model_self_grading"] is False
    assert result["safety"]["ground_truth_sent_to_model"] is False

    artifact = dataset / "evaluation" / "baseline-score.json"
    assert result["artifact"] == str(artifact)
    written = json.loads(artifact.read_text(encoding="utf-8"))
    assert "target" not in json.dumps(written, sort_keys=True)
    assert [case["case_id"] for case in written["cases"]] == ["acct-a", "acct-b"]


def test_score_prediction_file_rejects_unready_manifest(tmp_path: Path) -> None:
    dataset = _prepared_dataset(tmp_path)
    (dataset / "evaluation" / "evaluation-manifest.json").write_text(
        json.dumps({"ok": False, "stage": "BLOCKED_BY_SOURCE_EVIDENCE"}),
        encoding="utf-8",
    )
    predictions = tmp_path / "predictions.jsonl"
    _write_jsonl(
        predictions,
        [
            {"case_id": "acct-a", "prediction": _target()},
            {"case_id": "acct-b", "prediction": _target()},
        ],
    )

    with pytest.raises(EvaluationOperatorError, match="not ready"):
        score_prediction_file(tmp_path, predictions)
