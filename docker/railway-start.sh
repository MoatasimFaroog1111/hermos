#!/bin/sh
# Railway composition root for the public Hermes dashboard.
set -eu

export HERMES_DASHBOARD_HOST="${HERMES_DASHBOARD_HOST:-0.0.0.0}"
export HERMES_DASHBOARD_PORT="${PORT:-${HERMES_DASHBOARD_PORT:-9119}}"

# Application-owned bundled dashboard extensions in this deployment. Declare
# them required so the post-s6 preflight validates runtime assets and clears
# stale persisted hide/disable state from /opt/data. Accounting Brain remains
# read-only against Odoo; requiring its dashboard presence does not grant any
# additional Odoo permissions.
export HERMES_REQUIRED_BUNDLED_DASHBOARD_PLUGINS="${HERMES_REQUIRED_BUNDLED_DASHBOARD_PLUGINS:-hermes-avatar,accounting_brain}"

# The dashboard is the Railway web service's primary process. Keep the
# supervised dashboard slot disabled so it cannot compete for the same port
# when an operator also supplied HERMES_DASHBOARD=true in service variables.
unset HERMES_DASHBOARD

# A public bind must remain authenticated. Railway cannot populate secret
# variables from config-as-code, so provide a project-specific bootstrap hash
# only when no OAuth/basic-auth configuration exists. Operators can override
# both values with Railway variables without changing the image.
if [ -z "${HERMES_DASHBOARD_OAUTH_CLIENT_ID:-}" ]; then
    export HERMES_DASHBOARD_BASIC_AUTH_USERNAME="${HERMES_DASHBOARD_BASIC_AUTH_USERNAME:-admin}"
    if [ -z "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD:-}" ] && \
       [ -z "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH:-}" ]; then
        export HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH='scrypt$16384$8$1$ItGvTacr0NvX7hzOx2O3fQ==$jxuq5OB16a6f5tjGIBo2BnX8Rq9156fRxSdjU1Y503M='
        echo "[railway] Using the project bootstrap dashboard credential; rotate it with Railway variables." >&2
    fi
fi

echo "[railway] Starting Hermes dashboard on ${HERMES_DASHBOARD_HOST}:${HERMES_DASHBOARD_PORT}" >&2
exec /init /opt/hermes/docker/main-wrapper.sh dashboard \
    --host "$HERMES_DASHBOARD_HOST" \
    --port "$HERMES_DASHBOARD_PORT" \
    --no-open
