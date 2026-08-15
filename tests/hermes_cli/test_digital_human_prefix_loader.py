"""Regression coverage for Digital Human asset loading behind URL prefixes."""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENTRY = (
    _REPO_ROOT
    / "plugins"
    / "hermes-avatar"
    / "dashboard"
    / "dist"
    / "female-voice-entry.js"
)


def test_digital_human_nested_assets_follow_dashboard_prefix():
    source = _ENTRY.read_text(encoding="utf-8")

    assert "document.currentScript?.src" in source
    assert "window.__HERMES_BASE_PATH__" in source
    assert "new URL(fileName, ENTRY_SCRIPT_URL)" in source

    for asset in (
        "avatar-v4.js",
        "human-behavior-engine.js",
        "three-avatar-renderer.js",
        "realistic.css",
    ):
        assert f'pluginAssetUrl("{asset}")' in source

    assert 'const AVATAR_ENTRY = "/dashboard-plugins/' not in source
    assert 'const HUMAN_BEHAVIOR_ENTRY = "/dashboard-plugins/' not in source


def test_digital_human_preloads_renderer_before_avatar_entry():
    source = _ENTRY.read_text(encoding="utf-8")

    assert "const startRenderer = () =>" in source
    assert "startRenderer," in source
    assert "window.__HERMES_AVATAR_RENDERER__?.ThreeAvatarRenderer" in source
    assert "window[AVATAR_READY_FLAG] = true" in source
