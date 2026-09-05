"""Run a leakage-safe Accounting Brain baseline against the prepared holdout.

The model receives only hydrated source evidence plus historical analogues from
THE REFERENCE POOL. Holdout ground truth is opened exclusively inside this use
case after inference so the deterministic scorer can grade the prediction.

This module owns no provider SDK and performs no Odoo calls. Inference and
image interpretation sit behind :class:`BaselineInferencePort`; the production
adapter lives at the edge in ``hermes_inference.py``.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from plugins.accounting_brain.model_evaluation.scoring import (
    aggregate_evaluation_scores,
    score_journal_prediction,
)

BASELINE_CONTRACT_VERSION = "1.0"
_IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
_TEXT_MIMES = frozenset({"text/plain", "text/csv"})
_PDF_MIME = "application/pdf"
_XLS_MIMES = frozenset(
    {
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_MAX_TEXT_PER_ATTACHMENT = 12_000
_MAX_TEXT_PER_CASE = 28_000
_MAX_ANALOGUE_TARGET_CHARS = 18_000


class BaselineEvaluationError(RuntimeError):
    """Raised when a prepared evaluation set cannot be benchmarked safely."""


class BaselineInferencePort(Protocol):
    """Provider-neutral inference boundary used by the evaluation use case."""

    def safe_identity(self) -> dict[str, Any]:
        """Return non-secret model/provider identity for the audit report."""

    def describe_image(self, image_path: Path) -> str:
        """Return source-only accounting evidence extracted from one image."""

    def predict_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Return a strict JSON journal prediction from source evidence."""


@dataclass(frozen=True)
class EvidenceBundle:
    text: str
    usable: bool
    attachment_statuses: tuple[str, ...]
    consumed_mimetypes: tuple[str, ...]
    unsupported_mimetypes: tuple[str, ...]


