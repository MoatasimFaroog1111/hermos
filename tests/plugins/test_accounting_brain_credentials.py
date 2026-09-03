from __future__ import annotations

import pytest

from hermes_cli.plugins import PluginManager
from plugins.accounting_brain.odoo_discovery.contracts import (
    OdooConfigurationError,
    OdooCredentials,
    OdooReadError,
)
from plugins.accounting_brain.odoo_discovery.xmlrpc_adapter import (
    OdooXmlRpcReadAdapter,
    _read_timeout_seconds,
)


def test_credentials_accept_legacy_database_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODOO_URL", "https://example.odoo.com")
    monkeypatch.delenv("ODOO_DB", raising=False)
    monkeypatch.setenv("ODOO_DATABASE", "company-db")
    monkeypatch.setenv("ODOO_USERNAME", "reader@example.com")
    monkeypatch.setenv("ODOO_API_KEY", "super-secret-value")

    credentials = OdooCredentials.from_environment()

    assert credentials.database == "company-db"
    assert credentials.api_key == "super-secret-value"


def test_missing_credentials_error_never_contains_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODOO_URL", "https://example.odoo.com")
    monkeypatch.delenv("ODOO_DB", raising=False)
    monkeypatch.delenv("ODOO_DATABASE", raising=False)
    monkeypatch.setenv("ODOO_USERNAME", "reader@example.com")
    monkeypatch.setenv("ODOO_API_KEY", "super-secret-value")

    with pytest.raises(OdooConfigurationError) as raised:
        OdooCredentials.from_environment()

    message = str(raised.value)
    assert "ODOO_DB" in message
    assert "super-secret-value" not in message
    assert "reader@example.com" not in message
    assert "https://example.odoo.com" not in message


def test_odoo_read_timeout_defaults_and_clamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ODOO_READ_TIMEOUT_SECONDS", raising=False)
    assert _read_timeout_seconds() == 60.0

    monkeypatch.setenv("ODOO_READ_TIMEOUT_SECONDS", "1")
    assert _read_timeout_seconds() == 5.0

    monkeypatch.setenv("ODOO_READ_TIMEOUT_SECONDS", "999")
    assert _read_timeout_seconds() == 300.0

    monkeypatch.setenv("ODOO_READ_TIMEOUT_SECONDS", "invalid")
    assert _read_timeout_seconds() == 60.0


def test_read_adapter_blocks_mutation_before_network_access() -> None:
    adapter = OdooXmlRpcReadAdapter(
        OdooCredentials(
            url="https://example.odoo.com",
            database="company-db",
            username="reader@example.com",
            api_key="super-secret-value",
        )
    )

    with pytest.raises(OdooReadError, match="Blocked non-read Odoo method: write"):
        adapter._execute_read("account.move", "write", [], {})


def test_bundled_accounting_brain_autoloads_and_registers_cli() -> None:
    manager = PluginManager()
    manager.discover_and_load()

    assert "accounting_brain" in manager._plugins
    loaded = manager._plugins["accounting_brain"]
    assert loaded.manifest.source == "bundled"
    assert loaded.manifest.kind == "backend"
    assert loaded.enabled is True, f"error: {loaded.error}"

    assert "accounting" in manager._cli_commands
    command = manager._cli_commands["accounting"]
    assert callable(command["setup_fn"])
    assert callable(command["handler_fn"])
