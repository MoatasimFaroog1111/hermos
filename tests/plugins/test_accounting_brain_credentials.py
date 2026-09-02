from __future__ import annotations

import pytest

from plugins.accounting_brain.odoo_discovery.contracts import (
    OdooConfigurationError,
    OdooCredentials,
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
