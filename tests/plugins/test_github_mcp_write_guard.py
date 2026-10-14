"""Tests for github-mcp-write-guard."""

import importlib.util
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
