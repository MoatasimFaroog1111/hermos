# Research runbook and production stop

Work from the existing isolated checkout, not a new worktree. No persistent
process is needed. These commands use the separate research environment and
leave root Hermes dependencies/lockfiles unchanged.

```bash
cd /workspace/hermos
export UV_CACHE_DIR=/workspace/.cache/uv
export UV_PYTHON_INSTALL_DIR=/workspace/.local/python
uv venv /workspace/.venvs/platinum --python 3.11
uv pip sync --python /workspace/.venvs/platinum/bin/python --require-hashes platinum_forecasting/requirements.lock
HERMES_PYTHON=/workspace/.venvs/platinum/bin/python bash scripts/run_tests.sh -j 3 tests/platinum_forecasting
/workspace/.venvs/platinum/bin/python -m platinum_forecasting.cli status --output /workspace/platinum_runs/run_20261019
```

Run installation refreshes with `uv pip sync`; do not recreate an existing
venv unnecessarily. The above dependency sync was executed twice, with the
second run confirming all 34 packages. The canonical test runner is mandatory.
Use separate `hermos` and `platinum` venvs; optional research libraries are not
required by core Hermes. No credentials or cloud subscription are needed for
offline research. GitHub read/push uses the existing platform HTTPS Git proxy.
GitHub REST API access returned Forbidden; Git access does not imply API access.

## Reproduction

The workbook remains at
`/workspace/attachments/16350ac2-8c9b-4daf-8d3a-bca83ed0597f/platinum_yahoo_full.xlsx`.
Its digest appears in DATA_AUDIT_REPORT.md. Raw workbook and cleaned data are
not tracked or pushed. Actual run output is `/workspace/platinum_runs/run_20261019`.
This local attachment path is not guaranteed to restore in a fresh environment;
retain the source workbook securely with the owner, do not put it in Git.

CLI commands `audit`, `select`, `evaluate` accept `--workbook` and `--output`;
selection/evaluation also take `--frequency daily|hourly --horizon N`.
Use an empty output directory for a reproduction; preserve prior ledgers.
Select all declared horizons before evaluating: daily 1/5; hourly 1/4/24.
`evaluate` refuses a consumed holdout. A crash after consumption requires
investigation, not deleting the marker and retrying silently. Reproduction
of this same test period is an engineering check, never fresh validation.
Freeze source/dependencies and compare selection hashes; runtime durations
and creation timestamps are nondeterministic, prediction algorithms are seeded.

## Deployment and rollback

Do not activate any real model from this experiment. The local Python forecast
contract is tested using synthetic fixtures; no online provider, approved real
artifact, active skill or Telegram forecast is deployed. The serving path is
read-only, has no HTTP auth boundary, and trusts filesystem permissions on
operator-owned registry/provider objects. Do not expose them as arbitrary chat
inputs or an unauthenticated service.

For a future approved model, back up the active manifest and its exact artifact
checksum, verify the new version in staging with current data, then atomically
replace the active manifest only after human approval. On failure, restore the
prior reviewed manifest/artifact and rerun readiness/smoke checks. A synthetic
rollback test verifies rejection and restoration; actual production rollback
was not executed. Never roll back to a previously rejected model.

## Review workflow

Branch: `feat/platinum-forecasting-research`. Review source, tests, evidence and
reports before merging. No main-branch change or production deployment is
authorized by the research. The provided new CI workflow is not a claim that
GitHub Actions passed. Full Hermes suites, live model/provider calls, remote
Telegram behavior and fresh-environment restoration were not validated.
