import hashlib
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from platinum_forecasting.forecast_service import ForecastService, DataSnapshot


def registry(tmp_path, approved=True):
    artifact = {"kind": "linear_return", "features": ["feature__price_level"],
                "coefficients": [0.], "intercept": .001}
    data = json.dumps(artifact).encode()
    (tmp_path / "model.json").write_bytes(data)
    record = {"model_id": "daily-h1-v1", "frequency": "daily", "horizon": 1,
              "artifact": "model.json", "artifact_sha256": hashlib.sha256(data).hexdigest(),
              "promotion_status": "approved" if approved else "research_only",
              "quantitative_pass": approved, "data_provenance_verified": approved,
              "interval_relative_radius": .01, "empirical_interval_coverage": .9}
    (tmp_path / "active.json").write_text(json.dumps(record), encoding="utf-8")
    return tmp_path


def snapshot(stale=False, complete=True):
    now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    t = pd.date_range(end=now-timedelta(days=10 if stale else 1), periods=80, freq="D", tz="UTC")
    close = 1000 + np.arange(80)*.1
    bars = pd.DataFrame({"timestamp": t, "open": close, "high": close+2,
                         "low": close-2, "close": close, "volume": 100, "segment": 1})
    return DataSnapshot(bars=bars, information_cutoff=t[-1].to_pydatetime(),
                        target_timestamp=now+timedelta(days=1), complete=complete,
                        calendar_verified=True), now


def test_unpromoted_registry_never_returns_forecast(tmp_path):
    data, now = snapshot()
    with pytest.raises(ValueError, match="not approved"):
        ForecastService(registry(tmp_path, False), lambda: data).forecast("daily", 1, now)


@pytest.mark.parametrize("stale,complete", [(True, True), (False, False)])
def test_stale_or_incomplete_prices_fail_closed(tmp_path, stale, complete):
    data, now = snapshot(stale, complete)
    with pytest.raises(ValueError, match="stale|incomplete"):
        ForecastService(registry(tmp_path), lambda: data).forecast("daily", 1, now)


def test_tampered_artifact_rejected(tmp_path):
    root = registry(tmp_path)
    (root / "model.json").write_text("{}", encoding="utf-8")
    data, now = snapshot()
    with pytest.raises(ValueError, match="checksum"):
        ForecastService(root, lambda: data).forecast("daily", 1, now)


def test_fresh_cutoff_cannot_disguise_stale_last_price(tmp_path):
    data, now = snapshot(stale=True)
    forged = DataSnapshot(data.bars, now, data.target_timestamp, True, True)
    with pytest.raises(ValueError, match="stale"):
        ForecastService(registry(tmp_path), lambda: forged).forecast("daily", 1, now)


def test_provider_segment_labels_cannot_hide_price_gaps(tmp_path):
    data, now = snapshot()
    data.bars.loc[data.bars.index[:-1], "timestamp"] -= pd.Timedelta(days=30)
    with pytest.raises(ValueError, match="continuous"):
        ForecastService(registry(tmp_path), lambda: data).forecast("daily", 1, now)


def test_approved_synthetic_fixture_exercises_real_inference(tmp_path):
    data, now = snapshot()
    result = ForecastService(registry(tmp_path), lambda: data).forecast("daily", 1, now)
    assert result.predicted_price == pytest.approx(data.bars.close.iloc[-1]*np.exp(.001))
    assert result.lower_price < result.predicted_price < result.upper_price
    assert result.unit == "USD/troy_ounce"
    assert result.instrument == "PL=F futures"
    assert result.information_cutoff < result.issued_at < result.target_timestamp


def test_frequency_cannot_load_other_project_model(tmp_path):
    data, now = snapshot()
    with pytest.raises(ValueError, match="frequency or horizon"):
        ForecastService(registry(tmp_path), lambda: data).forecast("hourly", 1, now)


def test_registry_path_cannot_escape_root(tmp_path):
    root = registry(tmp_path)
    p = root / "active.json"
    record = json.loads(p.read_text())
    record["artifact"] = "../model.json"
    p.write_text(json.dumps(record), encoding="utf-8")
    data, now = snapshot()
    with pytest.raises(ValueError):
        ForecastService(root, lambda: data).forecast("daily", 1, now)


def test_rollback_restores_previous_reviewed_registry(tmp_path):
    root = registry(tmp_path)
    approved = (root / "active.json").read_bytes()
    data, now = snapshot()
    service = ForecastService(root, lambda: data)
    before = service.forecast("daily", 1, now)
    manifest = json.loads(approved)
    manifest["promotion_status"] = "research_only"
    (root / "active.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        service.forecast("daily", 1, now)
    (root / "active.json").write_bytes(approved)
    assert service.forecast("daily", 1, now) == before
