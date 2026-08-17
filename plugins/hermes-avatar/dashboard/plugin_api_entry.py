"""Deployment composition root for the Hermes Digital Human API.

Keeps environment-specific avatar upload sizing and deployment diagnostics out
of the core plugin API. The underlying storage remains streaming, bounded,
GLB-validated and atomic.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


_DEFAULT_MAX_MB = 64
_MIN_MAX_MB = 8
_MAX_MAX_MB = 128


def _configured_max_bytes() -> int:
    raw = (os.getenv("HERMES_AVATAR_MAX_UPLOAD_MB") or "").strip()
    try:
        requested = int(raw) if raw else _DEFAULT_MAX_MB
    except ValueError:
        requested = _DEFAULT_MAX_MB
    bounded = max(_MIN_MAX_MB, min(_MAX_MAX_MB, requested))
    return bounded * 1024 * 1024


def _dashboard_manifest() -> dict[str, object]:
    """Read the colocated dashboard contract as the diagnostics source of truth."""
    manifest_path = Path(__file__).with_name("manifest.json")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Unable to read Hermes Digital Human manifest") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Hermes Digital Human manifest must be a JSON object")
    return payload


def _load_base_module():
    module_name = "hermes_avatar_dashboard_plugin_api"
    module = sys.modules.get(module_name)
    if module is not None:
        return module

    module_path = Path(__file__).with_name("plugin_api.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load Hermes Digital Human API")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _install_health_diagnostics(base_module, manifest: dict[str, object]) -> None:
    """Decorate core health output with the deployed dashboard contract.

    The core API previously carried an independent hard-coded version, which
    drifted from the dashboard manifest and made production debugging report two
    different Digital Human versions. Keep the core module deployment-agnostic
    and enrich its health payload here at the composition boundary instead.
    """
    base_health_payload = base_module._health_payload
    manifest_version = str(manifest.get("version") or "").strip()
    manifest_entry = str(manifest.get("entry") or "").strip()

    def deployment_health_payload() -> dict:
        payload = dict(base_health_payload())
        if manifest_version:
            payload["version"] = manifest_version
            payload["dashboard_manifest_version"] = manifest_version
        if manifest_entry:
            payload["dashboard_entry"] = manifest_entry
        payload["dashboard_contract_loaded"] = True
        return payload

    base_module._health_payload = deployment_health_payload


_base = _load_base_module()
_MANIFEST = _dashboard_manifest()
_MAX_BYTES = _configured_max_bytes()

# plugin_api.py intentionally owns validation/storage behavior. This composition
# root supplies only deployment policy and diagnostics required in production.
_base._MAX_AVATAR_BYTES = _MAX_BYTES
_base._AVATAR_STORAGE.max_bytes = _MAX_BYTES
_install_health_diagnostics(_base, _MANIFEST)

router = _base.router
