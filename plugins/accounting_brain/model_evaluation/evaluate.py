"""Score Accounting Brain holdout predictions without exposing ground truth.

A model runner receives only ``evaluation-inputs.jsonl`` and writes
``evaluation-predictions.jsonl``. This module is then invoked separately by the
trusted evaluation process, which joins predictions to the private historical
ground truth by ``case_id`` and applies deterministic accounting scoring.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from plugins.accounting_brain.model_evaluation.production_gate import (
    ProductionThresholds,
    evaluate_production_readiness,
)
from plugins.accounting_brain.model_evaluation.scoring import (
    aggregate_evaluation_scores,
    score_journal_prediction,
)


class EvaluationRunError(RuntimeError):
    """Raised when holdout predictions cannot be evaluated safely."""


def score_latest_evaluation(
    datasets_root: Path,
    *,
    thresholds: ProductionThresholds | None = None,
) -> dict[str, Any]:
    """Score the newest prepared evaluation using its fixed predictions file.

    The function is fail-closed: missing or duplicate cases, version mismatch,
    extra predictions, malformed payloads, or an unready preparation manifest
    all block the evaluation rather than silently reducing the denominator.
    """

    evaluation_root = _latest_evaluation_root(Path(datasets_root))
    manifest = _load_json(evaluation_root / "evaluation-manifest.json")
    if manifest.get("ok") is not True or manifest.get("stage") != "EVALUATION_DATA_READY":
        raise EvaluationRunError(
            "Evaluation manifest is not in EVALUATION_DATA_READY state"
        )

    truth_rows = _load_jsonl(evaluation_root / "evaluation-ground-truth.jsonl")
    prediction_rows = _load_jsonl(evaluation_root / "evaluation-predictions.jsonl")
    if not truth_rows:
        raise EvaluationRunError("Evaluation ground truth contains no cases")
    if not prediction_rows:
        raise EvaluationRunError("Evaluation predictions contain no cases")

    expected = _index_rows(truth_rows, label="ground truth")
    predicted = _index_rows(prediction_rows, label="predictions")
    expected_ids = set(expected)
    predicted_ids = set(predicted)
    if expected_ids != predicted_ids:
        missing = sorted(expected_ids - predicted_ids)
        extra = sorted(predicted_ids - expected_ids)
        raise EvaluationRunError(
            "Prediction case IDs must exactly match the holdout; "
            f"missing={missing[:10]} extra={extra[:10]}"
        )

    contract_version = str(manifest.get("contract_version") or "")
    case_scores: list[dict[str, Any]] = []
    for case_id in sorted(expected_ids):
        truth_row = expected[case_id]
        prediction_row = predicted[case_id]
        if str(truth_row.get("contract_version") or "") != contract_version:
            raise EvaluationRunError(
                f"Ground-truth contract mismatch for case {case_id}"
            )
        if str(prediction_row.get("contract_version") or "") != contract_version:
            raise EvaluationRunError(
                f"Prediction contract mismatch for case {case_id}"
            )

        prediction = prediction_row.get("prediction")
        if not isinstance(prediction, dict):
            raise EvaluationRunError(
                f"Prediction for case {case_id} must be a JSON object"
            )
        target = truth_row.get("target")
        if not isinstance(target, dict):
            raise EvaluationRunError(
                f"Ground truth for case {case_id} must be a JSON object"
            )

        score = score_journal_prediction(target, prediction)
        case_scores.append({"case_id": case_id, "score": score})

    aggregate = aggregate_evaluation_scores(
        [item["score"] for item in case_scores]
    )
    production = evaluate_production_readiness(
        manifest,
        aggregate,
        thresholds=thresholds,
    )
    result = {
        "ok": production["ok"],
        "stage": production["stage"],
        "contract_version": contract_version,
        "evaluation_cases": len(case_scores),
        "aggregate": aggregate,
        "production_gate": production,
        "artifacts": {
            "case_scores_file": "evaluation-case-scores.jsonl",
            "report_file": "evaluation-score-report.json",
        },
        "safety": {
            "model_received_ground_truth": False,
            "model_self_grading": False,
            "odoo_mutations": False,
            "auto_post": False,
            "human_review_required": True,
        },
    }

    _write_jsonl_atomic(
        evaluation_root / result["artifacts"]["case_scores_file"],
        case_scores,
    )
    _write_json_atomic(
        evaluation_root / result["artifacts"]["report_file"],
        result,
    )
    return result


def _latest_evaluation_root(datasets_root: Path) -> Path:
    root = datasets_root.expanduser().resolve()
    if not root.exists():
        raise EvaluationRunError("No Accounting Brain dataset directory exists")
    candidates = sorted(
        path / "evaluation"
        for path in root.iterdir()
        if path.is_dir()
        and path.name.startswith("golden-")
        and (path / "evaluation" / "evaluation-manifest.json").is_file()
    )
    if not candidates:
        raise EvaluationRunError("No prepared Accounting Brain evaluation exists")
    return candidates[-1]


def _index_rows(
    rows: list[dict[str, Any]],
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id") or "").strip()
        if not case_id:
            raise EvaluationRunError(f"{label} contains a row without case_id")
        if case_id in indexed:
            raise EvaluationRunError(f"{label} contains duplicate case_id {case_id}")
        indexed[case_id] = row
    return indexed


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvaluationRunError(f"Missing evaluation artifact: {path.name}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationRunError(f"Invalid evaluation artifact: {path.name}") from exc
    if not isinstance(value, dict):
        raise EvaluationRunError(f"Evaluation artifact must be an object: {path.name}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise EvaluationRunError(f"Missing evaluation artifact: {path.name}") from exc
    except OSError as exc:
        raise EvaluationRunError(f"Cannot read evaluation artifact: {path.name}") from exc

    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EvaluationRunError(
                f"Invalid JSONL in {path.name} at line {line_number}"
            ) from exc
        if not isinstance(value, dict):
            raise EvaluationRunError(
                f"JSONL row in {path.name} at line {line_number} must be an object"
            )
        rows.append(value)
    return rows


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    _write_text_atomic(path, text)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
