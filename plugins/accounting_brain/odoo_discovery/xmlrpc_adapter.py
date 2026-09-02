"""XML-RPC adapter implementing the read-only Odoo port.

No create/write/unlink/action_post/reconcile method is exposed. The private
executor also enforces an explicit read-method allow-list as defense in depth.
"""

from __future__ import annotations

import xmlrpc.client
from typing import Any, Sequence

from plugins.accounting_brain.odoo_discovery.contracts import (
    OdooCredentials,
    OdooReadError,
    OdooReadPort,
)


_READ_METHODS = frozenset(
    {
        "fields_get",
        "search",
        "read",
        "search_read",
        "search_count",
    }
)


class OdooXmlRpcReadAdapter(OdooReadPort):
    """Production Odoo adapter restricted to non-mutating RPC methods."""

    def __init__(self, credentials: OdooCredentials) -> None:
        self._credentials = credentials
        base_url = credentials.url.rstrip("/")
        self._common = xmlrpc.client.ServerProxy(
            f"{base_url}/xmlrpc/2/common",
            allow_none=True,
        )
        self._objects = xmlrpc.client.ServerProxy(
            f"{base_url}/xmlrpc/2/object",
            allow_none=True,
        )
        self._uid: int | None = None

    def authenticate(self) -> int:
        if self._uid is not None:
            return self._uid
        try:
            uid = self._common.authenticate(
                self._credentials.database,
                self._credentials.username,
                self._credentials.api_key,
                {},
            )
        except Exception as exc:  # credentials must never enter the message
            raise OdooReadError(
                f"Odoo authentication request failed ({type(exc).__name__})"
            ) from exc
        if not uid:
            raise OdooReadError("Odoo authentication was rejected")
        self._uid = int(uid)
        return self._uid

    def version(self) -> dict[str, Any]:
        try:
            value = self._common.version()
        except Exception as exc:
            raise OdooReadError(
                f"Unable to read Odoo version ({type(exc).__name__})"
            ) from exc
        return dict(value or {})

    def fields_get(
        self,
        model: str,
        *,
        attributes: Sequence[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        if attributes:
            kwargs["attributes"] = list(attributes)
        value = self._execute_read(model, "fields_get", [], kwargs)
        return dict(value or {})

    def search_read(
        self,
        model: str,
        domain: list[Any],
        *,
        fields: Sequence[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"offset": max(0, int(offset))}
        if fields is not None:
            kwargs["fields"] = list(fields)
        if limit is not None:
            kwargs["limit"] = max(0, int(limit))
        if order:
            kwargs["order"] = str(order)
        value = self._execute_read(model, "search_read", [domain], kwargs)
        return [dict(item) for item in (value or [])]

    def read(
        self,
        model: str,
        ids: Sequence[int],
        *,
        fields: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_ids = [int(item) for item in ids]
        if not normalized_ids:
            return []
        kwargs: dict[str, Any] = {}
        if fields is not None:
            kwargs["fields"] = list(fields)
        value = self._execute_read(model, "read", [normalized_ids], kwargs)
        return [dict(item) for item in (value or [])]

    def search_count(self, model: str, domain: list[Any]) -> int:
        value = self._execute_read(model, "search_count", [domain], {})
        return int(value or 0)

    def _execute_read(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any],
    ) -> Any:
        if method not in _READ_METHODS:
            raise OdooReadError(f"Blocked non-read Odoo method: {method}")
        uid = self.authenticate()
        try:
            return self._objects.execute_kw(
                self._credentials.database,
                uid,
                self._credentials.api_key,
                model,
                method,
                args,
                kwargs,
            )
        except xmlrpc.client.Fault as exc:
            # Fault text can contain model/field details, but never echo the
            # request payload or credentials.
            raise OdooReadError(
                f"Odoo read failed for {model}.{method}: fault {exc.faultCode}"
            ) from exc
        except Exception as exc:
            raise OdooReadError(
                f"Odoo read failed for {model}.{method} ({type(exc).__name__})"
            ) from exc
