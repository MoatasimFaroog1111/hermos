# Hourly model evaluation

Final holdout used once per eligible horizon. No tuning followed final outcomes. Prices and errors are USD/troy ounce. Holdout predictions are retained locally outside Git.

## Horizon 1 observed bars

Usable samples: 4869. Status: `frozen`.

Frozen model: `ridge_return`. Strongest validation-selected baseline: `baseline_naive`.

Final origins begin 2026-05-28 13:00:00+00:00; last target 2026-10-19 11:00:00+00:00. Frozen raw cutoff: 2026-05-28 13:00:00+00:00.

| Metric | Candidate | Baseline |
|---|---:|---:|
| n | 997 | 997 |
| mae | 6.6804292 | 6.6351053 |
| rmse | 9.6512614 | 9.6125875 |
| bias | 0.62507667 | 0.2611837 |
| smape | 0.38669207 | 0.3841113 |
| directional_accuracy | 0.48746239 | 0.012036108 |
| balanced_accuracy | 0.33530542 | 0.33333333 |
| positive_precision | 0.47802929 | 0 |
| positive_recall | 0.75738397 | 0 |
| return_mae | 0.0038665875 | 0.0038407766 |

Relative MAE: 1.00683093. Improvement: -0.6831%.
Empirical nominal-90% interval coverage: 95.0853%; mean width: 41.7032. Intervals use validation residuals, with no exchangeability or coverage guarantee.
Validation fold MAE ratios: [0.9999145274326192, 1.0024336408709171, 1.0070733222101254].
Validation relative MAE: 1.00316927.
Moving-block bootstrap improvement interval: [-0.101850, 0.009298]; lower bound uses alpha=.01 (five planned comparisons).

| Gate | Pass |
|---|---|
| material_improvement | False |
| fold_wins | False |
| fold_stability | True |
| holdout_sample_size | True |
| interval_coverage | True |
| bootstrap_improvement | False |

**Decision: research only; no promotion.**

Volatility-regime and test-start-sensitivity diagnostics are in the matching evidence JSON. These diagnostics were not used to reselect a model. No trading strategy or profitability evaluation was performed.

## Horizon 24 observed bars

Usable samples: 11. Status: `blocked_insufficient_samples`.

Not trained or evaluated: fewer than 500 usable samples. No scores or model artifact invented.

## Horizon 4 observed bars

Usable samples: 3386. Status: `frozen`.

Frozen model: `ridge_return`. Strongest validation-selected baseline: `baseline_naive`.

Final origins begin 2026-05-28 13:00:00+00:00; last target 2026-10-16 20:00:00+00:00. Frozen raw cutoff: 2026-05-28 13:00:00+00:00.

| Metric | Candidate | Baseline |
|---|---:|---:|
| n | 702 | 702 |
| mae | 14.178891 | 14.062537 |
| rmse | 19.741039 | 19.619278 |
| bias | 2.7647095 | 1.6423095 |
| smape | 0.81762892 | 0.81135984 |
| directional_accuracy | 0.48717949 | 0.0028490028 |
| balanced_accuracy | 0.3403268 | 0.33333333 |
| positive_precision | 0.47260274 | 0 |
| positive_recall | 0.8440367 | 0 |
| return_mae | 0.008170367 | 0.0081076039 |

Relative MAE: 1.00827403. Improvement: -0.8274%.
Empirical nominal-90% interval coverage: 95.0142%; mean width: 85.7372. Intervals use validation residuals, with no exchangeability or coverage guarantee.
Validation fold MAE ratios: [0.9979599603431671, 1.014191528400845, 1.0009562567081614].
Validation relative MAE: 1.00678993.
Moving-block bootstrap improvement interval: [-0.316516, 0.073441]; lower bound uses alpha=.01 (five planned comparisons).

| Gate | Pass |
|---|---|
| material_improvement | False |
| fold_wins | False |
| fold_stability | True |
| holdout_sample_size | True |
| interval_coverage | True |
| bootstrap_improvement | False |

**Decision: research only; no promotion.**

Volatility-regime and test-start-sensitivity diagnostics are in the matching evidence JSON. These diagnostics were not used to reselect a model. No trading strategy or profitability evaluation was performed.
