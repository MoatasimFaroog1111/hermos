"""Regression coverage for the Digital Human dashboard registration contract."""

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
_AVATAR = _ENTRY.with_name("avatar-v4.js")
_PLUGIN_LOADER = _REPO_ROOT / "web" / "src" / "plugins" / "usePlugins.ts"


def test_dashboard_requires_registration_immediately_after_entry_load():
    loader = _PLUGIN_LOADER.read_text(encoding="utf-8")

    assert "queueMicrotask(() =>" in loader
    assert "getPluginComponent(manifest.name)" in loader
    assert 'setPluginLoadError(manifest.name, "NO_REGISTER")' in loader


def test_digital_human_entry_registers_before_async_runtime_loading():
    source = _ENTRY.read_text(encoding="utf-8")

    register = 'REGISTRY.register("hermes-avatar", DigitalHumanBootstrapPage)'
    assert "function DigitalHumanBootstrapPage()" in source
    assert register in source
    assert "loadAvatarEntry();" in source
    assert source.index(register) < source.index("loadAvatarEntry();")


def test_full_avatar_replaces_bootstrap_registration_when_ready():
    source = _AVATAR.read_text(encoding="utf-8")

    assert 'REGISTRY.register("hermes-avatar", DigitalHumanPage)' in source
