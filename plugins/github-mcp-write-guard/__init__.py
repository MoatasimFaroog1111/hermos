"""GitHub MCP write guard.

Policy:
- GitHub MCP read operations pass without interruption.
- Mutating operations require Hermes' existing human approval gate.
- High-risk/destructive repository operations are blocked outright.
- Unknown future GitHub MCP tools fail safe to human approval.

The hook deliberately keys on the normalized Hermes MCP tool namespace
(``mcp__github__<tool>``) so direct and deferred/tool-search dispatch paths
hit the same policy chokepoint.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_GITHUB_PREFIX = "mcp__github__"

# Read-only verbs are intentionally conservative. New/unknown tools do not
# auto-pass; they fall through to human approval.
_READ_PREFIXES = (
    "get_",
    "list_",
    "search_",
    "fetch_",
    "compare_",
    "read_",
    "check_",
)

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
    if not isinstance(tool_name, str) or not tool_name.startswith(_GITHUB_PREFIX):
        return None
    short = tool_name[len(_GITHUB_PREFIX):].strip()
    return short or None


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
    short = _short_name(tool_name)
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

    if short.startswith(_READ_PREFIXES):
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
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
