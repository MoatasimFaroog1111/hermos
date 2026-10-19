"""Causal transformations shared by training and inference; no fitted state."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data_audit import Frequency

WARMUP = 48


def _segment_features(d: pd.DataFrame, frequency: Frequency) -> pd.DataFrame:
    c = d.close
    r = np.log(c).diff()
    f = pd.DataFrame(index=d.index)
    lags = (0, 1, 2, 3, 5, 10, 20) if frequency == "daily" else (0, 1, 2, 3, 5, 10)
    windows = (5, 10, 20, 48) if frequency == "daily" else (3, 6, 10, 12)
    warmup = WARMUP if frequency == "daily" else 12
    f["price_level"] = c
    for lag in lags:
        f[f"return_lag_{lag}"] = r.shift(lag)
    for window in windows:
        mean = c.rolling(window).mean()
        f[f"sma_ratio_{window}"] = c / mean - 1
        f[f"momentum_{window}"] = c / c.shift(window) - 1
        f[f"volatility_{window}"] = r.rolling(window).std()
        f[f"range_{window}"] = (d.high.rolling(window).max() - d.low.rolling(window).min()) / c
    f["ema_ratio"] = c / c.ewm(span=20, adjust=False).mean() - 1
    f["ewma_volatility"] = r.ewm(span=20, adjust=False).std()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    f["rsi"] = gain / (gain + loss).replace(0, np.nan)
    f["macd"] = (c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()) / c
    true_range = pd.concat([d.high-d.low, (d.high-c.shift()).abs(), (d.low-c.shift()).abs()], axis=1).max(axis=1)
    f["atr_ratio"] = true_range.rolling(14 if frequency == "daily" else 10).mean() / c
    f["candle_body"] = (c-d.open)/c
    f["upper_wick"] = (d.high-d[["open", "close"]].max(axis=1))/c
    f["lower_wick"] = (d[["open", "close"]].min(axis=1)-d.low)/c
    f["volume_log"] = np.log1p(d.volume)
    f["zero_volume"] = d.volume.eq(0).astype(float)
    for name, values, period in (("weekday", d.timestamp.dt.dayofweek, 7),
                                  ("month", d.timestamp.dt.month, 12)):
        f[name+"_sin"] = np.sin(2*np.pi*values/period)
        f[name+"_cos"] = np.cos(2*np.pi*values/period)
    if frequency == "hourly":
        f["hour_sin"] = np.sin(2*np.pi*d.timestamp.dt.hour/24)
        f["hour_cos"] = np.cos(2*np.pi*d.timestamp.dt.hour/24)
    f.loc[d.index[:warmup], :] = np.nan
    return f.replace([np.inf, -np.inf], np.nan)


def build_features(bars: pd.DataFrame, frequency: Frequency) -> pd.DataFrame:
    if bars.empty:
        return pd.DataFrame(index=bars.index)
    return pd.concat([_segment_features(d, frequency) for _, d in bars.groupby("segment", sort=False)]).sort_index()


def supervised_samples(bars: pd.DataFrame, frequency: Frequency, horizon: int) -> pd.DataFrame:
    if horizon < 1:
        raise ValueError("horizon must be positive")
    f = build_features(bars, frequency)
    grouped = bars.groupby("segment", sort=False)
    result = f.add_prefix("feature__")
    result["timestamp"] = bars.timestamp
    result["target_timestamp"] = grouped.timestamp.shift(-horizon)
    result["reference_close"] = bars.close
    result["target_close"] = grouped.close.shift(-horizon)
    result["target_return"] = np.log(result.target_close / bars.close)
    result["origin_index"] = bars.index
    result["segment"] = bars.segment
    # Baselines use exactly the same origin set as learned candidates.
    season = 5 if frequency == "daily" else 6
    result["baseline_naive"] = bars.close
    result["baseline_seasonal"] = grouped.close.shift(season - ((horizon-1) % season + 1))
    window = 20 if frequency == "daily" else 10
    means = pd.concat([d.close.rolling(window).mean() for _, d in grouped]).sort_index()
    drifts = pd.concat([d.close.diff().rolling(window).mean() for _, d in grouped]).sort_index()
    result["baseline_sma"] = means
    result["baseline_drift"] = bars.close + horizon * drifts
    return result.dropna().reset_index(drop=True)
