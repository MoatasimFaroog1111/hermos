# Forecasting architecture

The authoritative diagram and frozen protocol are in
[PLATINUM_FORECASTING_ARCHITECTURE.md](../../PLATINUM_FORECASTING_ARCHITECTURE.md).

Daily and hourly projects have independent configurations, cleaned frames,
sample populations, folds, searches, model decisions and registry directories.
No learned state or cross-frequency output passes between them. Shared code
implements deterministic data contracts and causal transformations.

Information cutoff is the availability time of a fully completed source bar.
Historical date labels alone do not prove that availability time. Research
origin is the completed observed bar index; target is the close h observed
bars later within the same conservative continuity segment. Daily horizons
are 1/5 bars; hourly horizons 1/4 bars are evaluated, 24 bars is blocked.
This restriction excludes many overnight/session transitions. Results do not
describe arbitrary next-session or 24-clock-hour predictions.

The local Forecast API is a typed Python contract, not a new HTTP listener.
`ForecastService` receives an injected verified-data provider and an
operator-owned registry. It reads safe JSON linear weights, checks digests,
rejects unapproved models, stale/incomplete prices and unsupported feature
schemas, then emits versioned price/interval/timestamp metadata. Its successful
path was tested with synthetic approved fixtures only. No real approved model
or verified current provider exists. ARIMA/tree export and online adapters are
intentionally not implemented or activated after failed promotion gates.

No core Hermes modules, root dependency declarations or root lockfiles changed.
The optional research dependency set has its own hashed lock. New tests skip
explicitly in a core-only environment and run in the dedicated research CI job.
The CI configuration was added; a remote GitHub Actions execution was not observed.
