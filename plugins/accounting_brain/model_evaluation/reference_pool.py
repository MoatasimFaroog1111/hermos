"""Materialize historical retrieval evidence without holdout leakage.

This trusted preparation step may read the private evaluation ground truth only
to identify which historical moves belong to the holdout. The resulting
reference artifact contains *only non-holdout Gold history* and can therefore be
consumed by the model runner without exposing holdout targets.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class ReferencePoolError(RuntimeError):
    """Raised when a safe historical retrieval pool cannot be constructed."""


def prepare_reference_pool(datasets_root: Path) -> dict[str, Any]:
    """Write ``evaluation-reference.jsonl`` for the newest prepared dataset."""

    evaluation_root = _latest_evaluation_root(Path(datasets_root))
    dataset_root = evaluation_root.parent
    manifest = _load_json(evaluation_root / "evaluation-manifest.json")
    if manifest.get("ok") is not True or manifest.get("stage") != "EVALUATION_DATA_READY":
        raise ReferencePoolError(
            "Evaluation must be EVALUATION_DATA_READY before reference preparation"
        )

    pairs = _load_jsonl(dataset_root / "pairs.jsonl")
    truth = _load_jsonl(evaluation_root / "evaluation-ground-truth.jsonl")
    if not pairs or not truth:
        raise ReferencePoolError("Golden Dataset or holdout ground truth is empty")

    holdout_move_ids = {
        _int_or_none((row.get("evidence") or {}).get("source_move_id"))
        for row in truth
        if isinstance(row.get("evidence"), dict)
    }
    holdout_move_ids.discard(None)
    holdout_checksums = _truth_holdout_checksums(
        evaluation_root / "evaluation-inputs.jsonl"
    )

    rows: list[dict[str, Any]] = []
    excluded_holdout = 0
    excluded_checksum = 0
    missing_source = 0
    for pair in pairs:
        move_id = _int_or_none(pair.get("source_move_id"))
        if move_id in holdout_move_ids:
            excluded_holdout += 1
            continue
        attachments = _safe_attachments(pair)
        if not attachments:
            missing_source += 1
            continue
        checksums = _attachment_checksums(attachments)
        if holdout_checksums.intersection(checksums):
            excluded_checksum += 1
            continue
        target = pair.get("target")
        if not isinstance(target, dict) or not target:
            continue
        rows.append(
            {
                "contract_version": manifest.get("contract_version"),
                "reference_id": f"move-{move_id or len(rows) + 1}",
                "source_move_id": move_id,
                "event_date": _event_date(pair),
                "source": {"attachments": attachments},
                "target": target,
            }
        )

    if not rows:
        raise ReferencePoolError("No leakage-safe historical references are available")

    output = evaluation_root / "evaluation-reference.jsonl"
    _write_jsonl_atomic(output, rows)
    report = {
        "ok": True,
        "stage": "REFERENCE_POOL_READY",
        "reference_cases": len(rows),
        "holdout_cases": len(holdout_move_ids),
        "excluded_holdout_moves": excluded_holdout,
        "excluded_exact_checksum_matches": excluded_checksum,
        "references_missing_source": missing_source,
        "artifact": output.name,
        "safety": {
            "holdout_targets_in_reference_pool": False,
            "exact_holdout_checksum_in_reference_pool": False,
            "odoo_mutations": False,
        },
    }
    _write_json_atomic(evaluation_root / "reference-pool-report.json", report)
    return report


def _latest_evaluation_root(datasets_root: Path) -> Path:
    root = datasets_root.expanduser().resolve()
    if not root.exists():
        raise ReferencePoolError("No Accounting Brain dataset directory exists")
    candidates = sorted(
        path / "evaluation"
        for path in root.iterdir()
        if path.is_dir()
        and path.name.startswith("golden-")
        and (path / "evaluation" / "evaluation-manifest.json").is_file()
    )
    if not candidates:
        raise ReferencePoolError("No prepared Accounting Brain evaluation exists")
    return candidates[-1]


def _safe_attachments(pair: dict[str, Any]) -> list[dict[str, Any]]:
    raw = (pair.get("input") or {}).get("attachments")
    if not isinstance(raw, list):
        return []
    safe: list[dict[str, Any]] = []
    allowed = {
        "attachment_id",
        "filename",
        "mimetype",
        "file_size",
        "checksum",
        "local_path",
        "content_sha256",
        "content_status",
    }
    for item in raw:
        if not isinstance(item, dict):
            continue
        safe.append({key: item.get(key) for key in allowed if key in item})
    return safe


def _truth_holdout_checksums(inputs_path: Path) -> set[str]:
    checksums: set[str] = set()
    for row in _load_jsonl(inputs_path):
        source = row.get("source")
        attachments = source.get("attachments") if isinstance(source, dict) else None
        if not isinstance(attachments, list):
            continue
        checksums.update(_attachment_checksums(attachments))
    return checksums


def _attachment_checksums(attachments: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for item in attachments:
        for key in ("content_sha256", "checksum"):
            value = item.get(key)
            if value:
                result.add(str(value).strip().lower())
    return result


def _event_date(pair: dict[str, Any]) -> str | None:
    document = (pair.get("input") or {}).get("document")
    if not isinstance(document, dict):
        return None
    for key in ("invoice_date", "date"):
        value = document.get(key)
        if value not in (None, False, ""):
            return str(value)[:10]
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value in (None, False, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReferencePoolError(f"Cannot read {path.name}") from exc
    if not isinstance(value, dict):
        raise ReferencePoolError(f"Invalid object in {path.name}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReferencePoolError(f"Cannot read {path.name}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReferencePoolError(
                f"Invalid JSONL in {path.name} line {line_number}"
            ) from exc
        if not isinstance(value, dict):
            raise ReferencePoolError(
                f"Invalid JSON object in {path.name} line {line_number}"
            )
        rows.append(value)
    return rows


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_text_atomic(
        path,
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
    )


def _write_text_atomic(path: Path, text: str) -> None:
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
