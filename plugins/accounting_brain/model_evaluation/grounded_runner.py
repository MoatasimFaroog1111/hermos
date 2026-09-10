"""Grounded evaluation using company memory + retrieval + DeepSeek fallback.

Safety contract: Reads ONLY evaluation-inputs.jsonl and evaluation-reference.jsonl.
NEVER reads evaluation-ground-truth.jsonl during inference. Predictions are written
to disk before deterministic scorer is invoked on ground truth.

Flow:
1. Derive company_memory from reference pool (non-holdout only)
2. For each case: build current document context + retrieve examples + build hints
3. Call LLM with json_schema; fallback to json_object if schema unsupported
4. Apply one schema-only repair (structure, not logic)
5. Validate schema locally
6. Write prediction to disk
7. Call existing score_latest_evaluation (which opens ground truth)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from plugins.accounting_brain.model_evaluation.baseline_runner import (
    PREDICTION_SCHEMA,
    StructuredLlmPort,
    _latest_evaluation_root,
    _load_json,
    _load_jsonl,
    _write_jsonl_atomic,
)
from plugins.accounting_brain.model_evaluation.company_memory import (
    CompanyMemoryError,
    build_memory_hints,
    derive_company_memory,
)
from plugins.accounting_brain.model_evaluation.retrieval import (
    RetrievalError,
    retrieve_historical_examples,
)
from plugins.accounting_brain.model_evaluation.scoring import (
    aggregate_evaluation_scores,
    score_journal_prediction,
)
from plugins.accounting_brain.model_evaluation.source_material import (
    SourceMaterialError,
    build_model_inputs,
)


class GroundedEvaluationError(RuntimeError):
    """Raised when grounded evaluation fails."""


ProgressCallback = Callable[[dict[str, Any]], None]

_GROUNDED_INSTRUCTIONS = """You are the Accounting Brain inside Hermes.
Infer the complete Odoo journal entry from the CURRENT SOURCE DOCUMENT.

You have:
1. COMPANY MEMORY: Consensus patterns from historical Gold entries (no amounts).
2. HISTORICAL EXAMPLES: Retrieved similar past entries from Gold history (no
   amounts).

Use company memory and examples ONLY for:
- Identifying applicable journals, move types, and accounts for this company
- Understanding currency and tax conventions
- Recognizing partner relationships and analytic patterns
- Learning debit/credit direction conventions per account

CRITICAL: Never copy amounts from historical examples. Amounts come ONLY
from the current source document. The entry must balance exactly.

