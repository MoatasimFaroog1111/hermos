"""Deterministic retrieval over leakage-safe historical accounting references."""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from plugins.accounting_brain.model_evaluation.source_material import (
    SourceMaterialError,
    build_model_inputs,
)


class RetrievalError(RuntimeError):
    """Raised when historical evidence cannot be retrieved safely."""


_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = {
    "the",
    "and",
    "for",
    "from",
    "with",
    "this",
    "that",
    "invoice",
    "document",
    "page",
    "فاتورة",
    "من",
    "في",
    "على",
    "الى",
    "إلى",
    "عن",
    "هذا",
    "هذه",
}


def retrieve_historical_examples(
    case_source: dict[str, Any],
    reference_rows: list[dict[str, Any]],
    *,
    dataset_root: Path,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Return top historical examples using source evidence only for ranking."""

    if top_k < 1:
        raise RetrievalError("top_k must be at least 1")
    query_text = _source_text(case_source, dataset_root)
    query_tokens = _tokens(query_text)
    if not query_tokens:
        query_tokens = _filename_tokens(case_source)
    if not query_tokens:
        raise RetrievalError("New source contains no retrievable text or filename tokens")

    documents: list[tuple[dict[str, Any], Counter[str]]] = []
    for row in reference_rows:
        source = row.get("source")
        if not isinstance(source, dict):
            continue
        try:
            text = _source_text(source, dataset_root)
        except SourceMaterialError:
            text = ""
        tokens = _tokens(text)
        if not tokens:
            tokens = _filename_tokens(source)
        if not tokens:
            continue
        documents.append((row, Counter(tokens)))

    if not documents:
        raise RetrievalError("Historical reference pool has no retrievable source evidence")

    document_frequency: Counter[str] = Counter()
    for _, counts in documents:
        document_frequency.update(counts.keys())
    total_documents = len(documents)
    query_counts = Counter(query_tokens)

    scored: list[tuple[float, dict[str, Any]]] = []
    for row, counts in documents:
        score = 0.0
        for token, query_count in query_counts.items():
            frequency = document_frequency.get(token, 0)
            if frequency <= 0 or counts.get(token, 0) <= 0:
                continue
            inverse_document_frequency = math.log(
                1.0 + (total_documents + 1.0) / (frequency + 1.0)
            )
            score += (
                min(query_count, counts[token])
                * inverse_document_frequency
                * (1.0 + math.log1p(counts[token]))
            )
        if score > 0.0:
            scored.append((score, row))

    scored.sort(
        key=lambda item: (
            item[0],
            str(item[1].get("event_date") or ""),
            str(item[1].get("reference_id") or ""),
        ),
        reverse=True,
    )
    selected = scored[: min(top_k, len(scored))]
    return [
        {
            "reference_id": row.get("reference_id"),
            "event_date": row.get("event_date"),
            "retrieval_score": round(score, 6),
            "source_summary": _source_summary(row.get("source")),
            "historical_posting": _compact_target(row.get("target")),
        }
        for score, row in selected
    ]


def _source_text(source: dict[str, Any], dataset_root: Path) -> str:
    blocks = build_model_inputs(source, dataset_root=dataset_root)
    parts: list[str] = []
    for block in blocks:
        if block.get("type") == "text":
            value = block.get("text")
            if isinstance(value, str):
                parts.append(value)
        elif block.get("type") == "image":
            name = block.get("file_name")
            if name:
                parts.append(str(name))
    return "\n".join(parts)


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in (match.group(0).casefold() for match in _TOKEN_RE.finditer(text))
        if len(token) >= 2 and token not in _STOPWORDS
    ]


def _filename_tokens(source: dict[str, Any]) -> list[str]:
    attachments = source.get("attachments")
    if not isinstance(attachments, list):
        return []
    text = " ".join(
        str(item.get("filename") or "")
        for item in attachments
        if isinstance(item, dict)
    )
    return _tokens(text)


def _source_summary(source: Any) -> dict[str, Any]:
    attachments = source.get("attachments") if isinstance(source, dict) else None
    if not isinstance(attachments, list):
        return {"attachments": []}
    return {
        "attachments": [
            {
                "filename": item.get("filename"),
                "mimetype": item.get("mimetype"),
            }
            for item in attachments
            if isinstance(item, dict)
        ]
    }


def _compact_target(target: Any) -> dict[str, Any]:
    if not isinstance(target, dict):
        return {}
    lines = target.get("journal_entry")
    compact_lines: list[dict[str, Any]] = []
    if isinstance(lines, list):
        for line in lines:
            if not isinstance(line, dict):
                continue
            compact_lines.append(
                {
                    "account_id": line.get("account_id"),
                    "account_code": line.get("account_code"),
                    "account_name": line.get("account_name"),
                    "debit": line.get("debit"),
                    "credit": line.get("credit"),
                    "tax_ids": line.get("tax_ids") or [],
                    "analytic_distribution": line.get("analytic_distribution") or {},
                }
            )
    return {
        "move_type": target.get("move_type"),
        "journal": target.get("journal"),
        "partner": target.get("partner"),
        "currency": target.get("currency"),
        "taxes": target.get("taxes") or [],
        "journal_entry": compact_lines,
    }
