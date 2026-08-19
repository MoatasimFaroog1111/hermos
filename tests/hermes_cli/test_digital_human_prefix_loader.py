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
    / "digital-human-entry.js"
)
_AVATAR = _ENTRY.with_name("avatar-v4.js")


def test_digital_human_nested_assets_follow_dashboard_prefix():
    source = _ENTRY.read_text(encoding="utf-8")
    avatar = _AVATAR.read_text(encoding="utf-8")

    assert "document.currentScript?.src" in source
    assert "window.__HERMES_BASE_PATH__" in source
    assert "new URL(ENTRY_SCRIPT_URL, window.location.href)" in source
    assert "new URL(fileName, entry)" in source

    for asset in (
        "deterministic-avatar-policy.js",
        "female-voice-entry.js",
        "human-behavior-engine.js",
        "avatar-v4.js",
    ):
        assert f'assetUrl("{asset}")' in source

    assert 'const avatarEntry = "/dashboard-plugins/' not in source
    assert 'const behaviorEntry = "/dashboard-plugins/' not in source

    # The renderer remains lazy-owned by avatar-v4 and inherits the entry
    # revision/query rather than using a stale absolute URL.
    assert "document.currentScript?.src" in avatar
    assert "new URL(OWN_SCRIPT_URL, window.location.href)" in avatar
    assert 'new URL("three-avatar-renderer.js", own)' in avatar
    assert "if (own.search) resolved.search = own.search;" in avatar


def test_digital_human_loads_behavior_before_lazy_avatar_renderer_path():
    source = _ENTRY.read_text(encoding="utf-8")
    avatar = _AVATAR.read_text(encoding="utf-8")

    assert "loadScript(behaviorEntry)" in source
    assert "loadScript(avatarEntry)" in source
    assert source.index("loadScript(behaviorEntry)") < source.index("loadScript(avatarEntry)")
    assert "loadRendererModule()" in avatar
    assert "window.__HERMES_AVATAR_RENDERER__?.ThreeAvatarRenderer" in avatar


def test_digital_human_loader_has_bounded_wait_and_visible_retry_state():
    source = _ENTRY.read_text(encoding="utf-8")

    assert "const SCRIPT_TIMEOUT_MS = 12000" in source
    assert "Timed out loading" in source
    assert "DigitalHumanEntryErrorPage" in source
    assert 'REGISTRY.register("hermes-avatar", DigitalHumanEntryErrorPage)' in source
    assert "RETRY DIGITAL HUMAN" in source
    assert "window.location.reload()" in source


def test_optional_runtime_failures_degrade_but_avatar_failure_is_terminal():
    source = _ENTRY.read_text(encoding="utf-8")

    assert "deterministic animation policy failed" in source
    assert "female voice runtime failed" in source
    assert "human behavior engine unavailable; continuing with base motion" in source
    assert ".then(() => loadScript(avatarEntry))" in source
    assert "base Digital Human entry failed" in source
