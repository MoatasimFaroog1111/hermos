"""KTA99 Hetzner Cloud adapter and mutation guard."""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import schemas, tools

_READ_TOOLS = {
    "hetzner_list_servers",
    "hetzner_get_server",
    "hetzner_get_server_metrics",
    "hetzner_list_firewalls",
    "hetzner_get_firewall",
    "hetzner_list_networks",
    "hetzner_list_actions",
    "hetzner_get_action",
    "hetzner_get_pricing",
}

_HARD_BLOCK = {
    "hetzner_server_delete",
    "hetzner_server_rebuild",
    "hetzner_server_create",
    "hetzner_firewall_delete",
    "hetzner_network_delete",
    "hetzner_ssh_key_delete",
}


def _target_summary(args: Any) -> str:
    if not isinstance(args, dict):
        return "Hetzner Cloud"
    parts = []
    if args.get("server_id") is not None:
        parts.append(f"server {args['server_id']}")
    if args.get("firewall_id") is not None:
        parts.append(f"firewall {args['firewall_id']}")
    if args.get("action_id") is not None:
        parts.append(f"action {args['action_id']}")
    return " · ".join(parts) if parts else "Hetzner Cloud"


def _on_pre_tool_call(
    tool_name: str = "",
    args: Any = None,
    **_: Any,
) -> Optional[Dict[str, str]]:
    if not isinstance(tool_name, str) or not tool_name.startswith("hetzner_"):
        return None

    if tool_name in _HARD_BLOCK:
        return {
            "action": "block",
            "message": (
                f"BLOCKED by hetzner-cloud guard: {tool_name} is destructive or "
                "cost-creating and is outside the current KTA99 operating envelope."
            ),
        }

    if tool_name in _READ_TOOLS:
        return None

    return {
        "action": "approve",
        "message": (
            f"Hetzner Cloud change requires approval: {tool_name} on "
            f"{_target_summary(args)}. Review the infrastructure impact before allowing it."
        ),
        "rule_key": f"hetzner:{tool_name}",
    }


def register(ctx) -> None:
    registrations = (
        (schemas.HETZNER_LIST_SERVERS, tools.hetzner_list_servers),
        (schemas.HETZNER_GET_SERVER, tools.hetzner_get_server),
        (schemas.HETZNER_GET_SERVER_METRICS, tools.hetzner_get_server_metrics),
        (schemas.HETZNER_LIST_FIREWALLS, tools.hetzner_list_firewalls),
        (schemas.HETZNER_GET_FIREWALL, tools.hetzner_get_firewall),
        (schemas.HETZNER_LIST_NETWORKS, tools.hetzner_list_networks),
        (schemas.HETZNER_LIST_ACTIONS, tools.hetzner_list_actions),
        (schemas.HETZNER_GET_ACTION, tools.hetzner_get_action),
        (schemas.HETZNER_GET_PRICING, tools.hetzner_get_pricing),
        (schemas.HETZNER_SERVER_REBOOT, tools.hetzner_server_reboot),
        (schemas.HETZNER_SERVER_POWER_ON, tools.hetzner_server_power_on),
        (schemas.HETZNER_SERVER_POWER_OFF, tools.hetzner_server_power_off),
        (schemas.HETZNER_SERVER_SHUTDOWN, tools.hetzner_server_shutdown),
        (schemas.HETZNER_FIREWALL_SET_RULES, tools.hetzner_firewall_set_rules),
        (schemas.HETZNER_FIREWALL_APPLY_TO_SERVER, tools.hetzner_firewall_apply_to_server),
        (schemas.HETZNER_FIREWALL_REMOVE_FROM_SERVER, tools.hetzner_firewall_remove_from_server),
    )
    for schema, handler in registrations:
        ctx.register_tool(
            name=schema["name"],
            toolset="hetzner-cloud",
            schema=schema,
            handler=handler,
        )
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