def run_baseline_evaluation(
    inference: BaselineInferencePort,
    datasets_root: Path,
    *,
    max_cases: int = 10,
    top_k: int = 3,
    min_consumable_coverage: float = 0.90,
) -> dict[str, Any]:
    """Run a bounded, auditable baseline without training or Odoo writes.

    ``max_cases`` deliberately defaults to ten because the first production run
    may use a paid inference provider. Cases are sampled evenly across the
    chronological holdout rather than taking an easy prefix. Every selected
    case is included in the aggregate score; unsupported evidence and inference
    failures score as failures instead of disappearing from the denominator.
    """
    if not 1 <= int(max_cases) <= 500:
        raise BaselineEvaluationError("max_cases must be between 1 and 500")
    if not 1 <= int(top_k) <= 10:
        raise BaselineEvaluationError("top_k must be between 1 and 10")
    if not 0.50 <= float(min_consumable_coverage) <= 1.0:
        raise BaselineEvaluationError(
            "min_consumable_coverage must be between 0.50 and 1.00"
        )

    dataset_root = _latest_ready_dataset(Path(datasets_root))
    evaluation_root = dataset_root / "evaluation"
    inputs = _load_jsonl(evaluation_root / "evaluation-inputs.jsonl")
    truths = _load_jsonl(evaluation_root / "evaluation-ground-truth.jsonl")
    pairs = _load_jsonl(dataset_root / "pairs.jsonl")

    if not inputs or not truths:
        raise BaselineEvaluationError("Prepared evaluation input or ground truth is empty")

    input_by_case = _unique_by_case(inputs, "evaluation inputs")
    truth_by_case = _unique_by_case(truths, "evaluation ground truth")
    if set(input_by_case) != set(truth_by_case):
        raise BaselineEvaluationError(
            "Evaluation inputs and ground truth do not contain the same case IDs"
        )

    selected_case_ids = _evenly_spaced_cases(list(input_by_case), int(max_cases))
    holdout_move_ids = _holdout_move_ids(truth_by_case)
    reference_pairs = [
        pair
        for pair in pairs
        if _safe_int(pair.get("source_move_id")) not in holdout_move_ids
        and str(pair.get("grade") or "") == "gold"
    ]
    if not reference_pairs:
        raise BaselineEvaluationError("The historical reference pool is empty")

    model_identity = inference.safe_identity()
    scores: list[dict[str, Any]] = []
    private_results: list[dict[str, Any]] = []
    consumable_cases = 0
    prediction_successes = 0
    parse_or_inference_failures = 0
    attachment_statuses: Counter[str] = Counter()
    consumed_mimetypes: Counter[str] = Counter()
    unsupported_mimetypes: Counter[str] = Counter()

    for case_id in selected_case_ids:
        source_row = input_by_case[case_id]
        # IMPORTANT: truth is intentionally not passed into evidence extraction,
        # retrieval, prompt construction, or inference. It is read only after
        # the prediction has already been produced.
        bundle = _prepare_source_evidence(
            dataset_root,
            source_row,
            inference,
        )
        attachment_statuses.update(bundle.attachment_statuses)
        consumed_mimetypes.update(bundle.consumed_mimetypes)
        unsupported_mimetypes.update(bundle.unsupported_mimetypes)

        prediction: dict[str, Any] = {}
        failure: str | None = None
        analogue_summaries: list[dict[str, Any]] = []
        if bundle.usable:
            consumable_cases += 1
            analogues = _retrieve_reference_analogues(
                bundle.text,
                reference_pairs,
                top_k=int(top_k),
            )
            analogue_summaries = [
                {
                    "source_move_id": _safe_int(pair.get("source_move_id")),
                    "similarity_score": score,
                }
                for score, pair in analogues
            ]
            try:
                prediction = inference.predict_json(
                    system_prompt=_prediction_system_prompt(),
                    user_prompt=_prediction_user_prompt(bundle.text, analogues),
                )
                if not isinstance(prediction, dict):
                    raise BaselineEvaluationError("Model prediction was not a JSON object")
                prediction_successes += 1
            except Exception as exc:  # noqa: BLE001 - case failure belongs in benchmark denominator
                parse_or_inference_failures += 1
                failure = _safe_error(exc)
                prediction = {}
        else:
            failure = "No model-consumable source evidence was available for this case"

        expected = truth_by_case[case_id].get("target")
        if not isinstance(expected, dict):
            raise BaselineEvaluationError(
                f"Ground truth target is invalid for evaluation case {case_id}"
            )
        score = score_journal_prediction(expected, prediction)
        scores.append(score)
        private_results.append(
            {
                "contract_version": BASELINE_CONTRACT_VERSION,
                "case_id": case_id,
                "prediction": prediction,
                "score": score,
                "failure": failure,
                "retrieved_reference_cases": analogue_summaries,
            }
        )

    selected_count = len(selected_case_ids)
    consumable_coverage = consumable_cases / selected_count if selected_count else 0.0
    coverage_passed = consumable_coverage >= float(min_consumable_coverage)
    aggregate = aggregate_evaluation_scores(scores)
    mode = "full" if selected_count >= len(input_by_case) else "smoke"

    predictions_path = evaluation_root / (
        "baseline-full-results.jsonl" if mode == "full" else "baseline-smoke-results.jsonl"
    )
    _write_jsonl_atomic(predictions_path, private_results)

    if not coverage_passed:
        stage = "BLOCKED_BY_MODALITY_COVERAGE"
        next_action = "ADD_OR_ENABLE_SOURCE_EXTRACTORS"
        ok = False
    elif prediction_successes == 0:
        stage = "BLOCKED_BY_MODEL_CONFIGURATION"
        next_action = "FIX_HERMES_MODEL_CONFIGURATION"
        ok = False
    elif mode == "full":
        stage = "BASELINE_FULL_COMPLETE"
        next_action = "MODEL_EVALUATION_REVIEW_REQUIRED"
        ok = True
    else:
        stage = "BASELINE_SMOKE_COMPLETE"
        next_action = "REVIEW_SMOKE_THEN_RUN_FULL_HOLDOUT"
        ok = True

    return {
        "ok": ok,
        "stage": stage,
        "next_action": next_action,
        "contract_version": BASELINE_CONTRACT_VERSION,
        "evaluation_mode": mode,
        "model": model_identity,
        "selected_cases": selected_count,
        "total_holdout_cases": len(input_by_case),
        "reference_pool_cases": len(reference_pairs),
        "retrieval_top_k": int(top_k),
        "inference": {
            "consumable_cases": consumable_cases,
            "prediction_successes": prediction_successes,
            "parse_or_inference_failures": parse_or_inference_failures,
        },
        "source_evidence": {
            "consumable_coverage": round(consumable_coverage, 4),
            "required_coverage": float(min_consumable_coverage),
            "attachment_statuses": dict(sorted(attachment_statuses.items())),
            "consumed_mimetypes": dict(sorted(consumed_mimetypes.items())),
            "unsupported_mimetypes": dict(sorted(unsupported_mimetypes.items())),
        },
        "scores": aggregate,
        "artifacts": {
            "private_results_file": predictions_path.name,
            "evaluation_directory": evaluation_root.name,
        },
        "leakage_controls": {
            "holdout_ground_truth_never_passed_to_model": True,
            "retrieval_pool_excludes_all_holdout_move_ids": True,
            "retrieval_uses_reference_history_only": True,
            "deterministic_scorer_runs_after_inference": True,
            "unsupported_cases_remain_in_score_denominator": True,
        },
        "safety": {
            "odoo_mutations": False,
            "training_performed": False,
            "model_training_enabled": False,
            "auto_post": False,
            "human_review_required": True,
            "secrets_exposed": False,
        },
    }


