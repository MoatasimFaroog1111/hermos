"""Tripo-backed character provider for Hermes Digital Human.

This module owns only Tripo API concerns: configuration, authenticated health
checks, transport error normalization, and secret-safe response shaping.  It
intentionally has no FastAPI, UI, avatar-storage, or Hermes-chat dependencies.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Callable

_TRIPO_API_BASE_URL = "https://api.tripo3d.ai/v2/openapi"
_TRIPO_BALANCE_PATH = "/user/balance"
_DEFAULT_TIMEOUT_SECONDS = 8.0
_MAX_PROVIDER_MESSAGE_CHARS = 300


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

    def health(self) -> dict[str, object]:
        """Verify Tripo reachability/authentication without creating a paid task.

        Tripo documents ``GET /user/balance`` as an immediate authenticated
        request, so it is used only as a credential probe.  Wallet values are
        deliberately not returned to the browser.
        """
        api_key = self._api_key_resolver()
        if not api_key:
            return ProviderHealth(
                provider=self.name,
                configured=False,
                reachable=False,
                authenticated=False,
                error="TRIPO_API_KEY is not configured",
            ).as_dict()

        request = urllib.request.Request(
            f"{_TRIPO_API_BASE_URL}{_TRIPO_BALANCE_PATH}",
            method="GET",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )

        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                status_code = int(getattr(response, "status", 200))
                raw = response.read()
                trace_id = self._trace_id(getattr(response, "headers", {}))
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = {}
                api_code = payload.get("code") if isinstance(payload, dict) else None
                authenticated = status_code == 200 and api_code == 0
                error = "" if authenticated else self._provider_message(raw)
                if not authenticated and not error:
                    error = "Tripo authentication check returned an unexpected response"
                return ProviderHealth(
                    provider=self.name,
                    configured=True,
                    reachable=True,
                    authenticated=authenticated,
                    status_code=status_code,
                    trace_id=trace_id,
                    error=error,
                ).as_dict()
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read()
            except OSError:
                raw = b""
            message = self._provider_message(raw)
            if not message:
                message = f"Tripo returned HTTP {exc.code}"
            return ProviderHealth(
                provider=self.name,
                configured=True,
                reachable=True,
                authenticated=False,
                status_code=int(exc.code),
                trace_id=self._trace_id(getattr(exc, "headers", {})),
                error=message,
            ).as_dict()
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            reason = getattr(exc, "reason", None) or str(exc) or type(exc).__name__
            return ProviderHealth(
                provider=self.name,
                configured=True,
                reachable=False,
                authenticated=False,
                error=f"Tripo is unreachable: {str(reason)[:_MAX_PROVIDER_MESSAGE_CHARS]}",
            ).as_dict()