Return only the requested JSON. Use two-decimal debit/credit strings.
This is draft-only evaluation: do not call tools, access Odoo, post, or
modify records.
"""


class GroundedEvaluationTelemetry:
    """Track tokens, cost, repairs, and timing (equivalent to baseline runner)."""

    def __init__(self) -> None:
        self.total_cases = 0
        self.successful_cases = 0
        self.fallback_cases = 0
        self.repair_cases = 0
        self.error_cases = 0

        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cost_usd = 0.0

        self.retrieval_counts: list[int] = []
        self.start_time = time.time()
        self.end_time: float | None = None

    def record_case(
        self,
        success: bool,
        fallback: bool = False,
        repair: bool = False,
        error: bool = False,
        tokens: int = 0,
        cost: float = 0.0,
        retrieval_count: int = 0,
    ) -> None:
        """Record metrics for one case."""
        self.total_cases += 1
        if success:
            self.successful_cases += 1
        if fallback:
            self.fallback_cases += 1
        if repair:
            self.repair_cases += 1
        if error:
            self.error_cases += 1

        self.total_tokens += tokens
        self.cost_usd += cost
        self.input_tokens += tokens // 2 if tokens > 0 else 0
        self.output_tokens += tokens // 2 if tokens > 0 else 0
        self.retrieval_counts.append(retrieval_count)

    def finalize(self) -> dict[str, Any]:
        """Produce final telemetry report."""
        self.end_time = time.time()
        elapsed = self.end_time - self.start_time

        avg_retrieval = (
            sum(self.retrieval_counts) / len(self.retrieval_counts)
            if self.retrieval_counts
            else 0.0
        )

        return {
            "stage": "grounded_evaluation_complete",
            "ok": self.total_cases > 0,
            "total_cases": self.total_cases,
            "successful_cases": self.successful_cases,
            "success_rate": (
                round(self.successful_cases / self.total_cases, 4)
                if self.total_cases > 0
                else 0.0
            ),
            "fallback_cases": self.fallback_cases,
            "repair_cases": self.repair_cases,
            "error_cases": self.error_cases,
            "tokens": {
                "input": self.input_tokens,
                "output": self.output_tokens,
                "total": self.total_tokens,
            },
            "cost_usd": round(self.cost_usd, 4),
            "retrieval": {
                "avg_per_case": round(avg_retrieval, 2),
                "total_retrieved": sum(self.retrieval_counts),
            },
            "timing": {
                "elapsed_seconds": round(elapsed, 2),
                "cases_per_second": (
                    round(self.total_cases / elapsed, 2) if elapsed > 0 else 0.0
                ),
            },
        }


def run_grounded_evaluation(
    datasets_root: Path,
    llm: StructuredLlmPort,
    *,
    top_k: int = 5,
    timeout_seconds: float = 120.0,
    max_tokens: int = 1800,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run grounded evaluation with company memory + retrieval.

    Args:
        datasets_root: Root of Accounting Brain datasets
        llm: Structured LLM compliant with StructuredLlmPort
        top_k: Number of historical examples to retrieve per case
        timeout_seconds: LLM call timeout
        max_tokens: Max response tokens
        progress_callback: Optional progress updates

    Returns:
        Telemetry and report

    Raises:
        GroundedEvaluationError: If evaluation cannot proceed safely
    """

    # Load ONLY inputs + reference (NEVER ground truth at this stage)
    evaluation_root = _latest_evaluation_root(Path(datasets_root))
    manifest = _load_json(evaluation_root / "evaluation-manifest.json")
    if (
        manifest.get("ok") is not True
        or manifest.get("stage") != "EVALUATION_DATA_READY"
    ):
        raise GroundedEvaluationError("Evaluation must be EVALUATION_DATA_READY")

    contract_version = str(manifest.get("contract_version") or "")
    dataset_root = evaluation_root.parent

    input_rows = _load_jsonl(evaluation_root / "evaluation-inputs.jsonl")
    reference_rows = _load_jsonl(evaluation_root / "evaluation-reference.jsonl")

    if not input_rows:
        raise GroundedEvaluationError("No model inputs")
    if not reference_rows:
        raise GroundedEvaluationError("No reference pool")

    # Derive company memory once from reference only
    try:
        memory = derive_company_memory(reference_rows)
    except CompanyMemoryError as exc:
        raise GroundedEvaluationError(f"Cannot derive memory: {exc}") from exc

    telemetry = GroundedEvaluationTelemetry()
    predictions: list[dict[str, Any]] = []
    memory_hint = build_memory_hints(memory)

    for row in input_rows:
        case_id = str(row.get("case_id") or "").strip()
        if not case_id:
            raise GroundedEvaluationError("No case_id in input")

        if str(row.get("contract_version") or "") != contract_version:
            raise GroundedEvaluationError(f"Contract mismatch: {case_id}")

        source = row.get("source")
        if not isinstance(source, dict):
            raise GroundedEvaluationError(f"No source for {case_id}")

        # Build current document context + retrieve historical examples
        try:
            current_blocks = build_model_inputs(
                source, dataset_root=dataset_root
            )
            examples = retrieve_historical_examples(
                source,
                reference_rows,
                dataset_root=dataset_root,
                top_k=top_k,
            )
        except (SourceMaterialError, RetrievalError) as exc:
            raise GroundedEvaluationError(
                f"Retrieval failed for {case_id}: {exc}"
            ) from exc

        # Construct LLM input
        memory_block = {
            "type": "text",
            "text": f"COMPANY MEMORY:\n{memory_hint}",
        }
        examples_block = {
            "type": "text",
            "text": (
                "HISTORICAL EXAMPLES:\n"
                + json.dumps(examples, ensure_ascii=False, sort_keys=True)
            ),
        }
        input_blocks = [*current_blocks, memory_block, examples_block]

        # Try json_schema first; fallback to json_object
        prediction = None
        fallback_used = False
        repair_needed = False
        error = False

        try:
            result = llm.complete_structured(
                instructions=_GROUNDED_INSTRUCTIONS,
                input=input_blocks,
                json_schema=PREDICTION_SCHEMA,
                json_mode=True,
                schema_name="odoo_journal_prediction_v1",
                temperature=0.0,
                max_tokens=max_tokens,
                timeout=timeout_seconds,
                purpose="accounting_grounded_evaluation",
            )
            prediction = getattr(result, "parsed", None)
        except Exception as exc:
            if "json_schema" in str(exc).lower():
                fallback_used = True
                try:
                    result = llm.complete_structured(
                        instructions=_GROUNDED_INSTRUCTIONS,
                        input=input_blocks,
                        json_mode=True,
                        temperature=0.0,
                        max_tokens=max_tokens,
                        timeout=timeout_seconds,
                        purpose="accounting_grounded_evaluation",
                    )
                    prediction = getattr(result, "parsed", None)
                except Exception as inner_exc:
                    error = True
                    raise GroundedEvaluationError(
                        f"Both json_schema and json_object failed for "
                        f"{case_id}: {type(inner_exc).__name__}"
                    ) from inner_exc
            else:
                error = True
                raise GroundedEvaluationError(
                    f"LLM inference failed for {case_id}: {type(exc).__name__}"
                ) from exc

        if not isinstance(prediction, dict):
            error = True
            raise GroundedEvaluationError(f"Invalid JSON for {case_id}")

        # Apply one schema-only repair (structure, not logic)
        prediction, repair_needed = _repair_schema_only(prediction)

        # Validate schema locally
        schema_valid = _validate_schema_locally(prediction)

        # Record telemetry
        usage = getattr(result, "usage", None)
        tokens = getattr(usage, "total_tokens", 0) if usage else 0
        cost = getattr(usage, "cost_usd", 0.0) if usage else 0.0

        telemetry.record_case(
            success=schema_valid and not error,
            fallback=fallback_used,
            repair=repair_needed,
            error=error,
            tokens=tokens,
            cost=cost,
            retrieval_count=len(examples),
        )

        predictions.append({
            "contract_version": contract_version,
            "case_id": case_id,
            "prediction": prediction,
            "retrieval": {
                "reference_count": len(examples),
                "reference_ids": [ex.get("reference_id") for ex in examples],
            },
            "grounded": {
                "fallback_used": fallback_used,
                "repair_applied": repair_needed,
                "schema_valid": schema_valid,
            },
        })

        if progress_callback:
            progress_callback({
                "case": case_id,
                "index": len(predictions),
                "total": len(input_rows),
            })

    # Write predictions to disk BEFORE calling deterministic scorer
    output_path = evaluation_root / "evaluation-grounded-predictions.jsonl"
    _write_jsonl_atomic(output_path, predictions)

    # Now call deterministic scorer (which opens ground truth)
    # Safe because ground truth was never used in inference
    scores: list[dict[str, Any]] = []
    truth_rows = _load_jsonl(evaluation_root / "evaluation-ground-truth.jsonl")
    truth_by_case = {row.get("case_id"): row for row in truth_rows}

    for pred in predictions:
        case_id = pred.get("case_id")
        truth_row = truth_by_case.get(case_id)
        if not truth_row:
            continue

        expected = truth_row.get("target", {})
        predicted = pred.get("prediction", {})
        score = score_journal_prediction(expected, predicted)
        score["case_id"] = case_id
        scores.append(score)

    score_summary = aggregate_evaluation_scores(scores)
    telemetry_report = telemetry.finalize()

    # Write grounded evaluation report
    report = {
        "ok": True,
        "stage": "grounded_evaluation_complete",
        "contract_version": contract_version,
        "company_memory": memory.to_dict(),
        "predictions_count": len(predictions),
        "scores_count": len(scores),
        "telemetry": telemetry_report,
        "scoring": score_summary,
        "artifact": output_path.name,
    }

    report_path = evaluation_root / "grounded-evaluation-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return report


