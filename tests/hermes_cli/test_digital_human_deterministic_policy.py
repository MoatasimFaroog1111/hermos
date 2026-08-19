"""Regression coverage for deterministic Digital Human animation/face policy."""

from __future__ import annotations

import json
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN = _REPO_ROOT / "plugins" / "hermes-avatar" / "dashboard"
_MANIFEST = _PLUGIN / "manifest.json"
_ENTRY = _PLUGIN / "dist" / "digital-human-entry.js"
_VOICE_ENTRY = _PLUGIN / "dist" / "female-voice-entry.js"
_POLICY = _PLUGIN / "dist" / "deterministic-avatar-policy.js"
_HOST_LOADER = _REPO_ROOT / "web" / "src" / "plugins" / "usePlugins.ts"


def test_manifest_routes_through_deterministic_entry():
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))

    assert manifest["entry"] == "dist/digital-human-entry.js"
    assert manifest["api"] == "plugin_api_entry.py"
    assert manifest["version"] == "0.8.9"


def test_wrapper_registers_synchronously_before_async_loading():
    source = _ENTRY.read_text(encoding="utf-8")
    register = 'REGISTRY.register("hermes-avatar", DigitalHumanBootstrapPage)'
    policy = 'assetUrl("deterministic-avatar-policy.js")'
    voice = 'assetUrl("female-voice-entry.js")'
    behavior = 'assetUrl("human-behavior-engine.js")'
    avatar = 'assetUrl("avatar-v4.js")'

    assert register in source
    assert policy in source
    assert voice in source
    assert behavior in source
    assert avatar in source
    assert source.index(register) < source.index("loadScript(policyEntry)")
    assert source.index(policy) < source.index(voice) < source.index(behavior) < source.index(avatar)


def test_wrapper_does_not_gate_primary_avatar_on_optional_sidecars():
    source = _ENTRY.read_text(encoding="utf-8")

    assert "SCRIPT_TIMEOUT_MS = 12000" in source
    assert "loadScript(voiceEntry).catch" in source
    assert "loadScript(behaviorEntry).catch" in source
    assert ".then(() => loadScript(avatarEntry))" in source
    assert 'window[AVATAR_READY_FLAG] = true' in source
    assert "female voice runtime failed" in source
    assert "human behavior engine unavailable; continuing with base motion" in source


def test_plugin_asset_revision_propagates_from_host_to_nested_runtime():
    host = _HOST_LOADER.read_text(encoding="utf-8")
    wrapper = _ENTRY.read_text(encoding="utf-8")
    voice = _VOICE_ENTRY.read_text(encoding="utf-8")

    assert 'params.set("hermes_plugin_v", version)' in host
    assert "pluginAssetUrl(manifest, manifest.css)" in host
    assert "pluginAssetUrl(manifest, manifest.entry)" in host
    assert "loadedScripts.current.delete(scriptSrc)" in host

    assert "if (entry.search) resolved.search = entry.search;" in wrapper
    for filename in (
        "deterministic-avatar-policy.js",
        "female-voice-entry.js",
        "human-behavior-engine.js",
        "avatar-v4.js",
    ):
        assert f'assetUrl("{filename}")' in wrapper

    # The voice sidecar is intentionally pure: it no longer owns nested asset
    # loading or DOM lifecycle. The composition root above is the single owner.
    assert "pluginAssetUrl" not in voice
    assert "MutationObserver" not in voice
    assert "querySelector" not in voice


def test_animation_policy_never_uses_random_clip_selection():
    source = _POLICY.read_text(encoding="utf-8")

    assert "Math.random" not in source
    assert "resolveExplicit" in source
    assert "resolveSemantic" in source
    assert "matches.length === 1" in source
    assert "generic Tripo name such as NlaTrack" in source
    assert "this.mixer.stopAllAction()" in source


def test_policy_supports_explicit_name_or_index_mapping():
    source = _POLICY.read_text(encoding="utf-8")

    assert "Number.isInteger(target)" in source
    assert "normalizeName(clip?.name) === normalized" in source
    for role in ("idle", "listening", "thinking", "speaking", "error"):
        assert f'{role}: "{role}"' in source


def test_face_policy_targets_arkit_52_and_reports_lipsync_readiness():
    source = _POLICY.read_text(encoding="utf-8")

    assert 'const ARKIT_52 = Object.freeze([' in source
    assert '"eyeBlinkLeft"' in source
    assert '"eyeBlinkRight"' in source
    assert '"jawOpen"' in source
    assert '"mouthFunnel"' in source
    assert '"mouthPucker"' in source
    assert '"mouthSmileLeft"' in source
    assert '"mouthSmileRight"' in source
    assert '"tongueOut"' in source
    assert "arkitCoverage" in source
    assert "lipSyncReady" in source
    assert 'requiredFaceStandard: "ARKit-52-compatible morph targets"' in source


def test_policy_preserves_full_gltf_animation_catalog_before_selection():
    source = _POLICY.read_text(encoding="utf-8")

    assert "capturedGLTF?.animations" in source
    assert "__hermesAnimationClips" in source
    assert "__hermesAnimationPolicy" in source
    assert "animationCatalog" in source
