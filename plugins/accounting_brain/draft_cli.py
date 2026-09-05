"""Operator CLI for draft-only Accounting Brain production inference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hermes_constants import get_hermes_home
from plugins.accounting_brain.model_evaluation.baseline_runner import build_host_llm
from plugins.accounting_brain.production_drafts.predict import (
    DraftPredictionError,
    prepare_accounting_draft,
)


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
    parser.set_defaults(func=draft_command)


def draft_command(args: argparse.Namespace) -> int:
    if getattr(args, "draft_action", None) != "predict":
        print("Choose action: predict")
        return 2

    home = get_hermes_home().resolve()
    try:
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
    except DraftPredictionError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 3
