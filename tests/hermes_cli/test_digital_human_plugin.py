"""Smoke tests for the bundled Hermes Digital Human dashboard plugin."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


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


def test_manifest_points_to_v3_runtime_assets():
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["name"] == "hermes-avatar"
    assert manifest["version"] == "0.3.0"
    assert manifest["tab"]["path"] == "/digital-human"
    assert manifest["entry"] == "dist/avatar-v3.js"
    assert manifest["css"] == "dist/realistic.css"
    assert manifest["api"] == "plugin_api.py"

    for relative_path in (manifest["entry"], manifest["css"], manifest["api"]):
        assert (_PLUGIN_DIR / relative_path).is_file(), relative_path

    assert (_PLUGIN_DIR / "dist" / "three-avatar-renderer.js").is_file()


def test_v3_entry_registers_plugin_and_loads_renderer_module():
    source = (_PLUGIN_DIR / "dist" / "avatar-v3.js").read_text(encoding="utf-8")

    assert 'REGISTRY.register("hermes-avatar", DigitalHumanPage)' in source
    assert "/dashboard-plugins/hermes-avatar/dist/three-avatar-renderer.js" in source
    assert "loadRendererModule()" in source
    assert "avatar_model_url" in source


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


def test_avatar_model_url_allows_only_same_origin_or_https(monkeypatch):
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