def _repair_schema_only(
    prediction: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Apply one schema-only repair step (structure, not logic).

    - Ensures journal_entry is a list
    - Adds missing required fields with structural defaults
    - Converts numeric debit/credit to ".2f" strings

    Returns: (repaired_prediction, repair_was_needed)
    """
    repair_needed = False

    if not isinstance(prediction.get("journal_entry"), list):
        prediction["journal_entry"] = []
        repair_needed = True

    lines = prediction.get("journal_entry", [])
    for line in lines:
        if not isinstance(line, dict):
            continue

        # Ensure debit/credit exist and are strings
        for field in ["debit", "credit"]:
            value = line.get(field)
            if value is None:
                line[field] = "0.00"
                repair_needed = True
            elif not isinstance(value, str):
                try:
                    line[field] = f"{float(value):.2f}"
                    repair_needed = True
                except (ValueError, TypeError):
                    line[field] = "0.00"
                    repair_needed = True

        # Ensure tax_ids and analytic_distribution exist
        if not isinstance(line.get("tax_ids"), list):
            line["tax_ids"] = []
            repair_needed = True

        if not isinstance(line.get("analytic_distribution"), dict):
            line["analytic_distribution"] = {}
            repair_needed = True

    return prediction, repair_needed


def _validate_schema_locally(prediction: dict[str, Any]) -> bool:
    """Local schema validation without calling LLM.

    Returns: True if schema is valid, False otherwise.
    """
    if not isinstance(prediction, dict):
        return False

    required = [
        "move_type",
        "journal",
        "partner",
        "currency",
        "taxes",
        "journal_entry",
    ]
    if not all(field in prediction for field in required):
        return False

    lines = prediction.get("journal_entry")
    if not isinstance(lines, list) or len(lines) < 2:
        return False

    for line in lines:
        if not isinstance(line, dict):
            return False
        line_required = [
            "account_code",
            "debit",
            "credit",
            "tax_ids",
            "analytic_distribution",
        ]
        if not all(field in line for field in line_required):
            return False

    return True
