"""Tests for the Digital Human Tripo provider boundary."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_DIR = _REPO_ROOT / "plugins" / "hermes-avatar" / "dashboard"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_tripo_provider():
    return _load_module(
        "hermes_avatar_tripo_provider_test",
        _PLUGIN_DIR / "tripo_provider.py",
    )


def _load_plugin_api():
    return _load_module(
        "hermes_avatar_dashboard_plugin_api_tripo_test",
        _PLUGIN_DIR / "plugin_api.py",
    )


class _FakeResponse:
    status = 200
    headers = {"X-Tripo-Trace-ID": "trace-test-123"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {
                "code": 0,
                "data": {"balance": 12345, "frozen": 0},
            }
        ).encode("utf-8")


def test_tripo_health_reports_not_configured_without_network_access():
    module = _load_tripo_provider()
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network transport must not run without a key")

    provider = module.TripoCharacterProvider(
        api_key_resolver=lambda: "",
        opener=fail_if_called,
    )

    result = provider.health()

    assert result == {
        "provider": "tripo",
        "configured": False,
        "reachable": False,
        "authenticated": False,
        "status_code": None,
        "trace_id": "",
        "error": "TRIPO_API_KEY is not configured",
    }
    assert called is False


def test_tripo_health_uses_balance_probe_and_never_exposes_secret():
    module = _load_tripo_provider()
    secret = "tsk_super_secret_value"
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return _FakeResponse()

    provider = module.TripoCharacterProvider(
        api_key_resolver=lambda: secret,
        opener=opener,
        timeout_seconds=3.5,
    )

    result = provider.health()

    assert captured == {
        "url": "https://api.tripo3d.ai/v2/openapi/user/balance",
        "method": "GET",
        "authorization": f"Bearer {secret}",
        "timeout": 3.5,
    }
    assert result == {
        "provider": "tripo",
        "configured": True,
        "reachable": True,
        "authenticated": True,
        "status_code": 200,
        "trace_id": "trace-test-123",
        "error": "",
    }
    serialized = json.dumps(result)
    assert secret not in serialized
    assert "balance" not in serialized
    assert "frozen" not in serialized


def test_plugin_exposes_tripo_descriptor_without_remote_call(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TRIPO_API_KEY", "tsk_descriptor_secret")
    module = _load_plugin_api()

    payload = module._health_payload()

    assert payload["character_providers"]["tripo"] == {
        "configured": True,
        "health_endpoint": "/api/plugins/hermes-avatar/providers/tripo/health",
        "credentials": "server-side-only",
    }
    assert "tsk_descriptor_secret" not in json.dumps(payload)


def test_plugin_tripo_health_route_depends_on_provider_contract(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    module = _load_plugin_api()

    class FakeProvider:
        name = "tripo"

        def configured(self) -> bool:
            return True

        def health(self) -> dict[str, object]:
            return {
                "provider": "tripo",
                "configured": True,
                "reachable": True,
                "authenticated": True,
                "status_code": 200,
                "trace_id": "fake-trace",
                "error": "",
            }

    module._TRIPO_PROVIDER = FakeProvider()
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/hermes-avatar")
    client = TestClient(app)

    response = client.get("/api/plugins/hermes-avatar/providers/tripo/health")

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["trace_id"] == "fake-trace"
