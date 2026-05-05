# Admin Panel Audit — Vittring

Date: 2026-05-05.
Branch: `claude/create-claude-md-5y5EA`.
Scope: read-only audit of the superadmin panel — access control, dangerous actions, CSRF, audit logging, query scaling, data exposure, action correctness, system triggers, visual consistency, empty states. Includes a survey of missing pages/features.

Source files inspected:

- `src/vittring/api/admin.py` — **does not exist**
- `src/vittring/api/templates/admin/_layout.html.j2`
- `src/vittring/api/templates/admin/overview.html.j2`
- `src/vittring/api/templates/admin/users.html.j2`
- `src/vittring/api/templates/admin/user_new.html.j2`
- `src/vittring/api/templates/admin/user_detail.html.j2`
- `src/vittring/api/templates/admin/subscriptions.html.j2`
- `src/vittring/api/templates/admin/signals.html.j2`
- `src/vittring/api/templates/admin/audit.html.j2`
- `src/vittring/api/templates/admin/system.html.j2`
- `src/vittring/api/templates/admin/email.html.j2`
- `src/vittring/api/deps.py` — `current_superuser`, `CurrentSuperuser` alias
- `src/vittring/audit/log.py` — `AuditAction` enum
- `src/vittring/security/csrf.py`
- `src/vittring/api/templates.py` — `csrf_input()` helper
- `src/vittring/main.py` — `app.include_router(admin.router)`
- `src/vittring/jobs/scheduler.py`
- `src/vittring/delivery/domain_setup.py`

---

## 0. P0 — admin router does not exist

The router is wired up in `src/vittring/main.py:22` (`from vittring.api import admin`) and mounted at `:84` (`app.include_router(admin.router)`), but **`src/vittring/api/admin.py` is not present in the repository.** A directory listing of `src/vittring/api/` shows only `account.py, auth.py, billing.py, deps.py, health.py, public.py, subscriptions.py, templates.py, unsubscribe.py, webhooks.py`. The application will fail at import time (`ModuleNotFoundError: No module named 'vittring.api.admin'`) and never start.

Everything below evaluates the surface that *does* exist — the templates plus the supporting plumbing (deps, audit constants, CSRF, scheduler) — and notes what the missing handler module must implement to make the templates work.

The audit therefore mixes two concerns:

1. **What's already wrong / weak** in the templates and dependencies that exist.
2. **What the missing `admin.py` must do** to satisfy each page (use as a TODO when the handler is finally written).

---

## 1. Cross-cutting findings

### 1.1 `current_superuser` raises 403 JSON, not redirect

- File: `src/vittring/api/deps.py:54`–`67`.
- Behaviour: when a non-superuser hits `/admin/...`, `HTTPException(403, "admin_required")` is raised, then the global handler at `main.py:93`–`95` returns it as a raw `JSONResponse({"detail":"admin_required"})`.
- Impact: any logged-in non-admin who navigates to `/admin` sees a JSON blob, not a friendly redirect to `/app` or to login. Same dead-end pattern called out in `docs/ui-audit.md` §1.2 for `/app` access.
- Note: `current_superuser` deliberately depends on `current_user` (not `current_verified_user`) so an unverified superuser can still log in and self-fix — this is documented in the docstring and is correct.
- Note: `current_user` returns 401 (not redirect) for an anonymous visitor, so unauthenticated `/admin` traffic also gets JSON. The handler should check the `Accept` header or detect HTML routes and redirect to `/auth/login?next=/admin/...`.

### 1.2 CSRF helper exists, but middleware is broken upstream

