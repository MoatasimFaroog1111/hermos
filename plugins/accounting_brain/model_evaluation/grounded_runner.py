"""Leakage-safe grounded Accounting Brain evaluation.

Inference reads only the current holdout source evidence and the non-holdout
Gold reference pool. It derives deterministic GITC company memory, retrieves
similar historical examples, fixes predictions to disk, and only then hands the
run to the existing trusted scorer. The scorer remains the sole component that
opens holdout ground truth and the sole source of the production-gate result.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from plugins.accounting_brain.model_evaluation.baseline_runner import (
    PREDICTION_SCHEMA,
    StructuredLlmPort,
    _is_unsupported_json_schema_response_format,
    _latest_evaluation_root,
    _load_json,
    _load_jsonl,
    _prediction_schema_violation,
    _repair_prediction_once,
    _validate_prediction_schema,
    _write_jsonl_atomic,
)
from plugins.accounting_brain.model_evaluation.company_memory import (
    CompanyMemoryError,
    build_memory_hints,
    derive_company_memory,
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


class GroundedEvaluationError(RuntimeError):
    """Raised when grounded evaluation cannot complete safely."""


ProgressCallback = Callable[[dict[str, Any]], None]

_GROUNDED_INSTRUCTIONS = """You are the Accounting Brain inside Hermes.
Infer the complete Odoo journal entry represented by the CURRENT SOURCE DOCUMENT.

You receive two kinds of company-specific evidence, both derived only from
EARLIER validated Gold history that is outside the holdout:
1. GITC ACCOUNTING MEMORY: exact Odoo entity IDs, chart-of-account conventions,
   journal/move-type relationships, currencies, taxes, debit/credit direction
   priors, partner prevalence and analytic patterns.
2. RETRIEVED HISTORICAL EXAMPLES: similar earlier postings with their validated
   Odoo targets.

Use that evidence to choose exact GITC account codes/IDs, journal IDs, partner
IDs when supported by the current document, currency IDs, tax IDs and analytic
conventions. Preserve an Odoo ID only when the evidence supports the same entity.
Never copy a monetary amount from historical evidence. Every debit/credit amount
must be independently supported by the CURRENT SOURCE DOCUMENT. Do not invent an
unsupported amount. The entry must balance exactly.

