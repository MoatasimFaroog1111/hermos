"""Preflight required bundled dashboard plugins for managed deployments.

This module is intentionally small and deployment-agnostic. A launcher can
set ``HERMES_REQUIRED_BUNDLED_DASHBOARD_PLUGINS`` to a comma-separated list of
application-owned bundled dashboard plugins that must remain available. The
preflight validates their manifest assets, removes stale persisted hide/disable
state, and prevents stale user-volume copies from shadowing a required bundled
plugin before the dashboard process starts.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Iterable

from hermes_cli.config import get_process_hermes_home, load_config, save_config
from hermes_cli.plugins import get_bundled_plugins_dir

_REQUIRED_ENV = "HERMES_REQUIRED_BUNDLED_DASHBOARD_PLUGINS"
_SHADOW_BACKUP_DIR = "plugin-shadow-backups"


def required_plugin_names(raw: str | None = None) -> tuple[str, ...]:
    value = os.getenv(_REQUIRED_ENV, "") if raw is None else raw
    names: list[str] = []
    seen: set[str] = set()
    for item in value.split(","):
        name = item.strip()
        if not name:
            continue
        if name in {".", ".."} or "/" in name or "\\" in name or ".." in name:
            raise ValueError(f"Invalid required bundled dashboard plugin name: {name!r}")
        if name not in seen:
            names.append(name)
            seen.add(name)
    return tuple(names)


def _resolved_declared_file(dashboard_dir: Path, value: object, field: str) -> Path | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"Dashboard manifest field {field!r} must be a string")
    candidate = (dashboard_dir / value).resolve()
    root = dashboard_dir.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Dashboard manifest field {field!r} escapes the plugin directory") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"Required dashboard plugin asset is missing: {candidate}")
    return candidate


def validate_bundled_dashboard_plugin(root: Path, name: str) -> dict:
    dashboard_dir = (root / name / "dashboard").resolve()
    manifest_path = dashboard_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Required dashboard plugin manifest is missing: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid dashboard manifest JSON: {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"Dashboard manifest must be an object: {manifest_path}")
    if manifest.get("name") != name:
        raise ValueError(
            f"Dashboard manifest name mismatch: expected {name!r}, got {manifest.get('name')!r}"
        )

    entry = _resolved_declared_file(dashboard_dir, manifest.get("entry"), "entry")
    if entry is None:
        raise ValueError(f"Required dashboard plugin {name!r} does not declare an entry asset")
    _resolved_declared_file(dashboard_dir, manifest.get("css"), "css")
    _resolved_declared_file(dashboard_dir, manifest.get("api"), "api")
    return manifest


def normalize_required_dashboard_plugins(config: dict, names: Iterable[str]) -> bool:
    required = set(names)
    if not required:
        return False

    changed = False
    plugins_cfg = config.get("plugins")
    if isinstance(plugins_cfg, dict):
        disabled = plugins_cfg.get("disabled")
        if isinstance(disabled, list):
            filtered = [value for value in disabled if value not in required]
            if filtered != disabled:
                plugins_cfg["disabled"] = filtered
                changed = True

    dashboard_cfg = config.get("dashboard")
    if isinstance(dashboard_cfg, dict):
        hidden = dashboard_cfg.get("hidden_plugins")
        if isinstance(hidden, list):
            filtered = [value for value in hidden if value not in required]
            if filtered != hidden:
                dashboard_cfg["hidden_plugins"] = filtered
                changed = True

    return changed


def quarantine_required_user_plugin_shadows(
    hermes_home: Path,
    names: Iterable[str],
) -> tuple[tuple[Path, Path], ...]:
    """Move same-name user copies aside so required bundled plugins win discovery.

    Dashboard discovery intentionally scans ``$HERMES_HOME/plugins`` before the
    bundled plugin tree so normal user plugins can override bundled plugins. A
    managed deployment can opt specific application-owned names into the
    required-bundled contract. For those names only, a stale persistent user
    copy must not claim ``seen_names`` before the bundled manifest is scanned.

    The conflicting copy is never deleted. It is atomically renamed on the same
    durable volume into ``$HERMES_HOME/plugin-shadow-backups``. Existing backups
    receive a numeric suffix so repeated/manual restores cannot overwrite data.
    """
    plugins_root = Path(hermes_home) / "plugins"
    backup_root = Path(hermes_home) / _SHADOW_BACKUP_DIR
    moved: list[tuple[Path, Path]] = []

    for name in names:
        source = plugins_root / name
        if not source.exists() and not source.is_symlink():
            continue

        backup_root.mkdir(parents=True, exist_ok=True)
        destination = backup_root / name
        suffix = 0
        while destination.exists() or destination.is_symlink():
            suffix += 1
            destination = backup_root / f"{name}.{suffix}"

        source.rename(destination)
        moved.append((source, destination))

    return tuple(moved)


def run_preflight(raw_names: str | None = None) -> tuple[tuple[str, ...], bool]:
    names = required_plugin_names(raw_names)
    if not names:
        return names, False

    bundled_root = get_bundled_plugins_dir().resolve()
    for name in names:
        validate_bundled_dashboard_plugin(bundled_root, name)

    shadow_moves = quarantine_required_user_plugin_shadows(
        get_process_hermes_home(),
        names,
    )
    for source, destination in shadow_moves:
        print(
            "[dashboard-plugin-preflight] moved user shadow "
            f"{source} -> {destination}",
            file=sys.stderr,
        )

    config = load_config()
    if not isinstance(config, dict):
        raise TypeError("Hermes config loader returned a non-object value")
    config_changed = normalize_required_dashboard_plugins(config, names)
    if config_changed:
        save_config(config)
    return names, bool(shadow_moves) or config_changed


def main() -> int:
    try:
        names, changed = run_preflight()
    except Exception as exc:
        print(f"[dashboard-plugin-preflight] ERROR: {exc}", file=sys.stderr)
        return 1

    if names:
        state = "reconciled persisted plugin state" if changed else "state already clean"
        print(
            f"[dashboard-plugin-preflight] required={','.join(names)}; {state}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