- File: `src/vittring/security/csrf.py:81`–`151`; `src/vittring/api/templates.py:14`–`37`.
- All admin POST forms call `{{ csrf_input() }}`, which renders `<input type="hidden" name="csrf_token" value="...">` from `request.state.csrf_token`. The CSRF middleware **does** look at the form field at lines 130–141, so once the cookie is delivered the forms will validate — *unlike* the public-side dashboard which the existing UI audit (`docs/ui-audit.md` §1.1) flagged for the same middleware.
- However: the middleware reads `cookies.get(CSRF_COOKIE_NAME)` and rejects if missing. The cookie is only set on the *response* of a GET (lines 113–114 / 163–164). On a fresh tab the first GET to `/admin` mints a token, sets the cookie, and renders the form. Submitting the form on the next request includes the cookie + the hidden field — that path works.
- **Risk:** if the operator opens two admin tabs side-by-side and the first GET sets the cookie under one Set-Cookie path while the middleware later mints a different token in another tab, the second tab's form will carry a stale `csrf_token` field but the freshest cookie. The middleware compares `submitted != cookie_token`, so the second submission silently 403s. Low likelihood but worth a regression test.
- **Risk:** the CSRF middleware reads body once and replays. If a downstream router were to use `Body(...)` instead of `Form(...)`, the bytes are intact, but the `parse_qs` validation in the middleware assumes form-urlencoded; multipart admin forms (e.g. file upload) would not have their tokens parsed. None of the current admin templates submit multipart, so this is latent.

### 1.3 Visual consistency — accent rule

- The differentiating rule in `_layout.html.j2:1`–`3`: "Mirrors the dashboard's dark Night theme but uses --v-amber as the active accent so the operator can tell at a glance they're in admin." Verified across all admin templates.
- Pages that **break** the rule:
  - `subscriptions.html.j2:51` — `signal_type == 'job'` and `'company_change'` both use `class="badge signal"` (`--v-signal`). This is fine as a *value*-encoding (signal-type) rather than admin-vs-app, but a strict reading of the rule says all admin-affordances should be amber. Recommend keeping signal as a data-tag colour but never as a chrome accent.
  - `user_detail.html.j2:95` — the "Ge premium" button uses `class="btn signal"` (green). It's a positive action and reads correctly, but it's the only chrome-level signal-coloured affordance in admin and visually competes with the amber accent. Consider `btn primary` (amber) instead.
  - `_layout.html.j2:152`–`155` — pip dots: `.pip.on { background: var(--v-signal); }`. Used as on/off status (good); the rule does not forbid signal-as-data, only signal-as-chrome. Acceptable.
  - `email.html.j2:50` — opened indicator uses `var(--v-signal)`, clicked uses `var(--v-amber)`. Mixed semantics; both are events but only one is amber. Either both should be amber (pure accent) or keep the data encoding consistently across signals/email pages.
- Otherwise the panel is consistent: navigation `active` state, eyebrows, `admin-pill`, focus rings, primary button — all amber.

### 1.4 Audit logging — admin context not captured

- `src/vittring/audit/log.py:55`–`73`: `audit()` accepts a single `user_id` plus `metadata`. No first-class field for "admin who performed the action vs. target user".
- Consequence: every admin action either (a) logs `user_id = target.id` and loses the actor, (b) logs `user_id = admin.id` and loses the target, or (c) the missing `admin.py` must encode both into `metadata` (e.g. `{"actor_user_id": admin.id, "target_user_id": user.id, ...}`).
- Recommendation: when `admin.py` is written, every admin action **must** log with `user_id = admin.id` AND `metadata = {"target_user_id": ..., "before": ..., "after": ...}`, so the audit page filter "user_id = X" returns admin-mutations performed by X, while the user-detail audit panel can filter by `metadata.target_user_id = subject.id`. The `user_detail.html.j2:166`–`183` panel implies it shows audit rows for the subject user (via `audit_rows` context var) — but if rows are joined on `user_id == subject.id`, mutations that the admin performed will be invisible there because `user_id` will be the admin's id. Resolve this design ambiguity before writing the handlers.

---

## 2. Page-by-page

### 2.1 `/admin` — overview

Template: `src/vittring/api/templates/admin/overview.html.j2`.

Required context: `user`, `admin_initials`, `stats` (≈14 numeric fields), `recent_users` (list with `id, email, plan, is_verified, created_at`), `recent_audit` (list with `created_at, user_email, user_id, action`).

