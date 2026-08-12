"""Smoke tests for the bundled Hermes Digital Human dashboard plugin."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_DIR = _REPO_ROOT / "plugins" / "hermes-avatar" / "dashboard"
_MANIFEST_PATH = _PLUGIN_DIR / "manifest.json"


def _load_plugin_api() -> ModuleType:
    module_name = "hermes_avatar_dashboard_plugin_api_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        _PLUGIN_DIR / "plugin_api.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _minimal_glb() -> bytes:
    json_chunk = b"{}  "
    total_length = 12 + 8 + len(json_chunk)
    return (
        b"glTF"
        + (2).to_bytes(4, "little")
        + total_length.to_bytes(4, "little")
        + len(json_chunk).to_bytes(4, "little")
        + b"JSON"
        + json_chunk
    )


@pytest.fixture
def avatar_client(monkeypatch, tmp_path):
    home = tmp_path / "hermes-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_AVATAR_GLB_URL", raising=False)

    plugin_api = _load_plugin_api()
    app = FastAPI()
    app.include_router(plugin_api.router, prefix="/api/plugins/hermes-avatar")
    return TestClient(app), home


def test_manifest_points_to_v4_runtime_assets():
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["name"] == "hermes-avatar"
    assert manifest["version"] == "0.4.0"
    assert manifest["tab"]["path"] == "/digital-human"
    assert manifest["entry"] == "dist/avatar-v4.js"
    assert manifest["css"] == "dist/realistic.css"
    assert manifest["api"] == "plugin_api.py"

    for relative_path in (manifest["entry"], manifest["css"], manifest["api"]):
        assert (_PLUGIN_DIR / relative_path).is_file(), relative_path

    assert (_PLUGIN_DIR / "dist" / "three-avatar-renderer.js").is_file()


def test_v4_entry_registers_plugin_and_supports_secure_upload():
    source = (_PLUGIN_DIR / "dist" / "avatar-v4.js").read_text(encoding="utf-8")

    assert 'REGISTRY.register("hermes-avatar", DigitalHumanPage)' in source
    assert "/dashboard-plugins/hermes-avatar/dist/three-avatar-renderer.js" in source
    assert "/api/plugins/hermes-avatar/avatar-model" in source
    assert "AvatarModelStore" in source
    assert "SDK.authedFetch" in source
    assert "LOAD GLB" in source


def test_three_renderer_uses_lazy_sdk_runtime_and_morph_targets():
    source = (_PLUGIN_DIR / "dist" / "three-avatar-renderer.js").read_text(
        encoding="utf-8"
    )

    assert "SDK.graphics?.loadThreeRuntime" in source
    assert "GLTFLoader" in source
    assert "morphTargetDictionary" in source
    assert "eyeBlinkLeft" in source
    assert "jawOpen" in source
    assert "procedural-fallback" in source


def test_dashboard_sdk_exposes_lazy_three_runtime():
    registry_source = (
        _REPO_ROOT / "web" / "src" / "plugins" / "registry.ts"
    ).read_text(encoding="utf-8")
    types_source = (
        _REPO_ROOT / "web" / "src" / "plugins" / "sdk.d.ts"
    ).read_text(encoding="utf-8")

    assert 'SDK_CONTRACT_VERSION = "1.2.0"' in registry_source
    assert "loadThreeRuntime" in registry_source
    assert 'import("three/examples/jsm/loaders/GLTFLoader.js")' in registry_source
    assert "HermesPluginThreeRuntime" in types_source
    assert "loadThreeRuntime" in types_source


def test_avatar_model_url_allows_only_same_origin_or_https(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    plugin_api = _load_plugin_api()

    monkeypatch.delenv("HERMES_AVATAR_GLB_URL", raising=False)
    assert plugin_api._avatar_model_url() == ""

    monkeypatch.setenv(
        "HERMES_AVATAR_GLB_URL",
        "/dashboard-plugins/hermes-avatar/assets/avatar.glb",
    )
    assert (
        plugin_api._avatar_model_url()
        == "/dashboard-plugins/hermes-avatar/assets/avatar.glb"
    )

    monkeypatch.setenv(
        "HERMES_AVATAR_GLB_URL",
        "https://assets.example.com/hermes.glb",
    )
    assert plugin_api._avatar_model_url() == "https://assets.example.com/hermes.glb"

    rejected_urls = (
        "http://assets.example.com/hermes.glb",
        "//assets.example.com/hermes.glb",
        "/\\assets.example.com/hermes.glb",
        "https:///missing-host.glb",
    )
    for rejected_url in rejected_urls:
        monkeypatch.setenv("HERMES_AVATAR_GLB_URL", rejected_url)
        assert plugin_api._avatar_model_url() == ""


def test_avatar_upload_get_delete_lifecycle(avatar_client):
    client, home = avatar_client
    glb = _minimal_glb()

    before = client.get("/api/plugins/hermes-avatar/health")
    assert before.status_code == 200
    before_data = before.json()
    assert before_data["version"] == "0.4.0"
    assert before_data["avatar_upload_supported"] is True
    assert before_data["avatar_model_configured"] is False

    uploaded = client.put(
        "/api/plugins/hermes-avatar/avatar-model",
        content=glb,
        headers={"Content-Type": "model/gltf-binary"},
    )
    assert uploaded.status_code == 200, uploaded.text
    uploaded_data = uploaded.json()
    assert uploaded_data["avatar_uploaded"] is True
    assert uploaded_data["avatar_provider"] == "uploaded-glb"
    assert uploaded_data["avatar_model_requires_auth"] is True
    assert uploaded_data["uploaded_bytes"] == len(glb)

    stored = home / "dashboard-assets" / "hermes-avatar" / "avatar.glb"
    assert stored.read_bytes() == glb

    fetched = client.get("/api/plugins/hermes-avatar/avatar-model")
    assert fetched.status_code == 200
    assert fetched.content == glb
    assert fetched.headers["content-type"].startswith("model/gltf-binary")
    assert fetched.headers["cache-control"] == "no-store"

    removed = client.delete("/api/plugins/hermes-avatar/avatar-model")
    assert removed.status_code == 200
    removed_data = removed.json()
    assert removed_data["removed"] is True
    assert removed_data["avatar_uploaded"] is False
    assert not stored.exists()

    missing = client.get("/api/plugins/hermes-avatar/avatar-model")
    assert missing.status_code == 404


def test_avatar_upload_rejects_non_glb(avatar_client):
    client, home = avatar_client

    response = client.put(
        "/api/plugins/hermes-avatar/avatar-model",
        content=b"not-a-glb",
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 400
    assert "not a GLB" in response.json()["detail"]
    stored = home / "dashboard-assets" / "hermes-avatar" / "avatar.glb"
    assert not stored.exists()
