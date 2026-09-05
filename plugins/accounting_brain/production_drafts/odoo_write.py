"""Create-only Odoo boundary for explicitly approved Accounting Brain drafts.

This adapter intentionally exposes exactly one mutation: creating a new
``account.move`` in draft state. There is no generic write(), unlink(), post(),
reconcile(), payment, or state-transition method.
"""

from __future__ import annotations

import os
import xmlrpc.client
from typing import Any, Protocol

from plugins.accounting_brain.odoo_discovery.contracts import OdooCredentials


class OdooDraftWriteError(RuntimeError):
    """Raised when an explicitly approved Odoo draft cannot be created."""


class OdooDraftWritePort(Protocol):
    def create_draft_move(self, values: dict[str, Any]) -> int:
        """Create one new account.move that must remain in draft state."""


_DEFAULT_TIMEOUT_SECONDS = 60.0


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout_seconds: float) -> None:
        super().__init__()
        self._timeout_seconds = timeout_seconds

    def make_connection(self, host: str):  # type: ignore[no-untyped-def]
        connection = super().make_connection(host)
        connection.timeout = self._timeout_seconds
        return connection


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout_seconds: float) -> None:
        super().__init__()
        self._timeout_seconds = timeout_seconds

    def make_connection(self, host: str):  # type: ignore[no-untyped-def]
        connection = super().make_connection(host)
        connection.timeout = self._timeout_seconds
        return connection


def _timeout_seconds() -> float:
    raw = (os.environ.get("ODOO_WRITE_TIMEOUT_SECONDS") or "").strip()
    try:
        value = float(raw) if raw else _DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        value = _DEFAULT_TIMEOUT_SECONDS
    if value != value:
        value = _DEFAULT_TIMEOUT_SECONDS
    return min(max(value, 5.0), 300.0)


def _transport(base_url: str, timeout: float):
    if base_url.lower().startswith("https://"):
        return _TimeoutSafeTransport(timeout)
    return _TimeoutTransport(timeout)


class OdooXmlRpcDraftCreateAdapter(OdooDraftWritePort):
    """Production adapter hard-coded to ``account.move.create`` only."""

    def __init__(self, credentials: OdooCredentials) -> None:
        self._credentials = credentials
        base_url = credentials.url.rstrip("/")
        timeout = _timeout_seconds()
        self._common = xmlrpc.client.ServerProxy(
            f"{base_url}/xmlrpc/2/common",
            allow_none=True,
            transport=_transport(base_url, timeout),
        )
        self._objects = xmlrpc.client.ServerProxy(
            f"{base_url}/xmlrpc/2/object",
            allow_none=True,
            transport=_transport(base_url, timeout),
        )
        self._uid: int | None = None

    def create_draft_move(self, values: dict[str, Any]) -> int:
        payload = _validated_create_payload(values)
        uid = self._authenticate()
        try:
            move_id = self._objects.execute_kw(
                self._credentials.database,
                uid,
                self._credentials.api_key,
                "account.move",
                "create",
                [payload],
                {},
            )
        except xmlrpc.client.Fault as exc:
            raise OdooDraftWriteError(
                f"Odoo draft creation failed: fault {exc.faultCode}"
            ) from exc
        except Exception as exc:
            raise OdooDraftWriteError(
                f"Odoo draft creation failed ({type(exc).__name__})"
            ) from exc
        try:
            identifier = int(move_id)
        except (TypeError, ValueError) as exc:
            raise OdooDraftWriteError("Odoo returned an invalid draft move id") from exc
        if identifier <= 0:
            raise OdooDraftWriteError("Odoo returned an invalid draft move id")
        return identifier

    def _authenticate(self) -> int:
        if self._uid is not None:
            return self._uid
        try:
            uid = self._common.authenticate(
                self._credentials.database,
                self._credentials.username,
                self._credentials.api_key,
                {},
            )
        except Exception as exc:
            raise OdooDraftWriteError(
                f"Odoo authentication request failed ({type(exc).__name__})"
            ) from exc
        if not uid:
            raise OdooDraftWriteError("Odoo authentication was rejected")
        self._uid = int(uid)
        return self._uid


def _validated_create_payload(values: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(values, dict) or not values:
        raise OdooDraftWriteError("Draft create payload is empty")
    payload = dict(values)
    state = payload.pop("state", "draft")
    if state != "draft":
        raise OdooDraftWriteError("Only draft account.move creation is permitted")
    if "line_ids" not in payload or not payload["line_ids"]:
        raise OdooDraftWriteError("Draft account.move requires journal lines")
    forbidden = {
        "posted_before",
        "payment_state",
        "secure_sequence_number",
        "inalterable_hash",
    }
    if forbidden.intersection(payload):
        raise OdooDraftWriteError("Unsafe account.move fields were supplied")
    return payload
