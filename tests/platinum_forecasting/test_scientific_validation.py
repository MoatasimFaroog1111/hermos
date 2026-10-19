import numpy as np
import pandas as pd
import pytest

from platinum_forecasting.validation import expanding_splits, metrics, loss_improvement_interval, acceptance
from platinum_forecasting.model_research import fit_predict


def samples(n=500, h=5):
    t = pd.date_range("2025-01-01", periods=n+h, freq="h", tz="UTC")
    return pd.DataFrame({"timestamp": t[:n], "target_timestamp": t[h:],
                         "reference_close": np.full(n, 1000.), "target_close": 1001.,
                         "target_return": np.log(1.001), "feature__x": np.sin(np.arange(n)),
                         "feature__return_lag_0": np.cos(np.arange(n))*.001})


def test_splits_purge_all_overlapping_labels_and_never_open_holdout():
    s = samples()
    holdout_start = 400
    splits = expanding_splits(s, holdout_start)
    assert len(splits) == 3
    for train, validation in splits:
        assert s.target_timestamp.iloc[train].max() < s.timestamp.iloc[validation].min()
        assert validation.max() < holdout_start
        assert s.target_timestamp.iloc[validation].max() < s.timestamp.iloc[holdout_start]


def test_insufficient_history_fails():
    with pytest.raises(ValueError, match="insufficient"):
        expanding_splits(samples(40), 32)


def test_metrics_are_numeric_and_include_zero_direction_as_class():
    m = metrics(np.array([100., 100., 100.]), np.array([101., 99., 100.]), np.array([101., 101., 100.]))
    assert m["mae"] == pytest.approx(2/3)
    assert m["directional_accuracy"] == pytest.approx(2/3)
    assert m["bias"] == pytest.approx(2/3)
    assert m["balanced_accuracy"] == pytest.approx(2/3)


def test_block_bootstrap_distinguishes_constant_advantage_reproducibly():
    a = loss_improvement_interval(np.ones(300)*2, np.ones(300), horizon=24)
    b = loss_improvement_interval(np.ones(300)*2, np.ones(300), horizon=24)
    assert a == b
    assert a["lower"] == pytest.approx(1.)


def test_failed_fold_stability_cannot_be_overridden_by_holdout_win():
    decision = acceptance(.8, [1.4, .7, .7], 500, .9, .1)
    assert not decision["quantitative_pass"]


def test_positive_holdout_alone_cannot_authorize_production():
    decision = acceptance(.8, [.9, .9, .9], 500, .9, .1)
    assert decision["quantitative_pass"]
    assert not decision["production_pass"]


@pytest.mark.parametrize("model", ["ridge_return", "ridge_price", "hist_gradient", "lightgbm", "arima_return"])
def test_fitted_predictions_ignore_other_future_rows(model):
    s = samples()
    train, future = s.iloc[:300].copy(), s.iloc[300:350].copy()
    pred = fit_predict(model, {}, train, future)
    changed = future.copy()
    changed.loc[changed.index[1:], ["feature__x", "target_close", "target_return"]] *= 10
    pred2 = fit_predict(model, {}, train, changed)
    assert np.isfinite(pred).all()
    assert pred[0] == pytest.approx(pred2[0])


def test_serving_feature_order_not_dataframe_column_order():
    s = samples()
    train, future = s.iloc[:300], s.iloc[300:350]
    a = fit_predict("ridge_return", {}, train, future)
    b = fit_predict("ridge_return", {}, train, future[future.columns[::-1]])
    assert np.allclose(a, b)
