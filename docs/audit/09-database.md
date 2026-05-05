# Database audit — `09-database.md`

Read-only review of SQLAlchemy queries, indexes, sessions, and performance
characteristics across `src/vittring/`. Targets the production stack
described in `CLAUDE.md`: Postgres 16 on a CX23 (2 vCPU, 4 GB RAM) with
two uvicorn workers and a separate scheduler process.

Findings are graded P0 (correctness/safety), P1 (clear performance hit at
modest scale), P2 (cleanup / future-proofing).

---

## 1. Indexes — table-by-table cross-check

Indexes are defined both in `src/vittring/models/*` and the Alembic
baseline `alembic/versions/20260505_0900_0001_initial_schema.py`. The model
declarations and the migration agree (good — one source of truth at deploy
time).

### `companies` (`models/company.py`)
| Index | Used by |
|---|---|
| PK `id` | implicit |
| UQ `orgnr` | `upsert_companies` ON CONFLICT, `upsert_companies` SELECT-by-IN, `digest._load_user_signals` joins (via `company_id` FK on the other side) |
| `idx_companies_municipality` | matching engine geo filter (in-memory only — DB never filters here) |
| `idx_companies_sni` | matching engine geo filter (likewise in-memory) |

Observation: `idx_companies_municipality` and `idx_companies_sni` are
**unused at the DB level today**. The matching engine receives company
fields via a Python join in `digest._load_user_signals` and applies all
filters in memory. They are still cheap insurance for ad-hoc admin
queries. P2.

### `job_postings`
| Index | Used by |
|---|---|
| UQ `external_id` | `insert_ignore` ON CONFLICT (jobtech persist) |
| `idx_jobs_published` | `digest._load_user_signals: where published_at >= since`, `admin.signals_explorer` order-by |
| `idx_jobs_company` | FK joins (none active in code today) |
| `idx_jobs_municipality` | nothing in code reads on this column at the DB level |

`/admin/signals?tab=jobs&q=…` filters with `func.lower(headline).like('%q%')`
— this is **always a sequential scan** because (a) the index is on raw
`workplace_municipality`, not `lower(headline)`, and (b) the leading `%`
disables a btree prefix index even if one existed. P1 if admin search is
used on a populated table; P2 otherwise (admin only, low traffic).

The `/ready` endpoint runs `select(func.max(JobPosting.ingested_at))`
on every probe (every 5 minutes from UptimeRobot + Caddy). Postgres can
satisfy `MAX(ingested_at)` from `idx_jobs_published`-style index only if
the column is indexed; **`ingested_at` is not indexed**, so this is a
sequential scan over the whole table. At 5k-50k rows the cost is small
but it grows linearly. P1 — add `idx_jobs_ingested` (btree on
`ingested_at DESC`) or change `/ready` to read `published_at` (already
indexed) plus a small offset.

### `company_changes`
| Index | Used by |
|---|---|
| `idx_changes_company_changed` (company_id, changed_at) | digest join filter |
| `idx_changes_purge_candidate` (ingested_at) WHERE personal_data_purged_at IS NULL | GDPR scrub |

Digest filter is `where changed_at >= since`. The composite
`(company_id, changed_at)` is **not** usable as a covering index for that
filter (changed_at is the second column, no leading equality on
company_id). The query falls back to a sequential scan. P1 — add
`idx_changes_changed_at` for the digest path, or drop the digest filter
and load via the composite index by company.

### `procurements`
| Index | Used by |
|---|---|
| UQ `external_id` | persist ON CONFLICT |
| `idx_proc_deadline` | not read in code today |
| `idx_proc_cpv` GIN | matching engine in-memory only |

Digest filters with `where ingested_at >= since`; `ingested_at` has
no index → sequential scan. P1 — add `idx_proc_ingested`.

### `subscriptions`
| Index | Used by |
|---|---|
| `idx_subs_user_active` (user_id) WHERE active | dashboard, digest per-user load, list page |

