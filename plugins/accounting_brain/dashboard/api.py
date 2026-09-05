"""Accounting Brain dashboard API composition root.

Keeps the established read-only Odoo routes intact while adding model-runtime
operations that never mutate Odoo and always remain draft-only.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hermes_constants import get_hermes_home
from plugins.accounting_brain.dashboard.plugin_api import router as data_router
from plugins.accounting_brain.model_evaluation.baseline_runner import (
    BaselineEvaluationError,
    build_host_llm,
    run_baseline_evaluation,
)
from plugins.accounting_brain.model_evaluation.evaluate import (
    EvaluationRunError,
    score_latest_evaluation,
)

router = APIRouter()
router.include_router(data_router)


class BaselineEvaluationRequest(BaseModel):
    """Bounded host-model evaluation settings."""

    timeout_seconds: float = Field(default=120.0, ge=15.0, le=300.0)
    max_tokens: int = Field(default=1800, ge=256, le=4096)


@router.post("/evaluation/run")
async def run_evaluation(request: BaselineEvaluationRequest) -> dict[str, Any]:
    """Run the active Hermes model on the prepared leakage-safe holdout."""

    try:
        return await asyncio.to_thread(_run_evaluation_sync, request)
    except BaselineEvaluationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/evaluation/score")
async def score_evaluation() -> dict[str, Any]:
    """Deterministically rescore the latest fixed holdout predictions."""

    try:
        return await asyncio.to_thread(_score_evaluation_sync)
    except EvaluationRunError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _run_evaluation_sync(request: BaselineEvaluationRequest) -> dict[str, Any]:
    datasets_root = get_hermes_home() / "accounting_brain" / "datasets"
    llm = build_host_llm()
    return run_baseline_evaluation(
        datasets_root,
        llm,
        timeout_seconds=request.timeout_seconds,
        max_tokens=request.max_tokens,
    )


def _score_evaluation_sync() -> dict[str, Any]:
    datasets_root = get_hermes_home() / "accounting_brain" / "datasets"
    return score_latest_evaluation(datasets_root)
