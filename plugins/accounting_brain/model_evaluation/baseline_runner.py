"""Run the leakage-safe Accounting Brain baseline through Hermes' host LLM.

The runner reads only ``evaluation-inputs.jsonl``. Ground truth is never opened
here. Predictions are persisted first and scored later by the trusted evaluator
in ``evaluate.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from plugins.accounting_brain.model_evaluation.evaluate import (
    EvaluationRunError,
    score_latest_evaluation,
)
from plugins.accounting_brain.model_evaluation.source_material import (
    SourceMaterialError,
    build_model_inputs,
)


class StructuredLlmPort(Protocol):
    def complete_structured(self, **kwargs: Any) -> Any: ...


PREDICTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "required": [
        "move_type",
        "journal",
        "partner",
        "currency",
        "taxes",
        "journal_entry",
    ],
    "properties": {
        "move_type": {"type": ["string", "null"]},
        "journal": {"type": ["object", "null"]},
        "partner": {"type": ["object", "null"]},
        "currency": {"type": ["object", "null"]},
        "taxes": {"type": "array"},
        "journal_entry": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": [
                    "account_code",
                    "debit",
                    "credit",
                    "tax_ids",
                    "analytic_distribution",
                ],
                "properties": {
                    "account_id": {"type": ["integer", "null"]},
                    "account_code": {"type": ["string", "null"]},
                    "account_name": {"type": ["string", "null"]},
                    "partner_id": {"type": ["integer", "null"]},
                    "partner_name": {"type": ["string", "null"]},
                    "label": {"type": ["string", "null"]},
                    "debit": {"type": ["string", "number"]},
                    "credit": {"type": ["string", "number"]},
                    "tax_ids": {"type": "array"},
                    "analytic_distribution": {"type": ["object", "null"]},
                },
            },
        },
    },
}

_INSTRUCTIONS = """You are the Accounting Brain inside Hermes.
Infer the complete Odoo journal entry represented by the attached source document.
Return only the requested JSON structure. Do not invent an unsupported amount.
The journal entry must balance exactly. Use debit/credit strings with two decimals.
Infer move_type, journal, partner, currency, taxes, account codes, tax IDs and
analytic distribution only from the document and your accounting knowledge.
This is an evaluation prediction only: do not call tools, do not access Odoo,
and do not post or modify any accounting record.
"""


class BaselineEvaluationError(RuntimeError):
    """Raised when the host model cannot produce a complete safe holdout run."""


def run_baseline_evaluation(
    datasets_root: Path,
    llm: StructuredLlmPort,
    *,
    timeout_seconds: float = 120.0,
    max_tokens: int = 1800,
) -> dict[str, Any]:
    """Run every prepared holdout case, persist predictions, then score them."""

    evaluation_root = _latest_evaluation_root(Path(datasets_root))
    manifest = _load_json(evaluation_root / "evaluation-manifest.json")
    if manifest.get("ok") is not True or manifest.get("stage") != "EVALUATION_DATA_READY":
        raise BaselineEvaluationError(
            "Prepare leakage-safe evaluation evidence before running the baseline"
        )

    contract_version = str(manifest.get("contract_version") or "")
    input_rows = _load_jsonl(evaluation_root / "evaluation-inputs.jsonl")
    if not input_rows:
        raise BaselineEvaluationError("Prepared evaluation contains no model inputs")

    dataset_root = evaluation_root.parent
    predictions: list[dict[str, Any]] = []
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }
    providers: set[str] = set()
    models: set[str] = set()

    for row in input_rows:
        case_id = str(row.get("case_id") or "").strip()
        if not case_id:
            raise BaselineEvaluationError("Evaluation input contains no case_id")
        if str(row.get("contract_version") or "") != contract_version:
            raise BaselineEvaluationError(f"Contract mismatch for case {case_id}")
        source = row.get("source")
        if not isinstance(source, dict):
            raise BaselineEvaluationError(f"Missing source for case {case_id}")

        try:
            model_inputs = build_model_inputs(source, dataset_root=dataset_root)
        except SourceMaterialError as exc:
            raise BaselineEvaluationError(f"Source preparation failed for {case_id}: {exc}") from exc

        try:
            result = llm.complete_structured(
                instructions=_INSTRUCTIONS,
                input=model_inputs,
                json_schema=PREDICTION_SCHEMA,
                json_mode=True,
                schema_name="odoo_journal_prediction_v1",
                temperature=0.0,
                max_tokens=max_tokens,
                timeout=timeout_seconds,
                purpose="accounting_baseline_evaluation",
            )
        except Exception as exc:
            raise BaselineEvaluationError(
                f"Host model inference failed for case {case_id}: {type(exc).__name__}"
            ) from exc

        prediction = getattr(result, "parsed", None)
        if not isinstance(prediction, dict):
            raise BaselineEvaluationError(
                f"Host model returned invalid structured JSON for case {case_id}"
            )
        predictions.append(
            {
                "contract_version": contract_version,
                "case_id": case_id,
                "prediction": prediction,
            }
        )
        provider = str(getattr(result, "provider", "") or "").strip()
        model = str(getattr(result, "model", "") or "").strip()
        if provider:
            providers.add(provider)
        if model:
            models.add(model)
        result_usage = getattr(result, "usage", None)
        if result_usage is not None:
            usage["input_tokens"] += int(getattr(result_usage, "input_tokens", 0) or 0)
            usage["output_tokens"] += int(getattr(result_usage, "output_tokens", 0) or 0)
            usage["total_tokens"] += int(getattr(result_usage, "total_tokens", 0) or 0)
            cost = getattr(result_usage, "cost_usd", None)
            if cost is not None:
                usage["cost_usd"] += float(cost)

    predictions_path = evaluation_root / "evaluation-predictions.jsonl"
    _write_jsonl_atomic(predictions_path, predictions)

    try:
        score_report = score_latest_evaluation(Path(datasets_root))
    except EvaluationRunError as exc:
        raise BaselineEvaluationError(f"Deterministic scoring failed: {exc}") from exc

    return {
        "ok": bool(score_report.get("ok")),
        "stage": score_report.get("stage"),
        "cases": len(predictions),
        "providers": sorted(providers),
        "models": sorted(models),
        "usage": {
            **usage,
            "cost_usd": round(float(usage["cost_usd"]), 6),
        },
        "score_report": score_report,
        "safety": {
            "ground_truth_visible_to_model": False,
            "odoo_mutations": False,
            "auto_post": False,
            "human_review_required": True,
        },
    }


def build_host_llm() -> StructuredLlmPort:
    """Construct the same host-owned LLM facade used by PluginContext.llm."""

    from agent.plugin_llm import PluginLlm

    return PluginLlm(plugin_id="accounting-brain")


def _latest_evaluation_root(datasets_root: Path) -> Path:
    root = datasets_root.expanduser().resolve()
    if not root.exists():
        raise BaselineEvaluationError("No Accounting Brain dataset directory exists")
    candidates = sorted(
        path / "evaluation"
        for path in root.iterdir()
        if path.is_dir()
        and path.name.startswith("golden-")
        and (path / "evaluation" / "evaluation-manifest.json").is_file()
    )
    if not candidates:
        raise BaselineEvaluationError("No prepared Accounting Brain evaluation exists")
    return candidates[-1]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineEvaluationError(f"Cannot read {path.name}") from exc
    if not isinstance(value, dict):
        raise BaselineEvaluationError(f"Invalid object in {path.name}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BaselineEvaluationError(f"Cannot read {path.name}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BaselineEvaluationError(
                f"Invalid JSONL in {path.name} line {line_number}"
            ) from exc
        if not isinstance(value, dict):
            raise BaselineEvaluationError(
                f"Invalid JSON object in {path.name} line {line_number}"
            )
        rows.append(value)
    return rows


def _write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
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
