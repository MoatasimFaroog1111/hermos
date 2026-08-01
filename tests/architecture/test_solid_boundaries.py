"""Behavioral contracts that protect the provider catalog SOLID boundary.

The tests exercise observable collaboration between the provider profile and
its model-catalog port. They deliberately avoid inspecting source text so
implementation details can be refactored without weakening the contract.
"""

from __future__ import annotations

import json

import providers.model_catalog as model_catalog
from providers.base import ProviderProfile
from providers.model_catalog import ModelCatalogRequest, UrllibModelCatalogClient


class RecordingCatalogClient:
    def __init__(self, result: list[str] | None = None) -> None:
        self.result = result
        self.requests: list[ModelCatalogRequest] = []

    def fetch_models(self, request: ModelCatalogRequest) -> list[str] | None:
        self.requests.append(request)
        return self.result


class FailingCatalogClient:
    def fetch_models(self, request: ModelCatalogRequest) -> list[str] | None:
        raise AssertionError("the default infrastructure adapter must not be used")


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def test_provider_profile_honors_injected_catalog_port(monkeypatch) -> None:
    """A profile depends on the injected port, not the default HTTP adapter."""
    injected = RecordingCatalogClient(["model-a", "model-b"])
    monkeypatch.setattr(
        model_catalog,
        "DEFAULT_MODEL_CATALOG_CLIENT",
        FailingCatalogClient(),
    )
    profile = ProviderProfile(
        name="example",
        base_url="https://provider.example/v1",
        models_url="https://catalog.example/models",
        default_headers={"X-Tenant": "tenant-a"},
        catalog_client=injected,
    )

    assert profile.fetch_models(api_key="secret", timeout=3.5) == [
        "model-a",
        "model-b",
    ]
    assert injected.requests == [
        ModelCatalogRequest(
            provider_name="example",
            base_url="https://provider.example/v1",
            models_url="https://catalog.example/models",
            api_key="secret",
            default_headers={"X-Tenant": "tenant-a"},
            timeout=3.5,
        )
    ]


def test_urllib_adapter_translates_port_request_to_hardened_http(monkeypatch) -> None:
    """The concrete adapter owns HTTP request construction and response parsing."""
    captured: dict[str, object] = {}

    def fake_open_credentialed_url(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse({"data": [{"id": "model-a"}, {"name": "ignored"}]})

    monkeypatch.setattr(
        model_catalog,
        "open_credentialed_url",
        fake_open_credentialed_url,
    )

    result = UrllibModelCatalogClient().fetch_models(
        ModelCatalogRequest(
            provider_name="example",
            models_url="https://catalog.example/models",
            api_key="secret",
            default_headers={"X-Tenant": "tenant-a"},
            timeout=4.25,
        )
    )

    assert result == ["model-a"]
    assert captured["timeout"] == 4.25
    request = captured["request"]
    assert request.full_url == "https://catalog.example/models"
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["authorization"] == "Bearer secret"
    assert headers["accept"] == "application/json"
    assert headers["x-tenant"] == "tenant-a"
    assert headers["user-agent"].startswith("hermes-cli")
