"""Prepare leakage-safe accounting model evaluation evidence.

This use case operates only on the private Golden Dataset under HERMES_HOME.
It may hydrate explicitly supported attachment bytes from Odoo through the
read-only port, but it never trains a model and never mutates Odoo.

The core safety rule is separation of model inputs from ground truth:
``evaluation-inputs.jsonl`` contains only source attachment evidence, while
``evaluation-ground-truth.jsonl`` contains the historical accounting target.
They are written as separate private files so a model runner cannot receive the
answer by accident.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from plugins.accounting_brain.journal_training.filesystem_dataset import (
    FilesystemTrainingDatasetSink,
)
from plugins.accounting_brain.journal_training.source_content import (
    is_supported_evidence_mimetype,
    normalize_mimetype,
)
from plugins.accounting_brain.odoo_discovery.contracts import OdooReadError, OdooReadPort

EVALUATION_CONTRACT_VERSION = "1.0"
_MODEL_INPUT_EXCLUDED_ODOO_FIELDS: tuple[str, ...] = (
    "source_move_id",
    "source_move_name",
    "document.move_type",
    "document.reference",
    "document.date",
    "document.invoice_date",
    "document.invoice_origin",
    "document.partner",
    "document.journal",
    "document.company",
    "document.currency",
    "document.amount_untaxed",
    "document.amount_tax",
    "document.amount_total",
    "target",
)


class EvaluationPreparationError(RuntimeError):
    """Raised when a private Golden Dataset cannot be prepared safely."""


def prepare_evaluation_evidence(
    reader: OdooReadPort,
    datasets_root: Path,
    *,
    hydrate_source_content: bool = False,
    max_attachment_bytes: int = 25 * 1024 * 1024,
    holdout_fraction: float = 0.20,
    min_holdout: int = 100,
    min_source_content_coverage: float = 0.90,
) -> dict[str, Any]:
    """Prepare the newest Gold dataset for model evaluation.

    The newest ``golden-*`` dataset is selected internally; callers cannot pass
    arbitrary filesystem paths. Gold pairs are sorted chronologically, the
    newest slice becomes holdout, and exact attachment checksums occurring in
    the reference pool are excluded from holdout to prevent trivial duplicate
    leakage.
    """
    root = _latest_golden_dataset(Path(datasets_root))
    pairs_path = root / "pairs.jsonl"
    pairs = _load_jsonl(pairs_path)
    if not pairs:
        raise EvaluationPreparationError("The latest Golden Dataset contains no pairs")

    non_gold = [row for row in pairs if str(row.get("grade")) != "gold"]
    if non_gold:
        raise EvaluationPreparationError(
            "Evaluation preparation accepts Gold-only datasets; Silver/Rejected rows were found"
        )

    company_ids = _company_ids(pairs)
    if len(company_ids) != 1:
        raise EvaluationPreparationError(
            "Evaluation dataset must contain exactly one Odoo company"
        )

    hydration_report = _existing_content_report(pairs)
    if hydrate_source_content:
        hydration_report = _hydrate_source_content(
            reader,
            root,
            pairs,
            max_attachment_bytes=max_attachment_bytes,
        )
        pairs = _load_jsonl(pairs_path)

    ordered = sorted(pairs, key=_chronology_key)
    requested_holdout = max(min_holdout, math.ceil(len(ordered) * holdout_fraction))
    holdout_size = max(0, min(len(ordered) - 1, requested_holdout))
    reference_pool = list(ordered[: len(ordered) - holdout_size])
    holdout_candidates = list(ordered[len(ordered) - holdout_size :])

    reference_checksums = _attachment_checksums(reference_pool)
    holdout: list[dict[str, Any]] = []
    duplicate_checksum_exclusions = 0
    for pair in holdout_candidates:
        pair_checksums = _attachment_checksums((pair,))
        if pair_checksums & reference_checksums:
            duplicate_checksum_exclusions += 1
            reference_pool.append(pair)
            reference_checksums.update(pair_checksums)
            continue
        holdout.append(pair)

    evaluation_root = root / "evaluation"
    evaluation_root.mkdir(parents=True, exist_ok=True)
    _chmod_private_dir(evaluation_root)
    inputs_path = evaluation_root / "evaluation-inputs.jsonl"
    truth_path = evaluation_root / "evaluation-ground-truth.jsonl"

    source_ready_cases = 0
    missing_date_cases = 0
    input_rows: list[dict[str, Any]] = []
    truth_rows: list[dict[str, Any]] = []
    for index, pair in enumerate(holdout, start=1):
        event_date = _pair_event_date(pair)
        if event_date is None:
            missing_date_cases += 1
        case_id = _case_id(pair, index)
        attachments = _safe_model_attachments(pair)
        if any(item.get("content_status") == "downloaded" for item in attachments):
            source_ready_cases += 1
        input_rows.append(
            {
                "contract_version": EVALUATION_CONTRACT_VERSION,
                "case_id": case_id,
                "source": {
                    "attachments": attachments,
                },
            }
        )
        truth_rows.append(
            {
                "contract_version": EVALUATION_CONTRACT_VERSION,
                "case_id": case_id,
                "evidence": {
                    "source_move_id": pair.get("source_move_id"),
                    "source_move_name": pair.get("source_move_name"),
                    "event_date": event_date.isoformat() if event_date else None,
                },
                "target": pair.get("target") or {},
            }
        )

    _write_jsonl_atomic(inputs_path, input_rows)
    _write_jsonl_atomic(truth_path, truth_rows)

    holdout_count = len(holdout)
    content_coverage = (
        source_ready_cases / holdout_count if holdout_count else 0.0
    )
    holdout_gate = holdout_count >= min_holdout
    content_gate = content_coverage >= min_source_content_coverage

    gates: dict[str, Any] = {
        "gold_only": True,
        "single_company_scope": True,
        "temporal_holdout": {
            "pass": holdout_gate,
            "holdout_cases": holdout_count,
            "minimum_required": min_holdout,
            "fraction_requested": holdout_fraction,
        },
        "exact_attachment_checksum_leakage_removed": True,
        "model_input_target_leakage_blocked": True,
        "source_content_coverage": {
            "pass": content_gate,
            "value": round(content_coverage, 4),
            "required": min_source_content_coverage,
            "ready_cases": source_ready_cases,
            "holdout_cases": holdout_count,
        },
        "model_training_enabled": False,
        "auto_post_disabled": True,
        "human_review_required": True,
    }

    if not holdout_gate:
        stage = "BLOCKED_BY_EVALUATION_SPLIT"
        next_action = "EXPAND_GOLD_DATASET"
        ok = False
    elif not content_gate:
        stage = "BLOCKED_BY_SOURCE_EVIDENCE"
        next_action = "HYDRATE_SAFE_GOLD_ATTACHMENTS"
        ok = False
    else:
        stage = "EVALUATION_DATA_READY"
        next_action = "RUN_BASELINE_MODEL_EVALUATION"
        ok = True

    report = {
        "ok": ok,
        "stage": stage,
        "next_action": next_action,
        "contract_version": EVALUATION_CONTRACT_VERSION,
        "dataset_root": str(root),
        "selected_company_id": next(iter(company_ids)),
        "gold_pairs": len(pairs),
        "reference_pool_cases": len(reference_pool),
        "holdout_cases": holdout_count,
        "duplicate_checksum_exclusions": duplicate_checksum_exclusions,
        "missing_date_cases": missing_date_cases,
        "hydration": hydration_report,
        "gates": gates,
        "leakage_controls": {
            "split_strategy": "chronological_latest_holdout",
            "exact_attachment_checksum_deduplication": True,
            "model_input_contains_only_source_attachment_evidence": True,
            "excluded_odoo_derived_fields": list(_MODEL_INPUT_EXCLUDED_ODOO_FIELDS),
            "ground_truth_separate_from_model_inputs": True,
        },
        "artifacts": {
            "inputs_file": inputs_path.name,
            "ground_truth_file": truth_path.name,
            "evaluation_directory": evaluation_root.name,
        },
        "safety": {
            "odoo_mutations": False,
            "training_performed": False,
            "auto_post": False,
            "secrets_exposed": False,
        },
    }
    manifest_path = evaluation_root / "evaluation-manifest.json"
    _write_json_atomic(manifest_path, report)
    report["artifacts"]["manifest_file"] = manifest_path.name
    return report


def _latest_golden_dataset(datasets_root: Path) -> Path:
    root = datasets_root.expanduser().resolve()
    if not root.exists():
        raise EvaluationPreparationError("No Accounting Brain dataset directory exists yet")
    candidates = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_dir()
            and path.name.startswith("golden-")
            and (path / "pairs.jsonl").is_file()
        ),
        key=lambda path: path.name,
    )
    if not candidates:
        raise EvaluationPreparationError("No private Golden Dataset was found")
    return candidates[-1]


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
                    raise EvaluationPreparationError(
                        f"Invalid JSON object in {path.name} line {line_number}"
                    )
                rows.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationPreparationError(
            f"Could not read private dataset {path.name}: {exc}"
        ) from exc
    return rows


def _company_ids(pairs: Iterable[dict[str, Any]]) -> set[int]:
    result: set[int] = set()
    for pair in pairs:
        company = (
            pair.get("input", {})
            .get("document", {})
            .get("company")
        )
        if isinstance(company, dict) and company.get("id") not in (None, False, ""):
            try:
                result.add(int(company["id"]))
            except (TypeError, ValueError):
                continue
    return result


def _pair_event_date(pair: dict[str, Any]) -> date | None:
    document = pair.get("input", {}).get("document", {})
    if not isinstance(document, dict):
        return None
    for key in ("invoice_date", "date"):
        raw = document.get(key)
        if raw in (None, False, ""):
            continue
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
    return None


def _chronology_key(pair: dict[str, Any]) -> tuple[date, int]:
    event_date = _pair_event_date(pair) or date.min
    try:
        move_id = int(pair.get("source_move_id") or 0)
    except (TypeError, ValueError):
        move_id = 0
    return event_date, move_id


def _attachment_checksums(pairs: Iterable[dict[str, Any]]) -> set[str]:
    checksums: set[str] = set()
    for pair in pairs:
        for attachment in _pair_attachments(pair):
            checksum = attachment.get("checksum") or attachment.get("content_sha256")
            if checksum:
                checksums.add(str(checksum).strip().lower())
    return checksums


def _pair_attachments(pair: dict[str, Any]) -> list[dict[str, Any]]:
    value = pair.get("input", {}).get("attachments", [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe_model_attachments(pair: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for attachment in _pair_attachments(pair):
        result.append(
            {
                "filename": attachment.get("filename"),
                "mimetype": normalize_mimetype(attachment.get("mimetype")),
                "file_size": attachment.get("file_size"),
                "local_path": attachment.get("local_path"),
                "content_sha256": attachment.get("content_sha256"),
                "content_status": attachment.get("content_status") or "metadata_only",
            }
        )
    return result


def _case_id(pair: dict[str, Any], index: int) -> str:
    seed = "|".join(
        (
            str(pair.get("source_move_id") or ""),
            str(_pair_event_date(pair) or ""),
            str(index),
        )
    )
    return "acct-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _existing_content_report(pairs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    mimetypes: Counter[str] = Counter()
    for pair in pairs:
        for attachment in _pair_attachments(pair):
            statuses[str(attachment.get("content_status") or "metadata_only")] += 1
            mime = normalize_mimetype(attachment.get("mimetype")) or "unknown"
            mimetypes[mime] += 1
    return {
        "requested": False,
        "attachment_status_counts": dict(sorted(statuses.items())),
        "attachment_mimetypes": dict(sorted(mimetypes.items())),
    }


def _hydrate_source_content(
    reader: OdooReadPort,
    dataset_root: Path,
    pairs: list[dict[str, Any]],
    *,
    max_attachment_bytes: int,
) -> dict[str, Any]:
    fields = reader.fields_get("ir.attachment", attributes=("type",))
    if "datas" not in fields:
        raise EvaluationPreparationError(
            "Odoo ir.attachment does not expose the datas field to this read-only user"
        )

    sink = FilesystemTrainingDatasetSink(dataset_root)
    metadata_by_id: dict[int, dict[str, Any]] = {}
    pair_locations: dict[int, list[dict[str, Any]]] = {}
    status_counts: Counter[str] = Counter()
    mimetype_counts: Counter[str] = Counter()

    for pair in pairs:
        for attachment in _pair_attachments(pair):
            try:
                attachment_id = int(attachment.get("attachment_id") or 0)
            except (TypeError, ValueError):
                attachment_id = 0
            if attachment_id <= 0:
                attachment["content_status"] = "invalid_attachment_id"
                status_counts["invalid_attachment_id"] += 1
                continue

            mime = normalize_mimetype(attachment.get("mimetype"))
            mimetype_counts[mime or "unknown"] += 1
            current_status = str(attachment.get("content_status") or "metadata_only")
            if current_status == "downloaded" and attachment.get("local_path"):
                status_counts["downloaded"] += 1
                continue
            if not is_supported_evidence_mimetype(mime):
                attachment["content_status"] = "unsupported_mimetype"
                status_counts["unsupported_mimetype"] += 1
                continue
            try:
                file_size = int(attachment.get("file_size")) if attachment.get("file_size") else None
            except (TypeError, ValueError):
                file_size = None
            if file_size is not None and file_size > max_attachment_bytes:
                attachment["content_status"] = "skipped_too_large"
                status_counts["skipped_too_large"] += 1
                continue

            metadata_by_id.setdefault(attachment_id, attachment)
            pair_locations.setdefault(attachment_id, []).append(attachment)

    ids = sorted(metadata_by_id)
    for chunk in _chunks(ids, 25):
        try:
            rows = reader.read("ir.attachment", chunk, fields=("id", "datas"))
        except OdooReadError:
            for attachment_id in chunk:
                for location in pair_locations.get(attachment_id, []):
                    location["content_status"] = "read_denied_or_unavailable"
                    status_counts["read_denied_or_unavailable"] += 1
            continue

        row_by_id = {
            int(row.get("id") or 0): row
            for row in rows
            if isinstance(row, dict) and row.get("id")
        }
        for attachment_id in chunk:
            locations = pair_locations.get(attachment_id, [])
            row = row_by_id.get(attachment_id)
            raw_value = row.get("datas") if row else None
            if not raw_value:
                for location in locations:
                    location["content_status"] = "empty_content"
                    status_counts["empty_content"] += 1
                continue
            try:
                content = base64.b64decode(raw_value, validate=False)
            except (TypeError, ValueError):
                for location in locations:
                    location["content_status"] = "invalid_base64"
                    status_counts["invalid_base64"] += 1
                continue
            if len(content) > max_attachment_bytes:
                for location in locations:
                    location["file_size"] = len(content)
                    location["content_status"] = "skipped_too_large"
                    status_counts["skipped_too_large"] += 1
                continue

            metadata = metadata_by_id[attachment_id]
            relative_path, sha256 = sink.write_attachment(
                attachment_id=attachment_id,
                filename=str(metadata.get("filename") or f"attachment-{attachment_id}"),
                content=content,
            )
            for location in locations:
                location["local_path"] = relative_path
                location["content_sha256"] = sha256
                location["file_size"] = len(content)
                location["content_status"] = "downloaded"
                status_counts["downloaded"] += 1

    pairs_path = dataset_root / "pairs.jsonl"
    _write_jsonl_atomic(pairs_path, pairs)
    hydration_report = {
        "requested": True,
        "max_attachment_bytes": max_attachment_bytes,
        "attachment_status_counts": dict(sorted(status_counts.items())),
        "attachment_mimetypes": dict(sorted(mimetype_counts.items())),
        "odoo_mutations": False,
    }
    _write_json_atomic(dataset_root / "source-hydration-report.json", hydration_report)
    return hydration_report


def _chunks(values: list[int], size: int) -> Iterable[list[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_private_dir(path.parent)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    _chmod_private_file(temp)
    temp.replace(path)
    _chmod_private_file(path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_private_dir(path.parent)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _chmod_private_file(temp)
    temp.replace(path)
    _chmod_private_file(path)


def _chmod_private_dir(path: Path) -> None:
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _chmod_private_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
