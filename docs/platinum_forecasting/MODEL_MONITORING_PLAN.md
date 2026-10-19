# Monitoring plan — inactive until acceptance

No production model or scheduled retraining is running. The following is the
operating contract for a future accepted version, not a claim of deployed
monitoring.

| Signal | Measurement and response |
|---|---|
| Data freshness | Validate actual last-price age and availability cutoff; reject future timestamps, >2-hour hourly data or >4-day daily data. Exchange-calendar-aware policies must supersede these conservative limits before activation. |
| Completion and gaps | Require independently verified completed bars and calendar; validate timestamps, OHLCV and expected target. Reject insufficient contiguous history. |
| Model readiness | Validate project/horizon, operator approval, data provenance, feature order and artifact SHA-256 on every local load. No fallback to an unapproved artifact. |
| Feature drift | Save training feature distributions per version; compare observed rolling distributions/PSI and missingness after >=200 observations. Establish thresholds on new validation data before deployment; alert an operator, never auto-promote. |
| Forecast error | Join each forecast ID/model ID with the actual target bar only after it completes. Record MAE, RMSE, relative MAE, directional outcomes and interval coverage over non-overlapping and overlapping horizon-aware windows separately. |
| Calibration | Monitor empirical coverage and interval width by horizon and volatility regime; investigate undercoverage before changing calibration using newly available data. |
| Operational faults | Log structured event type, project, horizon, model/dataset version, timestamp, latency and failure category. Never log credentials or whole environment/config dumps. |
| Regression | Compare against the same declared random-walk/strong baseline and track changes in price level/volatility. Sustained degradation triggers operator review and a safe stop. |
| Retraining | Manual offline job with bounded CPU/time. Use new data and a newly reserved holdout, validate train/inference parity, require independent review and human promotion. |
| Rollback | Keep prior approved immutable artifact/manifest; atomically restore it, run readiness/smoke checks and record operator action. |

The current CLI emits structured failure events; full metrics export, scheduled
monitoring and live-data error joins are deferred with production integration.
No scientific test here establishes trading profitability.
