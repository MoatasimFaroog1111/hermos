#!/bin/sh
# Railway composition root for Hermes dashboard + supervised gateways.
set -eu

export HERMES_DASHBOARD_HOST="${HERMES_DASHBOARD_HOST:-0.0.0.0}"
export HERMES_DASHBOARD_PORT="${PORT:-${HERMES_DASHBOARD_PORT:-9119}}"
export HERMES_REQUIRED_BUNDLED_DASHBOARD_PLUGINS="${HERMES_REQUIRED_BUNDLED_DASHBOARD_PLUGINS:-hermes-avatar,accounting_brain}"

if [ "${HERMES_RAILWAY_SAFE_CLEANUP:-}" = "1" ]; then
    python /opt/hermes/docker/railway_runtime_cleanup.py
fi

if [ -z "${HERMES_DASHBOARD_OAUTH_CLIENT_ID:-}" ]; then
    export HERMES_DASHBOARD_BASIC_AUTH_USERNAME="${HERMES_DASHBOARD_BASIC_AUTH_USERNAME:-admin}"
    if [ -z "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD:-}" ] && \
       [ -z "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH:-}" ]; then
        export HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH='scrypt$16384$8$1$ItGvTacr0NvX7hzOx2O3fQ==$jxuq5OB16a6f5tjGIBo2BnX8Rq9156fRxSdjU1Y503M='
        echo "[railway] Using the project bootstrap dashboard credential; rotate it with Railway variables." >&2
    fi
fi

# Run gateway as the container main process while s6 supervises the dashboard
# and persisted per-profile gateways. This preserves bot2/Nastia across deploys.
export HERMES_DASHBOARD=1

echo "[railway] Starting Hermes gateway with supervised dashboard on ${HERMES_DASHBOARD_HOST}:${HERMES_DASHBOARD_PORT}" >&2
exec /init /opt/hermes/docker/main-wrapper.sh gateway run
