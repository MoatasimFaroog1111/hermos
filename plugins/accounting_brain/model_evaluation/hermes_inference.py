"""Hermes inference adapter for Accounting Brain baseline evaluation.

The Accounting Brain use case never imports a vendor SDK. This adapter resolves
Hermes' configured runtime provider and constructs a stateless, tool-free agent
for each journal prediction. Images use Hermes' existing auxiliary vision route
for source transcription only.

No provider credential, base URL, source document text, or raw provider error is
returned to the dashboard.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from plugins.accounting_brain.model_evaluation.baseline import BaselineEvaluationError


class HermesBaselineInference:
    """Use the currently configured Hermes model without bypassing its router."""

    def __init__(self) -> None:
        from hermes_cli.config import load_config
        from hermes_cli.runtime_provider import resolve_runtime_provider

        cfg = load_config()
        model_cfg = cfg.get("model") or {}
        if isinstance(model_cfg, str):
            config_model = model_cfg.strip()
            config_provider = ""
        elif isinstance(model_cfg, dict):
            config_model = str(
                model_cfg.get("default") or model_cfg.get("model") or ""
            ).strip()
            config_provider = str(model_cfg.get("provider") or "").strip()
        else:
            config_model = ""
            config_provider = ""

        env_model = os.getenv("HERMES_INFERENCE_MODEL", "").strip()
        env_provider = os.getenv("HERMES_INFERENCE_PROVIDER", "").strip()
        self._model = env_model or config_model
        requested_provider = env_provider or config_provider or None
        if not self._model:
            raise BaselineEvaluationError(
                "Hermes has no configured inference model for baseline evaluation"
            )

        try:
            self._runtime = resolve_runtime_provider(
                requested=requested_provider,
                target_model=self._model,
            )
        except Exception as exc:  # noqa: BLE001 - normalize provider-specific failures
            raise BaselineEvaluationError(
                "Hermes could not resolve the configured baseline inference provider"
            ) from exc

        if not self._runtime.get("api_key") and not self._runtime.get("credential_pool"):
            raise BaselineEvaluationError(
                "Hermes baseline inference has no usable configured credential route"
            )

        self._provider = str(
            self._runtime.get("requested_provider")
            or self._runtime.get("provider")
            or requested_provider
            or "unknown"
        )
        self._vision_provider, self._vision_model = _safe_vision_identity()

    def safe_identity(self) -> dict[str, Any]:
        return {
            "provider": self._provider,
            "model": self._model,
            "vision_provider": self._vision_provider,
            "vision_model": self._vision_model,
            "tools_enabled": False,
            "memory_enabled": False,
            "context_files_enabled": False,
        }

    def describe_image(self, image_path: Path) -> str:
        """Extract source facts from an image using Hermes' vision router.

        The prompt explicitly prohibits ledger classification. Vision is an
        evidence-reading stage only; account/journal decisions happen later in
        the main baseline model with reference-pool history.
        """
        from tools.vision_tools import vision_analyze_tool

        prompt = (
            "Read this accounting source document carefully. Transcribe and extract "
            "only information actually visible in the image: supplier/customer name, "
            "document type, invoice/reference/PO numbers, dates, currency, line-item "
            "descriptions, subtotal, VAT/tax rate and amount, total, and any other "
            "accounting-relevant text. Preserve numbers exactly. Do NOT infer Odoo "
            "account codes, journal IDs, tax IDs, partner IDs, or any bookkeeping "
            "classification. Return concise plain text."
        )
        try:
            raw = asyncio.run(
                vision_analyze_tool(
                    image_url=str(image_path.resolve()),
                    user_prompt=prompt,
                )
            )
            envelope = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as exc:  # noqa: BLE001
            raise BaselineEvaluationError("Hermes vision evidence extraction failed") from exc

        if not isinstance(envelope, dict) or not envelope.get("success"):
            raise BaselineEvaluationError("Hermes vision evidence extraction was unavailable")
        analysis = str(envelope.get("analysis") or "").strip()
        if not analysis:
            raise BaselineEvaluationError("Hermes vision returned empty source evidence")
        return analysis[:12_000]

    def predict_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        from run_agent import AIAgent

        agent = None
        try:
            agent = AIAgent(
                api_key=self._runtime.get("api_key"),
                base_url=self._runtime.get("base_url"),
                provider=self._runtime.get("provider"),
                requested_provider=self._runtime.get("requested_provider"),
                api_mode=self._runtime.get("api_mode"),
                model=self._model,
                credential_pool=self._runtime.get("credential_pool"),
                enabled_toolsets=[],
                quiet_mode=True,
                platform="cli",
                skip_context_files=True,
                skip_memory=True,
                max_iterations=2,
            )
            agent.suppress_status_output = True
            agent.stream_delta_callback = None
            agent.tool_gen_callback = None
            result = agent.run_conversation(
                user_message=user_prompt,
                system_message=system_prompt,
            )
            final_response = result.get("final_response") if isinstance(result, dict) else None
            return _strict_json_object(final_response)
        except BaselineEvaluationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BaselineEvaluationError("Hermes baseline model inference failed") from exc
        finally:
            if agent is not None:
                _close_agent(agent)


def _strict_json_object(value: Any) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        raise BaselineEvaluationError("Baseline model returned an empty response")

    fence = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BaselineEvaluationError("Baseline model did not return strict JSON") from exc
    if not isinstance(payload, dict):
        raise BaselineEvaluationError("Baseline model JSON root must be an object")
    return payload


def _safe_vision_identity() -> tuple[str | None, str | None]:
    try:
        from agent.auxiliary_client import resolve_vision_provider_client

        provider, client, model = resolve_vision_provider_client()
        if client is None:
            return None, None
        return str(provider or "unknown"), str(model or "unknown")
    except Exception:
        return None, None


def _close_agent(agent: Any) -> None:
    try:
        session_messages = getattr(agent, "_session_messages", None)
        if isinstance(session_messages, list):
            agent.shutdown_memory_provider(session_messages)
        else:
            agent.shutdown_memory_provider()
    except Exception:
        pass
    try:
        agent.close()
    except Exception:
        pass
