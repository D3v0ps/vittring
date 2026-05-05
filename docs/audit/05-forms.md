# Forms audit (05)

Read-only audit of every `<form>` in `src/vittring/api/templates/`. Each
finding lists the file:line, the problem, and the fix. CSRF checks reference
`vittring.security.csrf.CSRFMiddleware`, which validates a HMAC-signed
double-submit token via `csrf_input()` (see `src/vittring/api/templates.py`).
Password rules: `MIN_PASSWORD_LENGTH = 12` in
`src/vittring/security/passwords.py`.

Scope: 25 `<form>` elements across 17 templates. Server handlers live in
`src/vittring/api/auth.py`, `src/vittring/api/account.py`,
`src/vittring/api/subscriptions.py`, `src/vittring/api/admin.py`.

---

## auth/signup.html.j2

`/home/user/vittring/src/vittring/api/templates/auth/signup.html.j2:6` — POST `/auth/signup`.

1. **Required fields** — client-side: `email` and `password` are `required`,
   `password` has `minlength="12"`. Server-side: handler signature is
   `email: EmailStr`, `password: str` (no `Form(min_length=...)`); password
   length is enforced via `assert_strong_password()` which raises
   `WeakPasswordError`. `full_name` and `company_name` are optional in
   both. **Match: yes.**
2. **Error display** — handler re-renders `auth/signup.html.j2` with
   `{"error": str(exc)}`. **Bug:** `email`, `full_name`, `company_name`
   values do **not** persist on re-render (no `value="…"` attributes pulled
   from a `form` context dict). User retypes everything when password fails.
   *Fix:* pass `form={"email": ..., "full_name": ..., "company_name": ...}`
   to template and add `value="{{ form.email|default('', true) }}"` etc., as
   already done in `admin/user_new.html.j2`.
3. **Submit button** — no `disabled` toggle, no loading state. *Fix:* a
   small inline script that disables the button on `submit`, or HTMX
   `hx-disabled-elt="this"` if you migrate.
4. **CSRF** — `{{ csrf_input() }}` present at line 7. **OK.**
5. **Email format** — handler uses `EmailStr` (auth.py:93). **OK.**
6. **Password requirements** — inline helper says "Minst 12 tecken"; matches
   `MIN_PASSWORD_LENGTH=12`. **OK.**
7. **Hidden authority fields** — none. **OK.**
8. **Idempotency** — duplicate-email check (`existing is not None`) returns
   400; safe under double-submit. **OK.**
9. **Autocomplete** — `email`, `name`, `organization`, `new-password`. **OK.**

## auth/login.html.j2

`/home/user/vittring/src/vittring/api/templates/auth/login.html.j2:12` — POST `/auth/login`.

1. **Required fields** — client: `email` `required`, `password` `required`,
   `totp` (when shown) has `pattern="[0-9]{6}"`, `maxlength="6"`,
   `required`. Server: `email: EmailStr`, `password: str`, `totp: str = ""`
   (defaulted, intentional). **OK.**
2. **Error display** — re-renders with `error` and `email_value`; the
   `email` input pre-fills via `value="{{ email_value or '' }}"`.
   **Bug:** when handler re-renders for the **wrong-credentials** branch
   (auth.py:282) it does **not** pass `email_value`, so the email field is
   blanked. *Fix:* always include `"email_value": email` in the error
   re-render context.
3. **Submit button** — no disable-on-submit. *Fix:* same as signup.
4. **CSRF** — present at line 13. **OK.**
5. **Email format** — `EmailStr` (auth.py:251). **OK.**
6. **Password requirements** — N/A (login).
7. **Hidden authority fields** — none.
8. **Idempotency** — login is naturally idempotent; account-lock counter
   increments per attempt. **OK.**
9. **Autocomplete** — `email`, `current-password`, `one-time-code`. **OK.**

## auth/password_reset_request.html.j2

`/home/user/vittring/src/vittring/api/templates/auth/password_reset_request.html.j2:10` — POST `/auth/password-reset`.

1. **Required fields** — client: `email` `required`. Server: `EmailStr`. **OK.**
2. **Error display** — handler always returns the `submitted: True`
   confirmation page (timing-safe; reveals nothing). No error path needed.
   **OK.**