Indexes match the access pattern. P0 covered.

### `delivered_alerts`
| Index | Used by |
|---|---|
| UQ `(user_id, signal_type, signal_id)` | `_already_delivered` lookup, `_record_deliveries` ON CONFLICT |
| **(no index on `resend_message_id`)** | webhook UPDATE WHERE resend_message_id = ? |

**P0 — missing index on `resend_message_id`.** `api/webhooks.py:53-63`
runs `UPDATE delivered_alerts SET opened_at|clicked_at … WHERE
resend_message_id = ?` for every Resend open/click event. With even a
modest digest volume (say 1k emails/day × multiple opens), this becomes a
sequential scan per webhook, holding a row-level lock across the scan.
Add `Index("idx_alerts_resend_msg", "resend_message_id")`.

Also missing: an index on `delivered_at` for the many `WHERE
delivered_at >= since` admin/email queries (overview, /admin/email,
/admin/users/{id} delivered list). With a `LIMIT 25` order-by-delivered_at
it forces a full sort on a sequential scan today. P1.

### `audit_log`
| Index | Used by |
|---|---|
| `idx_audit_user_created` (user_id, created_at) | per-user history (admin + GDPR export) |
| `idx_audit_action_created` (action, created_at) | overview "failed_logins_24h", `_last_admin_run` |

Note `_last_admin_run` (admin.py:1131) further narrows by
`audit_metadata['source'].astext == 'jobtech'`. The action+created_at
index handles the bulk; the JSONB containment check is then evaluated
on the already-narrow result. Acceptable. If future growth hurts, a GIN
index on `audit_metadata` jsonb_path_ops would help. P2.

