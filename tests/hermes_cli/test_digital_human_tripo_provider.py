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


class _JsonResponse:
    status = 200
    headers = {"X-Tripo-Trace-ID": "trace-test-123"}

    def __init__(self, payload: dict | None = None):
        self.payload = payload or {
            "code": 0,
            "data": {"balance": 12345, "frozen": 0},
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


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
        return _JsonResponse()

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


def test_tripo_task_status_hides_signed_model_url():
    module = _load_tripo_provider()
    secret = "tsk_task_secret"

    def opener(request, timeout):
        assert request.full_url.endswith("/task/fbf06c3d-b5aa-4f16-b27a-7bfe2260df61")
        assert request.get_header("Authorization") == f"Bearer {secret}"
        return _JsonResponse(
            {
                "code": 0,
                "data": {
                    "task_id": "fbf06c3d-b5aa-4f16-b27a-7bfe2260df61",
                    "type": "image_to_model",
                    "status": "success",
                    "progress": 100,
                    "output": {
                        "model": "https://signed.example/private/model.glb?token=secret",
                        "riggable": True,
                        "rig_type": "biped",
                    },
                },
            }
        )

    provider = module.TripoCharacterProvider(
        api_key_resolver=lambda: secret,
        opener=opener,
    )
    result = provider.get_task("fbf06c3d-b5aa-4f16-b27a-7bfe2260df61")

    assert result["status"] == "success"
    assert result["finalized"] is True
    assert result["model_available"] is True
    assert result["riggable"] is True
    assert result["rig_type"] == "biped"
    serialized = json.dumps(result)
    assert "signed.example" not in serialized
    assert secret not in serialized


def test_tripo_prerig_submission_uses_original_model_task_id():
    module = _load_tripo_provider()
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _JsonResponse(
            {"code": 0, "data": {"task_id": "prerig-task-123"}}
        )

    provider = module.TripoCharacterProvider(
        api_key_resolver=lambda: "tsk_test",
        opener=opener,
    )
    result = provider.submit_prerig_check("model-task-123")

    assert captured["url"] == "https://api.tripo3d.ai/v2/openapi/task"
    assert captured["method"] == "POST"
    assert captured["body"] == {
        "type": "animate_prerigcheck",
        "original_model_task_id": "model-task-123",
    }
    assert result["task_id"] == "prerig-task-123"
    assert result["type"] == "animate_prerigcheck"


def test_tripo_rig_submission_is_biped_glb_and_tripo_spec_by_default():
    module = _load_tripo_provider()
    captured = {}

    def opener(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _JsonResponse({"code": 0, "data": {"task_id": "rig-task-123"}})

    provider = module.TripoCharacterProvider(
        api_key_resolver=lambda: "tsk_test",
        opener=opener,
    )
    result = provider.submit_rig("model-task-123")

    assert captured["body"] == {
        "type": "animate_rig",
        "original_model_task_id": "model-task-123",
        "out_format": "glb",
        "rig_type": "biped",
        "spec": "tripo",
        "model_version": "v1.0-20240301",
    }
    assert result["task_id"] == "rig-task-123"
    assert result["out_format"] == "glb"


def test_plugin_exposes_tripo_descriptor_without_remote_call(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TRIPO_API_KEY", "tsk_descriptor_secret")
    module = _load_plugin_api()

    payload = module._health_payload()

    tripo = payload["character_providers"]["tripo"]
    assert tripo["configured"] is True
    assert tripo["health_endpoint"].endswith("/providers/tripo/health")
    assert tripo["task_endpoint"].endswith("/providers/tripo/tasks/{task_id}")
    assert tripo["prerig_endpoint"].endswith("/{task_id}/prerig-check")
    assert tripo["rig_endpoint"].endswith("/{task_id}/rig")
    assert tripo["rigging_requires_cost_confirmation"] is True
    assert tripo["credentials"] == "server-side-only"
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


def test_plugin_rig_route_requires_explicit_cost_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    module = _load_plugin_api()
    calls = []

    class FakeProvider:
        name = "tripo"

        def configured(self) -> bool:
            return True

        def submit_rig(self, task_id, **kwargs):
            calls.append((task_id, kwargs))
            return {"provider": "tripo", "task_id": "rig-result", "status": "submitted"}

    module._TRIPO_PROVIDER = FakeProvider()
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/hermes-avatar")
    client = TestClient(app)

    denied = client.post(
        "/api/plugins/hermes-avatar/providers/tripo/tasks/model-task/rig",
        json={"confirm_cost": False},
    )
    assert denied.status_code == 409
    assert calls == []

    accepted = client.post(
        "/api/plugins/hermes-avatar/providers/tripo/tasks/model-task/rig",
        json={"confirm_cost": True},
    )
    assert accepted.status_code == 200
    assert accepted.json()["task_id"] == "rig-result"
    assert calls == [
        (
            "model-task",
            {
                "out_format": "glb",
                "rig_type": "biped",
                "spec": "tripo",
                "model_version": "v1.0-20240301",
            },
        )
    ]
