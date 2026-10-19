from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from platinum_forecasting.data_audit import clean_bars, read_workbook
from platinum_forecasting.features import build_features, supervised_samples


def bars(n=180, frequency="hourly"):
    ts = pd.date_range("2025-01-01", periods=n, freq="h" if frequency == "hourly" else "B", tz="UTC")
    close = 1000 + np.arange(n) * .1 + np.sin(np.arange(n))
    return pd.DataFrame({"timestamp": ts, "open": close, "high": close + 2,
                         "low": close - 2, "close": close, "volume": 100})


@pytest.mark.parametrize("frequency", ["daily", "hourly"])
def test_invalid_ohlc_is_quarantined_without_repair(frequency):
    raw = bars(frequency=frequency)
    raw.loc[20, "high"] = 1
    cleaned, audit = clean_bars(raw, frequency)
    assert len(cleaned) == len(raw) - 2  # malformed + conservatively incomplete tail
    assert audit["invalid_ohlc"] == 1
    assert raw.loc[20, "high"] == 1
    assert not supervised_samples(cleaned, frequency, 4).origin_index.between(17, 20).any()


def test_conflicting_duplicates_fail_instead_of_guessing():
    raw = bars()
    conflict = raw.iloc[[10]].copy()
    conflict["close"] += .2
    with pytest.raises(ValueError, match="conflicting duplicate"):
        clean_bars(pd.concat([raw, conflict]), "hourly")


def test_exact_duplicates_removed_deterministically():
    raw = bars()
    cleaned, audit = clean_bars(pd.concat([raw, raw.iloc[[10]]]), "hourly")
    assert audit["exact_duplicates"] == 1
    assert len(cleaned) == len(raw) - 1


def test_off_hour_snapshot_and_unfinished_bar_excluded():
    raw = bars()
    raw.loc[len(raw)-1, "timestamp"] += pd.Timedelta(minutes=32)
    clean, audit = clean_bars(raw, "hourly")
    assert audit["off_grid"] == 1
    assert clean.timestamp.max() == raw.timestamp.iloc[-3]


def test_hourly_features_never_bridge_unverified_gaps():
    raw = bars(300).drop(index=range(100, 105))
    clean, _ = clean_bars(raw, "hourly")
    samples = supervised_samples(clean, "hourly", 4)
    assert ((samples.target_timestamp - samples.timestamp) == pd.Timedelta(hours=4)).all()
    gap_start = pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(hours=99)
    warmup_end = pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(hours=116)
    assert not samples.timestamp.between(gap_start, warmup_end).any()


@pytest.mark.parametrize("frequency", ["daily", "hourly"])
def test_future_mutation_cannot_change_earlier_features(frequency):
    raw = bars(frequency=frequency)
    clean, _ = clean_bars(raw, frequency)
    original = build_features(clean, frequency)
    mutated = clean.copy()
    mutated.loc[120:, ["open", "high", "low", "close", "volume"]] *= 4
    pd.testing.assert_frame_equal(original.iloc[:120], build_features(mutated, frequency).iloc[:120])


@pytest.mark.parametrize("frequency,horizon", [("daily", 5), ("hourly", 24)])
def test_target_is_exact_observed_bar_and_strictly_future(frequency, horizon):
    clean, _ = clean_bars(bars(frequency=frequency), frequency)
    samples = supervised_samples(clean, frequency, horizon)
    assert (samples.target_timestamp > samples.timestamp).all()
    assert np.allclose(samples.target_close, clean.close.iloc[samples.origin_index + horizon])


def test_schema_rejects_infinite_and_negative_prices():
    raw = bars()
    raw.loc[40, "close"] = np.inf
    raw.loc[45, "low"] = -1
    clean, audit = clean_bars(raw, "hourly")
    assert audit["invalid_numeric"] == 2
    assert np.isfinite(clean.close).all()


def test_text_prices_are_quarantined_and_numeric_strings_normalized():
    raw = bars().astype({"close": object, "volume": object})
    raw.loc[30, "close"] = "malformed"
    raw.loc[40, "volume"] = "100"
    clean, audit = clean_bars(raw, "hourly")
    assert audit["invalid_numeric"] == 1
    assert pd.api.types.is_numeric_dtype(clean.volume)
    assert np.isfinite(build_features(clean, "hourly").iloc[-1]).all()


def test_riyadh_timestamp_must_match_utc(tmp_path: Path):
    raw = bars(4).rename(columns={"timestamp": "timestamp_utc"})
    raw["timestamp_utc"] = raw.timestamp_utc.dt.tz_localize(None)
    raw["datetime_riyadh"] = raw.timestamp_utc + pd.Timedelta(hours=4)
    path = tmp_path / "invalid.xlsx"
    raw.to_excel(path, sheet_name="Hourly", index=False)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Riyadh"):
        read_workbook(path, "hourly")
    assert path.read_bytes() == before