### `users`
**No `__table_args__` — no indexes beyond PK and UQ on `email`.** The
admin overview runs `count(*) WHERE created_at >= week_ago` and the
listing runs `order by created_at desc limit 50`. Both will do a full
sort/scan as the user table grows. At expected scale (hundreds of users
in year one) it's negligible; flag for revisit. Also `func.lower(email)
.contains(q)` in admin user search is a sequential scan despite the
UQ on `email` (CITEXT). P2.

### `password_reset_tokens` / `email_verification_tokens`
PK is `token_hash` — lookups on `WHERE token_hash = …` are O(1). Good. No
secondary index on `user_id`; the only `user_id` query is via FK cascade
(no app-level select). Acceptable.

### `saved_signals`
UQ `(user_id, signal_type, signal_id)` covers the toggle endpoint's
existence-check. No `delete WHERE user_id = …` queries; FK ON DELETE
CASCADE handles user deletion. Adequate.

---

## 2. N+1 risks and inefficient SELECT patterns

### P0 — `subscriptions.create_subscription` count via `len(rows)`
`api/subscriptions.py:76-82`:
```python
count = (await session.execute(
    select(Subscription).where(Subscription.user_id == user.id)
)).all()
limit = _plan_limit(user.plan)
if limit is not None and len(count) >= limit:
```
This loads every Subscription row for the user just to compare the count
against `5 / 20`. Replace with `select(func.count()).select_from(Subscription)
.where(Subscription.user_id == user.id)` (a single COUNT query — no row
data over the wire). P0 because it executes on a hot user-facing path.

### P1 — Digest loads the entire 26-hour window into memory before user loop
`jobs/digest.py:88-123` (`_load_user_signals`) eagerly fetches all
job/change/procurement rows in the window, then iterates per user against
that in-memory list. CLAUDE.md §10's perf target ("5 000 signals × all
subs in <30s") is met by this design only because the dataset is small.

Risks:
- If a single signal type spikes (TED has a big day, JobTech publishes a
  Stockholm batch), memory grows linearly with signals × users (the
  list is shared but `_already_delivered` makes one query per user per
  signal type, so 3 queries × N users = 3N queries — N+1 by user).
- For a logical "100 active users" the digest issues at minimum 1 + N
  + 3N = 4N+1 round trips, plus the eager_changes query.
- The composite `_load_user_signals` query for changes does a join with
  Company. Good; uses no relationship lazy-load.

Recommendation: pre-compute per-user `delivered_set` once in a single
query grouped by user, or use a CTE / window function to filter
already-delivered in SQL.

### P1 — Admin user list "signal_count" only counts subscriptions
`api/admin.py:278-303` runs a per-page subscription-count grouped query
(good — single SELECT for the visible page). The field is named
`signal_count` but actually counts subscriptions, which the dashboard
also references. Naming bug, not a perf bug. P2.

### P1 — Admin signals tab triple-count probe
`api/admin.py:909-931` runs three independent COUNT queries in series for
the 24-h KPI panel. With `await` chained sequentially this is three
round-trips per page render. Combine into one `WITH` query or a single
union, or batch via `asyncio.gather`. P2.

### P1 — Admin overview = nine sequential aggregate queries
`api/admin.py:140-201` issues nine `await session.execute(...)` calls in
series before rendering. Each is cheap on small tables but at ~1-2 ms
DB round-trip + Python await overhead × 9 = ~20-50 ms latency. Combine
or `asyncio.gather`. P2.

### P2 — Admin audit detail builds per-page email map
`api/admin.py:1040-1042` calls `_user_email_map(...)` after every list
fetch — clean batched SELECT, not N+1. Looks fine.

### P2 — `users_list.total_label` does fake-count
`api/admin.py:320`: `total_label = f"~{len(rows) + offset}+"`. Avoids
an exact COUNT — sane choice; flagged just so reviewers know it's
intentional.

---

## 3. Unbounded SELECTs

| Location | Risk |
|---|---|
| `account.gdpr_export` (`account.py:462-470`) | Loads **all** Subscription / DeliveredAlert / AuditLog rows for the user with no LIMIT. For a heavy user who has been on the platform for a year this can be tens of thousands of rows held in memory while the JSON serializer walks them. P1 — stream as NDJSON or paginate; at minimum cap at e.g. 50k rows with a "_truncated" sentinel. |
| `digest._load_user_signals` | No LIMIT on the window. A bad ingest day could load 50k+ rows. P1. |
| `unsubscribe.unsubscribe` | `UPDATE Subscription WHERE user_id = ?` — bounded by the user's subscriptions (≤20). OK. |
| Admin list views | All correctly use `.offset(offset).limit(N)`. Good. |
| `gdpr.purge_deleted_users` | `select(User.id).where(deletion_requested_at < cutoff)` — unbounded but in practice rare. OK. |

---

## 4. `len(rows)` after `.all()` instead of COUNT

| Hit | Location | Severity |
|---|---|---|
| Subscription plan limit | `api/subscriptions.py:76-82` | **P0** |
| Admin user list pseudo-total | `api/admin.py:320` | P2 — intentional |
| `_record_deliveries` `if not rows` | `jobs/digest.py:335` | OK — list is in-memory dicts |
| `insert_ignore` returning rowcount | `ingest/_persist.py:60` | OK — `.returning(id)` then `len()`; correct way to count newly inserted with ON CONFLICT DO NOTHING |

---

## 5. Connection / session lifecycle

### Pool sizing (`db.py`)
- `pool_size=10`, `max_overflow=10` per process → up to 20 connections.
- Two uvicorn workers → 40 from API.
- Scheduler is a separate process with its own engine (one worker, but
  jobs run sequentially) → up to 20 more.
- **Theoretical ceiling: ~60 connections.** Postgres `max_connections=100`
  in `server_bootstrap.sh` (CLAUDE.md §16) → ~40 spare. Adequate.
- `pool_pre_ping=True`, `pool_recycle=1800` — sane.
- `expire_on_commit=False`, `autoflush=False` — sane and important for
  the FastAPI commit-on-success pattern.

### Session lifecycle
- API: `get_session` yields a session per request, commits on success,
  rolls back on exception. Correct.
- Jobs/scripts: `session_scope()` async context — same semantics.
- **Issue**: `BolagsverketAdapter.persist` (`ingest/bolagsverket.py:171-178`)
  imports `session_scope` from inside the method body and opens a session
  **per persist batch**. Combined with `upsert_companies` (which opens
  ITS OWN session) we get two transactions per batch. If the second
  transaction fails the first is already committed → partial state.
  Same pattern in `JobTechAdapter.persist` (`upsert_companies` + `insert_ignore`,
  each opens a session internally). P1 — push session ownership up to
  the orchestrator so a single transaction wraps `upsert_companies +
  insert_ignore` per batch.
- **Issue**: `_persist.insert_ignore` opens a session per call but only
  to `INSERT ... RETURNING id`. The session commits on context exit —
  fine in isolation. Combined with the point above, the issue is the
  cross-call atomicity, not the lifecycle of any single session.

### Long-running transactions across HTTP calls
None found. All HTTP calls (`http_client` in `_http.py`) are made
**outside** `session_scope` blocks: `fetch_since` is a generator that
yields plain Pydantic models, and `persist` is invoked only after a
batch is fully accumulated. Good — no locks held while waiting on
upstream APIs. The digest's `send_email` call **is** inside the
`session_scope` block (`jobs/digest.py:357 ... 420`); a slow Resend
response could hold an open transaction for tens of seconds. P1 — send
the email outside the transaction (collect digest sections in memory,
commit, then send + record deliveries in a second short transaction).

---

## 6. Eager vs lazy loads

No `relationship(...)` declarations in the models. Every "join" is an
explicit `select(A, B).join(B, A.fk == B.id)`. This is the safest pattern
available — there is no implicit lazy-load that could fire an N+1 from
template rendering. Excellent.

---

## 7. JSONB filter audit

| Site | Filter | Index? |
|---|---|---|
| `admin._last_admin_run` | `audit_metadata['source'].astext == source` | No GIN; but pre-filtered on `(action, created_at)` btree first → small result set, fine. P2 |
| `Subscription.criteria` (read-time matching) | matching is in-memory in Python; the DB never filters on JSONB criteria fields. Good. |
| `CompanyChange.old_value` / `new_value` | nulled-out by GDPR scrub; never queried. |

If the matcher ever pushes filters to SQL (CLAUDE.md §10 perf target may
demand this at >10k subs × >50k signals), a GIN index on
`subscriptions.criteria` jsonb_path_ops becomes mandatory.

---

## 8. Implicit / inefficient text filters

| Query | Issue |
|---|---|
| `admin.users_list` `func.lower(User.email).contains(q.lower())` | CITEXT column is already case-insensitive; wrapping in `func.lower(...)` strips the index. Use `User.email.ilike(f"%{q}%")` directly. P1. |
| `admin.signals_explorer` (jobs tab) `func.lower(headline).like('%q%')` | Leading-wildcard like — sequential scan. Acceptable for admin only but won't scale. Use `pg_trgm` GIN if needed. P2. |
| Same — changes/procurements tabs | Same pattern. P2. |

---

## 9. EXPLAIN-style notes (selected hot paths)

### Daily digest signal load (`jobs/digest.py`)
```sql
-- jobs:
SELECT * FROM job_postings WHERE published_at >= $1;
-- hits idx_jobs_published — Index Scan, Range. Good.

-- changes (joined with company):
SELECT cc.*, c.* FROM company_changes cc
JOIN companies c ON cc.company_id = c.id
WHERE cc.changed_at >= $1;
-- *** Sequential Scan on company_changes — no index on changed_at alone.
-- The (company_id, changed_at) composite is not selectable on changed_at only.

-- procurements:
SELECT * FROM procurements WHERE ingested_at >= $1;
-- *** Sequential Scan — no index on ingested_at.
```
At 30k-rows daily growth this is ~30ms today, but it scales linearly with
table size. Add btree(`changed_at`) and btree(`ingested_at`) on each.

### Resend webhook (`api/webhooks.py`)
```sql
UPDATE delivered_alerts SET opened_at = now() WHERE resend_message_id = $1;
-- *** Sequential Scan + ACCESS EXCLUSIVE row-level lock during scan.
```
Index `resend_message_id`. Critical at any production volume.

### Admin overview KPI panel (`api/admin.py:140-201`)
9 sequential `count(*)` queries on small tables today, but they read the
full table (heap + visibility map). Acceptable in year one, problematic
when `delivered_alerts` grows to millions.

---

## 10. Recommendations

Prioritized for implementation. Each line names file/table to touch.

### P0 — must-fix before scale
1. **Add index on `delivered_alerts.resend_message_id`.** New Alembic
   migration; bare btree is enough.
2. **Replace `len(rows)` count in `subscriptions.create_subscription`**
   (`api/subscriptions.py:76-82`) with `select(func.count())`.

### P1 — fix soon
3. Move `send_email` in `run_daily_digest` outside the `session_scope`
   block to avoid holding a Postgres transaction across an outbound HTTP
   call.
4. Pre-compute per-user `delivered_set` for the digest in a single
   query grouped by user (eliminate the 3N round-trips).
5. Add `btree(ingested_at)` to `procurements`, `btree(changed_at)` to
   `company_changes`, `btree(ingested_at)` to `job_postings` (or change
   `/ready` to read `published_at`).
6. `gdpr_export` — paginate or cap to avoid loading unbounded Audit/Alert
   history for long-tenured users.
7. Push transaction ownership for adapter persistence up: one
   `session_scope` wraps `upsert_companies + insert_ignore` per batch
   (atomicity).
8. `admin.users_list` — use `User.email.ilike(...)` instead of
   `func.lower(...)` so CITEXT can use the unique index.

### P2 — opportunistic
9. Add `btree(delivered_at DESC)` on `delivered_alerts` for
   admin/email/list views.
10. Combine the nine overview aggregate queries into one CTE or use
    `asyncio.gather` for parallelism.
11. Consider GIN(`pg_trgm`) on `job_postings.headline`,
    `companies.name`, `procurements.title` if admin search becomes
    routine.
12. Consider GIN on `subscriptions.criteria` once the matching engine
    pushes any filter to SQL.
13. Rename admin user-list `signal_count` → `subscription_count` for
    accuracy.
14. `_user_email_map` parameter type hint `SessionDep` is the FastAPI
    Annotated dep alias — replace with plain `AsyncSession` inside
    helper signatures (cosmetic, mypy-friendly).

---

## Appendix — Inventory of `.execute()` call sites

`grep -n session.execute src/vittring/`:

- `api/account.py` — 7 sites, all bounded by user_id or with explicit LIMIT.
- `api/admin.py` — ~30 sites; pagination uniform, occasional N+1 (overview).
- `api/auth.py` — 6 sites, all single-row lookups by indexed columns.
- `api/health.py` — 2 (cheap probes).
- `api/subscriptions.py` — 4 sites, the count-via-list issue is the
  only blocker.
- `api/unsubscribe.py` — 1 (UPDATE bounded by user_id).
- `api/webhooks.py` — 1 (UPDATE missing index — see P0).
- `ingest/_persist.py` — 3 (insert/upsert primitives).
- `ingest/bolagsverket.py` — 1 inline INSERT batch.
- `jobs/digest.py` — 5 sites, all bounded by `since` window or user_id.
- `jobs/gdpr.py` — 3 (scrub UPDATE, purge SELECT/DELETE).
- `audit/log.py` — 0 (uses `session.add`, owned by caller's transaction).
