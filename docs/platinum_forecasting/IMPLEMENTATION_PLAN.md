# Platinum Forecasting Implementation Plan

Goal: execute the user-specified staged research with independently gated daily
and hourly results, then prepare only justified Hermes integration.
Spec: [architecture](../../PLATINUM_FORECASTING_ARCHITECTURE.md).
Execution: inline; the user's explicit request authorizes progressing through
research stages without intermediate design approval. Production remains gated.

## Constraints
Python 3.11; isolated research dependencies; preserve Hermes core and lockfiles.
No raw dataset upload; no future leakage; no final-holdout retuning.

## Tasks
1. Data foundation: tests for malformed OHLC, duplicates, incomplete bars,
   timezone consistency, gaps and original-file preservation; implement audit
   and causal features. Run canonical Hermes test wrapper, then commit.
2. Scientific validation: tests for target purging, prefix invariance, fold-only
   preprocessing, metrics and reproducibility; implement fixed-budget candidates
   and frozen selection; run tests and commit before opening final holdout.
3. Independent decisions: hash and persist protocol/selection; evaluate holdout
   once per dataset/horizon, record every candidate and decision. Do not change
   selection in response to test scores. Write generated evidence outside Git.
4. Gated serving: test rejection of stale/incomplete data, unpromoted registry,
   tampered artifacts and unsupported horizons; implement typed JSON service and
   opt-in skill. No activation when data/model gates fail.
5. Reports and review: produce all requested reports, local smoke/repeatability
   checks, fresh code review, small commits, then attempt a PR with available
   scoped credentials. Never merge or publish production.

## Review focus
Conflicting duplicate timestamps must fail; same timestamp different timezone
representations must normalize; incomplete last bars must not enter features;
gaps must not become synthetic consecutive targets; holdout outcomes must not
alter model choice. Serving must reject caller-supplied promotion claims and
untrusted serialized objects.
