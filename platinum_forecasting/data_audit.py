"""Read-only workbook ingestion and deterministic observed-bar quarantine."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

Frequency = Literal["daily", "hourly"]
PRICE_COLUMNS = ["open", "high", "low", "close"]


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_workbook(path: Path, frequency: Frequency) -> pd.DataFrame:
    sheet = "Daily" if frequency == "daily" else "Hourly"
    raw = pd.read_excel(path, sheet_name=sheet)
    time_column = "date" if frequency == "daily" else "timestamp_utc"
    raw["timestamp"] = pd.to_datetime(raw[time_column], utc=True, errors="raise")
    if frequency == "hourly":
        local = pd.to_datetime(raw["datetime_riyadh"], errors="raise")
        normalized = local.dt.tz_localize("Asia/Riyadh").dt.tz_convert("UTC")
        if not normalized.equals(raw.timestamp):
            raise ValueError("Riyadh timestamps disagree with UTC")
    return raw[["timestamp", *PRICE_COLUMNS, "volume"]].copy()


def clean_bars(raw: pd.DataFrame, frequency: Frequency) -> tuple[pd.DataFrame, dict]:
    if frequency not in {"daily", "hourly"}:
        raise ValueError("unsupported frequency")
    columns = ["timestamp", *PRICE_COLUMNS, "volume"]
    d = raw[columns].copy()
    d["timestamp"] = pd.to_datetime(d.timestamp, utc=True, errors="raise")
    if d.timestamp.isna().any():
        raise ValueError("missing timestamp")
    audit = {"input_rows": len(d), "frequency": frequency,
             "original_sorted": bool(d.timestamp.is_monotonic_increasing),
             "start": str(d.timestamp.min()), "end": str(d.timestamp.max()),
             "null_counts": d.isna().sum().astype(int).to_dict(),
             "dtypes": d.dtypes.astype(str).to_dict()}
    duplicates = d.timestamp.duplicated(keep=False)
    if d.loc[duplicates].groupby("timestamp")[columns[1:]].nunique(dropna=False).gt(1).any().any():
        raise ValueError("conflicting duplicate timestamps")
    audit["exact_duplicates"] = int(d.timestamp.duplicated().sum())
    d = d.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    audit["interval_counts"] = {str(k): int(v) for k, v in d.timestamp.diff().value_counts().items()}
    audit["zero_volume"] = int(d.volume.eq(0).sum())
    audit["return_spikes_over_15pct"] = int(d.close.pct_change(fill_method=None).abs().gt(.15).sum())
    values = d[columns[1:]].apply(pd.to_numeric, errors="coerce")
    numeric = np.isfinite(values).all(axis=1) & values[PRICE_COLUMNS].gt(0).all(axis=1) & values.volume.ge(0)
    ohlc = (values.high >= values[["open", "close", "low"]].max(axis=1)) & (values.low <= values[["open", "close", "high"]].min(axis=1))
    grid = d.timestamp.eq(d.timestamp.dt.floor("h" if frequency == "hourly" else "D"))
    audit["invalid_numeric"] = int((~numeric).sum())
    audit["invalid_ohlc"] = int((numeric & ~ohlc).sum())
    audit["off_grid"] = int((~grid).sum())
    # Source extraction time and close-completion flags are not authenticated.
    # Exclude the last on-grid bar even if a trailing quote snapshot exists.
    last_grid = d.loc[grid, "timestamp"].max()
    incomplete = d.timestamp.eq(last_grid)
    audit["incomplete_tail_excluded"] = int(incomplete.sum())
    keep = numeric & ohlc & grid & ~incomplete
    # Quarantined rows create a hard segment break even when delta looks valid.
    d["source_row"] = np.arange(len(d))
    d = d.loc[keep].copy().reset_index(drop=True)
    delta = d.timestamp.diff()
    time_break = delta.ne(pd.Timedelta(hours=1)) if frequency == "hourly" else delta.gt(pd.Timedelta(days=4))
    breaks = time_break | d.source_row.diff().ne(1)
    d["segment"] = breaks.cumsum().astype(int)
    audit["retained_rows"] = len(d)
    audit["quarantined_rows"] = int(len(raw) - len(d))
    audit["continuity_segments"] = int(d.segment.nunique())
    audit["research_only"] = True
    return d, audit
