import json
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD = _REPO_ROOT / "plugins" / "hermes-avatar" / "dashboard"
_MANIFEST = _DASHBOARD / "manifest.json"
_ENTRYPOINT = _DASHBOARD / "plugin_api_entry.py"


def test_avatar_manifest_uses_file_loader_safe_composition_root():
    """Keep deployment wiring compatible with the dashboard file loader."""
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    source = _ENTRYPOINT.read_text(encoding="utf-8")

    assert manifest["api"] == "plugin_api_entry.py"
    assert "spec_from_file_location(module_name, module_path)" in source
    assert 'Path(__file__).with_name("plugin_api.py")' in source
    assert "sys.modules[module_name] = module" in source
    assert "router = _base.router" in source
    assert "from plugin_api import" not in source
