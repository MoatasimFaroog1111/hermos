import json
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_RECOVERY = _REPO_ROOT / "web" / "src" / "plugins" / "coreManifestRecovery.ts"
_LOADER = _REPO_ROOT / "web" / "src" / "plugins" / "usePlugins.ts"
_APP = _REPO_ROOT / "web" / "src" / "App.tsx"
_MANIFEST = _REPO_ROOT / "plugins" / "hermes-avatar" / "dashboard" / "manifest.json"


def test_digital_human_manifest_is_sidebar_ready():
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    app = _APP.read_text(encoding="utf-8")

    assert manifest["name"] == "hermes-avatar"
    assert manifest["icon"] == "Sparkles"
    assert manifest["tab"]["path"] == "/digital-human"
    assert "Sparkles," in app
    assert "path: manifest.tab.path" in app


def test_hidden_bundled_digital_human_can_recover_from_static_manifest():
    source = _RECOVERY.read_text(encoding="utf-8")

    assert '{ name: "hermes-avatar", expectedPath: "/digital-human" }' in source
    assert "/dashboard-plugins/${encodeURIComponent(spec.name)}/manifest.json" in source
    assert 'credentials: "include"' in source
    assert 'cache: "no-store"' in source
    assert 'source: "bundled"' in source
    assert "if (!response.ok) return null" in source


def test_plugin_loader_applies_recovery_on_success_and_discovery_failure():
    source = _LOADER.read_text(encoding="utf-8")

    assert 'from "./coreManifestRecovery"' in source
    assert "const effective = await recoverBundledDashboardManifests(list);" in source
    assert ".then((list) => applyManifests(list))" in source
    assert ".catch(() => applyManifests([]))" in source