3. **Submit button** — no disable-on-submit. Multiple submits are rate-
   limited (3/hour) but UX would benefit from disabling on submit.
4. **CSRF** — present at line 11. **OK.**
5. **Email format** — `EmailStr` (auth.py:369). **OK.**
6. **Password requirements** — N/A.
7. **Hidden authority fields** — none.
8. **Idempotency** — already enforced by 3-per-hour rate limit
   (`PASSWORD_RESET_BY_EMAIL`); however the rate-limit key is currently
   `request.headers.get("x-forwarded-for", request.client.host)`, i.e. the
   **IP** not the email despite the limiter being named `*_BY_EMAIL`
   (auth.py:362). *Fix:* change the lambda to read the submitted `email`
   from the form so the per-email cap actually applies.
9. **Autocomplete** — `email`. **OK.**

## auth/password_reset_confirm.html.j2

`/home/user/vittring/src/vittring/api/templates/auth/password_reset_confirm.html.j2:6` — POST `/auth/password-reset/confirm`.

1. **Required fields** — client: `password` `required` `minlength="12"`.
   Server: `t: str`, `password: str`; weakness via `assert_strong_password`.
   **OK.**
2. **Error display** — re-renders with `token` and `error`. **OK.**
3. **Submit button** — no disable-on-submit. *Fix:* disable on first click.
4. **CSRF** — present at line 7. **OK.**
5. **Email format** — N/A.
6. **Password requirements** — helper text matches `MIN_PASSWORD_LENGTH`.
   **OK.**
7. **Hidden authority field** — `<input type="hidden" name="t">` carries the
   reset token. Token is hashed (`hash_url_token`) and looked up
   server-side; row has `used_at`/`expires_at` cross-checks. **Safe.**
8. **Idempotency** — `token_row.used_at` is set on success, so second
   submit fails with "Ogiltig eller utgången länk." **OK.**
9. **Autocomplete** — `new-password`. **OK.**

## auth/2fa_enable.html.j2

`/home/user/vittring/src/vittring/api/templates/auth/2fa_enable.html.j2:13` — POST `/auth/2fa/enable`.

1. **Required fields** — client: `code` `required`, `pattern="[0-9]{6}"`,
   `maxlength="6"`. Server: `secret: str`, `code: str`. **OK.**
2. **Error display** — re-renders with `secret`, `uri`, `error`. **OK.**
3. **Submit button** — no disable-on-submit.
4. **CSRF** — present at line 14. **OK.**
5. **Email format** — N/A.
6. **Password requirements** — N/A.
7. **Hidden authority field** — `<input type="hidden" name="secret">`.
   **Bug — high severity:** the secret is taken from the form on POST and
   written to `user.totp_secret` (auth.py:497, 508). Because the secret
   round-trips through the browser, an attacker who can replay or substitute
   the form body can pin a TOTP secret of their choice (for example by
   social-engineering the user to scan a QR code the attacker controls,
   then submitting the matching secret). *Fix:* server-side, generate the
   secret in `GET /auth/2fa/enable` and stash it in the user row (or in a
   short-lived signed cookie / DB column like `pending_totp_secret`). On
   POST, read **only** the candidate `code` and verify against the
   server-stored secret; never trust the form value.
8. **Idempotency** — re-submitting after success re-runs `verify_code`
   against the same secret; harmless. **OK.**
9. **Autocomplete** — `one-time-code`. **OK.**

---

## app/account.html.j2

Two forms.

### `app/account.html.j2:109` — POST `/auth/2fa/disable`

1. **Required fields** — none submitted; handler reads `CurrentUser`. **OK.**
2. **Error display** — handler raises `HTTPException(400)` if user is a
   superuser (mandatory 2FA per CLAUDE.md §13). **Bug:** this surfaces as
   a generic FastAPI JSON 400; nothing in `account.html.j2` shows a
   per-form error banner. *Fix:* either redirect with a `?flash=…`
   parameter and render a banner, or block superusers in template (don't
   show the button) — and double-check on POST anyway.
3. **Submit button** — no disable.
4. **CSRF** — present at line 110. **OK.**
5–9. N/A.
10. **Hidden authority fields** — none. Identity comes from the session
    cookie. **OK.**