| Item | Finding |
|---|---|
| 1. Access gating | Must depend on `CurrentSuperuser`. Handler missing — verify when written. |
| 2. Confirmation for dangerous actions | None on this page; no destructive actions. OK. |
| 3. CSRF | Read-only. Logout form in sidebar (`_layout.html.j2:363`) does call `{{ csrf_input() }}`. OK. |
| 4. Audit logging | Page is read-only; no audit needed. OK. |
| 5. Pagination + search | None — `recent_users` and `recent_audit` are intended as fixed-size previews. Handler must `LIMIT 10` (or similar), explicitly. **No unbounded query risk so long as the handler uses LIMIT.** |
| 6. Data exposure | No `password_hash` / `totp_secret` rendered. OK. |
| 7. Action button correctness | None. |
| 8. System triggers | None. |
| 9. Visual consistency | All amber-accented stat cards, eyebrows, hover states. OK. |
| 10. Empty states | `{% if recent_users %}` / `{% else %}` "Inga användare ännu." Same for audit. **Stat cards do not handle a fresh DB** — they will render `0` and percentages may divide by zero. Especially `stats.users_verified_pct` — handler must guard against `users_total == 0`. |

Notes:

- The "Misslyckade login 24h" stat (line 73) recolours red when > 0 — good signal for operator dashboard.
- Consider an explicit "fresh install" hero that nudges Karim to create the first user when `users_total == 0`, since the user-create flow is otherwise discoverable only via Användare.

### 2.2 `/admin/users` — list

Template: `src/vittring/api/templates/admin/users.html.j2`.

Context: `users`, `total_label`, `q`, `plan`, `page_num`, `page_size`, `prev_url`, `next_url`. Each user row needs `id, email, full_name, plan, is_verified, is_active, is_superuser, locked_until, deletion_requested_at, created_at, last_login_at, signal_count`.

| Item | Finding |
|---|---|
| 1. Access gating | Must depend on `CurrentSuperuser`. |
| 2. Confirmation | No destructive actions on the list. OK. |
| 3. CSRF | Filter form is GET — no CSRF. The "+ Skapa användare" button is a link (not a form). OK. |
| 4. Audit logging | Read; no audit. |
| 5. Pagination + search | Uses `page_num` / `page_size` / prev/next. **Risk:** `signal_count` per row implies an N+1 query unless the handler joins `subscriptions` with `count(*) GROUP BY user_id` — otherwise 50 rows = 50 round-trips. Handler must use a single CTE / subquery. The plain text-search `q` should be parameterised + indexed; `users.email` is `CITEXT` with a unique constraint (B-tree) which allows `email LIKE 'q%'` to be index-driven. Avoid `email ILIKE '%q%'` without trigram support — at 10k users it falls back to seq-scan. |
| 6. Data exposure | Profile columns only. OK. |
| 7. Action correctness | None on list. |
| 8. System triggers | None. |
| 9. Visual consistency | Uses amber pills, signal/danger badges sparingly. OK. |
| 10. Empty states | `{% else %}` "Inga användare matchar filtret." Distinct copy for filter-empty vs. plain-empty would help, but acceptable. |

Other:

- No bulk-action selectboxes (e.g. "promote 5 users to verified at once"). See §3 for missing-feature list.
- No CSV export of the filtered list — likely needed for support cases.

### 2.3 `/admin/users/new`

Template: `src/vittring/api/templates/admin/user_new.html.j2`.

Context on POST error: `error`, `form` (echoed back).

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. |
| 2. Confirmation | "Skapa användare" — non-destructive; no confirm needed. The `is_superuser` checkbox has no extra confirm — **promoting via signup form bypasses any "double-confirm" UX**. Consider warning text or disabling-by-default. |
| 3. CSRF | `{{ csrf_input() }}` present (line 16). OK. |
| 4. Audit logging | Handler must emit `ADMIN_USER_CREATE` with `metadata={"target_user_id": new.id, "email": ..., "plan": ..., "is_superuser": ..., "is_verified": ..., "actor_user_id": admin.id}`. If `is_superuser=True`, also emit `ADMIN_USER_PROMOTE`. |
| 5. Pagination/search | N/A. |
| 6. Data exposure | Plain password input (line 45). Admin types it → goes over HTTPS → bcrypt-hashed in handler. Don't echo password back into `form`. |
| 7. Action correctness | The Skapa flow does not include a "send welcome email" toggle — the page subtitle says "användaren får inte automatiskt ett välkomstmail." That's a deliberate choice; document it in the handler. |
| 8. System triggers | None. |
| 9. Visual consistency | Amber primary button. OK. |
| 10. Empty states | N/A. |

