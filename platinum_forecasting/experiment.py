"""Frozen selection and single-use holdout orchestration; no production side effects."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import optuna
import pandas as pd

from .configuration import ResearchConfig
from .data_audit import clean_bars, file_digest, read_workbook
from .features import supervised_samples
from .model_research import BASELINES, CANDIDATES, fit_predict
from .validation import acceptance, expanding_splits, loss_improvement_interval, metrics


def write_once(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def claim_holdout(directory: Path, selection_sha256: str) -> None:
    write_once(directory / "HOLDOUT_CONSUMED.json", {"selection_sha256": selection_sha256,
               "claimed_at": datetime.now(timezone.utc).isoformat()})


def verify_selection(selection: dict, dataset_sha256: str, code_sha256: str) -> None:
    if selection["dataset_sha256"] != dataset_sha256 or selection["code_sha256"] != code_sha256:
        raise ValueError("dataset or research code changed after selection")


def code_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def audit_workbook(workbook: Path, output: Path) -> dict:
    audits = {"dataset_sha256": file_digest(workbook), "sheets": pd.ExcelFile(workbook).sheet_names}
    for frequency in ("daily", "hourly"):
        bars, audit = clean_bars(read_workbook(workbook, frequency), frequency)
        audits[frequency] = audit
        output.mkdir(parents=True, exist_ok=True)
        bars.to_csv(output / f"{frequency}_clean.csv", index=False)
    write_once(output / "audit.json", audits)
    return audits


def _score_candidate(name: str, params: dict, samples: pd.DataFrame, splits: list, horizon: int) -> dict:
    rows, residuals, losses = [], [], []
    started = time.monotonic()
    for train_index, valid_index in splits:
        train, valid = samples.iloc[train_index], samples.iloc[valid_index]
        prediction = fit_predict(name, params, train, valid, horizon)
        rows.append(metrics(valid.reference_close.to_numpy(), valid.target_close.to_numpy(), prediction))
        residuals.extend((np.abs(prediction-valid.target_close.to_numpy())/valid.reference_close.to_numpy()).tolist())
        losses.extend(np.abs(prediction-valid.target_close.to_numpy()).tolist())
    radius = float(np.quantile(residuals, min(1., np.ceil((len(residuals)+1)*.9)/len(residuals)), method="higher"))
    return {"model": name, "params": params, "folds": rows,
            "validation_mae": float(np.mean(losses)), "interval_relative_radius": radius,
            "seconds": time.monotonic()-started}


def select(workbook: Path, output: Path, config: ResearchConfig) -> dict:
    directory = output / f"{config.frequency}_h{config.horizon}"
    if (directory / "selection.json").exists():
        raise FileExistsError("selection already frozen; do not retune from final outcomes")
    bars, audit = clean_bars(read_workbook(workbook, config.frequency), config.frequency)
    samples = supervised_samples(bars, config.frequency, config.horizon)
    metadata = {"config": config.model_dump(), "dataset_sha256": file_digest(workbook),
                "code_sha256": code_digest(), "audit": audit, "usable_samples": len(samples),
                "created_at": datetime.now(timezone.utc).isoformat()}
    if len(samples) < config.minimum_samples:
        metadata.update(status="blocked_insufficient_samples", production_pass=False)
        write_once(directory / "selection.json", metadata)
        return metadata
    # Cut off at 80% of cleaned row origins, independent of feature eligibility.
    cutoff_row = int(len(bars)*(1-config.holdout_fraction))
    cutoff = bars.timestamp.iloc[cutoff_row]
    holdout_start = int(samples.timestamp.searchsorted(cutoff))
    splits = expanding_splits(samples, holdout_start, cutoff)
    results = [_score_candidate(name, {}, samples, splits, config.horizon) for name in BASELINES+CANDIDATES]
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        family = trial.suggest_categorical("family", list(CANDIDATES[:-1]))
        if family.startswith("ridge"):
            params = {"alpha": trial.suggest_float("alpha", 1., 10000., log=True)}
        elif family == "hist_gradient":
            params = {"max_leaf_nodes": trial.suggest_categorical("leaves", [3, 7, 15]),
                      "l2_regularization": trial.suggest_float("l2", 1., 100., log=True)}
        else:
            params = {"num_leaves": trial.suggest_categorical("leaves", [3, 7, 15]),
                      "reg_lambda": trial.suggest_float("l2", 1., 100., log=True)}
        result = _score_candidate(family, params, samples, splits, config.horizon)
        results.append(result)
        return result["validation_mae"]

    study = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=config.seed), direction="minimize")
    study.optimize(objective, n_trials=config.trials, timeout=600)
    baseline = min((r for r in results if r["model"] in BASELINES), key=lambda r: r["validation_mae"])
    champion = min((r for r in results if r["model"] in CANDIDATES), key=lambda r: r["validation_mae"])
    metadata.update(status="frozen", holdout_start_timestamp=str(cutoff),
                    holdout_start_index=holdout_start, baseline=baseline, champion=champion,
                    candidates=results, features=sorted(c for c in samples if c.startswith("feature__")),
                    fold_boundaries=[{"train_end": str(samples.timestamp.iloc[t[-1]]),
                                     "max_train_target": str(samples.target_timestamp.iloc[t].max()),
                                     "validation_start": str(samples.timestamp.iloc[v[0]]),
                                     "validation_end": str(samples.timestamp.iloc[v[-1]])} for t, v in splits],
                    thresholds={"relative_mae": .95, "maximum_fold_ratio": 1.10,
                                "minimum_fold_wins": 2, "minimum_holdout": 200, "coverage": .85,
                                "bootstrap_alpha": .01}, optuna_completed_trials=len(study.trials))
    write_once(directory / "selection.json", metadata)
    return metadata


def evaluate(workbook: Path, output: Path, config: ResearchConfig) -> dict:
    directory = output / f"{config.frequency}_h{config.horizon}"
    path = directory / "selection.json"
    selected = json.loads(path.read_text(encoding="utf-8"))
    verify_selection(selected, file_digest(workbook), code_digest())
    if selected["config"] != config.model_dump():
        raise ValueError("configuration changed after selection")
    if selected["status"] != "frozen":
        return {"status": selected["status"], "production_pass": False}
    claim_holdout(directory, file_digest(path))
    bars, _ = clean_bars(read_workbook(workbook, config.frequency), config.frequency)
    samples = supervised_samples(bars, config.frequency, config.horizon)
    cutoff = pd.Timestamp(selected["holdout_start_timestamp"])
    train = samples.loc[samples.target_timestamp < cutoff]
    test = samples.loc[samples.timestamp >= cutoff]
    winner, baseline = selected["champion"], selected["baseline"]
    started = time.monotonic()
    prediction = fit_predict(winner["model"], winner["params"], train, test, config.horizon)
    baseline_prediction = fit_predict(baseline["model"], {}, train, test, config.horizon)
    score = metrics(test.reference_close.to_numpy(), test.target_close.to_numpy(), prediction)
    baseline_score = metrics(test.reference_close.to_numpy(), test.target_close.to_numpy(), baseline_prediction)
    radius = test.reference_close.to_numpy()*winner["interval_relative_radius"]
    coverage = float(np.mean(np.abs(prediction-test.target_close.to_numpy()) <= radius))
    bootstrap = loss_improvement_interval(np.abs(baseline_prediction-test.target_close.to_numpy()),
                                          np.abs(prediction-test.target_close.to_numpy()), config.horizon)
    fold_ratios = [m["mae"]/b["mae"] for m,b in zip(winner["folds"], baseline["folds"])]
    relative = score["mae"]/baseline_score["mae"]
    decision = acceptance(relative, fold_ratios, len(test), coverage, bootstrap["lower"])
    score.update(relative_mae=relative, interval_coverage=coverage,
                 mean_interval_width=float(np.mean(2*radius)))
    volatility = test[[c for c in test if "volatility_" in c][0]].to_numpy()
    threshold = float(train[[c for c in train if "volatility_" in c][0]].median().iloc[0])
    regimes = {}
    for label, mask in (("low_volatility", volatility<=threshold), ("high_volatility", volatility>threshold)):
        if mask.any():
            regimes[label] = metrics(test.reference_close.to_numpy()[mask], test.target_close.to_numpy()[mask], prediction[mask])
    portions = {}
    for fraction in (0., .25, .5):
        start = int(len(test)*fraction)
        portions[str(fraction)] = metrics(test.reference_close.to_numpy()[start:], test.target_close.to_numpy()[start:], prediction[start:])
    result = {"status": "evaluated_once", "selection_sha256": file_digest(path),
              "config": config.model_dump(), "champion": winner["model"], "baseline": baseline["model"],
              "holdout": score, "baseline_holdout": baseline_score, "fold_ratios": fold_ratios,
              "bootstrap": bootstrap, "decision": decision, "regimes": regimes,
              "test_start_sensitivity_diagnostic_only": portions,
              "validation_relative_mae": winner["validation_mae"]/baseline["validation_mae"],
              "seconds": time.monotonic()-started,
              "first_origin": str(test.timestamp.iloc[0]), "last_target": str(test.target_timestamp.iloc[-1])}
    write_once(directory / "evaluation.json", result)
    predictions = test[["timestamp", "target_timestamp", "reference_close", "target_close"]].copy()
    predictions["prediction"] = prediction
    predictions["baseline"] = baseline_prediction
    predictions["lower_90"] = prediction-radius
    predictions["upper_90"] = prediction+radius
    predictions.to_csv(directory / "holdout_predictions.csv", index=False)
    return result
