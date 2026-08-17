"""Tripo-backed character provider for Hermes Digital Human.

This module owns only Tripo API concerns: configuration, authenticated health
checks, task inspection, rig workflow submission, transport error
normalization, and secret-safe response shaping.  It intentionally has no
FastAPI, UI, avatar-storage, or Hermes-chat dependencies.
"""

from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Callable

_TRIPO_API_BASE_URL = "https://api.tripo3d.ai/v2/openapi"
_TRIPO_BALANCE_PATH = "/user/balance"
_TRIPO_TASK_PATH = "/task"
_DEFAULT_TIMEOUT_SECONDS = 12.0
_MAX_PROVIDER_MESSAGE_CHARS = 300
_MAX_TASK_ID_CHARS = 128
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ALLOWED_RIG_FORMATS = frozenset({"glb", "fbx"})
_ALLOWED_RIG_TYPES = frozenset({"biped", "quadruped", "hexapod", "octopod", "serpentine", "fish"})
_ALLOWED_RIG_SPECS = frozenset({"tripo", "mixamo"})
_ALLOWED_RIG_VERSIONS = frozenset({"v2.5-20260210", "v1.0-20240301"})
_FINAL_TASK_STATES = frozenset(
    {"success", "failed", "banned", "expired", "cancelled", "unknown"}
)


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    provider: str
    configured: bool
    reachable: bool
    authenticated: bool
    status_code: int | None = None
    trace_id: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class TripoProviderError(RuntimeError):
    """Secret-safe provider failure suitable for translation at the API edge."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        trace_id: str = "",
    ) -> None:
        super().__init__(message[:_MAX_PROVIDER_MESSAGE_CHARS])
        self.status_code = status_code
        self.trace_id = trace_id[:128]


class TripoCharacterProvider:
    """Server-side Tripo adapter used by the Digital Human composition root."""

    name = "tripo"

    def __init__(
        self,
        *,
        api_key_resolver: Callable[[], str] | None = None,
        opener: Callable[..., object] | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key_resolver = api_key_resolver or self._environment_api_key
        self._opener = opener or urllib.request.urlopen
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def _environment_api_key() -> str:
        return (os.getenv("TRIPO_API_KEY") or "").strip()

    def configured(self) -> bool:
        return bool(self._api_key_resolver())

    @staticmethod
    def _trace_id(headers: object) -> str:
        getter = getattr(headers, "get", None)
        if not callable(getter):
            return ""
        value = getter("X-Tripo-Trace-ID") or getter("x-tripo-trace-id") or ""
        return str(value).strip()[:128]

    @staticmethod
    def _provider_message(raw: bytes) -> str:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        message = payload.get("message") or payload.get("suggestion") or ""
        if not isinstance(message, str):
            return ""
        return message.strip()[:_MAX_PROVIDER_MESSAGE_CHARS]

    @staticmethod
    def _validate_task_id(task_id: str) -> str:
        value = str(task_id or "").strip()
        if (
            not value
            or len(value) > _MAX_TASK_ID_CHARS
            or not _TASK_ID_RE.fullmatch(value)
        ):
            raise ValueError("Invalid Tripo task id")
        return value

    def _require_api_key(self) -> str:
        api_key = self._api_key_resolver()
        if not api_key:
            raise TripoProviderError("TRIPO_API_KEY is not configured")
        return api_key

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[dict[str, object], int, str]:
        """Execute one authenticated Tripo request and normalize its envelope."""
        api_key = self._require_api_key()
        body = None
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            f"{_TRIPO_API_BASE_URL}{path}",
            data=body,
            method=method,
            headers=headers,
        )

        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                status_code = int(getattr(response, "status", 200))
                raw = response.read()
                trace_id = self._trace_id(getattr(response, "headers", {}))
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read()
            except OSError:
                raw = b""
            message = self._provider_message(raw) or f"Tripo returned HTTP {exc.code}"
            raise TripoProviderError(
                message,
                status_code=int(exc.code),
                trace_id=self._trace_id(getattr(exc, "headers", {})),
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            reason = getattr(exc, "reason", None) or str(exc) or type(exc).__name__
            raise TripoProviderError(
                f"Tripo is unreachable: {str(reason)[:_MAX_PROVIDER_MESSAGE_CHARS]}"
            ) from exc

        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TripoProviderError(
                "Tripo returned an invalid JSON response",
                status_code=status_code,
                trace_id=trace_id,
            ) from exc
        if not isinstance(envelope, dict):
            raise TripoProviderError(
                "Tripo returned an unexpected response",
                status_code=status_code,
                trace_id=trace_id,
            )

        code = envelope.get("code")
        if status_code != 200 or code != 0:
            message = self._provider_message(raw)
            if not message:
                message = f"Tripo request failed with code {code!r}"
            raise TripoProviderError(
                message,
                status_code=status_code,
                trace_id=trace_id,
            )
        return envelope, status_code, trace_id

    @staticmethod
    def _envelope_data(envelope: dict[str, object]) -> dict[str, object]:
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise TripoProviderError("Tripo response did not contain task data")
        return data

    @staticmethod
    def _task_summary(data: dict[str, object], trace_id: str = "") -> dict[str, object]:
        output = data.get("output") if isinstance(data.get("output"), dict) else {}
        assert isinstance(output, dict)
        status = str(data.get("status") or "unknown")
        task_id = str(data.get("task_id") or "")
        task_type = str(data.get("type") or "")
        progress = data.get("progress")
        if not isinstance(progress, (int, float)):
            progress = None

        rig_type = output.get("rig_type") or data.get("rig_type") or ""
        riggable = output.get("riggable")
        if not isinstance(riggable, bool):
            riggable = None

        # Signed output URLs intentionally remain server-side. They are short-lived
        # provider artifacts and should not become a browser-facing storage contract.
        return {
            "provider": "tripo",
            "task_id": task_id,
            "type": task_type,
            "status": status,
            "finalized": status in _FINAL_TASK_STATES,
            "progress": progress,
            "model_available": bool(output.get("model")),
            "riggable": riggable,
            "rig_type": str(rig_type) if rig_type else "",
            "trace_id": trace_id,
        }

    def health(self) -> dict[str, object]:
        """Verify Tripo reachability/authentication without creating a paid task.

        Tripo documents ``GET /user/balance`` as an immediate authenticated
        request, so it is used only as a credential probe. Wallet values are
        deliberately not returned to the browser.
        """
        if not self.configured():
            return ProviderHealth(
                provider=self.name,
                configured=False,
                reachable=False,
                authenticated=False,
                error="TRIPO_API_KEY is not configured",
            ).as_dict()

        try:
            _envelope, status_code, trace_id = self._request_json(
                method="GET",
                path=_TRIPO_BALANCE_PATH,
            )
            return ProviderHealth(
                provider=self.name,
                configured=True,
                reachable=True,
                authenticated=True,
                status_code=status_code,
                trace_id=trace_id,
                error="",
            ).as_dict()
        except TripoProviderError as exc:
            reachable = exc.status_code is not None
            return ProviderHealth(
                provider=self.name,
                configured=True,
                reachable=reachable,
                authenticated=False,
                status_code=exc.status_code,
                trace_id=exc.trace_id,
                error=str(exc),
            ).as_dict()

    def get_task(self, task_id: str) -> dict[str, object]:
        """Return a secret-safe status summary for a Tripo task."""
        normalized = self._validate_task_id(task_id)
        envelope, _status_code, trace_id = self._request_json(
            method="GET",
            path=f"{_TRIPO_TASK_PATH}/{urllib.parse.quote(normalized, safe='')}",
        )
        return self._task_summary(self._envelope_data(envelope), trace_id)

    def submit_prerig_check(self, original_model_task_id: str) -> dict[str, object]:
        """Submit Tripo's free pre-rig suitability check."""
        original = self._validate_task_id(original_model_task_id)
        envelope, _status_code, trace_id = self._request_json(
            method="POST",
            path=_TRIPO_TASK_PATH,
            payload={
                "type": "animate_prerigcheck",
                "original_model_task_id": original,
            },
        )
        data = self._envelope_data(envelope)
        return {
            "provider": self.name,
            "task_id": str(data.get("task_id") or ""),
            "type": "animate_prerigcheck",
            "status": "submitted",
            "trace_id": trace_id,
        }

    def submit_rig(
        self,
        original_model_task_id: str,
        *,
        out_format: str = "glb",
        rig_type: str = "biped",
        spec: str = "tripo",
        model_version: str = "v1.0-20240301",
    ) -> dict[str, object]:
        """Submit a Tripo rigging task after the API layer confirms paid intent."""
        original = self._validate_task_id(original_model_task_id)
        out_format = str(out_format or "").strip().lower()
        rig_type = str(rig_type or "").strip().lower()
        spec = str(spec or "").strip().lower()
        model_version = str(model_version or "").strip()
        if out_format not in _ALLOWED_RIG_FORMATS:
            raise ValueError("Tripo rig output format must be glb or fbx")
        if rig_type not in _ALLOWED_RIG_TYPES:
            raise ValueError("Unsupported Tripo rig type")
        if spec not in _ALLOWED_RIG_SPECS:
            raise ValueError("Tripo rig spec must be tripo or mixamo")
        if model_version not in _ALLOWED_RIG_VERSIONS:
            raise ValueError("Unsupported Tripo rig model version")

        envelope, _status_code, trace_id = self._request_json(
            method="POST",
            path=_TRIPO_TASK_PATH,
            payload={
                "type": "animate_rig",
                "original_model_task_id": original,
                "out_format": out_format,
                "rig_type": rig_type,
                "spec": spec,
                "model_version": model_version,
            },
        )
        data = self._envelope_data(envelope)
        return {
            "provider": self.name,
            "task_id": str(data.get("task_id") or ""),
            "type": "animate_rig",
            "status": "submitted",
            "out_format": out_format,
            "rig_type": rig_type,
            "spec": spec,
            "model_version": model_version,
            "trace_id": trace_id,
        }
