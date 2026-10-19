"""Purged chronological validation and predeclared acceptance rules."""
from __future__ import annotations

import numpy as np
import pandas as pd


def expanding_splits(samples: pd.DataFrame, holdout_start: int) -> list[tuple[np.ndarray, np.ndarray]]:
    if holdout_start < 200:
        raise ValueError("insufficient history for three expanding folds")
    # 50%,60%,70%,80% of the original ordered samples.
    boundaries = np.linspace(int(holdout_start*.625), holdout_start, 4, dtype=int)
    splits = []
    for left, right in zip(boundaries[:-1], boundaries[1:]):
        train = np.flatnonzero((samples.index < left) & (samples.target_timestamp < samples.timestamp.iloc[left]))
        valid = np.flatnonzero((samples.index >= left) & (samples.index < right) &
                              (samples.target_timestamp < samples.timestamp.iloc[holdout_start]))
        if len(train) < 100 or len(valid) < 20:
            raise ValueError("insufficient purged fold samples")
        splits.append((train, valid))
    return splits


def metrics(reference: np.ndarray, actual: np.ndarray, predicted: np.ndarray) -> dict:
    reference, actual, predicted = (np.asarray(x, dtype=float) for x in (reference, actual, predicted))
    if not len(actual) or not all(np.isfinite(x).all() for x in (reference, actual, predicted)):
        raise ValueError("empty or nonfinite evaluation")
    err = predicted-actual
    true_direction, forecast_direction = np.sign(actual-reference), np.sign(predicted-reference)
    recall = [float(np.mean(forecast_direction[true_direction==c]==c)) for c in np.unique(true_direction)]
    positive = true_direction > 0
    predicted_positive = forecast_direction > 0
    return {"n": len(actual), "mae": float(np.mean(np.abs(err))),
            "rmse": float(np.sqrt(np.mean(err**2))), "bias": float(np.mean(err)),
            "smape": float(np.mean(2*np.abs(err)/(np.abs(actual)+np.abs(predicted)))*100),
            "directional_accuracy": float(np.mean(true_direction==forecast_direction)),
            "balanced_accuracy": float(np.mean(recall)),
            "positive_precision": float(np.sum(positive & predicted_positive)/max(1, predicted_positive.sum())),
            "positive_recall": float(np.sum(positive & predicted_positive)/max(1, positive.sum())),
            "return_mae": float(np.mean(np.abs((predicted-actual)/reference)))}


def loss_improvement_interval(baseline_loss: np.ndarray, model_loss: np.ndarray,
                              horizon: int, draws: int = 2000) -> dict:
    difference = np.asarray(baseline_loss)-np.asarray(model_loss)
    n = len(difference)
    if n < 2:
        raise ValueError("insufficient bootstrap observations")
    block = min(n, max(horizon, int(np.ceil(n**(1/3)))))
    rng = np.random.default_rng(20261019)
    means = np.empty(draws)
    for i in range(draws):
        starts = rng.integers(0, n-block+1, size=int(np.ceil(n/block)))
        indexes = (starts[:, None] + np.arange(block)).ravel()[:n]
        means[i] = np.mean(difference[indexes])
    return {"mean": float(np.mean(difference)), "lower": float(np.quantile(means, .01)),
            "upper": float(np.quantile(means, .99)), "block_length": block,
            "draws": draws, "method": "moving-block percentile bootstrap, one-sided alpha=.05/5"}


def acceptance(holdout_relative_mae: float, fold_ratios: list[float], n: int,
               coverage: float, bootstrap_lower: float) -> dict:
    checks = {"material_improvement": holdout_relative_mae <= .95,
              "fold_wins": sum(r < 1 for r in fold_ratios) >= 2,
              "fold_stability": max(fold_ratios) <= 1.10,
              "holdout_sample_size": n >= 200,
              "interval_coverage": coverage >= .85,
              "bootstrap_improvement": bootstrap_lower > 0}
    return {"checks": checks, "quantitative_pass": all(checks.values()),
            "production_pass": False,
            "production_blockers": ["exchange calendar and bar publication/completion semantics unverified",
                                    "front-month rollover methodology unverified",
                                    "current licensed production data provider unavailable",
                                    "human production approval not supplied"]}
