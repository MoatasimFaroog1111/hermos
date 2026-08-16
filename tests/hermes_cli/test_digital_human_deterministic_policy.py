"""Regression coverage for deterministic Digital Human animation/face policy."""

from __future__ import annotations

import json
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN = _REPO_ROOT / "plugins" / "hermes-avatar" / "dashboard"
_MANIFEST = _PLUGIN / "manifest.json"
_ENTRY = _PLUGIN / "dist" / "digital-human-entry.js"
_POLICY = _PLUGIN / "dist" / "deterministic-avatar-policy.js"


def test_manifest_routes_through_deterministic_entry():
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))

    assert manifest["entry"] == "dist/digital-human-entry.js"
    assert manifest["api"] == "plugin_api_entry.py"
    assert manifest["version"] == "0.8.2"


def test_wrapper_registers_synchronously_before_async_loading():
    source = _ENTRY.read_text(encoding="utf-8")
    register = 'REGISTRY.register("hermes-avatar", DigitalHumanBootstrapPage)'
    policy = 'assetUrl("deterministic-avatar-policy.js")'
    base = 'assetUrl("female-voice-entry.js")'

    assert register in source
    assert policy in source
    assert base in source
    assert source.index(register) < source.index("loadScript(policyEntry)")
    assert source.index(policy) < source.index(base)


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
