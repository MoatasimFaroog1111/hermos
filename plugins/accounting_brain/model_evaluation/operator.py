"""Operator use cases for Accounting Brain model evaluation.

This module deliberately does not run or train a model. It prepares leakage-safe
model inputs through the existing evaluation preparation use case and scores a
separate predictions file against private ground truth using deterministic
accounting invariants.

The prediction contract is intentionally narrow::

    {"case_id": "acct-...", "prediction": { ...journal target shape... }}

Ground truth is never copied into the predictions file and is never included in
the score report. This keeps answer data outside the model runner's input path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from plugins.accounting_brain.model_evaluation.prepare import (
    EvaluationPreparationError,
    prepare_evaluation_evidence,
)
from plugins.accounting_brain.model_evaluation.scoring import (
    aggregate_evaluation_scores,
    score_journal_prediction,
)
from plugins.accounting_brain.odoo_discovery.contracts import OdooReadPort


class EvaluationOperatorError(RuntimeError):
    """Raised when evaluation artifacts violate the operator contract."""


def prepare_operator_evaluation(
    reader: OdooReadPort,
    datasets_root: Path,
    *,
    hydrate_source_content: bool = False,
    max_attachment_bytes: int = 25 * 1024 * 1024,
    holdout_fraction: float = 0.20,
    min_holdout: int = 100,
    min_source_content_coverage: float = 0.90,
) -> dict[str, Any]:
    """Prepare the newest private Gold dataset for leakage-safe evaluation."""
    try:
        return prepare_evaluation_evidence(
            reader,
            datasets_root,
            hydrate_source_content=hydrate_source_content,
            max_attachment_bytes=max_attachment_bytes,
            holdout_fraction=holdout_fraction,
            min_holdout=min_holdout,
            min_source_content_coverage=min_source_content_coverage,
        )
    except EvaluationPreparationError as exc:
        raise EvaluationOperatorError(str(exc)) from exc


def score_prediction_file(
    datasets_root: Path,
    predictions_path: Path,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Score one complete prediction set against private evaluation truth.

    The newest ``golden-*`` dataset is selected using the same private-dataset
    convention as evaluation preparation. Coverage is fail-closed: duplicate,
    missing, or unknown case IDs reject the run instead of silently changing
    the denominator.
    """
    dataset_root = _latest_evaluation_dataset(Path(datasets_root))
    evaluation_root = dataset_root / "evaluation"
    truth_path = evaluation_root / "evaluation-ground-truth.jsonl"
    inputs_path = evaluation_root / "evaluation-inputs.jsonl"
    manifest_path = evaluation_root / "evaluation-manifest.json"

    required_files = (inputs_path, truth_path, manifest_path)
    if not all(path.is_file() for path in required_files):
        raise EvaluationOperatorError(
            "The latest Golden Dataset has not been prepared for evaluation"
        )

    manifest = _load_json(manifest_path)
    if manifest.get("stage") != "EVALUATION_DATA_READY" or not bool(
        manifest.get("ok")
    ):
        raise EvaluationOperatorError(
            "Evaluation manifest is not ready; resolve its data-quality gates first"
        )

    input_rows = _load_jsonl(inputs_path)
    truth_rows = _load_jsonl(truth_path)
    prediction_rows = _load_jsonl(Path(predictions_path).expanduser().resolve())

    input_ids = _unique_case_ids(input_rows, source="evaluation inputs")
    truth_by_id = _index_truth(truth_rows)
    predictions_by_id = _index_predictions(prediction_rows)

    truth_ids = set(truth_by_id)
    prediction_ids = set(predictions_by_id)
    if input_ids != truth_ids:
        raise EvaluationOperatorError(
            "Evaluation input and ground-truth case sets differ; prepare the dataset again"
        )

    missing = sorted(truth_ids - prediction_ids)
    unknown = sorted(prediction_ids - truth_ids)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing predictions={len(missing)}")
        if unknown:
            details.append(f"unknown predictions={len(unknown)}")
        raise EvaluationOperatorError(
            "Prediction case coverage must exactly match the holdout ("
            + ", ".join(details)
            + ")"
        )

    case_scores: list[dict[str, Any]] = []
    for case_id in sorted(truth_ids):
        score = score_journal_prediction(
            truth_by_id[case_id],
            predictions_by_id[case_id],
        )
        case_scores.append(
            {
                "case_id": case_id,
                "pass": bool(score.get("pass")),
                "critical": dict(score.get("critical") or {}),
                "secondary": dict(score.get("secondary") or {}),
                "predicted_summary": dict(score.get("predicted") or {}),
            }
        )

    destination = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else evaluation_root / "baseline-score.json"
    )
    aggregate = aggregate_evaluation_scores(case_scores)
    report: dict[str, Any] = {
        "ok": True,
        "stage": "BASELINE_EVALUATION_SCORED",
        "next_action": "REVIEW_BASELINE_METRICS_BEFORE_MODEL_SELECTION",
        "dataset": {
            "name": dataset_root.name,
            "holdout_cases": len(truth_ids),
        },
        "coverage": {
            "expected_cases": len(truth_ids),
            "prediction_cases": len(prediction_ids),
            "exact_case_coverage": True,
            "duplicate_case_ids": False,
            "unknown_case_ids": False,
        },
        "metrics": aggregate,
        "cases": case_scores,
        "artifact": str(destination),
        "safety": {
            "odoo_mutations": False,
            "training_performed": False,
            "auto_post": False,
            "model_self_grading": False,
            "ground_truth_sent_to_model": False,
        },
    }

    _write_private_json(destination, report)
    return report