Return only the requested JSON structure. Use two-decimal debit/credit values.
This is a draft-only evaluation: do not call tools, access Odoo, post, reconcile,
pay, delete, or modify any accounting record. Human review remains required.
"""


def run_grounded_evaluation(
    datasets_root: Path,
    llm: StructuredLlmPort,
    *,
    top_k: int = 5,
    timeout_seconds: float = 120.0,
    max_tokens: int = 1800,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run every holdout case with GITC memory + leakage-safe Gold retrieval."""
    started = time.monotonic()
    evaluation_root = _latest_evaluation_root(Path(datasets_root))
    manifest = _load_json(evaluation_root / "evaluation-manifest.json")
    if manifest.get("ok") is not True or manifest.get("stage") != "EVALUATION_DATA_READY":
        raise GroundedEvaluationError(
            "Prepare leakage-safe evaluation evidence before grounded evaluation"
        )

    contract_version = str(manifest.get("contract_version") or "")
    input_rows = _load_jsonl(evaluation_root / "evaluation-inputs.jsonl")
    reference_rows = _load_jsonl(evaluation_root / "evaluation-reference.jsonl")
    if not input_rows:
        raise GroundedEvaluationError("Prepared evaluation contains no model inputs")
    if not reference_rows:
        raise GroundedEvaluationError(
            "Prepare the leakage-safe historical reference pool before grounded evaluation"
        )

    try:
        memory = derive_company_memory(reference_rows)
    except CompanyMemoryError as exc:
        raise GroundedEvaluationError(f"Cannot derive GITC company memory: {exc}") from exc

    memory_hints = build_memory_hints(memory)
    dataset_root = evaluation_root.parent
    predictions: list[dict[str, Any]] = []
    retrieval_counts: list[int] = []
    repairs_attempted = 0
    json_schema_fallbacks = 0
    providers: set[str] = set()
    models: set[str] = set()
    usage: dict[str, float | int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }

    _emit_progress(
        progress_callback,
        phase="initialized",
        total_cases=len(input_rows),
        completed_cases=0,
        current_case=None,
        reference_cases=len(reference_rows),
        memory_accounts=len(memory.account_catalog),
        elapsed_seconds=0.0,
        repairs_attempted=0,
        json_schema_fallbacks=0,
    )

    for row in input_rows:
        case_started = time.monotonic()
        case_id = str(row.get("case_id") or "").strip()
        if not case_id:
            raise GroundedEvaluationError("Evaluation input contains no case_id")
        if str(row.get("contract_version") or "") != contract_version:
            raise GroundedEvaluationError(f"Contract mismatch for case {case_id}")
        source = row.get("source")
        if not isinstance(source, dict):
            raise GroundedEvaluationError(f"Missing source for case {case_id}")

        _emit_progress(
            progress_callback,
            phase="case_started",
            total_cases=len(input_rows),
            completed_cases=len(predictions),
            current_case=case_id,
            elapsed_seconds=round(time.monotonic() - started, 3),
            repairs_attempted=repairs_attempted,
            json_schema_fallbacks=json_schema_fallbacks,
        )

        try:
            current_blocks = build_model_inputs(source, dataset_root=dataset_root)
            examples = retrieve_historical_examples(
                source,
                reference_rows,
                dataset_root=dataset_root,
                top_k=max(1, min(10, int(top_k))),
            )
        except (SourceMaterialError, RetrievalError) as exc:
            raise GroundedEvaluationError(
                f"Grounded source preparation failed for {case_id}: {exc}"
            ) from exc

        retrieval_counts.append(len(examples))
        evidence_blocks = [
            {
                "type": "text",
                "text": "GITC ACCOUNTING MEMORY:\n" + memory_hints,
            },
            {
                "type": "text",
                "text": (
                    "RETRIEVED EARLIER GOLD EXAMPLES "
                    "(not current holdout ground truth):\n"
                    + json.dumps(examples, ensure_ascii=False, sort_keys=True)
                ),
            },
        ]

        model_call_started = time.monotonic()
        try:
            result, fallback_used = _complete_grounded_prediction(
                llm,
                model_inputs=[*current_blocks, *evidence_blocks],
                timeout_seconds=timeout_seconds,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            raise GroundedEvaluationError(
                f"Host model inference failed for case {case_id}: {type(exc).__name__}"
            ) from exc
        last_model_call_duration = round(time.monotonic() - model_call_started, 3)
        if fallback_used:
            json_schema_fallbacks += 1

        result_chain = [result]
        prediction = getattr(result, "parsed", None)
        if not isinstance(prediction, dict):
            raise GroundedEvaluationError(
                f"Host model returned invalid structured JSON for case {case_id}"
            )

        violation = _prediction_schema_violation(prediction)
        if violation is not None:
            repairs_attempted += 1
            _emit_progress(
                progress_callback,
                phase="schema_repair",
                total_cases=len(input_rows),
                completed_cases=len(predictions),
                current_case=case_id,
                validation_error=violation,
                elapsed_seconds=round(time.monotonic() - started, 3),
                repairs_attempted=repairs_attempted,
                json_schema_fallbacks=json_schema_fallbacks,
            )
            repair_started = time.monotonic()
            try:
                repair_result = _repair_prediction_once(
                    llm,
                    prediction=prediction,
                    validation_error=violation,
                    timeout_seconds=timeout_seconds,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                raise GroundedEvaluationError(
                    f"Host model schema repair failed for case {case_id}: "
                    f"{type(exc).__name__}"
                ) from exc
            last_model_call_duration = round(time.monotonic() - repair_started, 3)
            result_chain.append(repair_result)
            repaired = getattr(repair_result, "parsed", None)
            if not isinstance(repaired, dict):
                raise GroundedEvaluationError(
                    f"Schema repair returned invalid JSON for case {case_id}"
                )
            prediction = repaired

        try:
            _validate_prediction_schema(prediction, case_id=case_id)
        except Exception as exc:
            raise GroundedEvaluationError(str(exc)) from exc

        predictions.append(
            {
                "contract_version": contract_version,
                "case_id": case_id,
                "prediction": prediction,
                "retrieval": {
                    "reference_ids": [item.get("reference_id") for item in examples],
                    "reference_count": len(examples),
                },
                "grounding": {
                    "company_memory": True,
                    "memory_reference_cases": len(reference_rows),
                },
            }
        )

        for call_result in result_chain:
            _accumulate_usage(usage, call_result)
            provider = str(getattr(call_result, "provider", "") or "").strip()
            model = str(getattr(call_result, "model", "") or "").strip()
            if provider:
                providers.add(provider)
            if model:
                models.add(model)

        _emit_progress(
            progress_callback,
            phase="case_completed",
            total_cases=len(input_rows),
            completed_cases=len(predictions),
            current_case=case_id,
            reference_count=len(examples),
            elapsed_seconds=round(time.monotonic() - started, 3),
            case_duration_seconds=round(time.monotonic() - case_started, 3),
            last_model_call_duration_seconds=last_model_call_duration,
            repairs_attempted=repairs_attempted,
            json_schema_fallbacks=json_schema_fallbacks,
            providers=sorted(providers),
            models=sorted(models),
            total_tokens=int(usage["total_tokens"]),
            cost_usd=round(float(usage["cost_usd"]), 6),
        )

    # This exact filename is the trusted scorer contract. Predictions are fixed
    # before score_latest_evaluation is invoked; inference never opens truth.
    _write_jsonl_atomic(
        evaluation_root / "evaluation-predictions.jsonl",
        predictions,
    )

    _emit_progress(
        progress_callback,
        phase="scoring",
        total_cases=len(input_rows),
        completed_cases=len(predictions),
        current_case=None,
        elapsed_seconds=round(time.monotonic() - started, 3),
        repairs_attempted=repairs_attempted,
        json_schema_fallbacks=json_schema_fallbacks,
    )

    try:
        score_report = score_latest_evaluation(Path(datasets_root))
    except EvaluationRunError as exc:
        raise GroundedEvaluationError(f"Deterministic scoring failed: {exc}") from exc

    _emit_progress(
        progress_callback,
        phase="completed",
        total_cases=len(input_rows),
        completed_cases=len(predictions),
        current_case=None,
        stage=score_report.get("stage"),
        ok=bool(score_report.get("ok")),
        elapsed_seconds=round(time.monotonic() - started, 3),
        repairs_attempted=repairs_attempted,
        json_schema_fallbacks=json_schema_fallbacks,
    )

    return {
        "ok": bool(score_report.get("ok")),
        "stage": score_report.get("stage"),
        "mode": "gitc_company_memory_retrieval",
        "cases": len(predictions),
        "reference_cases": len(reference_rows),
        "memory": {
            "accounts": len(memory.account_catalog),
            "journals": len(memory.journal_catalog),
            "currencies": len(memory.currency_catalog),
            "taxes": len(memory.tax_catalog),
            "partners": len(memory.partner_catalog),
        },
        "retrieval": {
            "top_k": max(1, min(10, int(top_k))),
            "average_references": round(
                sum(retrieval_counts) / len(retrieval_counts), 4
            )
            if retrieval_counts
            else 0.0,
        },
        "repairs_attempted": repairs_attempted,
        "json_schema_fallbacks": json_schema_fallbacks,
        "providers": sorted(providers),
        "models": sorted(models),
        "usage": {
            "input_tokens": int(usage["input_tokens"]),
            "output_tokens": int(usage["output_tokens"]),
            "total_tokens": int(usage["total_tokens"]),
            "cost_usd": round(float(usage["cost_usd"]), 6),
        },
        "score_report": score_report,
        "production_gate": score_report.get("production_gate"),
        "safety": {
            "holdout_ground_truth_visible_to_model": False,
            "reference_pool_is_non_holdout_history": True,
            "company_memory_is_non_holdout_history": True,
            "predictions_fixed_before_scoring": True,
            "odoo_mutations": False,
            "auto_post": False,
            "human_review_required": True,
        },
    }


def _complete_grounded_prediction(
    llm: StructuredLlmPort,
    *,
    model_inputs: list[dict[str, Any]],
    timeout_seconds: float,
    max_tokens: int,
) -> tuple[Any, bool]:
    common = {
        "input": model_inputs,
        "json_mode": True,
        "schema_name": "odoo_journal_prediction_v1",
        "temperature": 0.0,
        "max_tokens": max(256, min(4096, int(max_tokens))),
        "timeout": max(15.0, min(300.0, float(timeout_seconds))),
        "purpose": "accounting_grounded_evaluation",
    }
    try:
        return (
            llm.complete_structured(
                instructions=_GROUNDED_INSTRUCTIONS,
                json_schema=PREDICTION_SCHEMA,
                **common,
            ),
            False,
        )
    except Exception as exc:
        if not _is_unsupported_json_schema_response_format(exc):
            raise

    schema_text = json.dumps(PREDICTION_SCHEMA, ensure_ascii=False, sort_keys=True)
    fallback_instructions = (
        f"{_GROUNDED_INSTRUCTIONS}\n\n"
        "Return one JSON object matching this schema exactly.\n"
        f"JSON schema:\n{schema_text}"
    )
    return (
        llm.complete_structured(
            instructions=fallback_instructions,
            json_schema=None,
            **common,
        ),
        True,
    )


def _accumulate_usage(usage: dict[str, float | int], result: Any) -> None:
    result_usage = getattr(result, "usage", None)
    if result_usage is None:
        return
    usage["input_tokens"] = int(usage["input_tokens"]) + int(
        getattr(result_usage, "input_tokens", 0) or 0
    )
    usage["output_tokens"] = int(usage["output_tokens"]) + int(
        getattr(result_usage, "output_tokens", 0) or 0
    )
    usage["total_tokens"] = int(usage["total_tokens"]) + int(
        getattr(result_usage, "total_tokens", 0) or 0
    )
    cost = getattr(result_usage, "cost_usd", None)
    if cost is not None:
        usage["cost_usd"] = float(usage["cost_usd"]) + float(cost)


def _emit_progress(callback: ProgressCallback | None, **progress: Any) -> None:
    if callback is None:
        return
    try:
        callback(dict(progress))
    except Exception:
        # Telemetry must never be able to alter accounting evaluation behavior.
        return
