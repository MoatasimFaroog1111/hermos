# Model comparison

Candidate selection used three purged expanding folds, then eight Optuna trials per eligible dataset/horizon. Four eligible experiments contain 17 configurations each (68 configurations and 204 fold fits). Seeds and parameters are frozen in evidence. No deep networks, GPUs, paid cloud resources, external covariates, stacking or large search were justified by the audited data.

| Project/horizon | Candidate | Validation MAE | Parameters |
|---|---|---:|---|
| daily_h1 | baseline_naive | 12.581491 | `{}` |
| daily_h1 | baseline_seasonal | 27.542129 | `{}` |
| daily_h1 | baseline_drift | 12.802693 | `{}` |
| daily_h1 | baseline_sma | 29.730901 | `{}` |
| daily_h1 | ridge_return | 12.678599 | `{}` |
| daily_h1 | ridge_price | 23.183769 | `{}` |
| daily_h1 | hist_gradient | 12.892035 | `{}` |
| daily_h1 | lightgbm | 12.637574 | `{}` |
| daily_h1 | arima_return | 12.583336 | `{}` |
| daily_h1 | ridge_price | 13.794697 | `{"alpha": 23.72207603798195}` |
| daily_h1 | lightgbm | 12.640809 | `{"num_leaves": 15, "reg_lambda": 31.63025292838844}` |
| daily_h1 | ridge_price | 13.100080 | `{"alpha": 12.347759201050502}` |
| daily_h1 | ridge_return | 12.685536 | `{"alpha": 80.649608843936}` |
| daily_h1 | ridge_return | 12.595108 | `{"alpha": 3008.532811312054}` |
| daily_h1 | lightgbm | 12.622873 | `{"num_leaves": 7, "reg_lambda": 97.98243909989455}` |
| daily_h1 | hist_gradient | 13.126145 | `{"l2_regularization": 23.48144791327791, "max_leaf_nodes": 15}` |
| daily_h1 | ridge_return | 12.613016 | `{"alpha": 1251.4198263706699}` |
| daily_h5 | baseline_naive | 27.690167 | `{}` |
| daily_h5 | baseline_seasonal | 27.690167 | `{}` |
| daily_h5 | baseline_drift | 32.430334 | `{}` |
| daily_h5 | baseline_sma | 37.231362 | `{}` |
| daily_h5 | ridge_return | 28.090618 | `{}` |
| daily_h5 | ridge_price | 34.510948 | `{}` |
| daily_h5 | hist_gradient | 30.088661 | `{}` |
| daily_h5 | lightgbm | 28.409549 | `{}` |
| daily_h5 | arima_return | 27.644307 | `{}` |
| daily_h5 | ridge_price | 28.987016 | `{"alpha": 23.72207603798195}` |
| daily_h5 | lightgbm | 28.254205 | `{"num_leaves": 15, "reg_lambda": 31.63025292838844}` |
| daily_h5 | ridge_price | 28.737689 | `{"alpha": 12.347759201050502}` |
| daily_h5 | ridge_return | 28.120782 | `{"alpha": 80.649608843936}` |
| daily_h5 | ridge_return | 27.506610 | `{"alpha": 3008.532811312054}` |
| daily_h5 | lightgbm | 28.091223 | `{"num_leaves": 7, "reg_lambda": 97.98243909989455}` |
| daily_h5 | hist_gradient | 30.813343 | `{"l2_regularization": 23.48144791327791, "max_leaf_nodes": 15}` |
| daily_h5 | ridge_return | 27.595678 | `{"alpha": 1251.4198263706699}` |
| hourly_h1 | baseline_naive | 11.460646 | `{}` |
| hourly_h1 | baseline_seasonal | 29.067470 | `{}` |
| hourly_h1 | baseline_drift | 12.211913 | `{}` |
| hourly_h1 | baseline_sma | 23.292998 | `{}` |
| hourly_h1 | ridge_return | 11.601539 | `{}` |
| hourly_h1 | ridge_price | 50.795443 | `{}` |
| hourly_h1 | hist_gradient | 11.693873 | `{}` |
| hourly_h1 | lightgbm | 11.537655 | `{}` |
| hourly_h1 | arima_return | 11.772750 | `{}` |
| hourly_h1 | ridge_price | 17.880499 | `{"alpha": 23.72207603798195}` |
| hourly_h1 | lightgbm | 11.535208 | `{"num_leaves": 15, "reg_lambda": 31.63025292838844}` |
| hourly_h1 | ridge_price | 13.913377 | `{"alpha": 12.347759201050502}` |
| hourly_h1 | ridge_return | 11.610601 | `{"alpha": 80.649608843936}` |
| hourly_h1 | ridge_return | 11.496968 | `{"alpha": 3008.532811312054}` |
| hourly_h1 | lightgbm | 11.498541 | `{"num_leaves": 7, "reg_lambda": 97.98243909989455}` |
| hourly_h1 | hist_gradient | 11.766005 | `{"l2_regularization": 23.48144791327791, "max_leaf_nodes": 15}` |
| hourly_h1 | ridge_return | 11.515831 | `{"alpha": 1251.4198263706699}` |
| hourly_h4 | baseline_naive | 23.422907 | `{}` |
| hourly_h4 | baseline_seasonal | 30.155874 | `{}` |
| hourly_h4 | baseline_drift | 27.286538 | `{}` |
| hourly_h4 | baseline_sma | 32.903637 | `{}` |
| hourly_h4 | ridge_return | 24.051050 | `{}` |
| hourly_h4 | ridge_price | 71.229055 | `{}` |
| hourly_h4 | hist_gradient | 25.226895 | `{}` |
| hourly_h4 | lightgbm | 24.212710 | `{}` |
| hourly_h4 | arima_return | 27.154395 | `{}` |
| hourly_h4 | ridge_price | 31.363128 | `{"alpha": 23.72207603798195}` |
| hourly_h4 | lightgbm | 24.383393 | `{"num_leaves": 15, "reg_lambda": 31.63025292838844}` |
| hourly_h4 | ridge_price | 26.944786 | `{"alpha": 12.347759201050502}` |
| hourly_h4 | ridge_return | 24.097642 | `{"alpha": 80.649608843936}` |
| hourly_h4 | ridge_return | 23.581947 | `{"alpha": 3008.532811312054}` |
| hourly_h4 | lightgbm | 23.921842 | `{"num_leaves": 7, "reg_lambda": 97.98243909989455}` |
| hourly_h4 | hist_gradient | 25.847339 | `{"l2_regularization": 23.48144791327791, "max_leaf_nodes": 15}` |
| hourly_h4 | ridge_return | 23.648004 | `{"alpha": 1251.4198263706699}` |

## Final decisions

| Project | Model | MAE | Baseline MAE | MAE improvement | Promoted |
|---|---|---:|---:|---:|---|
| daily_h1 | arima_return | 21.84617 | 21.83568 | -0.048% | No |
| daily_h5 | ridge_return | 46.17500 | 46.27011 | 0.206% | No |
| hourly_h1 | ridge_return | 6.68043 | 6.63511 | -0.683% | No |
| hourly_h24 | Insufficient data | — | — | — | No |
| hourly_h4 | ridge_return | 14.17889 | 14.06254 | -0.827% | No |

No candidate demonstrates a material, statistically supported improvement over the strongest validation baseline. This is a negative result for this specified search, not evidence that all possible future methods fail. Return regression supplies both price and direction; direction was not optimized separately from the preregistered price-loss criterion. Balanced accuracy includes the zero-return class. Relative MAE is reported rather than MASE; the baseline is the validation-selected comparator.

ARIMA(1,0,0) return parameters are fitted on the longest contiguous training-origin segment only; hourly fits can be short. This is deliberately a small statistical comparator. SARIMA, exponential smoothing, XGBoost/CatBoost and deep networks were not executed; this is not an exhaustive benchmark. Generalization, regime and interval diagnostics do not certify source publication timing.