def _latest_evaluation_dataset(datasets_root: Path) -> Path:
    root = datasets_root.expanduser().resolve()
    if not root.is_dir():
        raise EvaluationOperatorError(
            "No private Accounting Brain dataset directory exists"
        )
    candidates = sorted(
        path
        for path in root.iterdir()
        if path.is_dir()
        and path.name.startswith("golden-")
        and (path / "pairs.jsonl").is_file()
        and (path / "evaluation").is_dir()
    )
    if not candidates:
        raise EvaluationOperatorError("No prepared private Golden Dataset was found")
    return candidates[-1]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationOperatorError(f"Could not read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvaluationOperatorError(f"{path.name} must contain one JSON object")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, start=1):
                text = raw.strip()
                if not text:
                    continue
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise EvaluationOperatorError(
                        f"{path.name} line {line_number} must be a JSON object"
                    )
                rows.append(value)
    except EvaluationOperatorError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationOperatorError(f"Could not read {path.name}: {exc}") from exc
    if not rows:
        raise EvaluationOperatorError(f"{path.name} contains no cases")
    return rows


def _case_id(row: dict[str, Any], *, source: str) -> str:
    value = str(row.get("case_id") or "").strip()
    if not value:
        raise EvaluationOperatorError(f"A {source} row is missing case_id")
    return value


def _unique_case_ids(rows: list[dict[str, Any]], *, source: str) -> set[str]:
    result: set[str] = set()
    for row in rows:
        case_id = _case_id(row, source=source)
        if case_id in result:
            raise EvaluationOperatorError(f"Duplicate case_id in {source}: {case_id}")
        result.add(case_id)
    return result


def _index_truth(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = _case_id(row, source="ground truth")
        if case_id in result:
            raise EvaluationOperatorError(f"Duplicate case_id in ground truth: {case_id}")
        target = row.get("target")
        if not isinstance(target, dict):
            raise EvaluationOperatorError(
                f"Ground truth case {case_id} has no target object"
            )
        result[case_id] = target
    return result


def _index_predictions(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = _case_id(row, source="predictions")
        if case_id in result:
            raise EvaluationOperatorError(f"Duplicate case_id in predictions: {case_id}")
        prediction = row.get("prediction")
        if not isinstance(prediction, dict):
            raise EvaluationOperatorError(
                f"Prediction case {case_id} must contain a prediction object"
            )
        result[case_id] = prediction
    return result


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