Other:

- Password complexity rules (`min 12 chars`, haveibeenpwned check per CLAUDE.md §13) must be enforced server-side; the form only sets `minlength="12"` client-side (trivially bypassable).
- `is_verified` defaults checked (line 49). Reasonable for admin-created users; document why (admin vouches for them).

### 2.4 `/admin/users/{id}` — detail

Template: `src/vittring/api/templates/admin/user_detail.html.j2`.

Context: `subject`, `flash`, `flash_kind`, `subscriptions`, `audit_rows`, `delivered`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. |
| 2. Confirmation | "Schemalägg radering" → `onsubmit="return confirm(...)"` (line 114). "Hård-radera nu" → confirm (line 120). **Missing: "Ge premium" / "Lås upp" / "Skicka verifieringslänk" / "Ångra radering" / `Spara` (edit form including `is_superuser` flip) have no confirm.** Promotion to superuser via the edit form is irreversible-ish and should require an extra modal or a separate "Promote to superuser" form with its own confirm and an `ADMIN_USER_PROMOTE` audit. |
| 3. CSRF | Every form (`/edit`, `/promote`, `/unlock`, `/resend-verify`, `/cancel-delete`, `/schedule-delete`, `/hard-delete`, `subscription/toggle`) renders `{{ csrf_input() }}`. OK. |
| 4. Audit logging | Handler must distinguish: edit → `ADMIN_USER_EDIT` (with diff in metadata); promote-button → `ADMIN_USER_PROMOTE`; unlock → `ADMIN_USER_UNLOCK`; resend-verify → `ADMIN_USER_VERIFICATION_RESEND`; schedule-delete → `ADMIN_USER_DELETE_REQUEST`; cancel-delete → `ADMIN_USER_DELETE_CANCEL`; hard-delete → `ADMIN_USER_DELETE`; subscription toggle → `ADMIN_SUBSCRIPTION_TOGGLE`. **All audit constants exist** in `audit/log.py:40`–`52` so the vocabulary is ready. The edit form does not separately expose a `plan` change; if plan changes via edit, also emit `ADMIN_PLAN_CHANGE` (constant exists at line 48). |
| 5. Pagination/search | The detail page renders **all** subscriptions, audit rows for the subject, and delivered alerts inline. For a power user with thousands of delivered alerts, this becomes unbounded. Handler must `LIMIT N` (e.g. last 50) and link "Visa alla →" out to a subject-scoped audit/email view. The audit table on this page is "Senaste aktivitet" — implies a limit; the delivered table is "Senaste leveranser" — same. Confirm both have explicit `ORDER BY ... DESC LIMIT 50`. |
| 6. Data exposure | Profile table (lines 23–40) renders id, email, name, company, plan, trial, verified, active, superuser, 2fa enable date, failed_login_count, locked_until, created, last_login_at, last_login_ip, deletion_requested_at. **Does not render `password_hash` or `totp_secret`. OK.** It does render `last_login_ip` (PII / PD) — required for incident triage; document in `docs/gdpr.md`. |
| 7. Action correctness | "Lås upp konto" — the form posts to `/admin/users/{id}/unlock` with no payload; the handler must clear *both* `failed_login_count = 0` AND `locked_until = NULL`. Verify the handler does both (template gives no proof). "Ge premium (Pro + verifiera)" — handler must set `plan='pro'` AND `is_verified=true`; both must be in a single transaction so a partial promotion is impossible. The button label is correct in Swedish. |
| 8. System triggers | None. |
| 9. Visual consistency | Quick-actions row mixes `btn signal` (premium), `btn` (unlock, resend, cancel), `btn danger` (delete buttons). Signal-coloured "premium" stands out — see §1.3. |
| 10. Empty states | "Användaren har inga prenumerationer.", "Ingen aktivitet registrerad.", "Inga e-postleveranser ännu." All in place. |

Specific issues:

