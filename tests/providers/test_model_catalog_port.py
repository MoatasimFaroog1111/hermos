"""Contract tests for the provider model-catalog abstraction."""

from providers.base import ProviderProfile
from providers.model_catalog import (
    ModelCatalogClient,
    ModelCatalogRequest,
    UrllibModelCatalogClient,
)


class RecordingCatalogClient:
    def __init__(self, result=None):
        self.result = result
        self.requests = []

    def fetch_models(self, request: ModelCatalogRequest):
        self.requests.append(request)
        return self.result


def test_profile_delegates_model_discovery_to_injected_port():
    client = RecordingCatalogClient(["model-a", "model-b"])
    profile = ProviderProfile(
        name="example",
        base_url="https://default.example/v1",
        models_url="https://catalog.example/models",
        default_headers={"X-Tenant": "tenant-a"},
        catalog_client=client,
    )

    result = profile.fetch_models(
        api_key="secret",
        base_url="https://runtime.example/v1",
        timeout=3.5,
    )

    assert result == ["model-a", "model-b"]
    assert len(client.requests) == 1
    request = client.requests[0]
    assert request.provider_name == "example"
    assert request.models_url == "https://catalog.example/models"
    assert request.base_url == "https://runtime.example/v1"
    assert request.api_key == "secret"
    assert request.default_headers == {"X-Tenant": "tenant-a"}
    assert request.timeout == 3.5


def test_catalog_request_resolution_preserves_existing_precedence():
    explicit = ModelCatalogRequest(
        provider_name="example",
        models_url="https://catalog.example/list",
        base_url="https://runtime.example/v1",
    )
    fallback = ModelCatalogRequest(
        provider_name="example",
        base_url="https://runtime.example/v1/",
    )
    missing = ModelCatalogRequest(provider_name="example")

    assert explicit.resolved_url() == "https://catalog.example/list"
    assert fallback.resolved_url() == "https://runtime.example/v1/models"
    assert missing.resolved_url() is None


def test_default_adapter_satisfies_catalog_contract():
    assert isinstance(UrllibModelCatalogClient(), ModelCatalogClient)
