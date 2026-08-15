"""Focused smoke coverage for the Hermes Human Behavior Engine."""

from pathlib import Path
import shutil
import subprocess


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DIST = _REPO_ROOT / "plugins" / "hermes-avatar" / "dashboard" / "dist"


def test_female_voice_entry_loads_behavior_before_avatar_runtime():
    source = (_DIST / "female-voice-entry.js").read_text(encoding="utf-8")

    behavior = "/dashboard-plugins/hermes-avatar/dist/human-behavior-engine.js"
    avatar = "/dashboard-plugins/hermes-avatar/dist/avatar-v4.js"
    assert behavior in source
    assert avatar in source
    assert "HUMAN_BEHAVIOR_ENTRY" in source
    assert "window.__HERMES_HUMAN_BEHAVIOR__" in source
    assert source.index("HUMAN_BEHAVIOR_ENTRY") < source.index("loadAvatarEntry();")


def test_human_behavior_engine_separates_behavior_responsibilities():
    source = (_DIST / "human-behavior-engine.js").read_text(encoding="utf-8")

    assert 'const VERSION = "1.0.0"' in source
    assert "class AttentionController" in source
    assert "class BlinkController" in source
    assert "class ExpressionController" in source
    assert "class BodyMotionController" in source
    assert "class HumanBehaviorEngine" in source
    assert "class HumanizedThreeAvatarRenderer" in source
    assert "decorateRendererModule" in source
    assert "installRendererHook" in source


def test_human_behavior_engine_has_state_aware_human_motion():
    source = (_DIST / "human-behavior-engine.js").read_text(encoding="utf-8")

    for state in ("idle", "listening", "thinking", "speaking", "error"):
        assert f'"{state}"' in source

    assert "pendingSecondBlink" in source
    assert "briefBreak" in source
    assert "nextWeightShiftAt" in source
    assert "nextGestureAt" in source
    assert "eyeSquintLeft" in source
    assert "eyeSquintRight" in source
    assert "prefers-reduced-motion" not in source  # renderer supplies this policy


def test_behavior_layer_fails_open_to_existing_avatar_motion():
    source = (_DIST / "female-voice-entry.js").read_text(encoding="utf-8")

    assert "human behavior engine unavailable; continuing with base motion" in source
    assert "startAvatar();" in source


def test_human_behavior_runtime_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if node is None:
        return

    for filename in (
        "human-behavior-engine.js",
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