- `trial_ends_at` and `locked_until` are free-text inputs (`type="text"` with placeholder `2026-05-19T12:00`). Use `type="datetime-local"` (already styled in `_layout.html.j2:210`) — server still must parse to UTC. Free text is fragile.
- Edit form silently lets the admin clear `is_active`, freezing the user out. Acceptable for support cases, but the audit must capture this transition.
- Edit form does not gate the "is_superuser" checkbox by checking that the admin isn't demoting the last superuser. Handler must enforce `count(is_superuser) > 1` before allowing demotion of self.

### 2.5 `/admin/subscriptions`

Template: `src/vittring/api/templates/admin/subscriptions.html.j2`.

Context: `subscriptions`, `signal_type`, `page_num`, `prev_url`, `next_url`. Each row: `id, name, user_id, user_email, signal_types, criteria, active, created_at`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. |
| 2. Confirmation | "Pausa / Aktivera" toggle — non-destructive. OK. |
| 3. CSRF | `{{ csrf_input() }}` per toggle form (line 64). OK. |
| 4. Audit logging | Handler must emit `ADMIN_SUBSCRIPTION_TOGGLE` with `metadata={"target_user_id": s.user_id, "subscription_id": s.id, "from": active, "to": new_active}`. |
| 5. Pagination + search | `page_num` / prev/next. Filter is signal-type only — **no free-text search by user email or subscription name**. With 10k users × ~3 subscriptions each = 30k rows, scrolling is unusable. Add `q=` filter on `subscriptions.name` + join on `user_email`. Handler must `LIMIT/OFFSET` and avoid loading `criteria` JSONB column repeatedly into memory; consider lazy `<details>` expansion (already done client-side at line 55). |
| 6. Data exposure | `criteria` JSONB rendered raw in `<details>`. Criteria can include orgnrs, keywords — not sensitive PD, but consider redacting if the criteria ever stores phone/email-like patterns (defensive). |
| 7. Action correctness | Toggle reverses `active`. Verify handler: must set `active = NOT active` and not pre-stomp other subscription fields. |
| 8. System triggers | None. |
| 9. Visual consistency | Uses signal/amber badges keyed off signal_type — same caveat as §1.3. |
| 10. Empty states | "Inga prenumerationer matchar filtret." OK. |

Missing:

- No bulk pause/resume.
- No "delete subscription" admin path — can only toggle. May be intentional (delete should be user-side only); confirm.

### 2.6 `/admin/signals`

Template: `src/vittring/api/templates/admin/signals.html.j2`.

Context: `tab` ∈ {jobs, changes, procurements}, `q`, `rows`, `counts_24h`, `page_num`, `prev_url`, `next_url`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. |
| 2. Confirmation | Read-only. |
| 3. CSRF | Read-only (no forms beyond the GET filter). OK. |
| 4. Audit logging | Browsing signals is not a sensitive action; no audit needed. |
| 5. Pagination + search | `q` is free text on jobs/headlines, company names, procurement titles. Each table can hit hundreds of thousands of rows over time — the existing schema (`idx_jobs_published`, `idx_jobs_municipality`, `idx_proc_cpv`) supports temporal/CPV filters but **not** free-text search. Handler must use `to_tsvector` or a trigram index, otherwise `ILIKE %q%` will table-scan. Indexes for full-text search are not in the migrations either; this is a future enhancement. Pagination `OFFSET` page-num at large page numbers will degrade quadratically — switch to keyset pagination once tables grow past ~100k rows. |
| 6. Data exposure | Bolagsverket "changes" tab renders `old_value` / `new_value` JSON — these may contain officer names (PD). The `personal_data_purged_at` column is checked at line 72: if set, "rensad" is shown instead of the diff. Verify the handler **filters out** rows where `personal_data_purged_at IS NOT NULL` from the diff render — currently the template only hides if both `old_value` and `new_value` are falsy, but the GDPR scrubber nulls both, so this works in practice. Defensively: belt-and-braces — handler should `COALESCE` both to NULL when purged. |
| 7. Action correctness | None. |
| 8. System triggers | None. |
| 9. Visual consistency | Tabs use amber active state, badges signal/amber. OK. |
| 10. Empty states | "Inga signaler matchar." OK. |

