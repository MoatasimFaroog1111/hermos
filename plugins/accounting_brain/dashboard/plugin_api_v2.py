"""Accounting Brain dashboard API with safe background baseline evaluation.

This module extends the existing read-only Accounting Brain dashboard router.
Baseline evaluation consumes only the prepared source-only holdout through the
existing model-evaluation use case. It never mutates Odoo, trains a model, or
auto-posts accounting entries.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from hermes_constants import get_hermes_home
from plugins.accounting_brain.dashboard.plugin_api import router
from plugins.accounting_brain.model_evaluation.baseline_runner import (
    BaselineEvaluationError,
    build_host_llm,
    run_baseline_evaluation,
)


class BaselineEvaluationRequest(BaseModel):
    """Bounded host-model settings for one baseline holdout run."""

    timeout_seconds: float = Field(default=120.0, ge=15.0, le=300.0)
    max_tokens: int = Field(default=1800, ge=256, le=4096)


_BASELINE_LOCK = asyncio.Lock()
_BASELINE_TASK: asyncio.Task[None] | None = None
_BASELINE_STATE: dict[str, Any] = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "result": None,
    "error": None,
}


@router.post("/evaluation/baseline")
async def start_baseline_evaluation(
    request: BaselineEvaluationRequest,
) -> dict[str, Any]:
    """Start one background baseline run without holding the HTTP request open."""

    global _BASELINE_TASK
    async with _BASELINE_LOCK:
        if _BASELINE_TASK is not None and not _BASELINE_TASK.done():
            raise HTTPException(
                status_code=409,
                detail="A baseline model evaluation is already running",
            )

        _BASELINE_STATE.update(
            {
                "status": "running",
                "started_at": _timestamp(),
                "finished_at": None,
                "result": None,
                "error": None,
            }
        )
        _BASELINE_TASK = asyncio.create_task(_run_baseline_background(request))
        return _public_state()


@router.get("/evaluation/baseline")
async def baseline_evaluation_status() -> dict[str, Any]:
    """Return the active run state or the newest persisted baseline report."""

    if _BASELINE_STATE["status"] == "idle":
        persisted = _load_latest_report()
        if persisted is not None:
            return {
                "status": "completed" if persisted.get("error") is None else "failed",
                "started_at": persisted.get("started_at"),
                "finished_at": persisted.get("finished_at"),
                "result": persisted.get("result"),
                "error": persisted.get("error"),
                "safety": _safety_summary(),
            }
    return _public_state()


async def _run_baseline_background(request: BaselineEvaluationRequest) -> None:
    try:
        result = await asyncio.to_thread(_run_baseline_sync, request)
    except BaselineEvaluationError as exc:
        _finish_failed(str(exc))
    except Exception as exc:  # fail closed; do not expose traceback or secrets
        _finish_failed(f"Baseline evaluation failed: {type(exc).__name__}")
    else:
        _BASELINE_STATE.update(
            {
                "status": "completed",
                "finished_at": _timestamp(),
                "result": result,
                "error": None,
            }
        )
        _persist_state()


def _run_baseline_sync(request: BaselineEvaluationRequest) -> dict[str, Any]:
    datasets_root = get_hermes_home() / "accounting_brain" / "datasets"
    report = run_baseline_evaluation(
        datasets_root,
        build_host_llm(),
        timeout_seconds=request.timeout_seconds,
        max_tokens=request.max_tokens,
    )
    report["dashboard_execution"] = {
        "background_task": True,
        "training_performed": False,
        "odoo_mutations": False,
        "auto_post": False,
    }
    return report


def _finish_failed(message: str) -> None:
    _BASELINE_STATE.update(
        {
            "status": "failed",
            "finished_at": _timestamp(),
            "result": None,
            "error": message,
        }
    )
    _persist_state()


def _public_state() -> dict[str, Any]:
    return {
        **_BASELINE_STATE,
        "safety": _safety_summary(),
    }


def _safety_summary() -> dict[str, bool]:
    return {
        "ground_truth_visible_to_model": False,
        "odoo_mutations": False,
        "training_performed": False,
        "auto_post": False,
        "human_review_required": True,
    }


def _reports_root() -> Path:
    root = (get_hermes_home() / "accounting_brain" / "reports").resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def _persist_state() -> Path:
    path = _reports_root() / f"baseline-model-evaluation-{_timestamp()}.json"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(_public_state(), ensure_ascii=False, indent=2, sort_keys=True),
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
    if isinstance(_BASELINE_STATE.get("result"), dict):
        _BASELINE_STATE["result"]["report_file"] = path.name
    return path


def _load_latest_report() -> dict[str, Any] | None:
    root = get_hermes_home() / "accounting_brain" / "reports"
    if not root.exists():
        return None
    candidates = sorted(root.glob("baseline-model-evaluation-*.json"))
    if not candidates:
        return None
    try:
        value = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
