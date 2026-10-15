"""Tests for github-mcp-write-guard."""

import importlib.util
import json

import pytest
import yaml
import sys
import types
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_plugin():
    plugin_dir = _repo_root() / "plugins" / "github-mcp-write-guard"
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    spec = importlib.util.spec_from_file_location(
        "hermes_plugins.github_mcp_write_guard",
        plugin_dir / "__init__.py",
        submodule_search_locations=[str(plugin_dir)],
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "hermes_plugins.github_mcp_write_guard"
    sys.modules["hermes_plugins.github_mcp_write_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_non_github_tool_is_ignored():
    mod = _load_plugin()
    assert mod._on_pre_tool_call("web_search", {"q": "x"}) is None


def test_known_read_tools_pass_without_approval():
    mod = _load_plugin()
    for name in (
        "mcp__github__search_repositories",
        "mcp__github__list_commits",
        "mcp__github__fetch_file",
        "mcp__github__get_pull_request",
        "mcp__github__compare_commits",
        "mcp__github__check_pull_request_status",
    ):
        assert mod._on_pre_tool_call(name, {}) is None


def test_write_tools_require_human_approval():
    mod = _load_plugin()
    for name in (
        "mcp__github__create_branch",
        "mcp__github__create_file",
        "mcp__github__update_file",
        "mcp__github__push_files",
        "mcp__github__create_pull_request",
        "mcp__github__update_pull_request",
        "mcp__github__merge_pull_request",
        "mcp__github__issue_write",
        "mcp__github__add_issue_comment",
        "mcp__github__rerun_workflow_job",
    ):
        out = mod._on_pre_tool_call(
            name,
            {"repository_full_name": "owner/repo", "path": "x.py"},
        )
        assert out["action"] == "approve"
        assert out["rule_key"].startswith("github:")


def test_destructive_admin_actions_are_hard_blocked():
    mod = _load_plugin()
    for name in (
        "mcp__github__delete_file",
        "mcp__github__delete_branch",
        "mcp__github__delete_repository",
        "mcp__github__create_repository",
        "mcp__github__fork_repository",
    ):
        out = mod._on_pre_tool_call(name, {"repository_full_name": "owner/repo"})
        assert out["action"] == "block"
        assert "BLOCKED" in out["message"]


def test_unknown_future_github_tool_fails_safe_to_approval():
    mod = _load_plugin()
    out = mod._on_pre_tool_call(
        "mcp__github__rotate_deployment_key",
        {"repository_full_name": "owner/repo"},
    )
    assert out["action"] == "approve"
    assert out["rule_key"] == "github:rotate_deployment_key"


def test_target_summary_is_human_readable_and_secret_free():
    mod = _load_plugin()
    out = mod._on_pre_tool_call(
        "mcp__github__update_file",
        {
            "repository_full_name": "owner/repo",
            "path": ".github/workflows/ci.yml",
            "authorization": "SHOULD_NOT_APPEAR",
        },
    )
    assert "owner/repo" in out["message"]
    assert ".github/workflows/ci.yml" in out["message"]
    assert "SHOULD_NOT_APPEAR" not in out["message"]


def _registered_guard(monkeypatch, tmp_path, servers, entries=None):
    from hermes_cli import plugins
    config = {"mcp_servers": servers, "plugins": {"entries": entries or {}}}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    manager = plugins.PluginManager()
    manager._discovered = True
    monkeypatch.setattr(plugins, "_plugin_manager", manager)
    manager._load_plugin(plugins.PluginManifest(
        name="github-mcp-write-guard", source="bundled",
        path=str(_repo_root() / "plugins" / "github-mcp-write-guard"),
    ))
    assert manager._plugins["github-mcp-write-guard"].error is None
    return manager


@pytest.mark.parametrize("alias,server", [
    ("gh", {"url": "https://api.githubcopilot.com/mcp/"}),
    ("github-enterprise", {"command": "docker", "args": ["run", "ghcr.io/github/github-mcp-server"]}),
    ("company.tools", {"url": "https://api.githubcopilot.com/mcp/"}),
])
def test_configured_aliases_cannot_bypass_guard(monkeypatch, tmp_path, alias, server):
    from hermes_cli.plugins import get_pre_tool_call_directive
    from tools.mcp_tool import mcp_prefixed_tool_name
    _registered_guard(monkeypatch, tmp_path, {alias: server})
    action, _ = get_pre_tool_call_directive(mcp_prefixed_tool_name(alias, "delete_repository"), {})
    assert action == "block"
    action, _ = get_pre_tool_call_directive(mcp_prefixed_tool_name(alias, "create_branch"), {})
    assert action == "approve"


def test_explicit_enterprise_alias_is_guarded(monkeypatch, tmp_path):
    from hermes_cli.plugins import get_pre_tool_call_directive
    _registered_guard(monkeypatch, tmp_path,
        {"internal": {"url": "https://git.example.test/mcp"}},
        {"github-mcp-write-guard": {"servers": ["internal"]}})
    action, _ = get_pre_tool_call_directive("mcp__internal__delete_file", {})
    assert action == "block"


@pytest.mark.parametrize("tool", ["issue_read", "pull_request_read", "actions_get", "actions_list", "projects_get", "projects_list"])
def test_known_suffix_reads_pass(tool):
    assert _load_plugin()._on_pre_tool_call("mcp__github__" + tool, {}) is None


def test_unknown_read_like_name_still_requires_approval():
    result = _load_plugin()._on_pre_tool_call("mcp__github__get_and_delete_repository", {})
    assert result["action"] == "approve"


@pytest.mark.parametrize("provider", ["github", "hetzner"])
@pytest.mark.parametrize("decision", ["deny", "timeout", "error"])
def test_real_dispatch_never_reaches_mutation_after_rejection(monkeypatch, tmp_path, provider, decision):
    from hermes_cli import plugins
    from tools import approval
    from tools.registry import registry
    from model_tools import handle_function_call
    manager = _registered_guard(monkeypatch, tmp_path, {"gh": {"url": "https://api.githubcopilot.com/mcp/"}})
    calls = []
    if provider == "hetzner":
        manager._load_plugin(plugins.PluginManifest(name="hetzner-cloud", source="bundled",
            path=str(_repo_root() / "plugins" / "hetzner-cloud")))
        assert manager._plugins["hetzner-cloud"].error is None
        module = manager._plugins["hetzner-cloud"].module
        monkeypatch.setattr(module.tools, "_request", lambda *a, **k: calls.append(a) or {})
        name = "hetzner_server_reboot"
        args = {"server_id": 123}
    else:
        name = "mcp__gh__create_branch"
        args = {"owner": "owner", "repo": "repo", "branch": "test"}
        registry.register(name=name, toolset="guard-test", schema={"name":name,"parameters":{"type":"object"}},
            handler=lambda *a, **k: calls.append(a) or "{}")
    requests = []
    def respond(*a, **k):
        requests.append((a,k))
        if decision == "error":
            raise RuntimeError("approval transport unavailable")
        return {"approved": False, "message": "BLOCKED: " + decision}
    monkeypatch.setattr(approval, "request_tool_approval", respond)
    try:
        result = json.loads(handle_function_call(name, args, enabled_tools=[name]))
        assert "error" in result
        assert requests, "approval gate was not reached"
        assert calls == [], "mutation crossed the approval boundary"
    finally:
        if provider == "github":
            registry.deregister(name)


def test_unrelated_mcp_stays_outside_guard(monkeypatch, tmp_path):
    from hermes_cli.plugins import get_pre_tool_call_directive
    _registered_guard(monkeypatch, tmp_path, {"calendar": {"url": "https://calendar.example.test/mcp"}})
    action, _ = get_pre_tool_call_directive("mcp__calendar__create_event", {})
    assert action is None


def test_invalid_configuration_blocks_mcp_without_leaking_contents(monkeypatch, tmp_path):
    from hermes_cli import plugins
    manager = _registered_guard(monkeypatch, tmp_path, {})
    (tmp_path / "config.yaml").write_text("mcp_servers: [SECRET_VALUE\n")
    manager._plugins["github-mcp-write-guard"].module.register(
        plugins.PluginContext(manager._plugins["github-mcp-write-guard"].manifest, manager))
    action, message = plugins.get_pre_tool_call_directive("mcp__unknown__create_branch", {})
    assert action == "block"
    assert "SECRET_VALUE" not in message


@pytest.mark.parametrize("ref", ["${GITHUB_MCP_URL}", "${env:GITHUB_MCP_URL}"])
def test_environment_based_mcp_identity_is_guarded(monkeypatch, tmp_path, ref):
    from hermes_cli.plugins import get_pre_tool_call_directive
    monkeypatch.setenv("GITHUB_MCP_URL", "https://api.githubcopilot.com/mcp/")
    _registered_guard(monkeypatch, tmp_path, {"corp": {"url": ref}})
    action, _ = get_pre_tool_call_directive("mcp__corp__delete_repository", {})
    assert action == "block"


def test_new_alias_configured_after_registration_is_guarded(monkeypatch, tmp_path):
    from hermes_cli.plugins import get_pre_tool_call_directive
    _registered_guard(monkeypatch, tmp_path, {})
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"mcp_servers": {"later": {"url": "https://api.githubcopilot.com/mcp/"}}}))
    action, _ = get_pre_tool_call_directive("mcp__later__delete_repository", {})
    assert action == "block"


def test_managed_mcp_identity_is_guarded(monkeypatch, tmp_path):
    from hermes_cli.plugins import get_pre_tool_call_directive
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "config.yaml").write_text(yaml.safe_dump({"mcp_servers": {"managed_git": {"url": "https://api.githubcopilot.com/mcp/"}}}))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    _registered_guard(monkeypatch, tmp_path, {})
    action, _ = get_pre_tool_call_directive("mcp__managed_git__delete_repository", {})
    assert action == "block"


def test_removed_alias_remains_guarded_for_live_tools(monkeypatch, tmp_path):
    from hermes_cli.plugins import get_pre_tool_call_directive
    _registered_guard(monkeypatch, tmp_path, {"old_git": {"url": "https://api.githubcopilot.com/mcp/"}})
    (tmp_path / "config.yaml").write_text("mcp_servers: {}\n")
    action, _ = get_pre_tool_call_directive("mcp__old_git__delete_repository", {})
    assert action == "block"
