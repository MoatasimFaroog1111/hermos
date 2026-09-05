"""Evaluate retrieval-grounded Accounting Brain predictions.

The model sees the current source document plus a small set of *earlier,
non-holdout* historical posting examples. Holdout ground truth remains private
and is opened only by the deterministic scorer after predictions are fixed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from plugins.accounting_brain.model_evaluation.baseline_runner import (
    BaselineEvaluationError,
    PREDICTION_SCHEMA,
    StructuredLlmPort,
    _latest_evaluation_root,
    _load_json,
    _load_jsonl,
    _write_jsonl_atomic,
)
from plugins.accounting_brain.model_evaluation.evaluate import (
    EvaluationRunError,
    score_latest_evaluation,
)
from plugins.accounting_brain.model_evaluation.retrieval import (
    RetrievalError,
    retrieve_historical_examples,
)
from plugins.accounting_brain.model_evaluation.source_material import (
    SourceMaterialError,
    build_model_inputs,
)


_RETRIEVAL_INSTRUCTIONS = """You are the Accounting Brain inside Hermes.
Infer the complete Odoo journal entry represented by the CURRENT SOURCE DOCUMENT.
You are also given HISTORICAL ACCOUNTING EXAMPLES retrieved from earlier Gold
history. Use those examples only as evidence for company-specific chart of
accounts, journal, tax, partner and analytic conventions. Never copy an amount
from an example unless the current document independently supports that amount.
Return only the requested JSON. The entry must balance exactly. Use two-decimal
debit/credit values. This is draft-only evaluation: do not call tools, access
Odoo, post, reconcile, or modify records.
"""


def run_retrieval_evaluation(
    datasets_root: Path,
    llm: StructuredLlmPort,
    *,
    top_k: int = 5,
    timeout_seconds: float = 120.0,
    max_tokens: int = 1800,
) -> dict[str, Any]:
    """Run a historical-retrieval baseline over every prepared holdout case."""

    evaluation_root = _latest_evaluation_root(Path(datasets_root))
    manifest = _load_json(evaluation_root / "evaluation-manifest.json")
    if manifest.get("ok") is not True or manifest.get("stage") != "EVALUATION_DATA_READY":
        raise BaselineEvaluationError(
            "Prepare leakage-safe evaluation evidence before retrieval evaluation"
        )
    contract_version = str(manifest.get("contract_version") or "")
    input_rows = _load_jsonl(evaluation_root / "evaluation-inputs.jsonl")
    reference_rows = _load_jsonl(evaluation_root / "evaluation-reference.jsonl")
    if not input_rows:
        raise BaselineEvaluationError("Prepared evaluation contains no model inputs")
    if not reference_rows:
        raise BaselineEvaluationError(
            "Prepare the leakage-safe historical reference pool before retrieval evaluation"
        )

    dataset_root = evaluation_root.parent
    predictions: list[dict[str, Any]] = []
    providers: set[str] = set()
    models: set[str] = set()
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }
    retrieval_counts: list[int] = []

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
            current_blocks = build_model_inputs(source, dataset_root=dataset_root)
            examples = retrieve_historical_examples(
                source,
                reference_rows,
                dataset_root=dataset_root,
                top_k=top_k,
            )
        except (SourceMaterialError, RetrievalError) as exc:
            raise BaselineEvaluationError(
                f"Retrieval preparation failed for {case_id}: {exc}"
            ) from exc

        retrieval_counts.append(len(examples))
        evidence_block = {
            "type": "text",
            "text": (
                "HISTORICAL ACCOUNTING EXAMPLES (earlier Gold history; not current "
                "ground truth):\n"
                + json.dumps(examples, ensure_ascii=False, sort_keys=True)
            ),
        }
        try:
            result = llm.complete_structured(
                instructions=_RETRIEVAL_INSTRUCTIONS,
                input=[*current_blocks, evidence_block],
                json_schema=PREDICTION_SCHEMA,
                json_mode=True,
                schema_name="odoo_journal_prediction_v1",
                temperature=0.0,
                max_tokens=max_tokens,
                timeout=timeout_seconds,
                purpose="accounting_retrieval_evaluation",
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
                "retrieval": {
                    "reference_ids": [item.get("reference_id") for item in examples],
                    "reference_count": len(examples),
                },
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

    _write_jsonl_atomic(
        evaluation_root / "evaluation-predictions.jsonl",
        predictions,
    )
    try:
        score_report = score_latest_evaluation(Path(datasets_root))
    except EvaluationRunError as exc:
        raise BaselineEvaluationError(f"Deterministic scoring failed: {exc}") from exc

    return {
        "ok": bool(score_report.get("ok")),
        "stage": score_report.get("stage"),
        "mode": "historical_retrieval",
        "cases": len(predictions),
        "top_k": top_k,
        "average_references": round(
            sum(retrieval_counts) / len(retrieval_counts), 4
        )
        if retrieval_counts
        else 0.0,
        "providers": sorted(providers),
        "models": sorted(models),
        "usage": {
            **usage,
            "cost_usd": round(float(usage["cost_usd"]), 6),
        },
        "score_report": score_report,
        "safety": {
            "holdout_ground_truth_visible_to_model": False,
            "reference_pool_is_non_holdout_history": True,
            "odoo_mutations": False,
            "auto_post": False,
            "human_review_required": True,
        },
    }
