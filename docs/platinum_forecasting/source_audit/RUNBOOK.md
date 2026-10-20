# Reproduce the provenance audit

Use the existing isolated checkout and separate research virtual environment.
No new dependencies were added to either the root lock or the research lock.

```bash
cd /workspace/hermos
HERMES_PYTHON=/workspace/.venvs/platinum/bin/python bash scripts/run_tests.sh -j 3 tests/platinum_forecasting tests/platinum_data_audit
/workspace/.venvs/platinum/bin/python -m scripts.platinum_data_audit.run_audit \
  --workbook /workspace/attachments/16350ac2-8c9b-4daf-8d3a-bca83ed0597f/platinum_yahoo_full.xlsx \
  --output /workspace/platinum_audits/NEW_UNIQUE_AUDIT_DIRECTORY \
  --probe-sources --reconcile-provider
```

Choose a new output directory for each run; an existing one is rejected. Without
the two optional network flags, the tool runs workbook-only diagnostics and
clearly records that sources were not probed. Public probes use inherited proxy
and TLS trust, 15-second timeouts and a 3 MiB response limit, with no authentication
or bypass. Reconciliation is limited to the first/last anomaly windows and the
largest gap, each capped at 120 calendar days; no paid service is used.

The executed output is
`/workspace/platinum_audits/provenance_20261020_verified_sources`.
Raw source responses and row-level flags stay outside Git. This directory's
summary.json contains aggregate results, URLs and response digests. The report
includes current CME contract fields and targeted reconciliation outcomes.

The original workbook is hashed before/after reading. Model code, features,
experiments and old evidence remain untouched. This command never calls the
training or final-evaluation entry points. It never writes a repaired price or
approval status of true. A successful diagnostic run is not dataset readiness.

The prospective cutoff follows all inspected source timestamps and the end of
source probing, including newly retrieved Yahoo chart metadata. Repeating the
audit creates a new inspection time; it does not create new blind validation.

Verified locally: 28 new audit tests, plus all 41 existing research tests.
Tests include Chicago DST, half-hour anchors, numeric anomaly classification,
original-file protection, vendor reconciliation, and prospective-cutoff safety.
The CI workflow now covers both test directories; remote CI results are separate
from local evidence. Independent review found no important audit blocker and
recommended moving the unseen cutoff after source probing; that recommendation
was implemented and regression-tested. No full Hermes suite or new model run
was performed.

Network draft additions for this follow-up: www.cmegroup.com, finance.yahoo.com,
query1.finance.yahoo.com and the settlement redirect host
cmegroupclientsite.atlassian.net, preserving existing api.github.com and package
presets. The first three became reachable; settlement redirect access was still
denied in the recorded run. Review/save the network settings if that evidence
is needed next; a draft save is not a claim that every runtime destination works.
