# Architecture

System architecture overview for Vittring. Covers the four primary flows
(request, ingest, alert, deploy), the component boundaries that make the code
testable, and a top-level diagram. Detailed per-module rules live in
`CLAUDE.md`.

## Request flow

A user-facing HTTP request traverses these layers:

1. **Browser** issues HTTPS request to `vittring.karimkhalil.se`.
2. **Caddy 2** terminates TLS (Let's Encrypt cert), applies security headers
   (HSTS, CSP, X-Frame-Options, Referrer-Policy), and forwards to
   `localhost:8000`.
3. **uvicorn** runs FastAPI under the `vittring-api` systemd unit, bound only
   to loopback.
4. **FastAPI router** dispatches to the matching endpoint.
5. **CSRF middleware** validates the double-submit token on state-changing
   methods (`POST/PUT/PATCH/DELETE`) for browser clients.
6. **Security-headers middleware** is a defence-in-depth layer that re-applies
   headers Caddy already sets, in case Caddy is bypassed in test or local dev.
7. **Endpoint** runs business logic, requesting an **async SQLAlchemy session**
   from the dependency-injection scope.
8. **Postgres 16** serves the query over a pooled asyncpg connection on
   loopback.

The request returns synchronously — Vittring has no in-request background work
beyond logging and metrics. Everything heavy goes through the scheduler.

## Ingest flow

Each open-data source has its own adapter under `src/vittring/ingest/` that
conforms to the `IngestAdapter` protocol. The runtime shape:

1. **APScheduler** (cron trigger, 06:00 Europe/Stockholm) calls
   `adapter.run_once()` from the `vittring-scheduler` process.
2. The adapter loads the watermark (`ingest_state.last_published_at`) and
   issues paginated `httpx.AsyncClient` requests, wrapped in **tenacity** for
   exponential-backoff retry on 5xx and connection errors.
3. `fetch_since(ts)` is implemented as an **async generator** yielding
   normalised dataclasses (e.g. `JobHit`, `CompanyChange`, `Procurement`).
4. A **batched persist** function consumes the generator in pages of 100,
   building bulk `INSERT ... ON CONFLICT DO NOTHING` statements keyed on
   `(source, external_id)`.
5. After a successful page, the watermark advances. On exception, the
   watermark stays put so the next run replays.
6. **Sentry breadcrumbs** record per-page counts and HTTP status codes for
   post-hoc debugging.

This split keeps the network layer (adapters) decoupled from the database
layer (persist), and lets tests feed canned generators without touching HTTP.

## Alert flow

The daily digest job runs at 06:30 Europe/Stockholm, after all three ingest
adapters have completed.

1. **Cron trigger** (APScheduler) loads every signal row written in the last
   26 hours across `jobs`, `company_changes`, and `procurements`. The
   one-hour overlap absorbs the rare ingest-runs-late case without duplicating
   alerts (idempotency on delivery, see step 7).
2. For each **active, email-verified** user, load their subscriptions.
3. **Group signals by subscription** so each subscription becomes a candidate
   set.
4. Run `match_jobs()`, `match_company_changes()`, and `match_procurements()`
   predicates against the candidate set. The matching engine is **pure**: no
   DB, no IO, deterministic. Inputs are dataclasses, output is a filtered list
   plus a per-match score.
5. Render the email body with **Jinja2** — separate `digest.html` and
   `digest.txt` templates, both Swedish, both rendered in the same
   FastAPI process (no separate worker for templating).
6. **Send via Resend** (`POST /emails`). The Resend webhook posts back
   delivery and bounce events.
7. Record one **`DeliveredAlert`** row per (user, signal_type, signal_id)
   with a unique constraint that doubles as the idempotency key — re-running
   the digest is a no-op.

If a user has zero matches, no email is sent (no "no news today" filler).

## Deploy flow

Tag-driven, see `docs/deployment.md` for the operator perspective. The
machinery:

1. Operator pushes `v0.1.0` (signed tag).
2. **GitHub Actions** workflow `deploy.yml` triggers on `v*.*.*`. It re-runs
   CI for the tag SHA, then SSHes into `vittring@62.238.37.54`.
3. The workflow runs `scripts/deploy.sh <tag>` on the server. The script:
   - `git clone --branch <tag>` into
     `/opt/vittring/releases/<timestamp>-<tag>/`.
   - `uv sync --frozen --no-dev` builds the venv inside that release.
   - `alembic upgrade head` runs against the live DB.
   - `ln -sfn <release-dir> /opt/vittring/current` does the **atomic symlink
     swap**.
   - `systemctl reload vittring-api` (zero-downtime SIGHUP) and
     `systemctl restart vittring-scheduler`.
4. Workflow polls `curl localhost:8000/health` until status is `ok` (or fails
   the run after 60 seconds).

Migrations run before the swap, so the new code never serves traffic against
an unmigrated schema. Migrations must be backward-compatible with the
previous release; the symlink swap is irreversible without a re-deploy.

## Component boundaries

The code is structured so each layer has one responsibility and one
testing strategy:

- **Matching engine** (`src/vittring/matching/`) is **pure**: no DB, no IO, no
  global state. Inputs are dataclasses, outputs are dataclasses. 100% unit
  test coverage is the target — every match predicate has table-driven tests
  with positive and negative examples.
- **Ingest adapters** (`src/vittring/ingest/`) are async generators feeding a
  shared **batched persist**. Adapters are tested with `respx` (mocked
  `httpx`); the persist layer is tested against a real Postgres in a
  pytest fixture.
- **Templates** (`src/vittring/delivery/templates/`) are Jinja2 in the same
  Python process as FastAPI — no separate template service. Tests render
  against fixture data and assert on the resulting HTML/text.
- **Scheduler** (`vittring-scheduler` systemd unit) runs in its own process,
  independent of the API. They share the same code tree and venv but never
  share memory. Restarting one does not affect the other.
- **Auth and CSRF** are middleware in the API process; both have unit tests
  for the token logic and integration tests via `httpx.AsyncClient`.

This split is what keeps the matching engine fast to test and the ingest
adapters easy to mock — every IO boundary is named and small.

## Diagram

```
                                Internet
                                    |
                                    v
                    +---------------------------+
                    |          Caddy 2          |
                    | TLS, HSTS, CSP, headers   |
                    +-------------+-------------+
                                  |
                       loopback   |   :8000
                                  v
              +-------------------+--------------------+
              |                                        |
              v                                        v
   +----------+----------+              +--------------+--------------+
   |    vittring-api     |              |    vittring-scheduler       |
   | (uvicorn + FastAPI) |              | (APScheduler, ingest +      |
   | CSRF, auth, routes  |              |  digest jobs, own process)  |
   +----+--------+-------+              +-----+-----+-----+-----------+
        |        |                            |     |     |
        |        |                            |     |     |
        v        v                            v     v     v
   +----+--+  +--+----+                    +--+--+ +-+--+ ++----+
   | Post- |  |Resend |                    |Job-  |Bolag-| TED  |
   | gres  |  |(email)|                    |Tech  |sverket|     |
   +-------+  +-------+                    +------+------+------+
        |
        v
   (Sentry: errors and breadcrumbs from both processes)
```