def _latest_ready_dataset(datasets_root: Path) -> Path:
    root = datasets_root.expanduser().resolve()
    if not root.exists():
        raise BaselineEvaluationError("No Accounting Brain dataset directory exists")
    candidates = sorted(
        path
        for path in root.iterdir()
        if path.is_dir()
        and path.name.startswith("golden-")
        and (path / "evaluation" / "evaluation-manifest.json").is_file()
    )
    if not candidates:
        raise BaselineEvaluationError("No prepared model-evaluation dataset was found")
    candidate = candidates[-1]
    try:
        manifest = json.loads(
            (candidate / "evaluation" / "evaluation-manifest.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineEvaluationError(f"Could not read evaluation manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("stage") != "EVALUATION_DATA_READY":
        raise BaselineEvaluationError(
            "The newest evaluation manifest has not passed EVALUATION_DATA_READY"
        )
    return candidate


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
                    raise BaselineEvaluationError(
                        f"Invalid JSON object in {path.name} line {line_number}"
                    )
                rows.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineEvaluationError(f"Could not read {path.name}: {exc}") from exc
    return rows


def _unique_by_case(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id") or "").strip()
        if not case_id:
            raise BaselineEvaluationError(f"Missing case_id in {label}")
        if case_id in result:
            raise BaselineEvaluationError(f"Duplicate case_id {case_id} in {label}")
        result[case_id] = row
    return result


def _evenly_spaced_cases(case_ids: list[str], limit: int) -> list[str]:
    if limit >= len(case_ids):
        return list(case_ids)
    if limit <= 1:
        return [case_ids[len(case_ids) // 2]]
    indexes = {
        min(len(case_ids) - 1, round(index * (len(case_ids) - 1) / (limit - 1)))
        for index in range(limit)
    }
    selected = [case_ids[index] for index in sorted(indexes)]
    # Rounding can theoretically collapse adjacent indexes on very small input.
    if len(selected) < limit:
        for case_id in case_ids:
            if case_id not in selected:
                selected.append(case_id)
            if len(selected) == limit:
                break
    return selected[:limit]


def _holdout_move_ids(truth_by_case: dict[str, dict[str, Any]]) -> set[int]:
    ids: set[int] = set()
    for row in truth_by_case.values():
        evidence = row.get("evidence") if isinstance(row, dict) else None
        raw = evidence.get("source_move_id") if isinstance(evidence, dict) else None
        value = _safe_int(raw)
        if value is not None:
            ids.add(value)
    return ids


def _prepare_source_evidence(
    dataset_root: Path,
    source_row: dict[str, Any],
    inference: BaselineInferencePort,
) -> EvidenceBundle:
    source = source_row.get("source")
    attachments = source.get("attachments") if isinstance(source, dict) else None
    if not isinstance(attachments, list):
        attachments = []

    pieces: list[str] = []
    statuses: list[str] = []
    consumed: list[str] = []
    unsupported: list[str] = []
    remaining = _MAX_TEXT_PER_CASE

    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        status = str(attachment.get("content_status") or "unknown")
        statuses.append(status)
        mime = str(attachment.get("mimetype") or "unknown").strip().lower()
        if status != "downloaded":
            unsupported.append(mime)
            continue
        local_path = attachment.get("local_path")
        if not local_path:
            unsupported.append(mime)
            continue
        path = _safe_dataset_path(dataset_root, str(local_path))
        if path is None or not path.is_file():
            unsupported.append(mime)
            continue

        extracted: str | None = None
        try:
            if mime in _IMAGE_MIMES:
                extracted = inference.describe_image(path)
            elif mime in _TEXT_MIMES:
                extracted = _read_text_file(path)
            elif mime == _PDF_MIME:
                extracted = _extract_pdf_text(path)
            elif mime in _XLS_MIMES:
                extracted = _extract_spreadsheet_text(path)
            elif mime == _DOCX_MIME:
                extracted = _extract_docx_text(path)
        except Exception:  # noqa: BLE001 - extraction failure is recorded as unsupported evidence
            extracted = None

        if not extracted or not extracted.strip():
            unsupported.append(mime)
            continue
        consumed.append(mime)
        filename = str(attachment.get("filename") or path.name)
        piece = f"SOURCE FILE: {filename}\nMIME: {mime}\n{extracted.strip()}"
        piece = piece[: min(_MAX_TEXT_PER_ATTACHMENT, remaining)]
        if piece:
            pieces.append(piece)
            remaining -= len(piece)
        if remaining <= 0:
            break

    text = "\n\n----- SOURCE EVIDENCE -----\n\n".join(pieces).strip()
    return EvidenceBundle(
        text=text,
        usable=bool(text),
        attachment_statuses=tuple(statuses),
        consumed_mimetypes=tuple(consumed),
        unsupported_mimetypes=tuple(unsupported),
    )


def _safe_dataset_path(dataset_root: Path, relative_path: str) -> Path | None:
    raw = Path(relative_path)
    if raw.is_absolute():
        return None
    root = dataset_root.resolve()
    try:
        candidate = (root / raw).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()[: 4 * _MAX_TEXT_PER_ATTACHMENT]
    return raw.decode("utf-8", errors="replace")[:_MAX_TEXT_PER_ATTACHMENT]


def _extract_pdf_text(path: Path) -> str | None:
    # Prefer a Python library when it happens to be installed by another Hermes
    # capability, but never lazy-install dependencies during an evaluation run.
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]

        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:8])
        if text.strip():
            return text[:_MAX_TEXT_PER_ATTACHMENT]
    except Exception:
        pass

    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return None
    try:
        completed = subprocess.run(
            [pdftotext, "-layout", "-f", "1", "-l", "8", str(path), "-"],
            check=False,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="replace")[:_MAX_TEXT_PER_ATTACHMENT]


def _extract_spreadsheet_text(path: Path) -> str | None:
    try:
        import xlrd  # type: ignore[import-not-found]

        book = xlrd.open_workbook(str(path), on_demand=True)
        sheet = book.sheet_by_index(0)
        rows: list[str] = []
        for row_index in range(min(sheet.nrows, 200)):
            values = [str(sheet.cell_value(row_index, col)) for col in range(sheet.ncols)]
            rows.append("\t".join(values))
        return "\n".join(rows)[:_MAX_TEXT_PER_ATTACHMENT]
    except Exception:
        return None


def _extract_docx_text(path: Path) -> str | None:
    try:
        from docx import Document  # type: ignore[import-not-found]

        document = Document(str(path))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)[
            :_MAX_TEXT_PER_ATTACHMENT
        ]
    except Exception:
        return None


def _retrieve_reference_analogues(
    evidence_text: str,
    reference_pairs: list[dict[str, Any]],
    *,
    top_k: int,
) -> list[tuple[float, dict[str, Any]]]:
    normalized_evidence = _normalize_text(evidence_text)
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for pair in reference_pairs:
        document = pair.get("input", {}).get("document", {})
        if not isinstance(document, dict):
            document = {}
        score = 0.0
        score += 5.0 * _phrase_hit(normalized_evidence, _ref_name(document.get("partner")))
        score += 4.0 * _phrase_hit(normalized_evidence, document.get("reference"))
        score += 2.5 * _phrase_hit(normalized_evidence, document.get("invoice_origin"))
        score += 1.5 * _phrase_hit(normalized_evidence, _ref_name(document.get("currency")))
        for key in ("amount_total", "amount_tax", "amount_untaxed"):
            if _money_hit(evidence_text, document.get(key)):
                score += 3.0
        score += 2.0 * _token_overlap(
            normalized_evidence,
            _normalize_text(_ref_name(document.get("partner")) or ""),
        )
        move_id = _safe_int(pair.get("source_move_id")) or 0
        scored.append((score, move_id, pair))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [(round(score, 4), pair) for score, _move_id, pair in scored[:top_k]]


def _prediction_system_prompt() -> str:
    return (
        "You are the baseline accounting classifier inside Hermes Accounting Brain. "
        "This is an evaluation, not production posting. Use ONLY the supplied source "
        "evidence and the supplied REFERENCE-POOL historical analogues. Never invent "
        "an Odoo account, journal, tax, partner, company, or currency identifier that "
        "is not supported by those analogues. Preserve source monetary amounts exactly. "
        "Return exactly one JSON object and no markdown or explanation."
    )


def _prediction_user_prompt(
    evidence_text: str,
    analogues: list[tuple[float, dict[str, Any]]],
) -> str:
    safe_analogues: list[dict[str, Any]] = []
    for similarity, pair in analogues:
        document = pair.get("input", {}).get("document", {})
        target = pair.get("target", {})
        safe_analogues.append(
            {
                "similarity_score": similarity,
                "historical_source": {
                    "move_type": document.get("move_type") if isinstance(document, dict) else None,
                    "reference": document.get("reference") if isinstance(document, dict) else None,
                    "invoice_origin": document.get("invoice_origin") if isinstance(document, dict) else None,
                    "partner": document.get("partner") if isinstance(document, dict) else None,
                    "journal": document.get("journal") if isinstance(document, dict) else None,
                    "company": document.get("company") if isinstance(document, dict) else None,
                    "currency": document.get("currency") if isinstance(document, dict) else None,
                    "amount_untaxed": document.get("amount_untaxed") if isinstance(document, dict) else None,
                    "amount_tax": document.get("amount_tax") if isinstance(document, dict) else None,
                    "amount_total": document.get("amount_total") if isinstance(document, dict) else None,
                },
                "historical_posted_target": target,
            }
        )
    analogue_json = json.dumps(
        safe_analogues,
        ensure_ascii=False,
        sort_keys=True,
    )[:_MAX_ANALOGUE_TARGET_CHARS]

    return (
        "SOURCE EVIDENCE (current holdout document; no Odoo target fields):\n"
        f"{evidence_text}\n\n"
        "REFERENCE-POOL ANALOGUES (older, non-holdout posted history):\n"
        f"{analogue_json}\n\n"
        "Predict the historical-style journal target for the current source. "
        "Required JSON shape:\n"
        "{\n"
        '  "move_type": string|null,\n'
        '  "partner": {"id": integer|null, "name": string|null}|null,\n'
        '  "journal": {"id": integer|null, "name": string|null}|null,\n'
        '  "company": {"id": integer|null, "name": string|null}|null,\n'
        '  "currency": {"id": integer|null, "name": string|null}|null,\n'
        '  "taxes": [{"id": integer, "name": string|null}],\n'
        '  "journal_entry": [\n'
        "    {\n"
        '      "account_id": integer|null, "account_code": string|null,\n'
        '      "account_name": string|null, "partner_id": integer|null,\n'
        '      "partner_name": string|null, "label": string|null,\n'
        '      "debit": "0.00", "credit": "0.00", "balance": "0.00",\n'
        '      "amount_currency": string|null, "currency_id": integer|null,\n'
        '      "currency_name": string|null, "tax_ids": [integer],\n'
        '      "analytic_distribution": object|null\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "The journal entry must balance. Output JSON only."
    )


def _normalize_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^\w\d]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _ref_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    text = str(name).strip() if name not in (None, False, "") else ""
    return text or None


