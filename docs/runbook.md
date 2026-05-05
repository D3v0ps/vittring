# Runbook

Incident response for Vittring. Each section is a scenario with the symptoms,
the commands to run, and a decision path. Escalation contact is Karim (owner) —
reach him via SMS or `info@karimkhalil.se` for any P1 (customer-visible
outage, data loss, security event).

All commands assume `ssh vittring@62.238.37.54` unless noted. Sudo where
required; the `vittring` user has passwordless sudo for `systemctl`,
`journalctl`, and the backup scripts.

---

## Site is down

Symptom: UptimeRobot alert, `/health` non-200, customer report.

```bash
# 1. API process state
systemctl status vittring-api
journalctl -u vittring-api -n 200 --no-pager

# 2. Caddy reverse proxy
systemctl status caddy
tail -n 100 /var/log/caddy/vittring.log

# 3. Postgres
sudo -u postgres pg_isready
journalctl -u postgresql -n 100 --no-pager

# 4. Disk
df -h /opt /var

# 5. Bypass Caddy and hit uvicorn directly
curl -fsS localhost:8000/health
```

Decision path:

- `vittring-api` is `failed` or `inactive`: `systemctl restart vittring-api`,
  then watch the journal. If it crashes again on start, it's almost always a
  config or migration issue — see deployment.md "debugging a failed deploy".
- API is up but Caddy is failing: check the Caddyfile syntax with
  `caddy validate --config /etc/caddy/Caddyfile`, then `systemctl reload caddy`.
- Postgres is down: `systemctl restart postgresql`. If it won't come back, check
  disk (next section) and `journalctl -u postgresql`.
- All processes look fine but `/health` fails: check `/etc/vittring/.env` for
  truncation or permission changes (`stat /etc/vittring/.env` should be
  `0640 vittring:vittring`).

Escalate to Karim if downtime exceeds 15 minutes or data loss is suspected.

---

## Site is slow

Symptom: p95 latency spike in Sentry, customer reports of slow pages.

```bash
# Long-running queries
sudo -u postgres psql vittring -c "
  SELECT pid, now() - query_start AS runtime, state, query
  FROM pg_stat_activity
  WHERE state != 'idle' AND now() - query_start > interval '5 seconds'
  ORDER BY runtime DESC;"

# Connection pool saturation
sudo -u postgres psql vittring -c "
  SELECT state, count(*) FROM pg_stat_activity
  WHERE datname = 'vittring' GROUP BY state;"

# uvicorn worker load
ps -eo pid,pcpu,pmem,cmd --sort=-pcpu | grep uvicorn | head
```

Cross-reference with Sentry traces (`Performance` tab) for the slow endpoint.
Common causes:

- A specific endpoint is missing an index — capture `EXPLAIN ANALYZE` and add
  the index in a migration.
- The connection pool is saturated (count near `pool_size + max_overflow`):
  bounce the API, then investigate which endpoint is leaking sessions.
- Scheduler is running a heavy ingest at the same time: confirm with
  `journalctl -u vittring-scheduler -f` and reschedule if needed.

---

## DB disk full

Symptom: `disk full` errors in Postgres journal, writes failing, possible
read-only fallback.

```bash
# Confirm disk
df -h /var/lib/postgresql

# Largest relations
sudo -u postgres psql vittring -c "
  SELECT relname,
         pg_size_pretty(pg_total_relation_size(c.oid)) AS total
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public'
  ORDER BY pg_total_relation_size(c.oid) DESC
  LIMIT 20;"

# WAL and log dirs
du -sh /var/lib/postgresql/16/main/pg_wal
du -sh /var/log/postgresql
```

Steps:

1. Free up logs: rotate `/var/log/postgresql/*` (logrotate normally handles
   this; if not, gzip or delete the oldest manually).
2. `VACUUM FULL` the largest tables that have high dead-tuple ratios. Check
   `pg_stat_user_tables.n_dead_tup` first. Note: `VACUUM FULL` takes an
   `ACCESS EXCLUSIVE` lock — schedule a maintenance window if user-facing.
3. If WAL is the bloat source, ensure `wal_keep_size` and replication slots are
   sane; drop unused slots with `pg_drop_replication_slot()`.
