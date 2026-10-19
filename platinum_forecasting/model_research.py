"""Small CPU-only candidate set; transforms fit strictly inside each fold."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.arima.model import ARIMA
from threadpoolctl import threadpool_limits

BASELINES = ("baseline_naive", "baseline_seasonal", "baseline_drift", "baseline_sma")
CANDIDATES = ("ridge_return", "ridge_price", "hist_gradient", "lightgbm", "arima_return")


def fit_predict(name: str, params: dict, train: pd.DataFrame, evaluation: pd.DataFrame,
                horizon: int = 1) -> np.ndarray:
    if name in BASELINES:
        return evaluation[name].to_numpy(float)
    features = sorted(c for c in train if c.startswith("feature__"))
    if name == "arima_return":
        # ARIMA(1,0,0) on one-bar returns; no cross-gap transition is learned:
        # each observed feature is a one-bar return inside a continuity segment.
        # Concatenation estimates stationary parameters only, not serving state.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            fitted = ARIMA(train["feature__return_lag_0"].to_numpy(), order=(1, 0, 0), trend="c").fit()
        mu, phi = float(fitted.params[0]), float(fitted.params[1])
        powers = sum(phi**k for k in range(1, horizon+1))
        expected = horizon*mu + (evaluation["feature__return_lag_0"].to_numpy()-mu)*powers
        return evaluation.reference_close.to_numpy()*np.exp(np.clip(expected, -.5, .5))
    if name.startswith("ridge_"):
        estimator = make_pipeline(StandardScaler(), Ridge(alpha=params.get("alpha", 100.)))
    elif name == "hist_gradient":
        estimator = HistGradientBoostingRegressor(max_iter=params.get("max_iter", 100),
            max_leaf_nodes=params.get("max_leaf_nodes", 7), min_samples_leaf=40,
            l2_regularization=params.get("l2_regularization", 10.), early_stopping=False, random_state=42)
    elif name == "lightgbm":
        estimator = LGBMRegressor(n_estimators=params.get("n_estimators", 100),
            num_leaves=params.get("num_leaves", 7), learning_rate=params.get("learning_rate", .03),
            reg_lambda=params.get("reg_lambda", 10.), min_child_samples=40,
            random_state=42, n_jobs=1, verbosity=-1, deterministic=True, force_col_wise=True)
    else:
        raise ValueError("unknown candidate")
    target = train.target_close if name == "ridge_price" else train.target_return
    with threadpool_limits(limits=1):
        estimator.fit(train[features], target)
        prediction = estimator.predict(evaluation[features])
    if name == "ridge_price":
        return np.asarray(prediction)
    return evaluation.reference_close.to_numpy()*np.exp(np.clip(prediction, -.5, .5))
