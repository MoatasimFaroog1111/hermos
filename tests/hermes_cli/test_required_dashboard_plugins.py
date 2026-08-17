import json
from pathlib import Path

import pytest

from hermes_cli.required_dashboard_plugins import (
    normalize_required_dashboard_plugins,
    required_plugin_names,
    validate_bundled_dashboard_plugin,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_required_names_are_deduplicated_and_reject_paths():
    assert required_plugin_names(" hermes-avatar,hermes-avatar, other ") == (
        "hermes-avatar",
        "other",
    )
    with pytest.raises(ValueError):
        required_plugin_names("../hermes-avatar")


def test_normalize_required_plugin_state_preserves_unrelated_preferences():
    config = {
        "plugins": {"disabled": ["hermes-avatar", "other-plugin"]},
        "dashboard": {"hidden_plugins": ["other-dashboard", "hermes-avatar"]},
    }

    assert normalize_required_dashboard_plugins(config, ["hermes-avatar"]) is True
    assert config["plugins"]["disabled"] == ["other-plugin"]
    assert config["dashboard"]["hidden_plugins"] == ["other-dashboard"]
    assert normalize_required_dashboard_plugins(config, ["hermes-avatar"]) is False


def test_validate_required_dashboard_plugin_checks_declared_assets(tmp_path):
    dashboard = tmp_path / "hermes-avatar" / "dashboard"
    dist = dashboard / "dist"
    dist.mkdir(parents=True)
    (dist / "entry.js").write_text("console.log('ok')", encoding="utf-8")
    (dist / "style.css").write_text(".ok{}", encoding="utf-8")
    (dashboard / "plugin_api_entry.py").write_text("router = object()\n", encoding="utf-8")
    (dashboard / "manifest.json").write_text(
        json.dumps(
            {
                "name": "hermes-avatar",
                "entry": "dist/entry.js",
                "css": "dist/style.css",
                "api": "plugin_api_entry.py",
            }
        ),
        encoding="utf-8",
    )

    manifest = validate_bundled_dashboard_plugin(tmp_path, "hermes-avatar")
    assert manifest["entry"] == "dist/entry.js"

    (dist / "entry.js").unlink()
    with pytest.raises(FileNotFoundError):
        validate_bundled_dashboard_plugin(tmp_path, "hermes-avatar")


def test_railway_wires_digital_human_as_required_after_s6_bootstrap():
    railway = (_REPO_ROOT / "docker" / "railway-start.sh").read_text(encoding="utf-8")
    wrapper = (_REPO_ROOT / "docker" / "main-wrapper.sh").read_text(encoding="utf-8")

    assert 'HERMES_REQUIRED_BUNDLED_DASHBOARD_PLUGINS:-hermes-avatar' in railway
    assert "python -m hermes_cli.required_dashboard_plugins" in wrapper
    assert wrapper.index(". /opt/hermes/.venv/bin/activate") < wrapper.index(
        "python -m hermes_cli.required_dashboard_plugins"
    )
