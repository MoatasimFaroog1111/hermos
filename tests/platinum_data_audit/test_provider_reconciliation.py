import pytest

pytest.importorskip("pandas", reason="optional platinum audit dependencies")
import pandas as pd

from scripts.platinum_data_audit.provider_reconciliation import compare_daily_window


def payload(close):
    return {"chart": {"error": None, "result": [{"meta": {"symbol": "PL=F", "instrumentType": "FUTURE"},
            "timestamp": [946872000], "indicators": {"quote": [{"open": [100.], "high": [102.], "low": [98.], "close": [close], "volume": [10]}]}}]}}


def raw():
    return pd.DataFrame({"date": pd.to_datetime(["2000-01-03"]), "open": [100.], "high": [102.],
                         "low": [98.], "close": [110.], "volume": [10]})


def test_vendor_can_reproduce_anomaly_without_proving_settlement_cause():
    result = compare_daily_window(raw(), payload(110.))
    assert result["shared_dates"] == 1
    assert result["all_ohlc_identical_rows"] == 1
    assert result["workbook_ohlc_anomalies_reproduced"] == 1
    assert not result["settlement_cause_verified"]


def test_changed_vendor_price_is_reported_never_repaired():
    d = raw()
    result = compare_daily_window(d, payload(101.))
    assert result["per_column_mismatches"]["close"] == 1
    assert d.close.iloc[0] == 110.


def test_null_vendor_quote_is_not_a_price_agreement():
    result = compare_daily_window(raw(), payload(None))
    assert result["all_ohlc_identical_rows"] == 0
    assert result["vendor_nonfinite_rows"] == 1
