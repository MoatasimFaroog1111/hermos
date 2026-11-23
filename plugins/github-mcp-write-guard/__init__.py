"""GitHub MCP write guard.

Policy:
- GitHub MCP read operations pass without interruption.
- Mutating operations require Hermes' existing human approval gate.
- High-risk/destructive repository operations are blocked outright.
- Unknown future GitHub MCP tools fail safe to human approval.

The hook derives normalized MCP namespaces from the active profile so direct
and deferred/tool-search dispatch paths hit the same policy chokepoint.
Enterprise/proxy identities can be declared in
``plugins.entries.github-mcp-write-guard.servers``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import yaml
from hermes_constants import get_hermes_home

# Keep old identities protected while cached MCP tools can still be live.
_KNOWN_PREFIXES: set[str] = {"mcp__github__"}

# Explicit reads only: a future "get_and_delete_*" must never auto-pass.
_READ_TOOLS = {
    "get_me", "get_file_contents", "fetch_file", "fetch_blob", "fetch_commit",
    "get_repository", "get_repo", "get_commit", "get_commit_combined_status",
    "list_commits", "list_branches", "list_tags", "get_tag", "get_latest_release",
    "get_release_by_tag", "list_releases", "get_pull_request", "list_pull_requests",
    "get_pull_request_files", "get_pull_request_reviews", "get_pull_request_status",
    "get_pull_request_comments", "get_pull_request_diff", "get_pr_info", "get_pr_diff",
    "get_issue", "list_issues", "get_issue_comments", "get_label", "list_labels",
    "list_issue_types", "issue_read", "pull_request_read", "actions_get",
    "actions_list", "projects_get", "projects_list", "get_workflow",
    "list_workflows", "get_workflow_run", "list_workflow_runs", "get_job_logs",
    "get_workflow_run_logs", "get_workflow_run_usage", "list_workflow_jobs",
    "list_workflow_run_artifacts", "download_workflow_run_artifact",
    "search_repositories", "search_code", "search_issues", "search_pull_requests",
    "search_users", "search_commits", "compare_commits", "check_pull_request_status",
    "get_teams", "get_team_members", "list_notifications", "get_notification_details",
    "get_code_scanning_alert", "list_code_scanning_alerts", "get_secret_scanning_alert",
    "list_secret_scanning_alerts", "get_dependabot_alert", "list_dependabot_alerts",
    "get_discussion", "get_discussion_comments", "list_discussions",
}


def _configured_prefixes() -> tuple[str, ...]:
    from hermes_cli.config import load_config_readonly
    from hermes_cli.managed_scope import get_managed_dir
    from hermes_cli.env_loader import load_hermes_dotenv
    from tools.mcp_tool import _interpolate_env_vars

    # Validate before the host loader can fall back/log a YAML parse error.
    # This also covers managed config without exposing any credential contents.
    managed = get_managed_dir()
    paths = [get_hermes_home() / "config.yaml"]
    if managed:
        paths.append(managed / "config.yaml")
    for path in paths:
        raw = yaml.safe_load(path.read_text()) if path.exists() else {}
        if raw is not None and not isinstance(raw, dict):
            raise ValueError("config must be a mapping")
    load_hermes_dotenv()
    config = load_config_readonly()
    servers = config.get("mcp_servers") or {}
    if not isinstance(servers, dict):
        raise ValueError("mcp_servers must be a mapping")
    entries = (config.get("plugins") or {}).get("entries") or {}
    explicit = (entries.get("github-mcp-write-guard") or {}).get("servers", [])
    if not isinstance(explicit, list) or any(not isinstance(x, str) or not x for x in explicit):
        raise ValueError("guard servers must be a list of names")
    names = {"github", *explicit}
    for name, server in servers.items():
        server = _interpolate_env_vars(server)
        if not isinstance(server, dict):
            raise ValueError("MCP server must be a mapping")
        host = urlparse(str(server.get("url", ""))).hostname or ""
        command = " ".join([str(server.get("command", "")), *map(str, server.get("args") or [])])
        if (str(name).lower() == "gh" or "github" in str(name).lower()
                or host in {"api.githubcopilot.com", "github.com", "api.github.com"}
                or "github-mcp-server" in command):
            names.add(str(name))
    prefixes = {"mcp__" + re.sub(r"[^A-Za-z0-9_]", "_", name) + "__" for name in names}
    return tuple(sorted(prefixes, key=len, reverse=True))


# These actions are beyond the KTA99 operating envelope. They stay blocked
# even if a model retries/rephrases the request.
_HARD_BLOCK = {
    "delete_file",
    "delete_branch",
    "delete_repository",
    "create_repository",
    "fork_repository",
}


def _short_name(tool_name: str) -> Optional[str]:
    if not isinstance(tool_name, str) or not tool_name.startswith("mcp__"):
        return None
    _KNOWN_PREFIXES.update(_configured_prefixes())
    for prefix in sorted(_KNOWN_PREFIXES, key=len, reverse=True):
        if tool_name.startswith(prefix):
            return tool_name[len(prefix):].strip() or None
    return None


def _target_summary(args: Any) -> str:
    if not isinstance(args, dict):
        return "GitHub"
    repo = (
        args.get("repository_full_name")
        or args.get("repo_full_name")
        or (
            f"{args.get('owner')}/{args.get('repo')}"
            if args.get("owner") and args.get("repo")
            else None
        )
    )
    path = args.get("path")
    pr = args.get("pr_number") or args.get("pull_number") or args.get("pullNumber")
    parts = [str(repo)] if repo else ["GitHub"]
    if path:
        parts.append(str(path))
    if pr is not None:
        parts.append(f"PR #{pr}")
    return " · ".join(parts)


def _on_pre_tool_call(
    tool_name: str = "",
    args: Any = None,
    **_: Any,
) -> Optional[Dict[str, str]]:
    try:
        short = _short_name(tool_name)
    except Exception:
        # Policy/config failures must never fall through to the host's
        # observer-hook exception handling (which otherwise ignores errors).
        return {"action": "block", "message": "BLOCKED: GitHub guard configuration could not be loaded. Review profile config."}
    if short is None:
        return None

    if short in _HARD_BLOCK or short.startswith("delete_repository"):
        return {
            "action": "block",
            "message": (
                f"BLOCKED by github-mcp-write-guard: {short} is outside the "
                "approved KTA99 GitHub operating envelope. Use a reviewed, "
                "explicit administrative path instead."
            ),
        }

    if short in _READ_TOOLS:
        return None

    target = _target_summary(args)
    return {
        "action": "approve",
        "message": (
            f"GitHub write approval required: {short} on {target}. "
            "Review the requested mutation before allowing it."
        ),
        "rule_key": f"github:{short}",
    }


def register(ctx) -> None:
    try:
        _KNOWN_PREFIXES.update(_configured_prefixes())
    except Exception:
        # Dispatch revalidates and blocks until config becomes readable.
        pass
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
