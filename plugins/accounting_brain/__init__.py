"""Hermes Accounting Brain plugin.

Accounting capabilities stay at the Hermes edge so the core model tool schema
remains narrow. Odoo discovery/export is read-only, evaluation is leakage-safe,
and production inference can only produce human-reviewable draft proposals.
Automatic Odoo posting remains disabled.
"""

from __future__ import annotations

from plugins.accounting_brain.cli import accounting_command, register_cli
from plugins.accounting_brain.draft_cli import draft_command, register_draft_cli
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
            "Run the active Hermes host model against source-only holdout inputs, "
            "optionally ground predictions in earlier Gold history, and score "
            "fixed journal predictions deterministically."
        ),
    )
    ctx.register_cli_command(
        name="accounting-draft",
        help="Prepare a draft journal proposal from a private source document",
        setup_fn=register_draft_cli,
        handler_fn=draft_command,
        description=(
            "Use the active Hermes host model plus validated Gold history to "
            "prepare a deterministic-validated accounting draft for mandatory "
            "human review. No Odoo write or posting action is exposed."
        ),
    )
