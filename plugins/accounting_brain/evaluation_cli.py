"""Operator CLI for leakage-safe Accounting Brain model evaluation."""

from __future__ import annotations

import argparse
import json

from hermes_constants import get_hermes_home
from plugins.accounting_brain.model_evaluation.baseline_runner import (
    BaselineEvaluationError,
    build_host_llm,
    run_baseline_evaluation,
)
from plugins.accounting_brain.model_evaluation.evaluate import (
    EvaluationRunError,
    score_latest_evaluation,
)


def register_evaluation_cli(parser: argparse.ArgumentParser) -> None:
    subs = parser.add_subparsers(dest="evaluation_action")

    run = subs.add_parser(
        "run",
        help="Run the active Hermes model on the prepared accounting holdout",
    )
    run.add_argument("--timeout-seconds", type=float, default=120.0)
    run.add_argument("--max-tokens", type=int, default=1800)

    subs.add_parser(
        "score",
        help="Deterministically rescore fixed accounting holdout predictions",
    )
    parser.set_defaults(func=evaluation_command)


def evaluation_command(args: argparse.Namespace) -> int:
    action = getattr(args, "evaluation_action", None)
    datasets_root = get_hermes_home() / "accounting_brain" / "datasets"

    try:
        if action == "run":
            timeout_seconds = max(15.0, min(300.0, float(args.timeout_seconds)))
            max_tokens = max(256, min(4096, int(args.max_tokens)))
            report = run_baseline_evaluation(
                datasets_root,
                build_host_llm(),
                timeout_seconds=timeout_seconds,
                max_tokens=max_tokens,
            )
        elif action == "score":
            report = score_latest_evaluation(datasets_root)
        else:
            print("Choose one action: run or score")
            return 2
    except (BaselineEvaluationError, EvaluationRunError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 3