### 2.7 `/admin/audit`

Template: `src/vittring/api/templates/admin/audit.html.j2`.

Context: `rows`, `available_actions`, `filter_action`, `filter_user_id`, page nav. Each row: `created_at, user_id, user_email, action, ip, audit_metadata`.

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. |
| 2. Confirmation | Read-only. |
| 3. CSRF | Filter form is GET. OK. |
| 4. Audit logging | Read; no audit. |
| 5. Pagination + search | `idx_audit_user_created` and `idx_audit_action_created` exist (`models/audit.py:50`–`53`), so filtering on either column is index-friendly. Pure pagination over the unfiltered audit log can grow large; with 24-month retention and a busy product, expect millions of rows. Use keyset pagination via `WHERE created_at < :cursor LIMIT 50`. **Avoid `OFFSET` past page 100.** |
| 6. Data exposure | Renders `ip` and `audit_metadata` raw. If the handler stores PII (target email, password reset links, etc.) into metadata, it leaks here. Ensure the audit-writer (and `auth.py` callers) never embed token values, only token IDs. |
| 7. Action correctness | None. |
| 8. System triggers | None. |
| 9. Visual consistency | Amber filter buttons; mono table. OK. |
| 10. Empty states | "Inga händelser matchar filtret." OK. |

Missing:

- No date-range filter (`from`, `to`). For incident response on a specific day, the operator must page back manually.
- No "actor vs. target" distinction. As noted in §1.4, `user_id` may be either the actor or target; without a metadata-aware filter, the audit page can mix them. Add a `filter_target_user_id` that queries `audit_metadata->>'target_user_id'` (with a JSONB GIN index).

### 2.8 `/admin/system`

Template: `src/vittring/api/templates/admin/system.html.j2`.

Context: `app_version`, `python_version`, `flash`, `flash_kind`, `jobs` (list with `name, label, schedule, last_run`), `db_counts` (dict), `resend` (object with `domain, status, detail`).

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. |
| 2. Confirmation | Each manual trigger is wrapped in `onsubmit="return confirm('Trigga {{ j.label }} nu?');"` (line 36). OK — single confirm matches §22's expectations. |
| 3. CSRF | `{{ csrf_input() }}` per trigger form. OK. |
| 4. Audit logging | Handler must emit `ADMIN_TRIGGER_INGEST` (or `ADMIN_TRIGGER_DIGEST`, `ADMIN_TRIGGER_GDPR_SCRUB`). Constants exist (`audit/log.py:50`–`52`). Metadata should include `{"job_name": j.name, "actor_user_id": admin.id, "duration_ms": ...}`. |
| 5. Pagination/search | None. `db_counts` is a fixed dict. OK. |
| 6. Data exposure | App version, Python version are leaked to the admin (they're already an admin). OK. |
| 7. Action correctness | "Trigga" forms submit to `/admin/system/trigger/{name}`. The handler must map `j.name` (e.g. `ingest_jobtech`, `daily_digest`, `scrub_personal_data`, `purge_deleted_users`) onto the awaitables in `jobs/scheduler.py` (`_run_jobtech`, `run_daily_digest`, `scrub_personal_data`, `purge_deleted_users`). The scheduler's `add_job(...)` ids match exactly: `ingest_jobtech, ingest_bolagsverket, ingest_ted, daily_digest, scrub_personal_data, purge_deleted_users` (`scheduler.py:53,61,69,77,85,93`). Make sure the handler whitelists these names — never trust the path parameter blindly. |
| 8. System triggers — backgrounded? | The template's confirm + form-POST suggests a synchronous request. The handler **must not** `await _run_jobtech()` inline — JobTech and Bolagsverket runs can take minutes; the request will exceed gunicorn timeout. Use `asyncio.create_task(...)` (or, better, push a one-shot job onto the running APScheduler in the *scheduler* process via a queue — but the API process doesn't share APScheduler with the scheduler service per `scheduler.py:1`–`6`). Pragmatic fix: launch as `asyncio.create_task` and immediately redirect with a flash; surface success/failure later via the audit row + Sentry. Without backgrounding, manual triggers will silently 504. |
| 9. Visual consistency | Amber primary "Trigga" button, signal/amber/danger badges for Resend status. OK. |
| 10. Empty states | `j.last_run` shows "Inga data ännu" if null — handles fresh installs. `db_counts` will iterate over its keys; if the dict is empty, the grid renders nothing. Handler must always populate at least the canonical keys so the grid isn't blank. |

Resend domain panel:

- Template handles `verified, pending, not_started, unreachable, *anything else`. The handler must call `delivery.domain_setup.ensure_domain_verified(wait=False)` carefully — that function **raises `DomainNotVerifiedError`** when not verified (`domain_setup.py:144`), so the handler must catch and translate to `status='pending'` rather than letting the page 500. The "unreachable" status must be set when the API call to Resend itself fails (network, 5xx).
- The `/verify` POST hits Resend on every page load (line 132 of `domain_setup.py`). On a verified domain that's wasteful but harmless; on a non-verified domain the page will print DNS records to stdout (line 141) every refresh. Move `_print_records` out of the read-only flow when called from the request handler.

### 2.9 `/admin/email`

Template: `src/vittring/api/templates/admin/email.html.j2`.

Context: `stats` (sent_7d, opened_7d, clicked_7d, distinct_users_7d, open_rate, click_rate), `rows` (last 50 delivered_alerts).

| Item | Finding |
|---|---|
| 1. Access gating | `CurrentSuperuser`. |
| 2. Confirmation | Read-only. |
| 3. CSRF | None needed. |
| 4. Audit logging | Read; no audit. |
| 5. Pagination + search | Hard-coded "Senaste 50 leveranser" — bounded. The percentage stats `open_rate` / `click_rate` need a guard against division by zero on a fresh DB; handler must default to 0. |
| 6. Data exposure | `resend_message_id` is internal to Resend, not PD. OK. |
| 7. Action correctness | None. |
| 8. System triggers | None. |
| 9. Visual consistency | Open dot is `--v-signal` green; click is `--v-amber`. See §1.3 — mixed semantics. |
| 10. Empty states | "Inga e-postleveranser ännu." OK. |

Missing:

- No bounce / complaint metrics. CLAUDE.md §11 mandates "Three hard bounces in 30 days → user marked is_active=false". Where does the operator see bounce counts and which users are at risk? Add a "Bounces 30d" stat and a "Risky recipients" table.

---

## 3. Missing pages and features

This panel covers users, subscriptions, signals, audit, system, email — but several admin needs are not addressed:

1. **Bulk user actions.** No multi-select on `/admin/users` for "verify N", "send verification email to all unverified", "downgrade trial expirees".
2. **CSV export.** Audit, users, subscriptions, delivered_alerts — none can be exported. Support cases routinely need this.
3. **IP block list.** UFW + fail2ban operate at OS level (CLAUDE.md §13), but the app has no per-IP allow/deny list (e.g. block a scraper without SSH). Add an `ip_blocks` table + admin page.
4. **Scheduler health view.** `/admin/system` shows `last_run` from audit but no live introspection of the *scheduler process* — is APScheduler currently up? Stuck job? Last successful poll? Ideally a `/admin/system` panel hitting a status-file or an internal endpoint exposed by `vittring-scheduler.service`.
5. **Resend domain status.** Present (`/admin/system`), but **no UI for re-running `ensure_domain_verified`**. If DNS changes, Karim has no admin path to re-verify; he must SSH and run a CLI. Add a "Verifiera om" button.
6. **Resend webhook health.** No view of the last webhook delivered, signature failures, or unknown event types. Add a panel.
7. **Stripe / billing.** Deferred per CLAUDE.md §7 but the panel has no placeholder for "billing events" or "Stripe webhook events" page. Stub it now so the navigation is stable.
8. **GDPR-action queue.** When a user clicks "Delete account", `users.deletion_requested_at` is set. There is currently no admin view of "users pending hard-delete" with the date the grace period ends. Add a tab on `/admin/users` filtered by `deletion_requested_at IS NOT NULL`.
9. **GDPR export viewer.** Karim will eventually need to satisfy access requests on someone else's behalf. Add a "Generate GDPR export" button on `/admin/users/{id}` that calls the same code as `/account/export` but tagged with `actor_user_id` in the audit.
10. **Subprocessor / DPA log.** No place to record "DPA signed with Resend on 2026-04-01". Could be a static page rather than DB-backed.
11. **Backup status.** No view of last successful `pg_dump`, last successful `rsync` to Storage Box, sizes, retention pruning state. Critical for runbook (`docs/runbook.md` will need this).
12. **Rate-limit dashboard.** No view of which IPs are getting 429'd, which emails are hitting login rate limits.
13. **Audit-of-admin filter.** As mentioned in §1.4, the audit page cannot filter by "actions performed BY this admin user_id" vs. "actions affecting THIS target user_id".
14. **Notice / kill-switch panel.** No way to put up a global maintenance banner or pause all outbound email.

