"""Deployment composition root for the Hermes Digital Human API.

Keeps environment-specific avatar upload sizing out of the core plugin API.
The underlying storage remains streaming, bounded, GLB-validated and atomic.
"""

from __future__ import annotations

import importlib.util
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


_base = _load_base_module()
_MAX_BYTES = _configured_max_bytes()

# plugin_api.py intentionally owns validation/storage behavior. This composition
# root only supplies the deployment limit required for production avatar files.
_base._MAX_AVATAR_BYTES = _MAX_BYTES
_base._AVATAR_STORAGE.max_bytes = _MAX_BYTES

router = _base.router
