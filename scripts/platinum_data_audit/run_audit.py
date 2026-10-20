"""Generate evidence for source review, without training or editing raw data."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .session_hypotheses import classify_hourly_intervals, daily_gap_diagnostics, prospective_policy
from .source_evidence import SOURCE_URLS, probe_sources
from .provider_reconciliation import probe_problem_windows
from .workbook_forensics import ohlc_diagnostics, unit_diagnostics


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_findings(summary: dict) -> str:
    daily, hourly = summary["daily"], summary["hourly"]
    lines = ["# Platinum source and session audit", "",
             f"Original workbook SHA-256: `{summary['source_sha256']}`.",
             f"Audit frozen: {summary['frozen_at_utc']}.", "",
             "This is a new read-only forensic audit, not a new model experiment. Previous final holdouts remain consumed. No original values, feature policies, model choices or old results were changed.", "",
             "## Daily anomalies", "", "| Check | Count |", "|---|---:|"]
    for field in ("rows", "invalid_numeric", "ohlc_violations", "open_outside_range", "close_outside_range", "inverted_ranges", "open_and_close_outside", "zero_volume"):
        lines.append(f"| {field} | {daily[field]} |")
    lines += ["", f"Disjoint reasons: `{json.dumps(daily['reason_counts'],sort_keys=True)}`.",
              f"Violations by year: `{json.dumps(daily['violations_by_year'],sort_keys=True)}`.",
              f"Violations on/after the start of hourly coverage: {summary['daily_violations_in_hourly_coverage']}.",
              "", "A daily settlement versus intraday range mismatch, historical vendor adjustment or contract stitching could explain some close-outside-range rows. These are hypotheses, not established causes. Inverted high/low ranges cannot be justified by a settlement-only explanation. No prices are clipped, swapped, interpolated or replaced.",
              "", "## Daily date gaps", "", f"`{json.dumps(summary['daily_gaps'],sort_keys=True)}`", "",
              "Weekday counts are candidate labels, not confirmed missing exchange sessions. Holiday schedules and historical source coverage remain necessary.",
              "", "## Hourly interval evidence", "", "| Classification | Intervals |", "|---|---:|"]
    lines += [f"| {name} | {count} |" for name,count in summary["hourly_intervals"]["classification_counts"].items()]
    lines += ["", "The regular-session template uses America/Chicago DST rules and assumes a 17:00 opening, 16:00 close, daily maintenance and weekend closure. It is not an authenticated exchange holiday calendar; template-consistent intervals must not be described as verified exchange closures.",
              "", f"Half-hour anchored records: {summary['hourly_intervals']['half_hour_anchor_records']}; off-minute-grid records: {summary['hourly_intervals']['off_minute_grid_records']}.",
              "Consecutive half-hour anchored labels can be exactly one hour apart. They are not automatically invalid or synthetic. Their holiday/session anchoring requires vendor and exchange evidence. The terminal subhour quote does not establish a completed hourly candle.",
              "", f"Hourly numeric/OHLC violations: {hourly['invalid_numeric']}/{hourly['ohlc_violations']}.",
              "", "## Conversion and timestamp checks", "",
              f"USD/kg conversion diagnostics: `{json.dumps(summary['unit_conversions'],sort_keys=True)}`.",
              "The conversion-factor check establishes consistency with workbook arithmetic, not the market instrument, its native currency or permission to redistribute prices.",
              "UTC and Asia/Riyadh representations agree for every hourly record. This does not establish daily availability time or settlement publication time.",
              "", "## Source verification", "", "| Source | Observed outcome | Verified content |", "|---|---|---|"]
    for name, record in summary["source_access"].items():
        lines.append(f"| [{name}]({record['url']}) | {record['status']} | {record.get('authoritative_content_verified',False)} |")
    contract = summary["source_access"].get("cme_specs", {}).get("contract_metadata", {}).get("official_fields", {})
    if contract:
        lines += ["", "### Current official contract fields", "",
                  "Retrieved from CME product 446 via the endpoint used by its contract-specification page. These are current contract facts, not historical holiday rules or Yahoo rollover rules.", ""]
        for name in ("ProductName", "ContractUnit", "PriceQuotation", "SettlementMethod", "TradingHours", "TerminationOfTrading"):
            value = contract.get(name)
            if value is not None:
                text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                lines.append(f"- {name}: {html.unescape(re.sub('<[^>]+>', ' ', text))}")
    comparisons = summary.get("provider_window_comparisons", [])
    if comparisons:
        lines += ["", "### Targeted historical provider reconciliation", "",
                  "| Window | Outcome | Shared dates | OHLC identical | Reproduced anomalies | Vendor-only dates |",
                  "|---|---|---:|---:|---:|---:|"]
        for item in comparisons:
            c = item.get("comparison", {})
            lines.append(f"| {item['window']} | {item['status']} | {c.get('shared_dates','—')} | {c.get('all_ohlc_identical_rows','—')} | {c.get('workbook_ohlc_anomalies_reproduced','—')} | {c.get('vendor_only_dates_in_requested_window','—')} |")
        lines += ["", "Matching rows show that those anomalies also exist in the current vendor response, not only this workbook. Vendor-only dates establish additional current coverage; they do not prove the cause of the original omission, historical data availability or whether the vendor later revised history. This is a targeted same-provider comparison, not an independent price-source validation. No workbook rows were replaced or filled."]
    lines += ["", "Raw retrieved responses, when available, stay outside Git. HTTP success alone cannot verify session hours, contract rollover, quote-completion semantics or licensing. No browser challenge or proxy policy is bypassed.",
              "", "## Decision and new test policy", "", "**Production approval remains false.** No new forecast is issued and no model is retrained from these findings.",
              f"New final-test observations must become available strictly after `{summary['prospective_policy']['new_holdout_after_exclusive']}`. At least 200 eligible unseen observations per horizon are required under the existing minimum gate. The existing inspected workbook is not eligible as a fresh final test.",
              "First verify sources and register the revised calendar/feature policy using development data; seal a separate final period before outcomes or model selection can influence it. Future data do not yet exist in this audit output. Do not mistake an empty prospective policy for a reserved, evaluated holdout.",
              "", "Current blocker: authoritative vendor/exchange source evidence and sufficient new unseen completed observations. Model development can resume on disclosed development data only after a new preregistered experiment; promotion requires genuinely unseen final evidence."]
    return "\n".join(lines)+"\n"


def run_audit(workbook: Path, output: Path, frozen_at: pd.Timestamp,
              probe: bool = False, reconcile_provider: bool = False) -> dict:
    if output.exists():
        raise FileExistsError("audit output exists; preserve prior evidence")
    frozen_at = pd.Timestamp(frozen_at)
    if frozen_at.tzinfo is None:
        raise ValueError("timezone-aware freeze time required")
    before = _sha256(workbook)
    daily = pd.read_excel(workbook, sheet_name="Daily")
    hourly = pd.read_excel(workbook, sheet_name="Hourly")
    d_time = pd.to_datetime(daily.date, utc=True, errors="raise")
    h_time = pd.to_datetime(hourly.timestamp_utc, utc=True, errors="raise", format="mixed")
    riyadh = pd.to_datetime(hourly.datetime_riyadh, errors="raise", format="mixed").dt.tz_localize("Asia/Riyadh").dt.tz_convert("UTC")
    if not riyadh.equals(h_time):
        raise ValueError("Riyadh timestamps disagree with UTC")
    d_stats, d_flags = ohlc_diagnostics(daily, "date")
    h_stats, h_flags = ohlc_diagnostics(hourly, "timestamp_utc")
    h_summary, h_intervals = classify_hourly_intervals(h_time)
    d_summary, d_intervals = daily_gap_diagnostics(d_time)
    summary = {"schema_version": "1", "source_sha256": before,
               "frozen_at_utc": frozen_at.tz_convert("UTC").isoformat(),
               "production_approved": False, "daily": d_stats, "hourly": h_stats,
               "daily_gaps": d_summary, "hourly_intervals": h_summary,
               "daily_violations_in_hourly_coverage": int(((d_flags.reason != "valid_ohlc") & (d_flags.timestamp >= h_time.min().floor("D"))).sum()),
               "unit_conversions": {"daily": unit_diagnostics(daily), "hourly": unit_diagnostics(hourly)},
               "prospective_policy": prospective_policy(max(d_time.max(), h_time.max()), frozen_at),
               "source_access": {name: {"url": url, "status": "not_probed", "authoritative_content_verified": False} for name,url in SOURCE_URLS.items()}}
    if _sha256(workbook) != before:
        raise ValueError("source workbook changed during read-only audit")
    output.mkdir(parents=True, exist_ok=False)
    if probe:
        summary["source_access"] = probe_sources(output / "source_cache")
    if reconcile_provider:
        summary["provider_window_comparisons"] = probe_problem_windows(daily, output / "provider_comparison_cache")
    if probe or reconcile_provider:
        finalized_at = pd.Timestamp(datetime.now(timezone.utc))
        latest_inspected = max(d_time.max(), h_time.max())
        charts = [summary["source_access"].get("yahoo_chart", {}).get("chart_metadata", {})]
        charts.extend(r.get("chart_metadata", {}) for r in summary.get("provider_window_comparisons", []))
        for chart in charts:
            if chart.get("last_chart_timestamp_utc"):
                latest_inspected = max(latest_inspected, pd.Timestamp(chart["last_chart_timestamp_utc"]))
            market_time = chart.get("vendor_metadata", {}).get("regularMarketTime")
            if market_time is not None:
                latest_inspected = max(latest_inspected, pd.Timestamp(market_time, unit="s", tz="UTC"))
        summary["source_review_completed_at_utc"] = finalized_at.isoformat()
        summary["prospective_policy"] = prospective_policy(latest_inspected, max(frozen_at, finalized_at))
    d_flags.to_csv(output / "daily_row_flags.csv", index=False)
    h_flags.to_csv(output / "hourly_row_flags.csv", index=False)
    h_intervals.to_csv(output / "hourly_interval_flags.csv", index=False)
    d_intervals.to_csv(output / "daily_date_gaps.csv", index=False)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    (output / "AUDIT_FINDINGS.md").write_text(render_findings(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only platinum workbook source/session audit; no training")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe-sources", action="store_true")
    parser.add_argument("--reconcile-provider", action="store_true", help="Compare at most three bounded Yahoo history windows; no repairs")
    args = parser.parse_args(argv)
    try:
        result = run_audit(args.workbook, args.output, pd.Timestamp(datetime.now(timezone.utc)), args.probe_sources, args.reconcile_provider)
        print(json.dumps({"status": "audited", "output": str(args.output), "source_sha256": result["source_sha256"], "production_approved": False}))
        return 0
    except (ValueError, FileExistsError, FileNotFoundError) as error:
        print(json.dumps({"status": "blocked", "error": str(error), "production_approved": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
