# KTA99bot: Hetzner → Hostinger migration (staging, not cut over)

## Verified inventory — 2026-11-23

**Destination:** Hostinger KVM 2 VPS `srv2066418.hstgr.cloud`,
`187.126.2.46`, Ubuntu 24.04. SSH login as root works with the
user's **existing local** `athmar_hostinger` key (never copy the private
key into the repository). About 90 GiB free disk and 5.8 GiB available RAM
were observed; Docker 29.9.1 and Compose v5.6.0 installed.

**Existing destination services (do not stop/recreate):** `athmar-ceo`,
`deploy-worker-1`, FDE production and staging API/DB/Keycloak/worker,
and `fde-vps-proxy-1` (Traefik on public ports 80/443).
Hermes was not running on the destination at inventory time.

**Old suspected source:** Hetzner `hermos-01` (37.27.152.4),
`hermes-app-1` historically hosted @KTA99bot. Hetzner Cloud reports the
server running. SSH with the available local key was denied. We cannot
claim the source Telegram gateway is healthy, nor copy its state, without
authenticated access. A Fly.io `hermos-moatasim` app also exists, but
its live status reported zero configured messaging platforms. **Do not
assume Fly.io is the source of Telegram.**

**Billing:** Hostinger hPanel showed a renewal/payment warning for this
VPS, with expiration date 2026-12-15. Resolve before relying on it.

## Safe target layout

The staging checkout lives in
`/opt/athmar-hermes-migration/repo`; data will be restored into
`/opt/athmar-hermes-migration/data`. Secrets must live in an
operator-controlled file `/opt/athmar-hermes-migration/secrets.env`
(mode 0600), or under the restored secure Hermes `.env`. Do not
create a new Telegram bot or change BotFather token.

`deploy/hostinger/compose.kta99.yml` is intentionally gated:

- Opt-in Docker Compose profile `cutover` (default `up` does not start it).
- Process requires `KTA99_MIGRATION_ARMED=yes` at runtime; otherwise exits.
- Dashboard binds **host localhost only** (`127.0.0.1:9119`), not
  Traefik or public ports; keep dashboard auth configured.
- Limits the container to 3 GB RAM and 1.5 CPUs and never touches
  the running FDE/CEO containers.

**Do not run `docker compose --profile cutover up -d` during staging.**
Do not use `docker compose down --volumes` or wipe the data directory.

## Steps before cutover

1. Confirm which source instance currently polls @KTA99bot. Check current
   Telegram connection, Hermes image/commit, GitHub MCP write guard, toolsets,
   job schedules and authorized users. Record results **without printing
   credentials**.
2. Backup the source **while it remains intact**: Docker Compose manifest,
   runtime environment names, `/opt/data` (or its actual volume/bind mount),
   `config.yaml`, `.env`, sessions, skills, attachments and persistent
   database files. Avoid copying database files from an inconsistent
   live snapshot; use SQLite backup or a short controlled quiesce.
3. Encrypt the backup for transit/storage and verify its SHA-256 digest;
   maintain a separate securely stored copy. Transfer with SSH/SCP/rsync,
   restricting access to the new root-owned target directory. Do **not**
   commit the backup, secrets or database to GitHub.
4. Restore the state to the staging `data` directory. Set required
   credentials via restricted runtime secret management. Set gateway
   dashboard authorization and keep the original Telegram token unchanged.
5. Record the verified source-backup digest in
   `/opt/athmar-hermes-migration/verified-source-backup.sha256` *only
   after* verifying the restored data matches the original archive.
6. Execute the **read-only** readiness check:
   ```sh
   bash /opt/athmar-hermes-migration/repo/deploy/hostinger/preflight-kta99.sh
   ```
   `NOT_READY_DO_NOT_START` is an expected result before data transfer.
7. Build the pinned image on a maintenance-friendly window without
   disrupting other users, then test Hermes locally **without Telegram
   polling**. Confirm OpenAI API access, DeepSeek fallback, existing tools,
   GitHub MCP guard, authorized user allowlist, and cron state.
8. During an explicitly planned cutover, stop the **old** Telegram poller,
   perform a final data sync, confirm there is one poller, set the
   `KTA99_MIGRATION_ARMED` flag via the protected runtime environment, and
   start the opt-in Compose profile. Check Telegram answer delivery.
9. After successful delivery, verify memory, tools, schedules, and guard
   rules. Only then persist OpenAI as default using a supported direct
   provider with the exact model available to the deployed Hermes version.
   Leave DeepSeek usable by `/model` and retain backup config.
10. Rollback: stop **only** the new target gateway, verify it no longer
    polls Telegram, and restart the original poller with its untouched data.
    Never run both pollers against the same token simultaneously.

## Status / hard blockers

- [x] Destination VPS identified, reachable through authenticated SSH.
- [x] Host resources, Docker and other service workloads inventoried.
- [x] Repository source cloned into isolated staging directory.
- [ ] Source Hermes runtime and active Telegram poller positively identified.
- [ ] Source backup securely exported and verified.
- [ ] Data and credentials restored to Hostinger.
- [ ] Staging preflight fully passes.
- [ ] OpenAI and Telegram integration tests pass on restored state.
- [ ] Cutover authorized, performed, and verified.
- [ ] Hostinger VPS renewal/payment warning resolved.
