import pytest

pytest.importorskip("pandas", reason="optional platinum audit dependencies")
import pandas as pd

from scripts.platinum_data_audit.workbook_forensics import ohlc_diagnostics, unit_diagnostics


def frame():
    return pd.DataFrame({"date": pd.to_datetime(["2000-01-03", "2000-01-04", "2025-01-02"]),
                         "open": [100., 100., 100.], "high": [102., 102., 102.],
                         "low": [98., 98., 98.], "close": [101., 101., 101.], "volume": [100, 100, 100]})


def test_disjoint_anomaly_reasons_do_not_double_count_rows():
    d = frame()
    d.loc[0, "open"] = 103
    d.loc[0, "close"] = 104
    d.loc[1, "close"] = 97
    before = d.copy(deep=True)
    report, flags = ohlc_diagnostics(d, "date")
    assert report["ohlc_violations"] == 2
    assert report["open_outside_range"] == 1
    assert report["close_outside_range"] == 2
    assert report["reason_counts"] == {"open_and_close_outside": 1, "close_outside_only": 1, "valid_ohlc": 1}
    assert flags.loc[0, "reason"] == "open_and_close_outside"
    pd.testing.assert_frame_equal(d, before)


def test_inverted_range_is_not_mislabeled_as_settlement_difference():
    d = frame()
    d.loc[0, ["high", "low"]] = [97, 103]
    report, flags = ohlc_diagnostics(d, "date")
    assert report["inverted_ranges"] == 1
    assert flags.loc[0, "reason"] == "inverted_range"


def test_malformed_numeric_is_separate_from_valid_numeric_ohlc():
    d = frame().astype({"close": object})
    d.loc[0, "close"] = "bad"
    report, flags = ohlc_diagnostics(d, "date")
    assert report["invalid_numeric"] == 1
    assert report["ohlc_violations"] == 0
    assert flags.loc[0, "reason"] == "invalid_numeric"


def test_unit_conversion_is_measured_not_assumed():
    d = frame()
    for c in ["open", "high", "low", "close"]:
        d[c+"_usd_kg"] = d[c]*32.15074657
    report = unit_diagnostics(d)
    assert report["close"]["mismatches"] == 0
    d.loc[1, "close_usd_kg"] += 20
    assert unit_diagnostics(d)["close"]["mismatches"] == 1


def test_missing_conversion_column_is_reported_unavailable():
    assert unit_diagnostics(frame())["close"]["status"] == "unavailable"
