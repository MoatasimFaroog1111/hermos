"""Load private Gold accounting history as retrieval-only production evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ProductionReferenceError(RuntimeError):
    """Raised when no safe production retrieval history is available."""


def load_production_references(
    datasets_root: Path,
    *,
    permitted_root: Path,
) -> tuple[Path, list[dict[str, Any]]]:
    """Load Gold pairs from the newest private dataset for draft retrieval."""

    dataset_root = _latest_golden_dataset(Path(datasets_root))
    permitted = Path(permitted_root).expanduser().resolve()
    _assert_within(dataset_root, permitted)
    pairs = _load_jsonl(dataset_root / "pairs.jsonl")
    references: list[dict[str, Any]] = []
    for pair in pairs:
        if str(pair.get("grade") or "").lower() != "gold":
            continue
        target = pair.get("target")
        if not isinstance(target, dict) or not target:
            continue
        attachments = _production_attachments(pair, dataset_root)
        if not attachments:
            continue
        references.append(
            {
                "reference_id": f"move-{pair.get('source_move_id')}",
                "event_date": _event_date(pair),
                "source": {"attachments": attachments},
                "target": target,
            }
        )
    if not references:
        raise ProductionReferenceError(
            "No Gold historical source documents are available for retrieval"
        )
    return dataset_root, references


def _production_attachments(
    pair: dict[str, Any],
    dataset_root: Path,
) -> list[dict[str, Any]]:
    raw = (pair.get("input") or {}).get("attachments")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or item.get("content_status") != "downloaded":
            continue
        local = item.get("local_path")
        if not isinstance(local, str) or not local.strip():
            continue
        path = (dataset_root / local).resolve()
        try:
            path.relative_to(dataset_root)
        except ValueError:
            continue
        if not path.is_file():
            continue
        result.append(
            {
                "filename": item.get("filename") or path.name,
                "mimetype": item.get("mimetype"),
                "checksum": item.get("checksum"),
                "content_sha256": item.get("content_sha256"),
                "local_path": str(path),
                "content_status": "downloaded",
            }
        )
    return result


def _latest_golden_dataset(datasets_root: Path) -> Path:
    root = datasets_root.expanduser().resolve()
    if not root.exists():
        raise ProductionReferenceError("No Accounting Brain dataset directory exists")
    candidates = sorted(
        path
        for path in root.iterdir()
        if path.is_dir()
        and path.name.startswith("golden-")
        and (path / "pairs.jsonl").is_file()
    )
    if not candidates:
        raise ProductionReferenceError("No private Golden Dataset is available")
    return candidates[-1]


def _event_date(pair: dict[str, Any]) -> str | None:
    document = (pair.get("input") or {}).get("document")
    if not isinstance(document, dict):
        return None
    for key in ("invoice_date", "date"):
        value = document.get(key)
        if value not in (None, False, ""):
            return str(value)[:10]
    return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ProductionReferenceError(f"Cannot read {path.name}") from exc
    result: list[dict[str, Any]] = []
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProductionReferenceError(
                f"Invalid JSONL in {path.name} line {line_number}"
            ) from exc
        if not isinstance(value, dict):
            raise ProductionReferenceError(
                f"Invalid JSON object in {path.name} line {line_number}"
            )
        result.append(value)
    return result


def _assert_within(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise ProductionReferenceError(
            "Golden Dataset is outside the permitted Hermes data root"
        ) from exc
