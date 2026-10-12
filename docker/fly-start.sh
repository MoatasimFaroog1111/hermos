#!/bin/sh
# Fly.io composition root for the Hermes dashboard + gateway.
#
# Fly Machines run their own init as PID 1 and exec the image entrypoint as
# a child process, so s6-overlay's /init aborts with
# "s6-overlay-suexec: fatal: can only run as pid 1" and the machine
# crash-loops.  This script replaces the s6 supervision tree on Fly:
#
#   1. run the same stage2 bootstrap the s6 image uses (UID remap, data
#      volume chown, config seeding, skills sync) as root;
#   2. start the dashboard and the gateway side by side as the hermes user;
#   3. restart whichever of the two exits, and forward SIGTERM on shutdown.
#
# Wired in via `[experimental] entrypoint` in fly.toml.  When the script
# does own PID 1 (plain `docker run`), it defers to /init so Docker keeps
# the full s6 behaviour.  Mirrors docker/railway-start.sh for the env setup.
set -u

export HERMES_DASHBOARD=1
export HERMES_DASHBOARD_HOST="${HERMES_DASHBOARD_HOST:-0.0.0.0}"
export HERMES_DASHBOARD_PORT="${PORT:-${HERMES_DASHBOARD_PORT:-9119}}"
export HERMES_REQUIRED_BUNDLED_DASHBOARD_PLUGINS="${HERMES_REQUIRED_BUNDLED_DASHBOARD_PLUGINS:-hermes-avatar,accounting_brain}"
# No s6 here: make `hermes gateway run` stay in the foreground instead of
# trying to dispatch to a supervised slot.
export HERMES_GATEWAY_NO_SUPERVISE=1
export HOME=/opt/data

if [ "$$" -eq 1 ]; then
    # We own PID 1 (plain Docker / Podman): keep the full s6 tree.
    exec /init /opt/hermes/docker/main-wrapper.sh gateway run
fi

echo "[fly] entrypoint is not PID 1; running without s6-overlay supervision" >&2

# /init normally seeds PATH with the s6 helpers (s6-setuidgid, ...).
export PATH="/command:/package/admin/s6/command:${PATH}"

if [ "$(id -u)" = 0 ]; then
    if ! /opt/hermes/docker/stage2-hook.sh; then
        echo "[fly] stage2 bootstrap failed" >&2
        exit 1
    fi
fi

# stage2-hook publishes the Chromium path for s6's with-contenv; pick it up
# manually since nothing here goes through with-contenv.
if [ -z "${AGENT_BROWSER_EXECUTABLE_PATH:-}" ] && \
        [ -f /run/s6/container_environment/AGENT_BROWSER_EXECUTABLE_PATH ]; then
    AGENT_BROWSER_EXECUTABLE_PATH="$(cat /run/s6/container_environment/AGENT_BROWSER_EXECUTABLE_PATH)"
    export AGENT_BROWSER_EXECUTABLE_PATH
fi

# shellcheck disable=SC1091
. /opt/hermes/.venv/bin/activate
cd /opt/data

# Run a command as the hermes user (no-op drop when already non-root).
as_hermes() { [ "$(id -u)" = 0 ] || { "$@"; return; }; s6-setuidgid hermes "$@"; }
exec_as_hermes() { [ "$(id -u)" = 0 ] || exec "$@"; exec s6-setuidgid hermes "$@"; }

if [ -n "${HERMES_REQUIRED_BUNDLED_DASHBOARD_PLUGINS:-}" ]; then
    if ! as_hermes python -m hermes_cli.required_dashboard_plugins; then
        echo "[fly] required dashboard plugins check failed" >&2
        exit 1
    fi
fi

if [ -z "${HERMES_DASHBOARD_OAUTH_CLIENT_ID:-}" ] && \
   [ -z "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD:-}" ] && \
   [ -z "${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH:-}" ]; then
    echo "[fly] WARNING: no dashboard auth configured; set HERMES_DASHBOARD_BASIC_AUTH_USERNAME/_PASSWORD with 'fly secrets set'" >&2
fi

DASH_PID=""
GW_PID=""

start_dashboard() {
    (
        exec_as_hermes hermes dashboard \
            --host "$HERMES_DASHBOARD_HOST" --port "$HERMES_DASHBOARD_PORT" --no-open
    ) &
    DASH_PID=$!
    echo "[fly] dashboard started (pid $DASH_PID) on ${HERMES_DASHBOARD_HOST}:${HERMES_DASHBOARD_PORT}" >&2
}

start_gateway() {
    (
        exec_as_hermes hermes gateway run
    ) &
    GW_PID=$!
    echo "[fly] gateway started (pid $GW_PID)" >&2
}

shutdown() {
    echo "[fly] shutdown requested; stopping gateway and dashboard" >&2
    [ -n "$GW_PID" ] && kill -TERM "$GW_PID" 2>/dev/null
    [ -n "$DASH_PID" ] && kill -TERM "$DASH_PID" 2>/dev/null
    wait
    exit 0
}
trap shutdown TERM INT

start_dashboard
start_gateway

# Poll-based supervisor (POSIX sh has no `wait -n`).  Sleeping in the
# background and waiting on it keeps the TERM trap responsive.
while :; do
    sleep 5 &
    wait $! 2>/dev/null
    if [ -n "$DASH_PID" ] && ! kill -0 "$DASH_PID" 2>/dev/null; then
        wait "$DASH_PID" 2>/dev/null
        echo "[fly] dashboard exited (rc=$?); restarting in 5s" >&2
        sleep 5
        start_dashboard
    fi
    if [ -n "$GW_PID" ] && ! kill -0 "$GW_PID" 2>/dev/null; then
        wait "$GW_PID" 2>/dev/null
        echo "[fly] gateway exited (rc=$?); restarting in 5s" >&2
        sleep 5
        start_gateway
    fi
done
