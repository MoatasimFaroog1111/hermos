"""JSON command transport for offline research and Hermes status requests."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .configuration import ResearchConfig
from .experiment import audit_workbook, evaluate, select


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent platinum futures research; no trading or auto-promotion")
    parser.add_argument("command", choices=["audit", "select", "evaluate", "status"])
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frequency", choices=["daily", "hourly"])
    parser.add_argument("--horizon", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            records = []
            for path in sorted(args.output.glob("*/selection.json")):
                s = json.loads(path.read_text(encoding="utf-8"))
                evaluation = path.parent / "evaluation.json"
                result = json.loads(evaluation.read_text(encoding="utf-8")) if evaluation.exists() else None
                records.append({"frequency": s["config"]["frequency"], "horizon": s["config"]["horizon"],
                                "status": s["status"], "usable_samples": s["usable_samples"],
                                "holdout": result["holdout"] if result else None,
                                "decision": result["decision"] if result else {"production_pass": False}})
            document = {"schema_version": "1", "projects": records,
                        "message_ar": "نتائج بحثية فقط؛ لا يوجد نموذج مفعّل للإنتاج."}
        elif not args.workbook:
            parser.error("--workbook required for research commands")
        elif args.command == "audit":
            document = audit_workbook(args.workbook, args.output)
        else:
            if not args.frequency:
                parser.error("--frequency required")
            config = ResearchConfig(frequency=args.frequency, horizon=args.horizon)
            document = (select if args.command == "select" else evaluate)(args.workbook, args.output, config)
        print(json.dumps(document, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, FileNotFoundError, FileExistsError, KeyError) as error:
        logging.error(json.dumps({"event": "platinum_command_failed", "error_type": type(error).__name__}))
        print(json.dumps({"status": "blocked", "error": str(error), "production_pass": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
