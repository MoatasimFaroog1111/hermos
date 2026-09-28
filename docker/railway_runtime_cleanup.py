#!/usr/bin/env python3
"""Railway-only runtime hygiene for persisted Hermes profile configuration.

This adapter is intentionally narrow and idempotent. It disables integrations
that are known to be non-functional in the Railway deployment without deleting
their configuration, preserves all secrets, and creates one-time backups before
mutating persisted files.

It is gated by HERMES_RAILWAY_SAFE_CLEANUP so upstream/default deployments are
unaffected unless the operator explicitly opts in.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import yaml

_TRUE = {"1", "true", "yes", "on"}
_BACKUP_SUFFIX = ".bak-cleanup-20260928"


def _enabled() -> bool:
    return os.getenv("HERMES_RAILWAY_SAFE_CLEANUP", "").strip().lower() in _TRUE


def _backup_once(path: Path) -> None:
    if not path.exists():
        return
    backup = path.with_name(path.name + _BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(path, backup)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _disable_mcp_servers(config: dict[str, Any]) -> None:
    servers = config.get("mcp_servers")
    if not isinstance(servers, dict):
        return
    for name in ("Google", "odoo_server", "blender"):
        server = servers.get(name)
        if isinstance(server, dict):
            server["enabled"] = False


def _platform(config: dict[str, Any], name: str) -> dict[str, Any]:
    platforms = config.setdefault("platforms", {})
    if not isinstance(platforms, dict):
        raise ValueError("platforms must be a mapping")
    value = platforms.setdefault(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"platforms.{name} must be a mapping")
    return value


def _clean_default(config_path: Path) -> None:
    if not config_path.exists():
        return
    _backup_once(config_path)
    config = _load_yaml(config_path)
    _disable_mcp_servers(config)
    _platform(config, "webhook")["enabled"] = False
    _write_yaml(config_path, config)


def _clean_bot2(config_path: Path, env_path: Path) -> None:
    if config_path.exists():
        _backup_once(config_path)
        config = _load_yaml(config_path)
        _disable_mcp_servers(config)
        _platform(config, "webhook")["enabled"] = True
        _platform(config, "whatsapp")["enabled"] = False
        _write_yaml(config_path, config)

    if env_path.exists():
        _backup_once(env_path)
        lines = env_path.read_text(encoding="utf-8").splitlines()
        kept = [line for line in lines if not line.startswith("WHATSAPP_ENABLED=")]
        suffix = "\n" if kept else ""
        env_path.write_text("\n".join(kept) + suffix, encoding="utf-8")


def main() -> int:
    if not _enabled():
        print("[railway-cleanup] skipped (HERMES_RAILWAY_SAFE_CLEANUP is not enabled)")
        return 0

    home = Path(os.getenv("HERMES_HOME", "/opt/data"))
    _clean_default(home / "config.yaml")
    _clean_bot2(home / "profiles" / "bot2" / "config.yaml", home / "profiles" / "bot2" / ".env")
    print("[railway-cleanup] applied safe runtime overrides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
