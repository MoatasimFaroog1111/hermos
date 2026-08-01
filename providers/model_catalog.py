"""Model-catalog port and default HTTP adapter.

This module keeps network access out of :mod:`providers.base`. Provider
profiles remain declarative and delegate live model discovery to the
``ModelCatalogClient`` abstraction.

The default adapter preserves the historical urllib behavior, including the
credential-safe redirect policy provided by ``open_credentialed_url``.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

from hermes_cli.urllib_security import open_credentialed_url

logger = logging.getLogger(__name__)


def profile_user_agent() -> str:
    """Return a stable Hermes user agent without creating an import cycle."""
    try:
        from hermes_cli import __version__ as version

        return f"hermes-cli/{version}"
    except Exception:
        return "hermes-cli"


@dataclass(frozen=True)
class ModelCatalogRequest:
    """Immutable input passed from a provider profile to a catalog client."""

    provider_name: str
    base_url: str = ""
    models_url: str = ""
    api_key: str | None = None
    default_headers: Mapping[str, str] = field(default_factory=dict)
    timeout: float = 8.0

    def resolved_url(self) -> str | None:
        """Resolve the catalog endpoint using the public compatibility order."""
        explicit = self.models_url.strip()
        if explicit:
            return explicit
        base = self.base_url.strip()
        if not base:
            return None
        return base.rstrip("/") + "/models"


@runtime_checkable
class ModelCatalogClient(Protocol):
    """Port used by provider profiles to discover live model identifiers."""

    def fetch_models(self, request: ModelCatalogRequest) -> list[str] | None:
        """Return model IDs, or ``None`` when discovery is unavailable."""
        ...


class UrllibModelCatalogClient:
    """Default model-catalog adapter using the hardened urllib transport."""

    def fetch_models(self, request: ModelCatalogRequest) -> list[str] | None:
        url = request.resolved_url()
        if not url:
            return None

        http_request = urllib.request.Request(url)
        if request.api_key:
            http_request.add_header("Authorization", f"Bearer {request.api_key}")
        http_request.add_header("Accept", "application/json")
        http_request.add_header("User-Agent", profile_user_agent())
        for key, value in request.default_headers.items():
            http_request.add_header(key, value)

        try:
            with open_credentialed_url(http_request, timeout=request.timeout) as response:
                payload = json.loads(response.read().decode())
            items = payload if isinstance(payload, list) else payload.get("data", [])
            return [
                item["id"]
                for item in items
                if isinstance(item, dict) and "id" in item
            ]
        except Exception as exc:
            logger.debug("fetch_models(%s): %s", request.provider_name, exc)
            return None


DEFAULT_MODEL_CATALOG_CLIENT: ModelCatalogClient = UrllibModelCatalogClient()
