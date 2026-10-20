import json
import hashlib

import pytest

pytest.importorskip("pandas", reason="optional platinum audit dependencies")
import pandas as pd

from scripts.platinum_data_audit.run_audit import run_audit


def workbook(path):
    daily = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=5), "open": 100.,
                          "high": 102., "low": 98., "close": 101., "volume": 10})
    hourly = daily.drop(columns="date").copy()
    hourly["timestamp_utc"] = pd.date_range("2025-01-01", periods=5, freq="h")
    hourly["datetime_riyadh"] = hourly.timestamp_utc + pd.Timedelta(hours=3)
    with pd.ExcelWriter(path) as writer:
        daily.to_excel(writer, sheet_name="Daily", index=False)
        hourly.to_excel(writer, sheet_name="Hourly", index=False)
        pd.DataFrame({"item": ["symbol"], "value": ["PL=F"]}).to_excel(writer, sheet_name="Notes", index=False)


def test_audit_writes_evidence_preserves_original_and_refuses_overwrite(tmp_path):
    path = tmp_path / "raw.xlsx"
    workbook(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    output = tmp_path / "audit"
    result = run_audit(path, output, pd.Timestamp("2026-10-20T04:00Z"))
    assert result["source_sha256"] == before
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert result["production_approved"] is False
    assert (output / "hourly_interval_flags.csv").is_file()
    assert json.loads((output / "summary.json").read_text())["daily"]["ohlc_violations"] == 0
    assert (output / "AUDIT_FINDINGS.md").is_file()
    with pytest.raises(FileExistsError):
        run_audit(path, output, pd.Timestamp("2026-10-20T04:00Z"))


def test_timezone_disagreement_blocks_audit(tmp_path):
    path = tmp_path / "raw.xlsx"
    workbook(path)
    h = pd.read_excel(path, sheet_name="Hourly")
    h["datetime_riyadh"] += pd.Timedelta(hours=1)
    with pd.ExcelWriter(path, mode="a", engine="openpyxl", if_sheet_exists="replace") as writer:
        h.to_excel(writer, sheet_name="Hourly", index=False)
    with pytest.raises(ValueError, match="Riyadh"):
        run_audit(path, tmp_path / "audit", pd.Timestamp("2026-10-20T04:00Z"))


def test_future_source_probe_observation_cannot_be_reused_as_unseen(tmp_path, monkeypatch):
    import scripts.platinum_data_audit.run_audit as module
    path = tmp_path / "raw.xlsx"
    workbook(path)
    monkeypatch.setattr(module, "probe_sources", lambda _: {
        "yahoo_chart": {"url": "https://query1.finance.yahoo.com/", "status": "retrieved_review_required",
                        "chart_metadata": {"last_chart_timestamp_utc": "2027-01-01T00:00:00+00:00"}}})
    result = run_audit(path, tmp_path / "audit", pd.Timestamp("2026-10-20T04:00Z"), probe=True)
    assert result["prospective_policy"]["new_holdout_after_exclusive"] == "2027-01-01T00:00:00+00:00"
