"""Focused smoke coverage for the Hermes Human Behavior Engine."""

import shutil
import subprocess
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DIST = _REPO_ROOT / "plugins" / "hermes-avatar" / "dashboard" / "dist"


def test_digital_human_entry_loads_behavior_before_avatar_runtime():
    source = (_DIST / "digital-human-entry.js").read_text(encoding="utf-8")

    behavior = 'assetUrl("human-behavior-engine.js")'
    avatar = 'assetUrl("avatar-v4.js")'
    assert behavior in source
    assert avatar in source
    assert "behaviorEntry" in source
    assert source.index("loadScript(behaviorEntry)") < source.index("loadScript(avatarEntry)")


def test_human_behavior_engine_separates_behavior_responsibilities():
    source = (_DIST / "human-behavior-engine.js").read_text(encoding="utf-8")

    for controller in (
        "IntervalGate",
        "AttentionController",
        "SaccadeController",
        "BreathController",
        "PostureController",
        "GestureController",
        "HumanBehaviorEngine",
    ):
        assert f"class {controller}" in source

    assert "patchRenderer" in source
    assert "installRendererHook" in source
    assert "speechEnergy" in source
    assert "human behavior fallback" in source


def test_human_behavior_engine_has_state_aware_human_motion():
    source = (_DIST / "human-behavior-engine.js").read_text(encoding="utf-8")

    for state in ("idle", "listening", "thinking", "speaking"):
        assert f'"{state}"' in source

    assert "breakGate" in source
    assert "rateGate" in source
    assert "nextListeningNod" in source
    assert "nextSpeechGesture" in source
    assert "microGate" in source
    assert "pointerActive" in source
    assert "reducedMotion" in source
    assert "prefers-reduced-motion" not in source  # renderer supplies this policy


def test_behavior_layer_fails_open_to_existing_avatar_motion():
    source = (_DIST / "digital-human-entry.js").read_text(encoding="utf-8")

    assert "human behavior engine unavailable; continuing with base motion" in source
    assert ".then(() => loadScript(avatarEntry))" in source


def test_voice_sidecar_has_no_dom_mutation_observer():
    source = (_DIST / "female-voice-entry.js").read_text(encoding="utf-8")

    assert "chooseFemaleVoice" in source
    assert "MutationObserver" not in source
    assert "querySelector" not in source
    assert "document.addEventListener" not in source
    assert "loadAvatarEntry" not in source


def test_human_behavior_runtime_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if node is None:
        return

    for filename in (
        "human-behavior-engine.js",
        "digital-human-entry.js",
        "female-voice-entry.js",
        "avatar-v4.js",
        "three-avatar-renderer.js",
    ):
        result = subprocess.run(
            [node, "--check", str(_DIST / filename)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{filename}: {result.stderr}"