4. Last resort: scale storage at Hetzner. CX23 -> CX33 has 80 GB; resize via
   the Cloud Console, then `resize2fs` after reboot.

Escalate to Karim before running `VACUUM FULL` on `signals` or `company_changes`
(the two largest tables).

---

## Email failing

Symptom: digest deliveries dropping, bounce rate spike, complaint webhook noise.

```bash
# Resend webhook reachability
curl -fsS https://vittring.karimkhalil.se/api/webhooks/resend -X POST \
     -H 'Content-Type: application/json' -d '{"type":"ping"}'

# Scheduler digest run
journalctl -u vittring-scheduler --since "06:00" --until "07:00" --no-pager

# Recent delivery rows
sudo -u postgres psql vittring -c "
  SELECT delivered_at, signal_type, provider_status
  FROM delivered_alerts
  ORDER BY delivered_at DESC
  LIMIT 20;"
```

Then in the Resend dashboard:

- Check the API key isn't disabled.
- Inspect bounces and complaints — high counts usually mean SPF/DKIM/DMARC
  drift; verify with `dig TXT karimkhalil.se` and `dig TXT resend._domainkey.karimkhalil.se`.
- If a single recipient is bouncing, suppress them (`users.email_blocked = true`)
  and notify the customer.

If the scheduler digest job failed: re-run by SSHing and triggering the digest
manually (`python -m vittring.delivery.digest --run-now`). Idempotency on
`delivered_alerts (user_id, signal_type, signal_id)` prevents duplicates.

---

## Ingest stale (no new rows)

Symptom: a daily report shows zero new jobs/changes/procurements, or the
"latest signal" timestamp on the admin page is older than 36 hours.

```bash
# Scheduler health
systemctl status vittring-scheduler
journalctl -u vittring-scheduler -f

# Watermark for each adapter
sudo -u postgres psql vittring -c "
  SELECT source, last_published_at, last_run_at, last_status
  FROM ingest_state ORDER BY source;"
```

If a single source is stale, run it manually to capture the failure:

```bash
sudo -u vittring bash -c "
  cd /opt/vittring/current && \
  source .venv/bin/activate && \
  python -c 'import asyncio; from vittring.ingest.jobtech import JobTechAdapter; \
asyncio.run(JobTechAdapter().run_once())'"
```

Repeat with `BolagsverketAdapter` or `TEDAdapter` as needed. If the upstream
returns 5xx persistently, just wait — the next scheduled run will retry.
Open a Sentry issue if it's been failing for more than 24 hours.

---

## Lost backup encryption passphrase

Symptom: trying to restore a `pg_dump.gpg` and `gpg` returns "decryption
failed: bad passphrase".

There is no recovery path. The passphrase is stored only in
`/etc/vittring/.env` on the production server (`BACKUP_PASSPHRASE`), and a
sealed copy in Karim's password manager. If both are gone:

1. Alert Karim immediately — this is a P1.
2. Try the most recent unencrypted Hetzner snapshot via the Hetzner Cloud
   Console (snapshots are full-disk, restored as a new server).
3. Going forward, rotate the passphrase and ensure the password-manager copy
   is restored from a recent export.

Do not attempt brute-force decryption; the passphrase is high-entropy.

---

## Sentry alert spam

Symptom: same error class firing dozens of times per hour, drowning useful
signal.

```bash
# Find the noisy issue in Sentry, copy the fingerprint, then locally:
git log --since "1 week" --oneline -- src/vittring
```

Steps:

1. Identify the unhandled exception class in Sentry. If it's user input, it
   should be caught and turned into a 4xx — fix in the endpoint, deploy.
2. If the issue is genuinely transient (e.g. upstream 503), wrap the call in
   tenacity with sane backoff and don't capture intermediate retries to Sentry.
3. While the fix is pending, mute the issue in Sentry (not the project) so
   real new errors still page.
4. Cut a patch tag (e.g. `v0.1.1`) and deploy. Confirm the issue resolves in
   Sentry's "resolved" state.

Escalate to Karim if the error implies data corruption (e.g. integrity errors,
unique-constraint violations on writes that should never collide).
