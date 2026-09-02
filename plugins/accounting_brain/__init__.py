"""Hermes Accounting Brain plugin.

Phase 1 deliberately exposes only an operator CLI. The accounting capability
lives at the edge of Hermes, preserving the core agent's narrow tool schema and
prompt-cache stability. The agent can invoke the CLI through the existing
terminal tool under guidance from the expert-accountant-odoo skill.
"""

from __future__ import annotations

from plugins.accounting_brain.cli import accounting_command, register_cli


def register(ctx) -> None:
    """Register the Accounting Brain operator CLI without adding model tools."""
    ctx.register_cli_command(
        name="accounting",
        help="Inspect Odoo accounting data and prepare training datasets",
        setup_fn=register_cli,
        handler_fn=accounting_command,
        description=(
            "Read-only Odoo schema discovery, historical journal-quality audit, "
            "and attachment-to-journal training-pair export for the Hermes "
            "Accounting Brain."
        ),
    )
