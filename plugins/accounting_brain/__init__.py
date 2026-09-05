"""Hermes Accounting Brain plugin.

Accounting capabilities stay at the Hermes edge so the core model tool schema
remains narrow. Odoo discovery/export is read-only, while model evaluation uses
Hermes' host-owned LLM facade and deterministic accounting scoring. Automatic
Odoo posting remains disabled.
"""

from __future__ import annotations

from plugins.accounting_brain.cli import accounting_command, register_cli
from plugins.accounting_brain.evaluation_cli import (
    evaluation_command,
    register_evaluation_cli,
)


def register(ctx) -> None:
    """Register Accounting Brain operator CLIs without adding model tools."""

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
    ctx.register_cli_command(
        name="accounting-evaluate",
        help="Run and score leakage-safe Accounting Brain model evaluation",
        setup_fn=register_evaluation_cli,
        handler_fn=evaluation_command,
        description=(
            "Run the active Hermes host model against source-only holdout inputs "
            "and deterministically score its fixed journal predictions."
        ),
    )
