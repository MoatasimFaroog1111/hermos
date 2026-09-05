"""Draft-only production inference for new accounting source documents."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.accounting_brain.model_evaluation.baseline_runner import (
    PREDICTION_SCHEMA,
    StructuredLlmPort,
)
from plugins.accounting_brain.model_evaluation.retrieval import (
    RetrievalError,
    retrieve_historical_examples,
)
from plugins.accounting_brain.model_evaluation.source_material import (
    SourceMaterialError,
    build_model_inputs,
)
from plugins.accounting_brain.production_drafts.reference_history import (
    ProductionReferenceError,
    load_production_references,
)
from plugins.accounting_brain.production_drafts.validation import (
    validate_draft_prediction,
)


class DraftPredictionError(RuntimeError):
    """Raised when a production draft cannot be prepared safely."""


DRAFT_PREDICTION_SCHEMA: dict[str, Any] = deepcopy(PREDICTION_SCHEMA)
DRAFT_PREDICTION_SCHEMA["required"] = [
    "move_type",
    "date",
    "reference",
    "journal",
    "partner",
    "company",
    "currency",
    "taxes",
    "journal_entry",
]
DRAFT_PREDICTION_SCHEMA["properties"].update(
    {
        "date": {"type": "string"},
        "reference": {"type": ["string", "null"]},
        "company": {"type": "object"},
    }
)

_DRAFT_INSTRUCTIONS = """You are the Accounting Brain inside Hermes.
Prepare a DRAFT Odoo journal entry for the CURRENT SOURCE DOCUMENT.
Historical examples come only from previously validated Gold company history.
Use them to follow company-specific account, journal, tax, partner and analytic
conventions, but never copy an amount unless the current document independently
supports it. Return move_type, accounting date (YYYY-MM-DD), source reference,
company, journal, partner, currency, taxes and all journal lines. Preserve Odoo
IDs from historical evidence only when the evidence supports the same entity.
Return only the requested JSON. The journal must balance exactly. Do not call
tools, write to Odoo, post, reconcile, pay, delete, or modify any record. A
human accountant will review the draft before any explicit Odoo create action.
"""


def prepare_accounting_draft(
    source_file: Path,
    *,
    hermes_home: Path,
    datasets_root: Path,
    output_root: Path,
    llm: StructuredLlmPort,
    top_k: int = 5,
    timeout_seconds: float = 120.0,
    max_tokens: int = 1800,
) -> dict[str, Any]:
    """Create and persist a human-reviewable journal proposal without Odoo writes."""

    home = Path(hermes_home).expanduser().resolve()
    source = Path(source_file).expanduser().resolve()
    _assert_permitted_source(source, home)
    if not source.is_file():
        raise DraftPredictionError("Source accounting document does not exist")

    mimetype, _ = mimetypes.guess_type(source.name)
    mimetype = mimetype or "application/octet-stream"
    source_sha256 = _sha256_file(source)
    source_payload = {
        "attachments": [
            {
                "filename": source.name,
                "mimetype": mimetype,
                "file_size": source.stat().st_size,
                "content_sha256": source_sha256,
                "local_path": str(source),
                "content_status": "downloaded",
            }
        ]
    }

    try:
        _, references = load_production_references(
            datasets_root,
            permitted_root=home,
        )
        examples = retrieve_historical_examples(
            source_payload,
            references,
            dataset_root=home,
            top_k=max(1, min(10, int(top_k))),
        )
        model_inputs = build_model_inputs(source_payload, dataset_root=home)
    except (ProductionReferenceError, RetrievalError, SourceMaterialError) as exc:
        raise DraftPredictionError(str(exc)) from exc

    evidence_block = {
        "type": "text",
        "text": (
            "HISTORICAL GOLD EXAMPLES (evidence only, never current ground truth):\n"
            + json.dumps(examples, ensure_ascii=False, sort_keys=True)
        ),
    }
    try:
        result = llm.complete_structured(
            instructions=_DRAFT_INSTRUCTIONS,
            input=[*model_inputs, evidence_block],
            json_schema=DRAFT_PREDICTION_SCHEMA,
            json_mode=True,
            schema_name="odoo_journal_draft_v1",
            temperature=0.0,
            max_tokens=max(256, min(4096, int(max_tokens))),
            timeout=max(15.0, min(300.0, float(timeout_seconds))),
            purpose="accounting_draft_prediction",
        )
    except Exception as exc:
        raise DraftPredictionError(
            f"Host model could not prepare a structured accounting draft: {type(exc).__name__}"
        ) from exc

    prediction = getattr(result, "parsed", None)
    if not isinstance(prediction, dict):
        raise DraftPredictionError("Host model returned invalid structured accounting JSON")

    validation = validate_draft_prediction(prediction)
    proposal = {
        "ok": bool(validation["valid"]),
        "stage": (
            "READY_FOR_HUMAN_REVIEW"
            if validation["valid"]
            else "BLOCKED_BY_DETERMINISTIC_VALIDATION"
        ),
        "production_mode": "draft_only",
        "source": {
            "filename": source.name,
            "mimetype": mimetype,
            "file_size": source.stat().st_size,
            "sha256": source_sha256,
        },
        "prediction": prediction,
        "validation": validation,
        "evidence": {
            "retrieval_mode": "historical_gold",
            "retrieved_references": examples,
            "reference_count": len(examples),
        },
        "model": {
            "provider": getattr(result, "provider", None),
            "model": getattr(result, "model", None),
        },
        "safety": {
            "odoo_write_performed": False,
            "auto_post": False,
            "human_review_required": True,
            "source_amounts_require_human_verification": True,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    output = _write_private_proposal(Path(output_root), proposal)
    proposal["proposal_file"] = output.name
    return proposal


def _assert_permitted_source(source: Path, home: Path) -> None:
    try:
        source.relative_to(home)
    except ValueError as exc:
        raise DraftPredictionError(
            "Source document must be inside the private Hermes data directory"
        ) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_private_proposal(root: Path, proposal: dict[str, Any]) -> Path:
    output_root = root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(output_root, 0o700)
    except OSError:
        pass
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = output_root / f"draft-proposal-{timestamp}.json"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
