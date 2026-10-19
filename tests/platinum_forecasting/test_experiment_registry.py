import json

import pytest

from platinum_forecasting.experiment import write_once, claim_holdout, verify_selection
from platinum_forecasting.configuration import ResearchConfig


def test_research_budget_is_validated():
    with pytest.raises(ValueError):
        ResearchConfig(frequency="hourly", horizon=0)
    with pytest.raises(ValueError):
        ResearchConfig(frequency="daily", horizon=24)


def test_selection_cannot_be_overwritten(tmp_path):
    path = tmp_path / "selection.json"
    write_once(path, {"candidate": "ridge_return"})
    with pytest.raises(FileExistsError):
        write_once(path, {"candidate": "lightgbm"})
    assert json.loads(path.read_text())["candidate"] == "ridge_return"


def test_holdout_is_consumed_before_execution_and_cannot_be_reopened(tmp_path):
    claim_holdout(tmp_path, "abc")
    with pytest.raises(FileExistsError):
        claim_holdout(tmp_path, "abc")


def test_selection_detects_modified_dataset_or_code(tmp_path):
    manifest = {"dataset_sha256": "a", "code_sha256": "b"}
    verify_selection(manifest, "a", "b")
    with pytest.raises(ValueError, match="changed"):
        verify_selection(manifest, "c", "b")
    with pytest.raises(ValueError, match="changed"):
        verify_selection(manifest, "a", "c")


def test_real_training_freeze_holdout_and_reopen_rejection(tmp_path):
    import numpy as np
    import pandas as pd
    from platinum_forecasting.experiment import select, evaluate
    from platinum_forecasting.features import build_features

    rng = np.random.default_rng(8)
    close = 1000*np.exp(np.cumsum(rng.normal(0, .002, 850)))
    raw = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=850),
                        "open": close, "high": close+2, "low": close-2,
                        "close": close, "volume": 100})
    path = tmp_path / "prices.xlsx"
    raw.to_excel(path, sheet_name="Daily", index=False)
    config = ResearchConfig(frequency="daily", horizon=1, trials=0)
    frozen = select(path, tmp_path / "run", config)
    assert frozen["status"] == "frozen"
    assert all(pd.Timestamp(f["max_train_target"]) < pd.Timestamp(f["validation_start"]) for f in frozen["fold_boundaries"])
    result = evaluate(path, tmp_path / "run", config)
    assert result["holdout"]["n"] > 100
    assert not result["decision"]["production_pass"]
    with pytest.raises(FileExistsError):
        evaluate(path, tmp_path / "run", config)
