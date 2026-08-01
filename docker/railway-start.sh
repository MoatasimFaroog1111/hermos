#!/bin/sh
# Railway composition root for the public Hermes dashboard.
set -eu

export HERMES_DASHBOARD_HOST="${HERMES_DASHBOARD_HOST:-0.0.0.0}"
export HERMES_DASHBOARD_PORT="${PORT:-${HERMES_DASHBOARD_PORT:-9119}}"

# The dashboard is the Railway web service's primary process. Keep the
# supervised dashboard slot disabled so it cannot compete for the same port
# when an operator also supplied HERMES_DASHBOARD=true in service variables.
unset HERMES_DASHBOARD

if [ -z "${HERMES_DASHBOARD_OAUTH_CLIENT_ID:-}" ]; then
    if [ -z "${HERMES_DASHBOARD_BASIC_AUTH_USERNAME:-}" ] || \
       { [ -z "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD:-}" ] && \
         [ -z "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH:-}" ]; }; then
        cat >&2 <<'EOF'
[railway] Hermes dashboard requires authentication on a public bind.
[railway] Configure either:
[railway]   HERMES_DASHBOARD_BASIC_AUTH_USERNAME
[railway]   HERMES_DASHBOARD_BASIC_AUTH_PASSWORD (or _PASSWORD_HASH)
[railway] or HERMES_DASHBOARD_OAUTH_CLIENT_ID.
[railway] The service will remain fail-closed until credentials are configured.
EOF
    fi
fi

echo "[railway] Starting Hermes dashboard on ${HERMES_DASHBOARD_HOST}:${HERMES_DASHBOARD_PORT}" >&2
exec /init /opt/hermes/docker/main-wrapper.sh dashboard \
    --host "$HERMES_DASHBOARD_HOST" \
    --port "$HERMES_DASHBOARD_PORT" \
    --no-open