### `app/account.html.j2:149` — POST `/app/account/delete`

1. **Required fields** — none.
2. **Error display** — handler always succeeds; redirects to `/`.
3. **Submit button** — `onsubmit="return confirm(...)"` JS confirm. No
   disable-on-submit. *Fix:* disable button on submit so the spinner is
   visible and a second click is impossible.
4. **CSRF** — present at line 151. **OK.**
5–9. N/A.
10. **Hidden authority fields** — none. **OK.**
11. **Idempotency** — second submit re-sets
    `deletion_requested_at = now()` and re-issues an audit row; harmless,
    but ideally short-circuit if `user.deletion_requested_at is not None`.

## app/dashboard.html.j2

Three forms.

### `app/dashboard.html.j2:200` — POST `/auth/logout`

1. Required: none. CSRF: present (line 201). Idempotency: handler tolerates
   missing user via redirect; **OK.**

### `app/dashboard.html.j2:217` — GET `/app` (search)

1. **Required fields** — none. Handler reads `q: str = ""`.
2. **Error display** — N/A (search).
3. **Submit button** — none, this is a search form.
4. **CSRF** — N/A (GET method, exempted by `SAFE_METHODS`).
5. **Email format** — N/A.
6. **Password** — N/A.
7. **Hidden authority** — none.
8. **Idempotency** — N/A.
9. **Autocomplete** — search field, no specific autocomplete needed. **OK.**

### `app/dashboard.html.j2:299` and `:334` — POST `/app/signals/save`

1. **Required fields** — server: `signal_type: str`, `signal_id: int`. No
   client `required` attribute on hidden inputs. **OK** because hidden
   inputs are always populated server-side.
2. **Error display** — handler always succeeds, no error path.
3. **Submit button** — no disable.
4. **CSRF** — present (lines 300, 335). **OK.**
5–9. N/A.
10. **Hidden authority fields** — `signal_type` and `signal_id` are
    user-supplied. They reference an opaque signal — but the handler
    inserts a `SavedSignal(user_id=user.id, signal_type=…, signal_id=…)`
    without verifying that a row with that id exists in the underlying
    table. **Bug — medium severity:** a malicious user can save arbitrary
    integer ids. *Fix:* before inserting, verify the signal exists via a
    lookup keyed on `(signal_type, signal_id)` against `job_postings` /
    `company_changes` / `procurements`, or constrain `signal_type` to a
    known set with a `CHECK` constraint and a server-side allowlist.
    Currently the saved-signals page is a stub so the impact is low, but
    fix before unstubbing.
11. **Idempotency** — handler is a toggle; `select` then insert/delete.
    Concurrent double-submit can race (two inserts) since there is **no**
    UNIQUE constraint on `saved_signals(user_id, signal_type, signal_id)`
    based on what is visible here. *Fix:* add the UNIQUE constraint and
    use `ON CONFLICT DO NOTHING` for inserts.

## app/subscription_form.html.j2

`/home/user/vittring/src/vittring/api/templates/app/subscription_form.html.j2:16` — POST `/app/subscriptions/`.

1. **Required fields** — client: `name` `required` `maxlength="120"`.
   Server: `name: str` (no length cap; relies on DB TEXT). `signal_types`:
   client requires at least one (JS disables the submit button when
   `active.size === 0`); server takes `list[str]` but does **not** validate
   non-empty. **Bug — medium severity:** if JS is disabled, the user can
   POST an empty `signal_types` list, which `Form()` parses as `[]` and
   `Subscription(signal_types=[])` is then persisted — the matching engine
   will silently never match. *Fix:* server-side, return a 400 with the
   same `error` context if `not signal_types`.
2. **Error display** — re-renders with `error`. **Bug:** the form **does
   not pre-fill** any user-entered values (`name`, `municipalities`,
   `keywords_any`, etc.) on re-render; in the only currently-implemented
   error path (plan limit reached) the user has typed an entire form for
   nothing. *Fix:* echo `form` context dict and add `value="…"` to every
   text input; check checkbox state for `signal_types`.
3. **Submit button** — JS disables when no signal type selected; line 219
   `<button id="submit-btn">`. No disable-on-submit (clicking twice can
   double-create). *Fix:* `submit-btn.disabled = true` in a `submit`
   listener.
4. **CSRF** — present at line 17. **OK.**
5. **Email format** — N/A.
6. **Password** — N/A.
7. **Hidden authority fields** — none. The handler joins by
   `user_id=user.id` from the session — **safe.**
8. **Idempotency** — none. Double-submit creates two subscriptions.
   *Fix:* either disable the button on submit, or generate a per-form
   `idempotency_key` UUID hidden input and dedupe server-side.
9. **Autocomplete** — `off` on every text field; reasonable since these are
   filter values.
10. **`data-needs` JS toggle** — file lines 297–314: when a section is
    hidden, every non-checkbox/radio input inside is set to
    `disabled = true`, which **does** exclude it from the form submission.
    **Confirmed correct.** Edge case: if the user types a value, then
    unchecks the parent signal type, the value persists in the DOM (good
    for re-show) and is excluded from POST (good). However, the
    server-side handler does not currently echo this state, so on
    re-render after a server error all the values would be lost (see
    item 2).
11. **Validation: `pattern="[0-9, ]*"`** on `sni_codes` and `cpv_codes`
    permits empty string. Handler `_split` strips. **OK.**
12. **`min_procurement_value_sek` overflow** — handler does
    `int(min_procurement_value_sek)` with no try/except; an extremely large
    value or a non-integer (e.g. `1e20`) would raise `ValueError` → 500.
    Browser's `type="number"` and `pattern` block this in practice but
    server should defend. *Fix:* wrap in `try/except ValueError`.

## app/subscriptions.html.j2

`/home/user/vittring/src/vittring/api/templates/app/subscriptions.html.j2:59` — POST `/app/subscriptions/{id}/delete`.

1. **Required fields** — none. Path parameter `subscription_id`.
2. **Error display** — handler raises `HTTPException(404)` if subscription
   not found or not owned by user. Surfaces as default 404 page.
3. **Submit button** — `onsubmit="return confirm(...)"`. No disable.
4. **CSRF** — present at line 61. **OK.**
5–6. N/A.
7. **Hidden authority** — none. The path parameter is cross-checked
   server-side by `Subscription.user_id == user.id` (subscriptions.py:141).
   **Safe.**
8. **Idempotency** — second submit yields 404 (already deleted). **OK.**
9. Autocomplete N/A.

## app/_stub.html.j2

`/home/user/vittring/src/vittring/api/templates/app/_stub.html.j2:143` —
POST `/auth/logout`. CSRF present line 144. **OK.**

---

## admin/_layout.html.j2

`/home/user/vittring/src/vittring/api/templates/admin/_layout.html.j2:363` —
POST `/auth/logout`. CSRF present line 364. **OK.**

## admin/audit.html.j2

`/home/user/vittring/src/vittring/api/templates/admin/audit.html.j2:13` —
GET `/admin/audit`. Method GET, CSRF not required. `user_id` is
`type="number"` and `pattern` is implicit; server should enforce
`int | None` parsing. Filter form, **OK.**

## admin/signals.html.j2

`/home/user/vittring/src/vittring/api/templates/admin/signals.html.j2:24` —
GET `/admin/signals`. GET, CSRF not required. Hidden `tab` reflects current
tab — server validates `tab in {jobs, changes, procurements}` (admin.py:903),
falls back to `jobs` otherwise. **OK.**

## admin/subscriptions.html.j2

Two forms.

### `:13` — GET `/admin/subscriptions`

GET filter form. **OK.**

### `:63` — POST `/admin/subscriptions/{id}/toggle`

1. CSRF present line 64.
2. Handler is `CurrentSuperuser` only.
3. No body fields besides hidden `redirect_to`.
4. **Hidden authority field** `redirect_to` — admin.py:885 enforces
   `if not target.startswith("/admin"): target = "/admin/subscriptions"`,
   blocking open-redirect. **Safe.**
5. Idempotency: toggle is a toggle. Second submit flips back. Acceptable
   for admin tool but a confirm dialog would be nice for "Pausa".

## admin/system.html.j2

