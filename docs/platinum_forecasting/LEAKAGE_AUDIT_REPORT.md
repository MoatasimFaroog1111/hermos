# Leakage audit

All executed experiments use the frozen protocol in the root architecture and
per-horizon selection manifests. Four actual holdouts were opened once each;
the 24-bar hourly horizon was not evaluated.

- Workbook bytes are hashed before selection and rechecked before evaluation.
- Numeric cleanup is deterministic and learns no global distribution. Prices
  and technical windows are not backfilled, centered or interpolated.
- Features use the completed origin bar or earlier bars in the same segment.
  Future mutations leave prior features unchanged in daily/hourly tests.
- Targets use a segment-local negative shift, never a fabricated market bar.
- Training labels must strictly precede the first validation origin. All
  validation target timestamps must also precede the frozen raw holdout cutoff.
- The last 20% of cleaned raw origins defines the cutoff even if feature warmup
  makes the first eligible holdout origin later. A reviewer found an earlier
  implementation moved that boundary; a regression test failed, then passed
  after the fix, before actual final evaluation.
- Scaling is inside each fitted linear pipeline. Trees have no fitted global
  imputation or external validation early stopping. All feature columns have
  finite observed inputs. No feature selection uses holdout data.
- ARIMA fits only a contiguous training-origin segment; future rows never
  change the first prediction in model-specific tests.
- Three training folds expand chronologically. Direct h-step labels are
  purged across boundaries. No post-validation training segment exists within
  a fold, so an additional post-window embargo is unnecessary here.
- Selection JSON is exclusive-create, with model/parameters/features, dataset
  digest, source digest, calibration radius, cutoffs and thresholds. A consumed
  marker is created before holdout execution. Reopening or overwriting fails.
- Synthetic end-to-end tests exercise real fitting, freezing, evaluation,
  report persistence and reopening rejection. These do not consume real data.
- Block-bootstrap differences use contiguous loss blocks of at least horizon
  length, 2,000 seeded draws, Bonferroni alpha=.01 for five planned comparisons.
  They approximate time dependence; they do not prove independence or eliminate
  market-regime risk. Interval coverage is empirical, not a confidence percent.

Source/selection hashes detect accidental changes, not a malicious local
operator. An operator can delete local ledgers; do not reuse an already viewed
holdout for subsequent model development. Any future experiment must disclose
this dataset's used test period and reserve genuinely new data.

**Remaining limitation:** actual vendor publication timestamps, historical
revisions, completed-bar flags and front-month roll methodology are unavailable.
Thus computational causality tests passed, but point-in-time market-data
certification did not. No claim of fully proven leakage-free production data
is made.
