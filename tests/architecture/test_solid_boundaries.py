"""Architecture tests that protect SOLID dependency boundaries.

These tests intentionally inspect imports rather than runtime behavior. Their
purpose is to stop infrastructure concerns from drifting back into declarative
provider profiles during future feature work.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def imported_modules(relative_path: str) -> set[str]:
    source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    return modules


def test_provider_profile_does_not_depend_on_network_infrastructure():
    imports = imported_modules("providers/base.py")
    forbidden_roots = {
        "httpx",
        "requests",
        "urllib",
        "urllib.request",
        "hermes_cli.urllib_security",
    }

    assert imports.isdisjoint(forbidden_roots), (
        "ProviderProfile must remain declarative. Put model-catalog HTTP access "
        "behind providers.model_catalog.ModelCatalogClient instead."
    )


def test_model_catalog_adapter_owns_hardened_http_dependency():
    imports = imported_modules("providers/model_catalog.py")

    assert "urllib.request" in imports
    assert "hermes_cli.urllib_security" in imports
