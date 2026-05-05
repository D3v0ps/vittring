# Deployment

How to deploy, roll back, and debug Vittring deploys. Reference doc; assumes the
operator already understands the stack described in `CLAUDE.md`.

## Prerequisites

- SSH access to `vittring@62.238.37.54` with a key registered in `~vittring/.ssh/authorized_keys`.
- A working clone of `D3v0ps/vittring` with permission to push tags.
- `uv` available locally (matching the version pinned in `pyproject.toml`).
- Caddy, PostgreSQL 16, and the two systemd units (`vittring-api`, `vittring-scheduler`)
  already provisioned via `scripts/server_bootstrap.sh`.

## First-time bootstrap

Run on a fresh Hetzner CX23 once. Idempotent but slow.

```bash
ssh root@62.238.37.54
git clone https://github.com/D3v0ps/vittring.git /tmp/vittring
bash /tmp/vittring/scripts/server_bootstrap.sh
```

The bootstrap script:

1. Creates the `vittring` system user with `/opt/vittring` as home.
2. Installs Python 3.12, `uv`, PostgreSQL 16, Caddy, and unattended-upgrades.
3. Lays down systemd units from `deploy/systemd/` and the Caddyfile from `deploy/Caddyfile`.
4. Initialises the Postgres role, database, and `/etc/vittring/.env` (mode 0640, owner `vittring:vittring`).
5. Installs the nightly cron in `/etc/cron.d/vittring-backup`.

After bootstrap, log in as `vittring` and run a first deploy against `main` to populate
`/opt/vittring/current` and run migrations.

## Ongoing deploys

Cut a tag locally and push:

```bash
git tag -s v0.1.0 -m "v0.1.0"
git push origin v0.1.0
```

GitHub Actions takes over from there. Manual SSH deploys should not be necessary
in normal operation.

## How the deploy workflow works

`.github/workflows/deploy.yml` triggers on tags matching `v*.*.*`. It:

1. Checks out the tag and verifies CI passed on the same SHA.
2. Loads `DEPLOY_SSH_KEY` from repo secrets and adds `62.238.37.54` to known hosts.
3. SSHes as `vittring@62.238.37.54` and runs `/opt/vittring/current/scripts/deploy.sh <tag>`.
4. Streams `journalctl -u vittring-api` for two minutes after deploy and fails the run
   on any `ERROR` log line.

The workflow has `concurrency: deploy` so two tags pushed close together queue
rather than collide.

## Release-symlink-swap strategy

`scripts/deploy.sh` (run as `vittring`) implements the swap:

1. `git clone --branch <tag>` into `/opt/vittring/releases/<timestamp>-<tag>/`.
2. `uv sync --frozen --no-dev` builds the venv inside that release directory.
3. `alembic upgrade head` runs against the live database, sourcing `/etc/vittring/.env`.
4. `ln -sfn <release-dir> /opt/vittring/current` atomically repoints the symlink.
5. `systemctl reload-or-restart vittring-api` (zero-downtime) and
   `systemctl restart vittring-scheduler` (cold restart is fine; no in-flight requests).
6. `curl localhost:8000/health` is polled until it returns `"status":"ok"`.
7. The five most recent releases are kept; older ones are pruned.

Migrations run before the symlink swap, so the new code never serves traffic against
an unmigrated schema. Migrations must be backward-compatible with the previous
release; see `CLAUDE.md` migrations section.

## Rolling back

Roll back by pointing `current` at any prior release directory and bouncing the
units:

```bash
ssh vittring@62.238.37.54
ls -1dt /opt/vittring/releases/*/ | head -5    # find the previous release
ln -sfn /opt/vittring/releases/<previous>/ /opt/vittring/current
systemctl restart vittring-api vittring-scheduler
curl -fsS localhost:8000/health
```

Rollback does not undo migrations. If the failed deploy ran a destructive
migration, restore from the most recent `pg_dump` in the Hetzner Storage Box
(see `scripts/restore.sh`).

## Debugging a failed deploy

Run these in order until you find the failure:

```bash
# Service status and recent logs
systemctl status vittring-api
journalctl -u vittring-api -f
journalctl -u vittring-scheduler -n 200

# HTTP path through Caddy
tail -f /var/log/caddy/vittring.log
curl -v localhost:8000/health             # bypasses Caddy, hits uvicorn directly

# Database reachability
sudo -u postgres psql -c '\l' | grep vittring

# Disk and memory
df -h /opt /var
free -m
```

Common failure modes:

- `alembic upgrade head` errors: schema drift or a new migration depending on
  data not in production. Roll back the symlink, fix the migration, re-tag.
- `uv sync --frozen` errors: `uv.lock` out of sync with `pyproject.toml`. Re-run
  `uv lock` locally and re-tag.
- `/health` returns 500: usually a missing env var. Diff `/etc/vittring/.env`
  against `.env.example` from the new release.

## Branch protection

`main` is protected. The following rules are enforced and should not be relaxed:

- Required status checks: `ci / lint`, `ci / test`, `ci / typecheck` must be green.
- Require linear history (no merge commits).
- Require signed commits (`git commit -S`).
- Require pull request reviews; admins are not exempt.
- Force pushes are blocked.

Tags pushed directly to `main` history are allowed and trigger deploys.

## Manually triggering the nightly backup

The nightly cron lives in `/etc/cron.d/vittring-backup` and runs `scripts/backup.sh`
at 03:30 Europe/Stockholm. To run it on demand:

```bash
ssh vittring@62.238.37.54
sudo run-parts --test /etc/cron.daily        # confirm cron file is valid
sudo /opt/vittring/current/scripts/backup.sh # run as root via sudo
```

The script `pg_dump`s the database, encrypts it with the passphrase from
`/etc/vittring/.env` (`BACKUP_PASSPHRASE`), and rsyncs to the Hetzner Storage Box.
Verify the upload by listing the remote directory; see the runbook for restore steps.