def _phrase_hit(normalized_evidence: str, value: Any) -> float:
    phrase = _normalize_text(value)
    if not phrase or len(phrase) < 2:
        return 0.0
    return 1.0 if phrase in normalized_evidence else 0.0


def _token_overlap(normalized_evidence: str, normalized_candidate: str) -> float:
    candidate_tokens = {token for token in normalized_candidate.split() if len(token) >= 3}
    if not candidate_tokens:
        return 0.0
    evidence_tokens = set(normalized_evidence.split())
    return len(candidate_tokens & evidence_tokens) / len(candidate_tokens)


def _money_hit(evidence_text: str, value: Any) -> bool:
    if value in (None, False, ""):
        return False
    raw = str(value).strip()
    if not raw:
        return False
    variants = {raw, raw.replace(",", "")}
    try:
        amount = float(raw.replace(",", ""))
        variants.update(
            {
                f"{amount:.2f}",
                f"{amount:,.2f}",
                f"{amount:g}",
            }
        )
    except ValueError:
        pass
    compact_evidence = evidence_text.replace(",", "")
    return any(
        variant and (variant in evidence_text or variant.replace(",", "") in compact_evidence)
        for variant in variants
    )


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, False, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    # Provider exceptions sometimes contain request bodies or headers. Reports
    # need an actionable category, not potentially sensitive diagnostic blobs.
    return re.sub(r"\s+", " ", text)[:300]


def _write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(temp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass
