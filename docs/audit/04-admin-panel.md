# Admin Panel Audit — Vittring

Date: 2026-05-05.
Branch: `claude/create-claude-md-5y5EA`.
Scope: read-only audit of the superadmin panel — access control, dangerous actions, CSRF, audit logging, query scaling, data exposure, action correctness, system triggers, visual consistency, empty states. Plus a survey of missing pages/features (bulk actions, IP block list, scheduler health view, Resend domain status).

Source files inspected:

- `src/vittring/api/admin.py` (the router; 1444 lines, all 9 admin pages plus action handlers).
- `src/vittring/api/templates/admin/_layout.html.j2`
- `src/vittring/api/templates/admin/{overview,users,user_new,user_detail,subscriptions,signals,audit,system,email}.html.j2`
- `src/vittring/api/deps.py` — `current_superuser`, `CurrentSuperuser`.
- `src/vittring/audit/log.py` — `AuditAction` enum.
- `src/vittring/security/csrf.py`, `src/vittring/api/templates.py` — CSRF middleware + `csrf_input()` helper.
- `src/vittring/jobs/scheduler.py` — APScheduler wiring (separate process).
- `src/vittring/delivery/domain_setup.py` — Resend domain verification.
- `src/vittring/main.py` — router registration.

---

## 1. Cross-cutting findings

### 1.1 Access gating

`current_superuser` (`deps.py:54`–`67`) is correctly applied via `CurrentSuperuser` annotation on **every** admin route — verified across all GET/POST handlers in `admin.py`. The dependency depends on `current_user` (not `current_verified_user`) by design so an unverified superuser can still self-service. OK.

**Issue:** when a non-superuser hits `/admin/*`, the dep raises `HTTPException(403, "admin_required")`, which `main.py:93`–`95` returns as raw `JSONResponse({"detail":"admin_required"})`. There is no friendly redirect to `/app` or `/auth/login?next=/admin/...`. This is the same pattern already flagged in `docs/ui-audit.md` §1.2 for verified-only routes. Recommend a small middleware that detects HTML routes and redirects rather than emitting JSON.

### 1.2 CSRF

`CSRFMiddleware` (`security/csrf.py:81`–`186`) reads either an `x-csrf-token` header or a `csrf_token` form field, comparing against a same-origin cookie. The `csrf_input()` global (`api/templates.py:18`–`24`) renders `<input type="hidden" name="csrf_token" value="...">` inside any template that calls it.

I audited every admin form. **All POST forms render `csrf_input()`:**

| Form | Template:line | csrf_input? |
|---|---|---|
| Sidebar logout | `_layout.html.j2:364` | yes |
| Create user | `user_new.html.j2:16` | yes |
| Edit user | `user_detail.html.j2:47` | yes |
| Promote (Pro + verify) | `user_detail.html.j2:94` | yes |
| Unlock account | `user_detail.html.j2:99` | yes |
| Resend verify | `user_detail.html.j2:104` | yes |
| Cancel deletion | `user_detail.html.j2:110` | yes |
| Schedule deletion | `user_detail.html.j2:115` | yes |
| Hard delete | `user_detail.html.j2:121` | yes |
| Subscription toggle (detail page) | `user_detail.html.j2:145` | yes |
| Subscription toggle (list page) | `subscriptions.html.j2:64` | yes |
| System trigger | `system.html.j2:37` | yes |

**No gaps.** Every state-changing admin form is covered.

Caveat: `docs/ui-audit.md` §1.1 flagged a related risk — that the CSRF cookie is only minted on the response of a GET, so the *first* POST after a long-lived idle tab can fail because the cookie expires (`Max-Age=86400`). The middleware's logic is the same here; a stale tab will get 403 `csrf_token_invalid`. Add an integration test that simulates a 25-hour-old tab.

### 1.3 Audit logging — actor vs. target

`audit()` in `audit/log.py:55`–`73` accepts a single `user_id`. The admin handlers consistently store the **target** user as `user_id` and embed the actor as `metadata["by_admin_id"]` (sometimes also `by_admin_email`). Examples:

- `users_new` (`admin.py:436`) → `user_id=new_user.id`, `metadata={"by_admin_id": user.id, "by_admin_email": user.email, ...}`.
- `user_edit` (`admin.py:593`) → `user_id=target.id`, `metadata={"by_admin_id": user.id, "changes": {...}}`.
- `user_promote` (`admin.py:650`) → same pattern.
- `user_unlock` (`admin.py:672`) → same.
- `user_resend_verify` (`admin.py:692`) → same.
- `user_schedule_delete` (`admin.py:718`) → same.
- `user_cancel_delete` (`admin.py:740`) → same.
- `user_hard_delete` (`admin.py:766`) → `user_id=None` (necessary because the FK SETs NULL once deletion runs), with `metadata={"by_admin_id": ..., "deleted_user_id": ..., "deleted_email": ...}`.
- `subscription_toggle` (`admin.py:872`) → `user_id=sub.user_id` (the target), `metadata={"by_admin_id": ..., "subscription_id": ..., "active": ...}`.
- `system_trigger` (`admin.py:1252` ff.) → `user_id=user.id` (the actor — there is no target), `metadata={"source": ..., "fetched": ..., ...}`.

**Issues:**

1. The `user_detail` page filters audit on `AuditLog.user_id == target.id` (`admin.py:493`), so it correctly surfaces every admin mutation against the target. **Good.** The audit page (`/admin/audit`) similarly filters by `user_id` (`admin.py:1036`), and the user-list of `recent_audit` on `/admin` (`admin.py:209`) shows the target as the row's user. So the actor-vs-target split is consistent.
2. The `/admin/audit` filter has no input for "actions performed BY admin id X". To find every admin mutation a particular operator made, you'd have to grep through the metadata of every row. Recommend adding a JSONB `metadata->>'by_admin_id'` filter (with a GIN index).
3. `user_hard_delete` writes the audit row **before** deleting (`admin.py:766` then `:779`). Correct order — once the user is deleted, the FK would null out. The `user_id=None` choice is appropriate; the `deleted_user_id` / `deleted_email` metadata preserves the target identity. **Good.**

### 1.4 Visual consistency — accent rule

The differentiating rule (`_layout.html.j2:1`–`3`) is "uses `--v-amber` as the active accent so the operator can tell at a glance they're in admin." Verified across all templates — sidebar `nav-item.active`, eyebrow text, primary button, page header eyebrow, focus rings — all amber.

Pages that **mix** signal-green into chrome (minor):

- `user_detail.html.j2:95` — "Ge premium" button uses `class="btn signal"` (green). It's the only chrome-level signal-coloured affordance in admin and visually competes with the amber primary. Consider `btn primary` (amber) instead, since it's the most-used action.
- `subscriptions.html.j2:51` — `'job'` and `'company_change'` badges use `signal`. This is a *value*-encoding (signal-type) rather than admin chrome, but a strict reading of the rule says all admin-affordances should be amber. Acceptable as data-tag colour.
- `email.html.j2:50`–`51` — opened indicator uses `--v-signal` green, clicked uses `--v-amber`. Mixed semantics. Either both should be amber (pure accent) or keep both as data encoding. Pick one.
- Pip dots (`_layout.html.j2:152`–`155`) use `--v-signal` for "on" — acceptable because they're status data, not chrome.

Otherwise the panel is consistent: navigation `active`, eyebrows, `admin-pill`, primary button — all amber. The sidebar avatar uses an amber gradient; the "Admin" pill is amber. **Rule is broadly upheld.**

### 1.5 Pagination + scaling

All list pages use `OFFSET`/`LIMIT` with `page_size = 50` (subscriptions, signals, users) or `100` (audit). `OFFSET`-pagination degrades quadratically once the table grows past ~100k rows; the existing schema has no provision for keyset cursor pagination. With 10k users `users_list` is fine, but `signals_explorer` against millions of `job_postings` rows will hurt. See per-page notes.

The `total_label` on `/admin/users` is computed as `~{offset+rowcount}+` if a full page came back, or `{offset+rowcount}` otherwise (`admin.py:320`). It approximates the running count; it does **not** show the true total. That's a deliberate choice (a `COUNT(*)` over filtered users on every page is expensive) and is acceptable, but the UI says "{total_label} användare i plattformen" (`users.html.j2:9`), which is misleading: with ~50 users it shows "50 användare" exactly, and with >50 it says "~50+" — confusing for the operator. Prefer a single `COUNT(*)` cached for the duration of the request, or change the copy.

### 1.6 Data exposure

I confirmed the templates render **no** sensitive credentials:

- `password_hash` — never referenced.
- `totp_secret` — never referenced (only `totp_enabled_at` shown on user detail at `user_detail.html.j2:33`).
- `last_login_ip` is shown on user detail (`user_detail.html.j2:38`). This is PD; document in `docs/gdpr.md`.
- `audit_metadata` on `/admin/audit` is rendered raw (line 49), so any handler that ever puts a token / link into metadata leaks it here. Existing code never does, but maintain that discipline.

**No exposure issues.**

### 1.7 Confirmation prompts (dangerous-action survey)

| Action | URL | Single confirm? | Verdict |
|---|---|---|---|
| Edit user (incl. flip `is_superuser`) | POST `/admin/users/{id}/edit` | **No** | Add a confirm when `is_superuser` flips. |
| Promote to Pro+verified | POST `/admin/users/{id}/promote` | **No** | Acceptable for an admin convenience. |
| Unlock account | POST `/admin/users/{id}/unlock` | **No** | Acceptable. |
| Resend verification | POST `/admin/users/{id}/resend-verify` | **No** | Acceptable (no-op currently — see §2.4). |
| Schedule deletion | POST `/admin/users/{id}/schedule-delete` | **Yes** (`onsubmit confirm`) | OK. |
| Cancel deletion | POST `/admin/users/{id}/cancel-delete` | **No** | Acceptable. |
| Hard delete now | POST `/admin/users/{id}/hard-delete` | **Yes** (`onsubmit confirm`) | OK; consider type-the-email double-confirm. |
| Subscription toggle | POST `/admin/subscriptions/{id}/toggle` | No | OK. |
| System trigger | POST `/admin/system/trigger/{name}` | **Yes** (`onsubmit confirm`) | OK. |

**Gap:** `is_superuser` promotion via the edit form has no extra friction. The handler does block self-deletion (`admin.py:759`–`763`: `if target.id == user.id: 400 cannot_delete_self`) — good — but the same demote-self protection is **missing** from `user_edit`: an admin can untick their own `is_superuser` checkbox, save, and lock themselves out of the panel. Add: `if target.id == user.id and not new_super: raise HTTPException(...)`. Same for `is_active=False` on self.

---

## 2. Page-by-page

### 2.1 `/admin` — overview

Handler: `admin.py:131`–`253`. Template: `admin/overview.html.j2`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. OK. |
| 2. Confirmation | No destructive actions on this page. OK. |
| 3. CSRF | Read-only; sidebar logout has CSRF (`_layout.html.j2:364`). OK. |
| 4. Audit logging | Not applicable (read-only). |
| 5. Pagination + search | Recent users limited to 10 (`admin.py:206`); recent audit limited to 15 (`:212`). Bounded. OK. |
| 6. Data exposure | No `password_hash`, no `totp_secret`. OK. |
| 7. Action correctness | None. |
| 8. System triggers | None. |
| 9. Visual consistency | Amber-accented stat cards / numerics; on the "Plan" group, Solo is signal-green and Team/Pro are amber (lines 45/49/53) — matches the public dashboard convention. OK. |
| 10. Empty states | `{% if recent_users %}` / `{% else %}` ("Inga användare ännu.") and recent audit symmetrical. **`stats.users_verified_pct` is guarded against ZeroDivisionError** at `admin.py:227`–`229`. **`open_rate`/`click_rate` on email page also guard.** Good. **However:** the stat-grid renders zeroes for a fresh DB — that's the empty state for the overview, but it makes the page look "production-ready and idle" rather than "fresh install, do something". Consider a dedicated banner when `users_total == 0` nudging the operator to create the first user. |

### 2.2 `/admin/users` — list

Handler: `admin.py:260`–`334`. Template: `admin/users.html.j2`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. OK. |
| 2. Confirmation | No destructive actions on the list. OK. |
| 3. CSRF | Filter form is GET. OK. |
| 4. Audit logging | Read-only. |
| 5. Pagination + search | Free-text search uses `func.lower(User.email).contains(q.lower())` (`admin.py:271`) — translates to `LOWER(email) LIKE '%q%'`. **`users.email` is `CITEXT` with a unique constraint (B-tree)**; that B-tree cannot accelerate `LIKE '%q%'` queries — they will sequence-scan. At 10k users still under a second; at 1M users it hurts. Add a `pg_trgm` GIN index on `email` if growth warrants. The `signal_count` per row is computed in a single grouped query (`admin.py:281`–`286`) — no N+1. **Good.** |
| 6. Data exposure | Profile columns only. OK. |
| 7. Action correctness | None on list. |
| 8. System triggers | None. |
| 9. Visual consistency | Amber pills, signal/danger badges sparingly. OK. |
| 10. Empty states | "Inga användare matchar filtret." with conditional "Rensa filter" link. OK. |

Other:

- No bulk-action selectboxes, no CSV export. See §3.
- No filter for "deletion_requested_at IS NOT NULL" — useful for the GDPR grace-period queue. See §3.

### 2.3 `/admin/users/new`

Handlers: `admin.py:341`–`453`. Template: `admin/user_new.html.j2`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. OK. |
| 2. Confirmation | "Skapa användare" — non-destructive. The `is_superuser` checkbox can be ticked at create time with no extra friction; promoting at signup is the same risk as via edit. Acceptable for first-time admin bootstrap, but log loudly. The handler does emit `ADMIN_USER_CREATE` (line 438). Consider adding `ADMIN_USER_PROMOTE` when `is_superuser=True` at create time so the audit trail mirrors the edit-promote case. |
| 3. CSRF | `{{ csrf_input() }}` (line 16). OK. |
| 4. Audit logging | `ADMIN_USER_CREATE` (line 438) with `metadata` covering admin id, plan, verification flags. Good. |
| 5. Pagination/search | N/A. |
| 6. Data exposure | The `form` echoed back on validation errors does **not** include the password (`admin.py:367`–`374`). OK. |
| 7. Action correctness | `assert_strong_password` runs (line 390); `bcrypt` hash via `hash_password` (line 422); duplicate email check (line 404). Plan validation against `ALLOWED_PLANS` (line 376). 14-day trial set automatically when `plan="trial"` (line 428). Good. |
| 8. System triggers | None. |
| 9. Visual consistency | Amber primary button. OK. |
| 10. Empty states | N/A. |

Notes:

- Subtitle says "användaren får inte automatiskt ett välkomstmail" (line 9). Confirmed: the handler never enqueues a welcome email. Document this design choice somewhere visible (e.g. handler docstring) so a future agent doesn't "fix" it by adding an email send that surprises the operator.
- The form sets `minlength="12"` client-side; `assert_strong_password` enforces server-side. Defence in depth — fine.
- The `is_verified` checkbox **defaults to checked** (template line 49: `{% if form.is_verified is not defined or form.is_verified %}checked{% endif %}`). Reasonable for admin-created users; document the assumption.

### 2.4 `/admin/users/{id}` — detail

Handler (GET): `admin.py:469`–`520`. Plus `user_edit, user_promote, user_unlock, user_resend_verify, user_schedule_delete, user_cancel_delete, user_hard_delete` (`:527`–`787`). Template: `user_detail.html.j2`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser` on every handler. OK. |
| 2. Confirmation | Hard-delete and schedule-delete confirmed (template lines 114, 120). Edit form has none even when toggling `is_superuser`. See §1.7. |
| 3. CSRF | All forms use `{{ csrf_input() }}`. OK. |
| 4. Audit logging | Every mutation emits the right `AuditAction`: edit→`ADMIN_USER_EDIT`, plan-change-side-effect→`ADMIN_PLAN_CHANGE` (line 607), promote→`ADMIN_USER_PROMOTE`, unlock→`ADMIN_USER_UNLOCK`, resend-verify→`ADMIN_USER_VERIFICATION_RESEND`, schedule-delete→`ADMIN_USER_DELETE_REQUEST`, cancel-delete→`ADMIN_USER_DELETE_CANCEL`, hard-delete→`ADMIN_USER_DELETE`. **Full coverage.** |
| 5. Pagination/search | All three inline tables (subscriptions, audit, delivered) are explicitly limited: subscriptions un-limited (line 487 — could blow up if a user has 1000s, see below), audit limited to 25 (`admin.py:495`), delivered to 25 (`:504`). Bounded enough for normal users; **subscriptions are unbounded** — at the Pro plan with "unlimited filters", a user could create 100s. Add `LIMIT 50` and a "view all" link. |
| 6. Data exposure | Profile renders id, email, name, company, plan, trial_ends_at, verified, active, superuser, totp_enabled_at (date only — not the secret), failed_login_count, locked_until, created_at, last_login_at, last_login_ip, deletion_requested_at. **No `password_hash`, no `totp_secret`.** OK. |
| 7. Action correctness | "Lås upp konto" → `user_unlock` sets `failed_login_count=0` AND `locked_until=None` (`admin.py:669`–`670`). **Correct.** "Ge premium" → `user_promote` sets `plan="pro"` AND `is_verified=True` (`admin.py:647`–`648`). **Correct.** Both in a single transaction (no explicit commit; SQLAlchemy session auto-commits on dependency exit, see `db.py`). Edit handler clears `failed_login_count = 0` when locked_until cleared (line 575) — nice safety. |
| 8. System triggers | None on this page. |
| 9. Visual consistency | Quick-actions row mixes `btn signal` (premium), `btn` (unlock, resend, cancel), `btn danger` (delete). Signal-coloured premium button stands out — see §1.4. |
| 10. Empty states | All present and Swedish. OK. |

Specific issues found in handler:

- `_parse_dt` (`admin.py:82`–`100`) parses ISO-ish strings; rejecting bad input returns `None` and the value is silently set to NULL. If admin types `2026-13-99` (invalid month), `trial_ends_at` is **silently cleared** rather than reported. Recommend surfacing a flash error.
- `trial_ends_at` and `locked_until` are `<input type="text">` (lines 60, 65); the layout already has `datetime-local` styling at `_layout.html.j2:210`. Switch to `<input type="datetime-local">`.
- **Self-demote / self-deactivate not blocked.** `user_edit` does not check `target.id == user.id` before turning off `is_superuser` or `is_active`. `user_hard_delete` does check (line 759). Add equivalent guard to `user_edit` so the last admin can't self-lockout.
- `user_resend_verify` (lines 683–704) audits but **does not actually send an email** — the metadata includes `"note": "no email sent (placeholder)"` and the flash text says "Loggat — verifieringslänk skickas inte automatiskt än." The button is essentially a TODO. Either implement (re-issue token + email) or remove the button until ready. Currently it misleads the operator.
- `_load_user_or_404` (lines 460–466) raises `HTTPException(404)`, which the global handler (`main.py:93`–`95`) renders as JSON. For an HTML route, a missing user produces a JSON 404 in the browser. Render an HTML 404 page for `/admin/*` GETs.

### 2.5 `/admin/subscriptions`

Handler: `admin.py:794`–`887`. Template: `admin/subscriptions.html.j2`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. OK. |
| 2. Confirmation | Toggle is non-destructive. OK. |
| 3. CSRF | `{{ csrf_input() }}` per toggle form. OK. |
| 4. Audit logging | `ADMIN_SUBSCRIPTION_TOGGLE` with `{by_admin_id, subscription_id, active}`. OK. |
| 5. Pagination + search | Filter is signal-type only — **no free-text search**. With ~30k subscriptions across 10k users, scrolling is unusable. Add `q=` filter on `subscriptions.name` + join on `users.email`. The query is `JOIN User` for the email column (line 804) — joining to the users table is fine; it's keyed by `subscription.user_id`. **`Subscription.signal_types.any(signal_type)` (line 806)** uses PostgreSQL ARRAY ANY — index-friendly only with a GIN on `signal_types` (the schema doesn't show one). Add an index. |
| 6. Data exposure | `criteria` JSONB rendered behind `<details>`. Contains keywords/orgnrs but no PD. OK. |
| 7. Action correctness | Toggle reverses `active` only (line 870); other fields untouched. OK. |
| 8. System triggers | None. |
| 9. Visual consistency | Signal/amber badges on signal_type — see §1.4. |
| 10. Empty states | "Inga prenumerationer matchar filtret." OK. |

Other:

- `redirect_to` (line 861) is sanity-checked to start with `/admin` (line 885). Good — prevents open-redirect.
- No bulk pause/resume; no admin-side delete (only user-side). Document.

### 2.6 `/admin/signals`

Handler: `admin.py:894`–`1016`. Template: `admin/signals.html.j2`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. OK. |
| 2. Confirmation | Read-only. |
| 3. CSRF | Read-only filter form. OK. |
| 4. Audit logging | Browsing signals is non-sensitive. None. |
| 5. Pagination + search | `func.lower(...).like('%q%')` across headlines, employer, municipality / company name+orgnr / procurement title+buyer. **Will sequence-scan** because the schema has no trigram or full-text index on these columns (`models/signals.py`, `models/company.py`, `migrations`). At a few thousand rows fine; at 100k+ painful. Add `pg_trgm` GIN indexes (or `to_tsvector` + GIN). Pagination is `OFFSET` — at large page numbers degrade. |
| 6. Data exposure | "changes" tab renders `old_value` / `new_value` JSON. The handler returns `personal_data_purged_at` to the template (line 974), and the template hides the diff via `{% if r.old_value or r.new_value %}` — **but** `personal_data_purged_at` is only used to render the "rensad" placeholder (line 72). If for any reason `personal_data_purged_at IS NOT NULL` but `old_value` is also non-null (corrupt data, partial purge), PD leaks. Belt-and-braces fix: skip rendering the diff when `personal_data_purged_at IS NOT NULL`, regardless of column nullability. |
| 7. Action correctness | None. |
| 8. System triggers | None. |
| 9. Visual consistency | Tabs use amber active state; CPV/value/buyer columns mono. OK. |
| 10. Empty states | "Inga signaler matchar." OK. |

Other:

- `rows` for the "changes" tab is built by manufacturing anonymous classes via `type("ChangeRow", (), {...})` (line 962). This works but is unconventional; a typed `dataclass` or Pydantic model would be more readable. Cosmetic.

### 2.7 `/admin/audit`

Handler: `admin.py:1023`–`1081`. Template: `admin/audit.html.j2`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. OK. |
| 2. Confirmation | Read-only. |
| 3. CSRF | Read-only filter is GET. OK. |
| 4. Audit logging | Read; none. |
| 5. Pagination + search | `idx_audit_user_created` and `idx_audit_action_created` exist (`models/audit.py:50`–`53`), so filtering on either column is index-friendly. Pure pagination via `OFFSET` over the unfiltered 24-month audit log will hurt past page ~100; switch to keyset cursor (`WHERE created_at < :cursor LIMIT 100`). |
| 6. Data exposure | `ip` and `audit_metadata` rendered. As long as no handler ever puts secrets into metadata, OK. |
| 7. Action correctness | None. |
| 8. System triggers | None. |
| 9. Visual consistency | Amber filter buttons; mono table. OK. |
| 10. Empty states | "Inga händelser matchar filtret." OK. |

**Missing filters:** date-range (`from`/`to`) and "performed by admin id" (filter `metadata->>'by_admin_id'`). See §3.

### 2.8 `/admin/system`

Handler: `admin.py:1138`–`1218` plus `system_trigger` `:1232`–`1358`. Template: `admin/system.html.j2`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. OK. |
| 2. Confirmation | Each manual trigger wrapped in `onsubmit="return confirm('Trigga {{ j.label }} nu?');"` (template line 36). OK. |
| 3. CSRF | `{{ csrf_input() }}` per trigger form. OK. |
| 4. Audit logging | Each branch emits the right action: ingest → `ADMIN_TRIGGER_INGEST` with `{source, fetched, new_rows, duration_seconds}` (lines 1252–1264) on success, plus a parallel error-logged audit row on failure. Same for digest, scrub, purge. **Coverage is complete.** |
| 5. Pagination/search | None. `db_counts` is a fixed dict over canonical models. OK. |
| 6. Data exposure | App + Python version exposed to admin. No secrets. OK. **However:** `resend_detail` is set to `str(exc)` on Resend API failure (line 1197). If Resend returns an authentication error, the response body could include a hint of the API key (rare but possible with `httpx.HTTPStatusError`). Sanitize by only showing `exc.__class__.__name__`. |
| 7. Action correctness | Whitelist `INGEST_ADAPTERS` dict (line 1225) protects against arbitrary `job_name`. Unknown name → 404 (line 1353). OK. |
| 8. System triggers — backgrounded? | **No.** Each trigger calls `await asyncio.wait_for(run_ingest(...), timeout=120)` (line 1249) — synchronously blocking the request for up to 120s (or 300s for digest, line 1282). Gunicorn's default timeout is 30s; the request will be killed before completion on a real ingest of 5000 jobs. Either: (a) launch as `asyncio.create_task(...)` and redirect with a flash "kör i bakgrunden"; (b) push to a queue handled by the scheduler process. The current design will silently 504. **Top P1 issue.** |
| 9. Visual consistency | Amber primary "Trigga" button; signal/amber/danger badges for Resend status. OK. |
| 10. Empty states | `last_run` shows "Inga data ännu" if null. `db_counts` always populated by canonical models. **Fresh-install safe.** OK. |

Resend domain panel:

- The handler **does** call `ensure_domain_verified(wait=False)` on every page render (line 1190) — meaning each `/admin/system` GET hits Resend's API and triggers a verification attempt. On a verified domain Resend returns quickly; on a non-verified domain the function in `delivery/domain_setup.py:144` raises `DomainNotVerifiedError` — which the handler catches into `resend_status="pending"` and `resend_detail=str(exc)`. **Side effect:** `domain_setup.ensure_domain_verified` calls `_print_records(...)` (line 141 of domain_setup) on every non-verified poll, which prints DNS records to stdout (systemd journal). This logs a long block of DNS records every time an admin loads `/admin/system` while the domain is pending. Move `_print_records` out of the request path or guard with a "first-call-per-process" flag.
- Status pill matrix in template: `verified, pending, not_started, unreachable, *anything else`. The handler emits `unknown, pending, unreachable, <DomainStatus value>`; "unknown" is mapped to the `else` → danger badge in the template (line 79). OK.
- **Missing:** no "Verifiera om" button. If DNS changes, the operator can only re-trigger by reloading the page (which already triggers verify on every load — fine, but that's accidental behaviour). Make it explicit via a button.

### 2.9 `/admin/email`

Handler: `admin.py:1365`–`1444`. Template: `admin/email.html.j2`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. OK. |
| 2. Confirmation | Read-only. |
| 3. CSRF | None needed. |
| 4. Audit logging | Read; none. |
| 5. Pagination + search | Hard-coded "Senaste 50 leveranser" via `LIMIT EMAIL_RECENT_LIMIT=50` (line 1414). Bounded. **`open_rate`/`click_rate` are guarded against ZeroDivisionError** (lines 1406–1407). Good. |
| 6. Data exposure | `resend_message_id` is internal to Resend, not PD. OK. |
| 7. Action correctness | None. |
| 8. System triggers | None. |
| 9. Visual consistency | Mixes signal-green for opened, amber for clicked. See §1.4. |
| 10. Empty states | "Inga e-postleveranser ännu." OK. |

**Missing:** no bounce / complaint metrics. CLAUDE.md §11 mandates "Three hard bounces in 30 days → user marked is_active=false". Where does the operator see bounce counts and which users are at risk? Add a "Bounces 30d" stat and a "Risky recipients" table.

---

## 3. Missing pages and features

This panel covers users, subscriptions, signals, audit, system, email — but several admin needs are not addressed:

1. **Bulk user actions.** No multi-select on `/admin/users` for "verify N", "send verification email to all unverified", "downgrade trial expirees".
2. **CSV export.** Audit, users, subscriptions, delivered_alerts — none can be exported. Support cases routinely need this.
3. **IP block list.** UFW + fail2ban operate at OS level (CLAUDE.md §13), but the app has no per-IP allow/deny list (e.g. block a scraper without SSH). Add an `ip_blocks` table + admin page.
4. **Scheduler health view.** `/admin/system` shows `last_run` from the audit log of *manual* triggers. There is **no view of the scheduler process's actual state** — is APScheduler currently up? Stuck job? Last successful scheduled poll? The scheduler runs in a separate systemd unit (`vittring-scheduler.service`, see CLAUDE.md §16, `jobs/scheduler.py:1`–`6`); the API process can't introspect it directly. Options: write `last_successful_run` per job to a `scheduler_state` DB table from the scheduler process; surface that on `/admin/system`.
5. **Resend domain re-verify button.** Implicit re-verification on page load (§2.8) is hidden. Add a "Verifiera om" button that posts to a dedicated endpoint.
6. **Resend webhook health.** No view of last webhook delivered, signature failures, or unknown event types. Add a panel.
7. **Stripe / billing.** Deferred per CLAUDE.md §7 but the panel has no placeholder for "billing events" / "Stripe webhook events" page. Stub it now so the navigation is stable when billing is enabled.
8. **GDPR-action queue.** When a user clicks "Delete account", `users.deletion_requested_at` is set. There is currently no admin view of "users pending hard-delete" with the date the grace period ends. Add a tab on `/admin/users` filtered by `deletion_requested_at IS NOT NULL`.
9. **Admin GDPR export.** No "Generate GDPR export for this user" button on user-detail. Karim will eventually need this for support cases.
10. **Subprocessor / DPA log.** No place to record "DPA signed with Resend on 2026-04-01". Could be a static page.
11. **Backup status.** No view of last successful `pg_dump`, last successful `rsync` to Storage Box (when enabled), sizes, retention pruning state. Critical for runbook.
12. **Rate-limit / lockout dashboard.** No view of which IPs are getting 429'd, which emails are hitting login rate limits, which users are currently locked.
13. **Audit-of-admin filter.** As mentioned in §1.3, the audit page can't filter by "actions performed BY this admin user_id" (i.e. `metadata->>'by_admin_id' = X`). Add this filter and a JSONB index.
14. **Notice / kill-switch panel.** No way to put up a global maintenance banner or pause all outbound email.
15. **Resend verify button is a no-op.** `user_resend_verify` audits but doesn't actually send. Either implement or remove the button.

---

## 4. Items to fix before shipping

P0 (correctness / production safety):

1. **`/admin/system/trigger/*` blocks the request for up to 120–300s** (`admin.py:1249, 1282, 1306, 1330`). Real ingests will exceed Gunicorn's timeout. Background with `asyncio.create_task` and report status via flash + audit row.
2. **Self-demote / self-deactivate not blocked in `user_edit`** (`admin.py:586`–`590`, `:577`–`580`). The last admin can lock themselves out. Add a guard mirroring `user_hard_delete:759`.
3. **`user_resend_verify` button is a no-op**. Implement actual verification email or remove the button (it lies to the operator).

P1 (security/UX):

4. Add type-the-email confirmation on `Hård-radera nu`.
5. Convert `trial_ends_at` / `locked_until` inputs to `<input type="datetime-local">`.
6. Sanitize `resend_detail` in `/admin/system` so that Resend API error bodies cannot leak the API key.
7. Hide `_print_records` stdout side-effect in `domain_setup.ensure_domain_verified` when called from a request handler.
8. Render an HTML 404 / 403 for admin routes; current global handler emits JSON.
9. Limit user-detail subscriptions list to 50 with "view all" link.

P2 (scale + completeness):

10. Replace `OFFSET`-pagination with keyset pagination on all list pages once tables exceed ~10k rows.
11. Add `pg_trgm` GIN indexes for `users.email`, `subscriptions.name`, `job_postings.headline`/`employer_name`, `procurements.title`/`buyer_name`, `companies.name`/`orgnr`. Only then enable free-text search at scale.
12. Add free-text search and date filters to `/admin/audit`.
13. Add the missing pages enumerated in §3.

---

## 5. Miscellaneous

- The eyebrow "Admin · X" copy is consistent across all pages — good.
- Swedish copy is direct and professional; no English loanwords noted.
- All forms use POST + `Form()`; no JS-driven mutations. Good — no XHR-CSRF gymnastics required.
- All admin templates inherit from the standalone `_layout.html.j2` (verified: `extends "admin/_layout.html.j2"` on every page).
- The "↩ Dashboard" link in the sidebar bounces to `/app` — useful for admin QA.
- Constant naming: `INGEST_ADAPTERS` in `admin.py:1225` is a tight whitelist — good defensive design.
- `_user_email_map` (`admin.py:103`–`111`) is a small N+1 mitigation utility — applied in overview and audit views. Good.
- The handlers emit `audit()` rows but never `await session.commit()` explicitly. Commits rely on FastAPI's dependency-exit semantics in `db.py`. Verify there's no missing-commit path on exception in the trigger handlers — a partial state where a job ran but the audit row wasn't persisted would erode the audit guarantee.

End of audit.