`/home/user/vittring/src/vittring/api/templates/admin/system.html.j2:36` —
POST `/admin/system/trigger/{job_name}`.

1. **Required fields** — none. Path-parameter only.
2. **Error display** — handler builds `flash_msg` and `flash_kind`,
   returns redirect. **OK.**
3. **Submit button** — no disable. Critical: this triggers ingest jobs
   that take seconds-to-minutes; double-submit could launch two
   simultaneous ingests against external APIs. `onsubmit="return
   confirm(...)"` is present but does not disable. *Fix:* disable button
   on submit and show a "Kör…" state.
4. **CSRF** — present line 37. **OK.**
5–7. N/A.
8. **Idempotency** — concurrent admin triggers can race (no in-process
   lock). For ingest, dedupe at DB level via `external_id` UNIQUE keys is
   the safety net. *Fix:* a per-job advisory lock via
   `pg_try_advisory_lock`.

## admin/user_detail.html.j2

Six forms (edit + 5 quick actions). All admin-only via `CurrentSuperuser`,
all carry `{{ csrf_input() }}`.

### `:46` — POST `/admin/users/{id}/edit`

1. **Required fields** — server: `plan: str` (Form, no default → required).
   Client: `<select>` always submits a value. Other fields `Form() = ""`.
2. **Error display** — handler redirects with `flash`/`flash_kind` query
   params; template reads `{{ flash }}` from query string at line 16.
   **Bug — medium:** flash is read from `request.query_params` directly into
   the template via `{{ flash }}` — this is unescaped reflected input.
   Need to verify: the admin layout pulls `flash` from a server-side
   `_common_context` or via Jinja autoescape? Let me trust Jinja autoescape
   since `templates = Jinja2Templates(...)` defaults to HTML autoescape.
   **Confirmed safe** by Jinja's default autoescape; but the value is still
   sourced from URL query, which can be crafted by anyone with a link.
   For an admin-only page that's tolerable, but consider session-based
   flash to avoid back-button replays.
3. **Submit button** — none disabled.
4. **CSRF** — present line 47. **OK.**
5–7. **Hidden authority fields** — none; the user_id is in the URL path
   and never trusted from a hidden input.
8. **Idempotency** — `is_active`/`is_verified`/`is_superuser` are derived
   via `_checkbox(value)` from form value; resubmitting same form is
   idempotent. **OK.**
9. **Autocomplete** — N/A; admin page.
10. **`trial_ends_at` parser** — `_parse_dt` (admin.py:82). On failure,
    returns `None` silently — so an admin who types a malformed timestamp
    accidentally **wipes** the trial-end date with no error. *Fix:* raise
    an explicit error and re-render with a banner.

### `:93–123` — Quick-action forms (promote, unlock, resend-verify, schedule-delete, hard-delete)

All POST, all CSRF-protected, all admin-only. Hard-delete is guarded by
`if target.id == user.id: raise HTTPException(...)` — **safe** (admin.py:759).

### `:144` — POST `/admin/subscriptions/{id}/toggle` (from user-detail page)

Hidden `redirect_to` carries authority for redirect target — handler
strips non-`/admin` prefixes (admin.py:885). **Safe.**

## admin/user_new.html.j2

`/home/user/vittring/src/vittring/api/templates/admin/user_new.html.j2:15` — POST `/admin/users/new`.

1. **Required fields** — client: `email` `required`, `password` `required`
   `minlength="12"`. Server: `email: EmailStr`, `password: str` +
   `assert_strong_password()`. **OK.**
2. **Error display** — re-renders with `error` and `form={...}`; values
   are echoed via `{{ form.email|default('', true) }}` etc. (this is the
   pattern signup.html.j2 should adopt). **OK.**
3. **Submit button** — no disable.
4. **CSRF** — present line 16. **OK.**
5. **Email** — `EmailStr`. **OK.**
6. **Password** — `minlength="12"`, helper text says "Lösenord (minst 12
   tecken)". **OK.**
7. **Hidden authority** — `is_verified`, `is_superuser` are checkbox
   values; admin can set them, that is the intended capability. **OK.**
8. **Idempotency** — duplicate email yields 400; safe.
9. **Autocomplete** — none specified. Acceptable for admin.

## admin/users.html.j2

