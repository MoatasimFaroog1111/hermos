"""Hetzner Cloud API handlers.

Only the official Hetzner Cloud API is contacted. Credentials are read from
HETZNER_API_TOKEN at call time and never returned or logged.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import httpx

_API_BASE = "https://api.hetzner.cloud/v1"
_TIMEOUT = 30.0
_USER_AGENT = "Athmar-KTA99-Hermes/1.0"


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive integer") from exc
    if result < 1:
        raise ValueError(f"{field} must be a positive integer")
    return result


def _page_params(args: Dict[str, Any]) -> Dict[str, Any]:
    page = _positive_int(args.get("page", 1), "page")
    per_page = _positive_int(args.get("per_page", 25), "per_page")
    if per_page > 50:
        raise ValueError("per_page must be <= 50")
    return {"page": page, "per_page": per_page}


def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    token = os.environ.get("HETZNER_API_TOKEN", "").strip()
    if not token:
        return {"error": "HETZNER_API_TOKEN is not configured for this Hermes profile"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
    }

    try:
        with httpx.Client(base_url=_API_BASE, headers=headers, timeout=_TIMEOUT) as client:
            response = client.request(method, path, params=params, json=body)
    except httpx.TimeoutException:
        return {"error": "Hetzner Cloud API request timed out"}
    except httpx.RequestError:
        return {"error": "Hetzner Cloud API request failed"}

    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {}

    if 200 <= response.status_code < 300:
        return payload if isinstance(payload, dict) else {"result": payload}

    api_error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(api_error, dict):
        message = api_error.get("message") or api_error.get("code") or "Hetzner API error"
        code = api_error.get("code")
    else:
        message = "Hetzner API error"
        code = None

    out: Dict[str, Any] = {
        "error": str(message),
        "status_code": int(response.status_code),
    }
    if code:
        out["code"] = str(code)
    return out


def _compact_server(server: Dict[str, Any]) -> Dict[str, Any]:
    public_net = server.get("public_net") or {}
    ipv4 = public_net.get("ipv4") or {}
    ipv6 = public_net.get("ipv6") or {}
    server_type = server.get("server_type") or {}
    location = server.get("datacenter", {}).get("location") or server.get("location") or {}
    return {
        "id": server.get("id"),
        "name": server.get("name"),
        "status": server.get("status"),
        "created": server.get("created"),
        "server_type": server_type.get("name") if isinstance(server_type, dict) else server_type,
        "location": location.get("name") if isinstance(location, dict) else location,
        "ipv4": ipv4.get("ip"),
        "ipv6": ipv6.get("ip"),
        "labels": server.get("labels") or {},
        "protection": server.get("protection") or {},
        "included_traffic": server.get("included_traffic"),
        "outgoing_traffic": server.get("outgoing_traffic"),
        "ingoing_traffic": server.get("ingoing_traffic"),
    }


def hetzner_list_servers(args: Dict[str, Any], **_: Any) -> str:
    try:
        params = _page_params(args)
    except ValueError as exc:
        return _json({"error": str(exc)})
    data = _request("GET", "/servers", params=params)
    if "error" in data:
        return _json(data)
    servers = data.get("servers") or []
    return _json({
        "servers": [_compact_server(s) for s in servers if isinstance(s, dict)],
        "meta": data.get("meta"),
    })


def hetzner_get_server(args: Dict[str, Any], **_: Any) -> str:
    try:
        server_id = _positive_int(args.get("server_id"), "server_id")
    except ValueError as exc:
        return _json({"error": str(exc)})
    data = _request("GET", f"/servers/{server_id}")
    if "error" in data:
        return _json(data)
    server = data.get("server")
    return _json({"server": _compact_server(server) if isinstance(server, dict) else server})


def hetzner_get_server_metrics(args: Dict[str, Any], **_: Any) -> str:
    try:
        server_id = _positive_int(args.get("server_id"), "server_id")
        step = _positive_int(args.get("step", 60), "step")
        if step > 86400:
            raise ValueError("step must be <= 86400")
    except ValueError as exc:
        return _json({"error": str(exc)})

    metric_type = str(args.get("type", "cpu"))
    if metric_type not in {"cpu", "disk", "network"}:
        return _json({"error": "type must be one of: cpu, disk, network"})
    start = str(args.get("start", "")).strip()
    end = str(args.get("end", "")).strip()
    if not start or not end:
        return _json({"error": "start and end ISO-8601 timestamps are required"})

    return _json(_request(
        "GET",
        f"/servers/{server_id}/metrics",
        params={"type": metric_type, "start": start, "end": end, "step": step},
    ))


def hetzner_list_firewalls(args: Dict[str, Any], **_: Any) -> str:
    try:
        params = _page_params(args)
    except ValueError as exc:
        return _json({"error": str(exc)})
    return _json(_request("GET", "/firewalls", params=params))


def hetzner_get_firewall(args: Dict[str, Any], **_: Any) -> str:
    try:
        firewall_id = _positive_int(args.get("firewall_id"), "firewall_id")
    except ValueError as exc:
        return _json({"error": str(exc)})
    return _json(_request("GET", f"/firewalls/{firewall_id}"))


def hetzner_list_networks(args: Dict[str, Any], **_: Any) -> str:
    try:
        params = _page_params(args)
    except ValueError as exc:
        return _json({"error": str(exc)})
    return _json(_request("GET", "/networks", params=params))


def hetzner_list_actions(args: Dict[str, Any], **_: Any) -> str:
    try:
        params = _page_params(args)
    except ValueError as exc:
        return _json({"error": str(exc)})
    status = args.get("status")
    if status is not None:
        status = str(status)
        if status not in {"running", "success", "error"}:
            return _json({"error": "status must be running, success, or error"})
        params["status"] = status
    params["sort"] = "started:desc"
    return _json(_request("GET", "/actions", params=params))


def hetzner_get_action(args: Dict[str, Any], **_: Any) -> str:
    try:
        action_id = _positive_int(args.get("action_id"), "action_id")
    except ValueError as exc:
        return _json({"error": str(exc)})
    return _json(_request("GET", f"/actions/{action_id}"))


def hetzner_get_pricing(args: Dict[str, Any], **_: Any) -> str:
    return _json(_request("GET", "/pricing"))


def _server_action(args: Dict[str, Any], action: str) -> str:
    try:
        server_id = _positive_int(args.get("server_id"), "server_id")
    except ValueError as exc:
        return _json({"error": str(exc)})
    return _json(_request("POST", f"/servers/{server_id}/actions/{action}", body={}))


def hetzner_server_reboot(args: Dict[str, Any], **_: Any) -> str:
    return _server_action(args, "reboot")


def hetzner_server_power_on(args: Dict[str, Any], **_: Any) -> str:
    return _server_action(args, "poweron")


def hetzner_server_power_off(args: Dict[str, Any], **_: Any) -> str:
    return _server_action(args, "poweroff")


def hetzner_server_shutdown(args: Dict[str, Any], **_: Any) -> str:
    return _server_action(args, "shutdown")


def _normalize_rules(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("rules must be an array")
    if len(value) > 100:
        raise ValueError("rules may contain at most 100 entries")
    allowed = {"direction", "protocol", "port", "source_ips", "destination_ips", "description"}
    out = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError(f"rule {index} must be an object")
        extra = set(raw) - allowed
        if extra:
            raise ValueError(f"rule {index} contains unsupported fields")
        direction = raw.get("direction")
        protocol = raw.get("protocol")
        if direction not in {"in", "out"}:
            raise ValueError(f"rule {index} direction must be in or out")
        if protocol not in {"tcp", "udp", "icmp", "esp", "gre"}:
            raise ValueError(f"rule {index} protocol is unsupported")
        clean = {"direction": direction, "protocol": protocol}
        for key in ("port", "source_ips", "destination_ips", "description"):
            if key in raw and raw[key] is not None:
                clean[key] = raw[key]
        out.append(clean)
    return out


def hetzner_firewall_set_rules(args: Dict[str, Any], **_: Any) -> str:
    try:
        firewall_id = _positive_int(args.get("firewall_id"), "firewall_id")
        rules = _normalize_rules(args.get("rules"))
    except ValueError as exc:
        return _json({"error": str(exc)})
    return _json(_request(
        "POST",
        f"/firewalls/{firewall_id}/actions/set_rules",
        body={"rules": rules},
    ))


def _firewall_resource_action(args: Dict[str, Any], action: str, key: str) -> str:
    try:
        firewall_id = _positive_int(args.get("firewall_id"), "firewall_id")
        server_id = _positive_int(args.get("server_id"), "server_id")
    except ValueError as exc:
        return _json({"error": str(exc)})
    resource = {"type": "server", "server": {"id": server_id}}
    return _json(_request(
        "POST",
        f"/firewalls/{firewall_id}/actions/{action}",
        body={key: [resource]},
    ))


def hetzner_firewall_apply_to_server(args: Dict[str, Any], **_: Any) -> str:
    return _firewall_resource_action(args, "apply_to_resources", "apply_to")


def hetzner_firewall_remove_from_server(args: Dict[str, Any], **_: Any) -> str:
    return _firewall_resource_action(args, "remove_from_resources", "remove_from")
