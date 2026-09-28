from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "docker" / "railway_runtime_cleanup.py"

spec = importlib.util.spec_from_file_location("railway_runtime_cleanup", _SCRIPT)
assert spec and spec.loader
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_cleanup_is_idempotent_and_preserves_unrelated_config(tmp_path, monkeypatch):
    home = tmp_path / "data"
    default_cfg = home / "config.yaml"
    bot_cfg = home / "profiles" / "bot2" / "config.yaml"
    bot_env = home / "profiles" / "bot2" / ".env"

    base = {
        "model": {"default": "deepseek/test"},
        "mcp_servers": {
            "Google": {"url": "https://www.google.com/"},
            "odoo_server": {"url": "https://example.invalid/"},
            "blender": {"command": "uvx", "enabled": True},
            "keep_me": {"url": "https://mcp.example.test/mcp", "enabled": True},
        },
        "platforms": {
            "webhook": {"enabled": True},
            "whatsapp": {"enabled": True},
        },
    }
    _write_yaml(default_cfg, base)
    _write_yaml(bot_cfg, base)
    bot_env.parent.mkdir(parents=True, exist_ok=True)
    bot_env.write_text(
        "TELEGRAM_BOT_TOKEN=keep-me\n"
        "WHATSAPP_ENABLED=true\n"
        "WHATSAPP_ALLOWED_USERS=123\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_RAILWAY_SAFE_CLEANUP", "1")
    monkeypatch.setenv("HERMES_HOME", str(home))

    assert cleanup.main() == 0
    assert cleanup.main() == 0

    default = yaml.safe_load(default_cfg.read_text(encoding="utf-8"))
    bot2 = yaml.safe_load(bot_cfg.read_text(encoding="utf-8"))
    env_text = bot_env.read_text(encoding="utf-8")

    assert default["platforms"]["webhook"]["enabled"] is False
    assert bot2["platforms"]["webhook"]["enabled"] is True
    assert bot2["platforms"]["whatsapp"]["enabled"] is False

    for config in (default, bot2):
        assert config["mcp_servers"]["Google"]["enabled"] is False
        assert config["mcp_servers"]["odoo_server"]["enabled"] is False
        assert config["mcp_servers"]["blender"]["enabled"] is False
        assert config["mcp_servers"]["keep_me"]["enabled"] is True
        assert config["model"]["default"] == "deepseek/test"

    assert "TELEGRAM_BOT_TOKEN=keep-me" in env_text
    assert "WHATSAPP_ALLOWED_USERS=123" in env_text
    assert "WHATSAPP_ENABLED=" not in env_text

    assert default_cfg.with_name("config.yaml.bak-cleanup-20260928").exists()
    assert bot_cfg.with_name("config.yaml.bak-cleanup-20260928").exists()
    assert bot_env.with_name(".env.bak-cleanup-20260928").exists()


def test_cleanup_is_opt_in(tmp_path, monkeypatch):
    home = tmp_path / "data"
    cfg = home / "config.yaml"
    _write_yaml(cfg, {"platforms": {"webhook": {"enabled": True}}})

    monkeypatch.delenv("HERMES_RAILWAY_SAFE_CLEANUP", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(home))

    before = cfg.read_text(encoding="utf-8")
    assert cleanup.main() == 0
    assert cfg.read_text(encoding="utf-8") == before