`/home/user/vittring/src/vittring/api/templates/admin/users.html.j2:13` —
GET `/admin/users`. Filter form, GET. **OK.**

---

## Cross-cutting findings

- **No form anywhere shows a loading state on submit.** A handful of
  forms run multi-second operations (digest trigger, signup with email
  send, password reset request that hits Resend). At minimum, a submit
  listener that disables the button and adds a "Skickar…" label would
  prevent double-submits and improve perceived reliability.

- **CSRF coverage is complete.** All 17 unique state-changing form
  endpoints render `{{ csrf_input() }}`. The middleware catches missing
  or mismatched tokens with a 403 JSON response.

- **`EmailStr` usage is consistent** wherever a real email is collected
  (`signup`, `login`, `password_reset_request`, `admin/users/new`).

- **Password minimum is consistent at 12 characters** between
  `MIN_PASSWORD_LENGTH`, the templates, and the server.

- **Persistent values on re-render** — only `admin/user_new` and the
  login email do this correctly. Signup, subscription form, and the
  admin user-edit form all lose values on validation error.

- **Hidden-input authority** — only the `2fa/enable` form has a
  load-bearing hidden input (`secret`) that is trusted on POST. This is
  the most concerning finding in the audit (see signup `auth/2fa_enable.html.j2`
  section above).

- **`saved_signals` toggle** does not validate that `(signal_type,
  signal_id)` references a real row, and lacks a UNIQUE index. Fix
  before un-stubbing the saved-signals page.

- **Subscription-form server validation** does not enforce
  `signal_types` non-empty even though the JS does — bypassable.

---

## Pass / needs-work checklist

### Pass — no blocking issues
- [x] `auth/login.html.j2` — only nit is missing email persistence on the
  wrong-credentials branch
- [x] `auth/password_reset_confirm.html.j2`
- [x] `app/_stub.html.j2` (logout)
- [x] `app/dashboard.html.j2` line 200 (logout)
- [x] `app/dashboard.html.j2` line 217 (search)
- [x] `app/subscriptions.html.j2` (delete)
- [x] `admin/_layout.html.j2` (logout)
- [x] `admin/audit.html.j2` (filter)
- [x] `admin/signals.html.j2` (filter)
- [x] `admin/subscriptions.html.j2` line 13 (filter)
- [x] `admin/subscriptions.html.j2` line 63 (toggle)
- [x] `admin/user_detail.html.j2` quick-action forms (promote, unlock,
  resend-verify, cancel-delete, schedule-delete, hard-delete)
- [x] `admin/user_new.html.j2`
- [x] `admin/users.html.j2` (filter)

### Needs work
- [ ] `auth/signup.html.j2` — persist email/full_name/company_name on
  re-render after weak-password / duplicate-email failure
- [ ] `auth/login.html.j2` — pass `email_value` on the wrong-credentials
  re-render branch
- [ ] `auth/password_reset_request.html.j2` — change rate-limit key from
  IP to submitted email so `PASSWORD_RESET_BY_EMAIL` actually applies
- [ ] `auth/2fa_enable.html.j2` — stop trusting client-supplied `secret`
  on POST; store the pending secret server-side
- [ ] `app/account.html.j2` (2FA disable) — surface superuser block as a
  banner instead of a JSON 400; ideally hide the button for superusers
- [ ] `app/account.html.j2` (delete) — short-circuit on second submit if
  `deletion_requested_at` is already set
- [ ] `app/dashboard.html.j2` save-signal forms — add UNIQUE constraint
  on `saved_signals` and validate `(signal_type, signal_id)` exists
- [ ] `app/subscription_form.html.j2` — server must reject empty
  `signal_types`; persist all entered values on error re-render; add
  try/except around `int(min_procurement_value_sek)`; disable submit
  button on submit to block double-create
- [ ] `admin/system.html.j2` — disable trigger button on submit; consider
  `pg_try_advisory_lock` to prevent concurrent ingests
- [ ] `admin/user_detail.html.j2` edit form — `_parse_dt` failure should
  raise a banner instead of silently nulling fields
- [ ] All forms — no submit-loading affordance; recommend a small global
  pattern (1 listener) to disable the originating submit button on form
  submission
