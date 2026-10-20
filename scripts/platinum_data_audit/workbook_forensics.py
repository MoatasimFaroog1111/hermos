"""Explain workbook inconsistencies without rewriting or repairing market prices."""
from __future__ import annotations

import numpy as np
import pandas as pd

PRICE_COLUMNS = ("open", "high", "low", "close")


def ohlc_diagnostics(raw: pd.DataFrame, timestamp_column: str) -> tuple[dict, pd.DataFrame]:
    values = raw[[*PRICE_COLUMNS, "volume"]].apply(pd.to_numeric, errors="coerce")
    timestamps = pd.to_datetime(raw[timestamp_column], utc=True, errors="raise")
    numeric = np.isfinite(values).all(axis=1) & values[list(PRICE_COLUMNS)].gt(0).all(axis=1) & values.volume.ge(0)
    inverted = numeric & values.high.lt(values.low)
    open_outside = numeric & (values.open.lt(values.low) | values.open.gt(values.high))
    close_outside = numeric & (values.close.lt(values.low) | values.close.gt(values.high))
    violations = numeric & (inverted | open_outside | close_outside)
    reasons = np.select([~numeric, inverted, open_outside & close_outside, open_outside, close_outside],
                        ["invalid_numeric", "inverted_range", "open_and_close_outside", "open_outside_only", "close_outside_only"],
                        default="valid_ohlc")
    flags = pd.DataFrame({"excel_row": np.arange(len(raw))+2, "timestamp": timestamps,
                          "reason": reasons}, index=raw.index)
    excursion = pd.concat([values.close-values.high, values.low-values.close], axis=1).max(axis=1).clip(lower=0)
    suspect_excursion = excursion.loc[close_outside]
    year_counts = timestamps.loc[violations].dt.year.value_counts().sort_index()
    summary = {"rows": len(raw), "invalid_numeric": int((~numeric).sum()),
               "ohlc_violations": int(violations.sum()), "open_outside_range": int(open_outside.sum()),
               "close_outside_range": int(close_outside.sum()), "inverted_ranges": int(inverted.sum()),
               "open_and_close_outside": int((open_outside & close_outside).sum()),
               "reason_counts": {str(k): int(v) for k,v in flags.reason.value_counts().items()},
               "violations_by_year": {str(k): int(v) for k,v in year_counts.items()},
               "close_excursion_usd_oz_quantiles": {str(k): float(v) for k,v in suspect_excursion.quantile([0,.25,.5,.75,1]).dropna().items()},
               "zero_volume": int(values.volume.eq(0).sum()),
               "duplicates": int(timestamps.duplicated().sum()),
               "outlier_policy": "describe_only_no_winsorization_or_repair",
               "settlement_mismatch_confirmed": False,
               "contract_roll_confirmed": False}
    return summary, flags


def unit_diagnostics(raw: pd.DataFrame) -> dict:
    results = {}
    for column in PRICE_COLUMNS:
        converted = column+"_usd_kg"
        if converted not in raw:
            results[column] = {"status": "unavailable"}
            continue
        native = pd.to_numeric(raw[column], errors="coerce")
        kilograms = pd.to_numeric(raw[converted], errors="coerce")
        comparable = np.isfinite(native) & np.isfinite(kilograms)
        absolute_error = (kilograms-native*32.15074657).abs()
        matches = np.isclose(kilograms, native*32.15074657, rtol=1e-9, atol=1e-6)
        results[column] = {"status": "checked", "comparable_rows": int(comparable.sum()),
                           "noncomparable_rows": int((~comparable).sum()),
                           "mismatches": int((comparable & ~matches).sum()),
                           "max_absolute_difference": float(absolute_error.loc[comparable].max()) if comparable.any() else None,
                           "factor_tested": 32.15074657}
    return results
