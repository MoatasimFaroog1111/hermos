"""Tool schemas for the Hetzner Cloud plugin."""

_ID = {
    "type": "integer",
    "minimum": 1,
}

_PAGE = {
    "type": "integer",
    "minimum": 1,
    "default": 1,
}

_PER_PAGE = {
    "type": "integer",
    "minimum": 1,
    "maximum": 50,
    "default": 25,
}

HETZNER_LIST_SERVERS = {
    "name": "hetzner_list_servers",
    "description": "List Hetzner Cloud servers in the configured project. Read-only.",
    "parameters": {
        "type": "object",
        "properties": {"page": _PAGE, "per_page": _PER_PAGE},
    },
}

HETZNER_GET_SERVER = {
    "name": "hetzner_get_server",
    "description": "Read current details for one Hetzner Cloud server. Read-only.",
    "parameters": {
        "type": "object",
        "properties": {"server_id": _ID},
        "required": ["server_id"],
    },
}

HETZNER_GET_SERVER_METRICS = {
    "name": "hetzner_get_server_metrics",
    "description": (
        "Read server metrics from Hetzner Cloud for a bounded time window. "
        "Use ISO-8601 start/end timestamps and one metric type."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "server_id": _ID,
            "type": {
                "type": "string",
                "enum": ["cpu", "disk", "network"],
                "default": "cpu",
            },
            "start": {"type": "string"},
            "end": {"type": "string"},
            "step": {"type": "integer", "minimum": 1, "maximum": 86400, "default": 60},
        },
        "required": ["server_id", "start", "end"],
    },
}

HETZNER_LIST_FIREWALLS = {
    "name": "hetzner_list_firewalls",
    "description": "List Hetzner Cloud firewalls and their current attachments/rules. Read-only.",
    "parameters": {
        "type": "object",
        "properties": {"page": _PAGE, "per_page": _PER_PAGE},
    },
}

HETZNER_GET_FIREWALL = {
    "name": "hetzner_get_firewall",
    "description": "Read one Hetzner Cloud firewall, including rules and applied resources. Read-only.",
    "parameters": {
        "type": "object",
        "properties": {"firewall_id": _ID},
        "required": ["firewall_id"],
    },
}

HETZNER_LIST_NETWORKS = {
    "name": "hetzner_list_networks",
    "description": "List Hetzner Cloud private networks. Read-only.",
    "parameters": {
        "type": "object",
        "properties": {"page": _PAGE, "per_page": _PER_PAGE},
    },
}

HETZNER_LIST_ACTIONS = {
    "name": "hetzner_list_actions",
    "description": "List recent Hetzner Cloud actions and their status. Read-only.",
    "parameters": {
        "type": "object",
        "properties": {
            "page": _PAGE,
            "per_page": _PER_PAGE,
            "status": {"type": "string", "enum": ["running", "success", "error"]},
        },
    },
}

HETZNER_GET_ACTION = {
    "name": "hetzner_get_action",
    "description": "Read one Hetzner Cloud action by ID. Read-only.",
    "parameters": {
        "type": "object",
        "properties": {"action_id": _ID},
        "required": ["action_id"],
    },
}

HETZNER_GET_PRICING = {
    "name": "hetzner_get_pricing",
    "description": "Read current Hetzner Cloud pricing information. Read-only.",
    "parameters": {"type": "object", "properties": {}},
}

_SERVER_MUTATION_DESCRIPTION = (
    "This changes a live Hetzner server and MUST pass the KTA99 human-approval gate "
    "before the API call is executed."
)

HETZNER_SERVER_REBOOT = {
    "name": "hetzner_server_reboot",
    "description": "Reboot a server. " + _SERVER_MUTATION_DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {"server_id": _ID},
        "required": ["server_id"],
    },
}

HETZNER_SERVER_POWER_ON = {
    "name": "hetzner_server_power_on",
    "description": "Power on a server. " + _SERVER_MUTATION_DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {"server_id": _ID},
        "required": ["server_id"],
    },
}

HETZNER_SERVER_POWER_OFF = {
    "name": "hetzner_server_power_off",
    "description": "Force power off a server. " + _SERVER_MUTATION_DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {"server_id": _ID},
        "required": ["server_id"],
    },
}

HETZNER_SERVER_SHUTDOWN = {
    "name": "hetzner_server_shutdown",
    "description": "Request an ACPI shutdown of a server. " + _SERVER_MUTATION_DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {"server_id": _ID},
        "required": ["server_id"],
    },
}

_FIREWALL_RULE = {
    "type": "object",
    "properties": {
        "direction": {"type": "string", "enum": ["in", "out"]},
        "protocol": {"type": "string", "enum": ["tcp", "udp", "icmp", "esp", "gre"]},
        "port": {"type": ["string", "null"]},
        "source_ips": {"type": "array", "items": {"type": "string"}},
        "destination_ips": {"type": "array", "items": {"type": "string"}},
        "description": {"type": ["string", "null"], "maxLength": 500},
    },
    "required": ["direction", "protocol"],
    "additionalProperties": False,
}

HETZNER_FIREWALL_SET_RULES = {
    "name": "hetzner_firewall_set_rules",
    "description": (
        "Replace all rules on one Hetzner Cloud firewall. Requires explicit human approval "
        "because a bad rule can cut off production access."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "firewall_id": _ID,
            "rules": {"type": "array", "items": _FIREWALL_RULE, "maxItems": 100},
        },
        "required": ["firewall_id", "rules"],
    },
}

HETZNER_FIREWALL_APPLY_TO_SERVER = {
    "name": "hetzner_firewall_apply_to_server",
    "description": "Attach a firewall to a server. Requires explicit human approval.",
    "parameters": {
        "type": "object",
        "properties": {"firewall_id": _ID, "server_id": _ID},
        "required": ["firewall_id", "server_id"],
    },
}

HETZNER_FIREWALL_REMOVE_FROM_SERVER = {
    "name": "hetzner_firewall_remove_from_server",
    "description": "Detach a firewall from a server. Requires explicit human approval.",
    "parameters": {
        "type": "object",
        "properties": {"firewall_id": _ID, "server_id": _ID},
        "required": ["firewall_id", "server_id"],
    },
}
