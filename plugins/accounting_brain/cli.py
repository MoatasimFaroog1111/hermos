"""Operator CLI for the Hermes Accounting Brain.

The CLI is intentionally read-only against Odoo. It produces private local
reports/datasets that can later feed document extraction, retrieval, and model
training pipelines. Historical audit/export operations are fail-closed to one
Odoo company through the same company-scope use case used by the dashboard.

Model-evaluation operations preserve the same boundary: preparation may read
source evidence from Odoo, while deterministic scoring operates only on private
local evaluation artifacts and never needs Odoo credentials.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from hermes_constants import get_hermes_home
from plugins.accounting_brain.journal_training.audit import build_training_audit
from plugins.accounting_brain.journal_training.export import export_training_pairs
from plugins.accounting_brain.journal_training.filesystem_dataset import (
    FilesystemTrainingDatasetSink,
)
from plugins.accounting_brain.journal_training.historical_journals import (
    JournalSelection,
    load_historical_journal_batch,
)
from plugins.accounting_brain.model_evaluation.operator import (
    EvaluationOperatorError,
    prepare_operator_evaluation,
    score_prediction_file,
)
from plugins.accounting_brain.odoo_discovery.company_scope import (
    OdooCompany,
    OdooCompanyScopeError,
    list_accessible_companies,
    resolve_company_scope,
)
from plugins.accounting_brain.odoo_discovery.contracts import (
    CORE_ACCOUNTING_MODELS,
    OdooConfigurationError,
    OdooCredentials,
    OdooReadError,
)
from plugins.accounting_brain.odoo_discovery.discover import discover_odoo_schema
from plugins.accounting_brain.odoo_discovery.xmlrpc_adapter import OdooXmlRpcReadAdapter


def register_cli(parser: argparse.ArgumentParser) -> None:
    subs = parser.add_subparsers(dest="accounting_action")

    subs.add_parser(
        "status",
        help="Validate read-only Odoo connectivity without exposing secrets",
    )

    discover = subs.add_parser(
        "discover",
        help="Inspect actual Odoo accounting model metadata",
    )
    discover.add_argument(
        "--model",
        action="append",
        default=[],
        help="Additional Odoo model to inspect (repeatable)",
    )
    discover.add_argument(
        "--only-model",
        action="append",
        default=[],
        help="Inspect only these models instead of the default accounting set",
    )
    discover.add_argument("--output", default="")

    audit = subs.add_parser(
        "audit",
        help="Audit historical posted journals for training-data quality",
    )
    _add_history_selection_args(audit)
    audit.add_argument("--output", default="")

    export = subs.add_parser(
        "export",
        help="Export validated attachment-to-journal training pairs",
    )
    _add_history_selection_args(export)
    export.add_argument("--output-dir", default="")
    export.add_argument(
        "--include-silver",
        action="store_true",
        help="Include review-required examples in addition to gold examples",
    )
    export.add_argument(
        "--download-attachments",
        action="store_true",
        help="Download readable source attachments into the private dataset directory",
    )
    export.add_argument(
        "--max-attachment-mb",
        type=int,
        default=25,
        help="Skip individual attachments larger than this many MiB",
    )

    evaluation = subs.add_parser(
        "evaluation",
        help="Prepare leakage-safe holdouts and deterministically score model predictions",
    )
    evaluation_subs = evaluation.add_subparsers(dest="accounting_evaluation_action")

    evaluation_prepare = evaluation_subs.add_parser(
        "prepare",
        help="Prepare the newest private Gold dataset for baseline evaluation",
    )
    evaluation_prepare.add_argument(
        "--hydrate-source-content",
        action="store_true",
        help="Read supported attachment bytes from Odoo into private dataset storage",
    )
    evaluation_prepare.add_argument(
        "--max-attachment-mb",
        type=int,
        default=25,
        help="Skip individual source attachments larger than this many MiB",
    )
    evaluation_prepare.add_argument(
        "--holdout-fraction",
        type=float,
        default=0.20,
        help="Newest chronological fraction reserved for evaluation",
    )
    evaluation_prepare.add_argument(
        "--min-holdout",
        type=int,
        default=100,
        help="Minimum number of leakage-safe evaluation cases required",
    )
    evaluation_prepare.add_argument(
        "--min-source-content-coverage",
        type=float,
        default=0.90,
        help="Minimum holdout fraction with downloaded source evidence",
    )

    evaluation_score = evaluation_subs.add_parser(
        "score",
        help="Score a complete predictions JSONL file with deterministic accounting invariants",
    )
    evaluation_score.add_argument(
        "--predictions",
        required=True,
        help=(
            "JSONL containing one object per holdout case: "
            "{case_id, prediction}. This command does not send data to a model."
        ),
    )
    evaluation_score.add_argument(
        "--output",
        default="",
        help="Optional score-report path; defaults inside the private evaluation directory",
    )

    parser.set_defaults(func=accounting_command)


def accounting_command(args: argparse.Namespace) -> int:
    action = getattr(args, "accounting_action", None)
    if not action:
        print("Usage: hermes accounting {status|discover|audit|export|evaluation}")
        return 2

    try:
        if action == "evaluation":
            evaluation_action = getattr(args, "accounting_evaluation_action", None)
            if evaluation_action == "score":
                return _cmd_evaluation_score(args)
            if evaluation_action == "prepare":
                return _cmd_evaluation_prepare(_reader_from_environment(), args)
            print("Usage: hermes accounting evaluation {prepare|score}")
            return 2

        reader = _reader_from_environment()
        if action == "status":
            return _cmd_status(reader)
        if action == "discover":
            return _cmd_discover(reader, args)
        if action == "audit":
            return _cmd_audit(reader, args)
        if action == "export":
            return _cmd_export(reader, args)
        print(f"Unknown accounting action: {action}")
        return 2
    except (
        EvaluationOperatorError,
        OdooConfigurationError,
        OdooReadError,
        OdooCompanyScopeError,
    ) as exc:
        print(f"Accounting Brain: {exc}")
        return 1


def _reader_from_environment() -> OdooXmlRpcReadAdapter:
    return OdooXmlRpcReadAdapter(OdooCredentials.from_environment())


def _cmd_status(reader: OdooXmlRpcReadAdapter) -> int:
    uid = reader.authenticate()
    version = reader.version()
    companies = list_accessible_companies(reader)
    payload = {
        "ok": True,
        "mode": "read_only",
        "authenticated_user_id": uid,
        "server_version": version.get("server_version"),
        "server_serie": version.get("server_serie"),
        "protocol": version.get("protocol_version"),
        "accessible_companies": [company.to_dict() for company in companies],
        "company_selection_required": len(companies) > 1,
        "secrets_printed": False,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_discover(reader: OdooXmlRpcReadAdapter, args: argparse.Namespace) -> int:
    only = [
        str(item).strip()
        for item in (getattr(args, "only_model", []) or [])
        if str(item).strip()
    ]
    extra = [
        str(item).strip()
        for item in (getattr(args, "model", []) or [])
        if str(item).strip()
    ]
    models = only if only else list(CORE_ACCOUNTING_MODELS) + extra
    report = discover_odoo_schema(reader, models=models).to_dict()
    output = _output_path(
        getattr(args, "output", ""),
        category="discovery",
        filename=f"odoo-schema-{_timestamp()}.json",
    )
    _write_private_json(output, report)
    available = sum(1 for item in report["models"] if item["available"])
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "read_only",
                "models_requested": len(report["models"]),
                "models_available": available,
                "output": str(output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _cmd_audit(reader: OdooXmlRpcReadAdapter, args: argparse.Namespace) -> int:
    selection, selected_company = _scoped_selection(reader, _selection_from_args(args))
    batch = load_historical_journal_batch(reader, selection)
    report = build_training_audit(batch)
    report["selection_parameters"] = {
        "max_moves": selection.max_moves,
        "date_from": selection.date_from,
        "date_to": selection.date_to,
        "company_id": selection.company_id,
    }
    report["selected_company"] = selected_company.to_dict()
    output = _output_path(
        getattr(args, "output", ""),
        category="reports",
        filename=f"training-audit-{_timestamp()}.json",
    )
    _write_private_json(output, report)
    summary = {
        "ok": True,
        "mode": "read_only",
        "output": str(output),
        "selected_company": selected_company.to_dict(),
        "sampled_posted_moves": report["selection"]["sampled_posted_moves"],
        "total_matching_posted_moves": report["selection"]["total_matching_posted_moves"],
        "grades": report["quality"]["grades"],
        "attachment_coverage": report["quality"]["attachment_coverage"],
        "gold_rate": report["quality"]["gold_rate"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_export(reader: OdooXmlRpcReadAdapter, args: argparse.Namespace) -> int:
    selection, selected_company = _scoped_selection(reader, _selection_from_args(args))
    batch = load_historical_journal_batch(reader, selection)
    output_arg = str(getattr(args, "output_dir", "") or "").strip()
    if output_arg:
        root = Path(output_arg).expanduser()
    else:
        root = (
            get_hermes_home()
            / "accounting_brain"
            / "datasets"
            / f"odoo-journals-{_timestamp()}"
        )
    sink = FilesystemTrainingDatasetSink(root)
    max_mb = max(1, int(getattr(args, "max_attachment_mb", 25) or 25))
    report = export_training_pairs(
        reader,
        batch,
        sink,
        include_silver=bool(getattr(args, "include_silver", False)),
        download_attachments=bool(getattr(args, "download_attachments", False)),
        max_attachment_bytes=max_mb * 1024 * 1024,
    )
    report["selected_company"] = selected_company.to_dict()
    report["selection_parameters"] = {
        "max_moves": selection.max_moves,
        "date_from": selection.date_from,
        "date_to": selection.date_to,
        "company_id": selection.company_id,
    }
    sink.write_report("export-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_evaluation_prepare(
    reader: OdooXmlRpcReadAdapter,
    args: argparse.Namespace,
) -> int:
    holdout_fraction = float(getattr(args, "holdout_fraction", 0.20) or 0.20)
    source_coverage = float(
        getattr(args, "min_source_content_coverage", 0.90) or 0.90
    )
    if not 0.0 < holdout_fraction < 1.0:
        raise EvaluationOperatorError("--holdout-fraction must be between 0 and 1")
    if not 0.0 <= source_coverage <= 1.0:
        raise EvaluationOperatorError(
            "--min-source-content-coverage must be between 0 and 1"
        )
    max_mb = max(1, int(getattr(args, "max_attachment_mb", 25) or 25))
    report = prepare_operator_evaluation(
        reader,
        _datasets_root(),
        hydrate_source_content=bool(
            getattr(args, "hydrate_source_content", False)
        ),
        max_attachment_bytes=max_mb * 1024 * 1024,
        holdout_fraction=holdout_fraction,
        min_holdout=max(1, int(getattr(args, "min_holdout", 100) or 100)),
        min_source_content_coverage=source_coverage,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if bool(report.get("ok")) else 1


def _cmd_evaluation_score(args: argparse.Namespace) -> int:
    predictions = Path(str(getattr(args, "predictions", "") or "")).expanduser()
    output_raw = str(getattr(args, "output", "") or "").strip()
    report = score_prediction_file(
        _datasets_root(),
        predictions,
        output_path=Path(output_raw).expanduser() if output_raw else None,
    )
    summary = {
        "ok": report["ok"],
        "stage": report["stage"],
        "next_action": report["next_action"],
        "dataset": report["dataset"],
        "coverage": report["coverage"],
        "metrics": report["metrics"],
        "artifact": report["artifact"],
        "safety": report["safety"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _add_history_selection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-moves", type=int, default=1000)
    parser.add_argument("--date-from", default="", help="YYYY-MM-DD")
    parser.add_argument("--date-to", default="", help="YYYY-MM-DD")
    parser.add_argument(
        "--company-id",
        type=int,
        default=0,
        help="Required when the Odoo connection can access multiple companies",
    )


def _selection_from_args(args: argparse.Namespace) -> JournalSelection:
    return JournalSelection(
        max_moves=max(1, int(getattr(args, "max_moves", 1000) or 1000)),
        date_from=_optional_text(getattr(args, "date_from", "")),
        date_to=_optional_text(getattr(args, "date_to", "")),
        company_id=(int(getattr(args, "company_id", 0) or 0) or None),
    )


def _scoped_selection(
    reader: OdooXmlRpcReadAdapter,
    selection: JournalSelection,
) -> tuple[JournalSelection, OdooCompany]:
    selected_company = resolve_company_scope(reader, selection.company_id)
    return replace(selection, company_id=selected_company.id), selected_company


def _datasets_root() -> Path:
    return (get_hermes_home() / "accounting_brain" / "datasets").resolve()


def _output_path(raw: str, *, category: str, filename: str) -> Path:
    value = str(raw or "").strip()
    if value:
        return Path(value).expanduser().resolve()
    return (get_hermes_home() / "accounting_brain" / category / filename).resolve()


def _write_private_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
