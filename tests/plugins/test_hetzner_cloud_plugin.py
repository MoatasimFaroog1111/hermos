"""Tests for the KTA99 Hetzner Cloud plugin."""

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_plugin():
    plugin_dir = _repo_root() / "plugins" / "hetzner-cloud"
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    name = "hermes_plugins.hetzner_cloud"
    spec = importlib.util.spec_from_file_location(
        name,
        plugin_dir / "__init__.py",
        submodule_search_locations=[str(plugin_dir)],
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = name
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_read_tools_pass_without_approval():
    mod = _load_plugin()
    for name in (
        "hetzner_list_servers",
        "hetzner_get_server",
        "hetzner_get_server_metrics",
        "hetzner_list_firewalls",
        "hetzner_get_firewall",
        "hetzner_list_networks",
        "hetzner_list_actions",
        "hetzner_get_action",
        "hetzner_get_pricing",
    ):
        assert mod._on_pre_tool_call(name, {}) is None


def test_mutations_require_human_approval():
    mod = _load_plugin()
    for name in (
        "hetzner_server_reboot",
        "hetzner_server_power_on",
        "hetzner_server_power_off",
        "hetzner_server_shutdown",
        "hetzner_firewall_set_rules",
        "hetzner_firewall_apply_to_server",
        "hetzner_firewall_remove_from_server",
    ):
        out = mod._on_pre_tool_call(name, {"server_id": 1, "firewall_id": 2})
        assert out["action"] == "approve"
        assert out["rule_key"] == f"hetzner:{name}"


def test_destructive_and_cost_creating_actions_are_hard_blocked():
    mod = _load_plugin()
    for name in (
        "hetzner_server_delete",
        "hetzner_server_rebuild",
        "hetzner_server_create",
        "hetzner_firewall_delete",
        "hetzner_network_delete",
        "hetzner_ssh_key_delete",
    ):
        out = mod._on_pre_tool_call(name, {"server_id": 1})
        assert out["action"] == "block"
        assert "BLOCKED" in out["message"]


def test_unknown_future_hetzner_tool_fails_safe_to_approval():
    mod = _load_plugin()
    out = mod._on_pre_tool_call("hetzner_change_primary_ip", {"server_id": 1})
    assert out["action"] == "approve"


def test_non_hetzner_tool_is_ignored():
    mod = _load_plugin()
    assert mod._on_pre_tool_call("web_search", {"q": "x"}) is None


def test_missing_token_fails_without_network(monkeypatch):
    mod = _load_plugin()
    monkeypatch.delenv("HETZNER_API_TOKEN", raising=False)
    result = json.loads(mod.tools.hetzner_list_servers({}))
    assert result["error"] == "HETZNER_API_TOKEN is not configured for this Hermes profile"


def test_request_uses_bearer_token_without_returning_it(monkeypatch):
    mod = _load_plugin()
    monkeypatch.setenv("HETZNER_API_TOKEN", "super-secret-token")

    captured = {}

    class Response:
        status_code = 200
        content = b"{}"
        def json(self):
            return {"servers": []}

    class Client:
        def __init__(self, *, base_url, headers, timeout):
            captured["base_url"] = base_url
            captured["headers"] = headers
            captured["timeout"] = timeout
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def request(self, method, path, params=None, json=None):
            captured["method"] = method
            captured["path"] = path
            captured["params"] = params
            captured["json"] = json
            return Response()

    monkeypatch.setattr(mod.tools.httpx, "Client", Client)
    result = mod.tools.hetzner_list_servers({})
    assert captured["base_url"] == "https://api.hetzner.cloud/v1"
    assert captured["headers"]["Authorization"] == "Bearer super-secret-token"
    assert "super-secret-token" not in result


def test_reboot_uses_expected_action_endpoint(monkeypatch):
    mod = _load_plugin()
    captured = {}

    def fake_request(method, path, *, params=None, body=None):
        captured.update(method=method, path=path, body=body)
        return {"action": {"id": 77, "status": "running"}}

    monkeypatch.setattr(mod.tools, "_request", fake_request)
    result = json.loads(mod.tools.hetzner_server_reboot({"server_id": 123}))
    assert captured == {
        "method": "POST",
        "path": "/servers/123/actions/reboot",
        "body": {},
    }
    assert result["action"]["id"] == 77


def test_firewall_set_rules_validates_and_posts(monkeypatch):
    mod = _load_plugin()
    captured = {}

    def fake_request(method, path, *, params=None, body=None):
        captured.update(method=method, path=path, body=body)
        return {"action": {"id": 88}}

    monkeypatch.setattr(mod.tools, "_request", fake_request)
    rules = [{
        "direction": "in",
        "protocol": "tcp",
        "port": "22",
        "source_ips": ["203.0.113.10/32"],
        "description": "admin ssh",
    }]
    result = json.loads(mod.tools.hetzner_firewall_set_rules({
        "firewall_id": 456,
        "rules": rules,
    }))
    assert captured["method"] == "POST"
    assert captured["path"] == "/firewalls/456/actions/set_rules"
    assert captured["body"] == {"rules": rules}
    assert result["action"]["id"] == 88


def test_firewall_apply_and_remove_payloads(monkeypatch):
    mod = _load_plugin()
    calls = []

    def fake_request(method, path, *, params=None, body=None):
        calls.append((method, path, body))
        return {"action": {"id": len(calls)}}

    monkeypatch.setattr(mod.tools, "_request", fake_request)
    mod.tools.hetzner_firewall_apply_to_server({"firewall_id": 9, "server_id": 4})
    mod.tools.hetzner_firewall_remove_from_server({"firewall_id": 9, "server_id": 4})
    resource = {"type": "server", "server": {"id": 4}}
    assert calls[0] == (
        "POST",
        "/firewalls/9/actions/apply_to_resources",
        {"apply_to": [resource]},
    )
    assert calls[1] == (
        "POST",
        "/firewalls/9/actions/remove_from_resources",
        {"remove_from": [resource]},
    )


def test_invalid_firewall_rule_never_calls_network(monkeypatch):
    mod = _load_plugin()

    def should_not_call(*args, **kwargs):
        pytest.fail("network must not be called")

    monkeypatch.setattr(mod.tools, "_request", should_not_call)
    result = json.loads(mod.tools.hetzner_firewall_set_rules({
        "firewall_id": 1,
        "rules": [{"direction": "sideways", "protocol": "tcp"}],
    }))
    assert "direction" in result["error"]
