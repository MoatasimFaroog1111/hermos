"""Compare bounded historical Yahoo windows with workbook values; never repair."""
from __future__ import annotations

import hashlib
import json
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from .source_evidence import yahoo_metadata
from .workbook_forensics import PRICE_COLUMNS, ohlc_diagnostics


def compare_daily_window(raw: pd.DataFrame, payload: dict) -> dict:
    yahoo_metadata(payload)
    result = payload["chart"]["result"][0]
    quotes = result.get("indicators", {}).get("quote", [])
    if len(quotes) != 1 or not isinstance(quotes[0], dict):
        raise ValueError("ambiguous provider quote series")
    vendor = pd.DataFrame({c: quotes[0][c] for c in (*PRICE_COLUMNS, "volume")})
    vendor["date"] = pd.to_datetime(result["timestamp"], unit="s", utc=True).normalize()
    workbook = raw.copy()
    workbook["date"] = pd.to_datetime(workbook.date, utc=True).dt.normalize()
    if vendor.date.duplicated().any() or workbook.date.duplicated().any():
        raise ValueError("ambiguous daily date labels")
    joined = workbook.merge(vendor, on="date", suffixes=("_workbook", "_vendor"))
    agreements = {}
    finite = pd.Series(True, index=joined.index)
    for c in PRICE_COLUMNS:
        a = pd.to_numeric(joined[c+"_workbook"], errors="coerce")
        b = pd.to_numeric(joined[c+"_vendor"], errors="coerce")
        finite &= np.isfinite(b)
        agreements[c] = np.isclose(a, b, rtol=1e-8, atol=1e-4, equal_nan=False)
    all_agree = pd.DataFrame(agreements).all(axis=1)
    workbook_subset = pd.DataFrame({c: joined[c+"_workbook"] for c in (*PRICE_COLUMNS,"volume")})
    workbook_subset["date"] = joined.date
    _, flags = ohlc_diagnostics(workbook_subset, "date")
    return {"shared_dates": len(joined), "all_ohlc_identical_rows": int(all_agree.sum()),
            "workbook_ohlc_anomalies_reproduced": int((all_agree & flags.reason.ne("valid_ohlc")).sum()),
            "per_column_mismatches": {c: int((~v).sum()) for c,v in agreements.items()},
            "vendor_nonfinite_rows": int((~finite).sum()),
            "vendor_only_dates_in_requested_window": int((~vendor.date.isin(workbook.date)).sum()),
            "date_alignment": "UTC calendar labels; not certified settlement/session availability",
            "settlement_cause_verified": False, "repairs_applied": 0}


def probe_problem_windows(raw: pd.DataFrame, cache: Path) -> list[dict]:
    _, flags = ohlc_diagnostics(raw, "date")
    dates = pd.to_datetime(raw.date, utc=True)
    bad = flags.loc[flags.reason.ne("valid_ohlc"), "timestamp"]
    windows = []
    if len(bad):
        for label, center in (("first_anomaly", bad.iloc[0]), ("last_anomaly", bad.iloc[-1])):
            windows.append((label, center-pd.Timedelta(days=5), center+pd.Timedelta(days=6)))
    deltas = dates.diff()
    if deltas.gt(pd.Timedelta(days=7)).any():
        location = int(deltas.reset_index(drop=True).idxmax())
        windows.append(("largest_gap", dates.iloc[location-1]-pd.Timedelta(days=2), dates.iloc[location]+pd.Timedelta(days=3)))
    cache.mkdir(parents=True, exist_ok=True)
    records = []
    for label, start, end in windows:
        if end-start > pd.Timedelta(days=120):
            records.append({"window": label, "status": "window_exceeds_audit_budget"})
            continue
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/PL%3DF?"
               f"period1={int(start.timestamp())}&period2={int(end.timestamp())}&interval=1d")
        record = {"window": label, "url": url, "start": start.isoformat(), "end_exclusive": end.isoformat()}
        try:
            with urlopen(Request(url, headers={"User-Agent": "platinum-data-audit/0.1"}), timeout=15,
                         context=ssl.create_default_context()) as response:
                body = response.read(3*1024*1024+1)
                if len(body) > 3*1024*1024:
                    raise ValueError("provider response exceeds audit budget")
            (cache / f"{label}.json").write_bytes(body)
            payload = json.loads(body)
            record.update(status="compared", response_sha256=hashlib.sha256(body).hexdigest(),
                          comparison=compare_daily_window(raw, payload), chart_metadata=yahoo_metadata(payload))
        except HTTPError as error:
            record.update(status="http_failure", http_status=error.code)
        except (URLError, OSError):
            record.update(status="proxy_or_transport_failure")
        except (ValueError, KeyError, TypeError):
            record.update(status="invalid_provider_response")
        records.append(record)
    return records
