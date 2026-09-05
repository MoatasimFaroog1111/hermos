"""Operator CLI for draft-only Accounting Brain production workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hermes_constants import get_hermes_home
from plugins.accounting_brain.model_evaluation.baseline_runner import build_host_llm
from plugins.accounting_brain.odoo_discovery.contracts import (
    OdooConfigurationError,
    OdooCredentials,
    OdooReadError,
)
from plugins.accounting_brain.odoo_discovery.xmlrpc_adapter import OdooXmlRpcReadAdapter
from plugins.accounting_brain.production_drafts.create_in_odoo import (
    ApprovedDraftError,
    create_reviewed_odoo_draft,
)
from plugins.accounting_brain.production_drafts.odoo_write import (
    OdooDraftWriteError,
    OdooXmlRpcDraftCreateAdapter,
)
from plugins.accounting_brain.production_drafts.predict import (
    DraftPredictionError,
    prepare_accounting_draft,
)


_CONFIRM_CREATE_DRAFT = "YES_CREATE_DRAFT"


def register_draft_cli(parser: argparse.ArgumentParser) -> None:
    subs = parser.add_subparsers(dest="draft_action")
    predict = subs.add_parser(
        "predict",
        help="Prepare a historical-retrieval accounting draft for human review",
    )
    predict.add_argument("--file", required=True)
    predict.add_argument("--top-k", type=int, default=5)
    predict.add_argument("--timeout-seconds", type=float, default=120.0)
    predict.add_argument("--max-tokens", type=int, default=1800)

    create = subs.add_parser(
        "create-odoo-draft",
        help="Create one reviewed proposal in Odoo as draft only",
    )
    create.add_argument("--proposal", required=True)
    create.add_argument("--company-id", type=int, default=None)
    create.add_argument(
        "--confirm-create-draft",
        required=True,
        help=f"Required literal confirmation: {_CONFIRM_CREATE_DRAFT}",
    )
    parser.set_defaults(func=draft_command)


def draft_command(args: argparse.Namespace) -> int:
    action = getattr(args, "draft_action", None)
    home = get_hermes_home().resolve()

    try:
        if action == "predict":
            report = prepare_accounting_draft(
                Path(args.file),
                hermes_home=home,
                datasets_root=home / "accounting_brain" / "datasets",
                output_root=home / "accounting_brain" / "drafts",
                llm=build_host_llm(),
                top_k=max(1, min(10, int(args.top_k))),
                timeout_seconds=max(15.0, min(300.0, float(args.timeout_seconds))),
                max_tokens=max(256, min(4096, int(args.max_tokens))),
            )
        elif action == "create-odoo-draft":
            if args.confirm_create_draft != _CONFIRM_CREATE_DRAFT:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": (
                                "Explicit confirmation required: "
                                f"--confirm-create-draft {_CONFIRM_CREATE_DRAFT}"
                            ),
                        },
                        ensure_ascii=False,
                    )
                )
                return 2
            credentials = OdooCredentials.from_environment()
            reader = OdooXmlRpcReadAdapter(credentials)
            writer = OdooXmlRpcDraftCreateAdapter(credentials)
            report = create_reviewed_odoo_draft(
                Path(args.proposal),
                permitted_root=home,
                reader=reader,
                writer=writer,
                requested_company_id=args.company_id,
            )
        else:
            print("Choose action: predict or create-odoo-draft")
            return 2
    except (
        ApprovedDraftError,
        DraftPredictionError,
        OdooConfigurationError,
        OdooDraftWriteError,
        OdooReadError,
    ) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 3
