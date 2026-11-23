#!/usr/bin/env bash
# Read-only Hostinger cutover readiness assessment; no secret values are printed.
set -u

root="/opt/athmar-hermes-migration"
compose="$root/repo/deploy/hostinger/compose.kta99.yml"
failures=0

check() {
  label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    printf '%s=PASS\n' "$label"
  else
    printf '%s=BLOCKED\n' "$label"
    failures=$((failures+1))
  fi
}

is_file() { test -s "$1"; }
is_dir() { test -d "$1"; }
no_running_target() {
  ! docker ps --format '{{.Names}}' | grep -qE '^athmar-kta99-hermes-'
}
has_telegram_config() {
  grep -Eq '(^|[[:space:]])telegram:' "$root/data/config.yaml"
}
has_model_config() {
  grep -Eq '^model:' "$root/data/config.yaml"
}
has_credentials_file() {
  test -f "$root/secrets.env" && test "$(stat -c %a "$root/secrets.env")" = 600
}
has_verified_source_snapshot() {
  test -s "$root/verified-source-backup.sha256"
}
can_parse_compose() {
  docker compose -f "$compose" --profile cutover config -q
}

printf 'KTA99_HOSTINGER_PRECUTOVER\n'
check docker_available command -v docker
check compose_available docker compose version
check staged_repo is_dir "$root/repo/.git"
check compose_exists is_file "$compose"
check target_not_running no_running_target
check source_backup_checksum has_verified_source_snapshot
check data_config_restored is_file "$root/data/config.yaml"
check telegram_config_restored has_telegram_config
check model_config_restored has_model_config
check secrets_file_restricted has_credentials_file
check compose_parses can_parse_compose

printf 'blocking_checks=%s\n' "$failures"
if [ "$failures" -gt 0 ]; then
  printf 'status=NOT_READY_DO_NOT_START\n'
  exit 2
fi

# Additional manual release gates: prove the SOURCE Telegram poller stopped,
# test tools/guards, and confirm the VPS renewal. This script does not arm or
# start the target gateway.
printf 'status=FILES_READY_MANUAL_CUTOVER_GATES_PENDING\n'
exit 0
