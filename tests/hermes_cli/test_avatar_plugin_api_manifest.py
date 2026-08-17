import json
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD = _REPO_ROOT / "plugins" / "hermes-avatar" / "dashboard"
_MANIFEST = _DASHBOARD / "manifest.json"
_WEB_SERVER = _REPO_ROOT / "hermes_cli" / "web_server.py"


def test_avatar_manifest_uses_direct_plugin_api_module_for_file_loader():
    """The dashboard loader executes the manifest API file by path.

    A shim that imports a sibling module by bare name is not importable when
    loaded with spec_from_file_location unless the dashboard directory is on
    sys.path. Keep the manifest pointed at the router module itself.
    """
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    api_path = _DASHBOARD / manifest["api"]
    api_source = api_path.read_text(encoding="utf-8")
    loader_source = _WEB_SERVER.read_text(encoding="utf-8")

    assert manifest["api"] == "plugin_api.py"
    assert api_path.is_file()
    assert "router = APIRouter()" in api_source
    assert "spec_from_file_location(module_name, api_path)" in loader_source
