# Daily model evaluation

Final holdout used once per eligible horizon. No tuning followed final outcomes. Prices and errors are USD/troy ounce. Holdout predictions are retained locally outside Git.

## Horizon 1 observed bars

Usable samples: 3832. Status: `frozen`.

Frozen model: `arima_return`. Strongest validation-selected baseline: `baseline_naive`.

Final origins begin 2021-12-06 00:00:00+00:00; last target 2026-10-16 00:00:00+00:00. Frozen raw cutoff: 2021-12-06 00:00:00+00:00.

| Metric | Candidate | Baseline |
|---|---:|---:|
| n | 1222 | 1222 |
| mae | 21.846168 | 21.835678 |
| rmse | 38.359092 | 38.345965 |
| bias | -0.74738153 | -0.56252048 |
| smape | 1.6724778 | 1.6717213 |
| directional_accuracy | 0.4811784 | 0.0024549918 |
| balanced_accuracy | 0.33220339 | 0.33333333 |
| positive_precision | 0 | 0 |
| positive_recall | 0 | 0 |
| return_mae | 0.016710671 | 0.016703106 |

Relative MAE: 1.00048038. Improvement: -0.0480%.
Empirical nominal-90% interval coverage: 84.2062%; mean width: 67.7200. Intervals use validation residuals, with no exchangeability or coverage guarantee.
Validation fold MAE ratios: [0.9963429487150696, 1.0016067682678205, 1.0008444578725673].
Validation relative MAE: 1.00014664.
Moving-block bootstrap improvement interval: [-0.024226, 0.002620]; lower bound uses alpha=.01 (five planned comparisons).

| Gate | Pass |
|---|---|
| material_improvement | False |
| fold_wins | False |
| fold_stability | True |
| holdout_sample_size | True |
| interval_coverage | False |
| bootstrap_improvement | False |

**Decision: research only; no promotion.**

Volatility-regime and test-start-sensitivity diagnostics are in the matching evidence JSON. These diagnostics were not used to reselect a model. No trading strategy or profitability evaluation was performed.

## Horizon 5 observed bars

Usable samples: 3806. Status: `frozen`.

Frozen model: `ridge_return`. Strongest validation-selected baseline: `baseline_naive`.

Final origins begin 2021-12-06 00:00:00+00:00; last target 2026-10-16 00:00:00+00:00. Frozen raw cutoff: 2021-12-06 00:00:00+00:00.

| Metric | Candidate | Baseline |
|---|---:|---:|
| n | 1218 | 1218 |
| mae | 46.174998 | 46.270113 |
| rmse | 75.245145 | 75.253477 |
| bias | -0.56887801 | -2.8412152 |
| smape | 3.5804144 | 3.6033634 |
| directional_accuracy | 0.53612479 | 0 |
| balanced_accuracy | 0.53373957 | 0 |
| positive_precision | 0.55522388 | 0 |
| positive_recall | 0.58215962 | 0 |
| return_mae | 0.035918576 | 0.036146583 |

Relative MAE: 0.99794434. Improvement: 0.2056%.
Empirical nominal-90% interval coverage: 85.8785%; mean width: 147.3707. Intervals use validation residuals, with no exchangeability or coverage guarantee.
Validation fold MAE ratios: [0.9884360963859969, 1.0015957883728768, 0.9887489409455529].
Validation relative MAE: 0.99337104.
Moving-block bootstrap improvement interval: [-1.146334, 1.227395]; lower bound uses alpha=.01 (five planned comparisons).

| Gate | Pass |
|---|---|
| material_improvement | False |
| fold_wins | True |
| fold_stability | True |
| holdout_sample_size | True |
| interval_coverage | True |
| bootstrap_improvement | False |

**Decision: research only; no promotion.**

Volatility-regime and test-start-sensitivity diagnostics are in the matching evidence JSON. These diagnostics were not used to reselect a model. No trading strategy or profitability evaluation was performed.