---

## 4. Summary table of dangerous-action confirmations

| Action | URL | Single confirm? | Recommended |
|---|---|---|---|
| Edit user (incl. flip `is_superuser`) | POST `/admin/users/{id}/edit` | **No** | Add confirm when `is_superuser` changes; consider separate POST for promote/demote. |
| Promote to premium | POST `/admin/users/{id}/promote` | **No** | Single confirm OK. |
| Unlock account | POST `/admin/users/{id}/unlock` | No | Single confirm not strictly required but helpful. |
| Resend verification email | POST `/admin/users/{id}/resend-verify` | No | OK as-is. |
| Schedule deletion | POST `/admin/users/{id}/schedule-delete` | **Yes** (`onsubmit confirm`) | OK. |
| Cancel deletion | POST `/admin/users/{id}/cancel-delete` | No | OK. |
| Hard delete now | POST `/admin/users/{id}/hard-delete` | **Yes** | Strongly consider double-confirm: type-the-email-to-delete pattern. |
| Toggle subscription | POST `/admin/subscriptions/{id}/toggle` | No | OK. |
| Trigger ingest/digest/scrub | POST `/admin/system/trigger/{name}` | **Yes** | OK; backgrounding required (§2.8). |

---

## 5. Items to fix before shipping

P0 (blocker):

1. Create `src/vittring/api/admin.py` with the router and handlers — currently the entire app fails to import.
2. Background `/admin/system/trigger/*` so triggers don't block the request.
3. Decide audit `user_id` semantics (actor vs. target) and propagate to handler design (§1.4); without this, the user-detail audit panel will be unreliable.

P1 (security/UX):

4. Add "type the email to confirm" double-confirm on `Hård-radera nu`.
5. Gate `is_superuser` flips in `/edit` behind a separate POST + confirm + an "are you the last superuser?" check.
6. Convert `trial_ends_at` / `locked_until` to `<input type="datetime-local">`.
7. Show JSON detail (`detail` field on Resend response) only behind a "show details" toggle on `/admin/system` so the page doesn't leak Resend internal error messages on screenshots.
8. Add date-range and target-user-id filters to `/admin/audit`.

P2 (scale + completeness):

9. Replace `OFFSET`-pagination with keyset pagination on `/admin/users`, `/admin/audit`, `/admin/subscriptions`, `/admin/signals` once tables exceed ~10k rows.
10. Add free-text search on `/admin/subscriptions` and `/admin/signals`, with appropriate indexes (`pg_trgm` or full-text).
11. Add bulk-action UI on `/admin/users` and `/admin/subscriptions`.
12. Build the missing pages enumerated in §3.

---

## 6. Miscellaneous

- The eyebrow "Admin · X" copy is consistent across all pages — good.
- Swedish copy is direct and professional; no English loanwords noted.
- All forms use POST + `Form()`; no JS-driven mutations needed (good, no XHR-CSRF gymnastics).
- All admin templates inherit from the standalone `_layout.html.j2` (not the public layout). Confirmed: `extends "admin/_layout.html.j2"` on every page.
- The sidebar logout form is the only POST in the layout itself — verified to render `csrf_input()` (line 364).
- The "↩ Dashboard" link bounces to `/app`, which the operator can use to verify the public-side experience without logging out. Useful for QA.

End of audit.
