# Vittring — Security Audit (Read-Only)

Scope: read-only review of the Vittring application attack surface — middleware
stack, auth flows, admin panel, webhook receivers, ingest sinks, Jinja
templates, and the operator CLI. No code was modified.

Reviewed at commit `bec98c5`. Findings are grouped by severity. Each entry
gives a `file:line` anchor (lines are the line as of the reviewed commit), the
defect, and a concrete remediation.

---

## P0 — Critical (must fix before any production exposure)

### P0-1. Auth-bypassed unsubscribe — anyone can pause every user's subscriptions
- **Where:** `src/vittring/api/unsubscribe.py:17-36`
- **What:** `GET /unsubscribe?t={user_id}` accepts the integer user id as the
  "token" and runs `UPDATE subscriptions SET active=false WHERE user_id=t`.
  The function-level docstring acknowledges "uses the user id as the token for
  simplicity; upgrade to a signed token in v2 to prevent enumeration." That
  enumeration is trivial (`/unsubscribe?t=1`, `t=2`, …) and unauthenticated.
  Any visitor can disable every customer's email digest.
- **Fix:** Issue a signed, opaque token per user (e.g. `hmac(secret, user_id)`
  or a random `unsubscribe_token` column) and verify it. Also restrict the
  endpoint to scope a single subscription rather than mass-pausing the user's
  entire account, and require POST (not GET) to prevent prefetchers/email
  link scanners from accidentally triggering it.

### P0-2. Jinja2 autoescape is OFF for every page template (`*.html.j2`)
- **Where:** `src/vittring/api/templates.py:14` instantiates
  `Jinja2Templates(directory=...)`. FastAPI's wrapper hands Jinja a
  `select_autoescape()` with the **default extensions only** —
  `('html', 'htm', 'xml')`. The project's templates all use the `.html.j2`
  extension, which falls *outside* the autoescape set. Verified by:

      >>> templates.env.autoescape("foo.html.j2")
      False

  Confirmed end-to-end: rendering `auth/login.html.j2` with
  `error="<script>alert(1)</script>"` and `email_value="<script>…</script>"`
  emits the raw `<script>` tag.
- **What:** Every `{{ … }}` in every page template is unescaped by default.
  Reflected and stored XSS sinks include:
  - Login error / `email_value` (`auth/login.html.j2:11,16`).
  - Signup error message (`auth/signup.html.j2:5`).
  - 2FA secret + `uri` echoed back (`auth/2fa_enable.html.j2:9-10,15`).
  - Password-reset form reflected `token` from URL (`auth/password_reset_confirm.html.j2:8`).
  - User-supplied profile fields shown in chrome (`user.full_name`,
    `user.company_name`, `user.email`) on `app/dashboard.html.j2:196-197`,
    `app/account.html.j2:30,34`, `app/_stub.html.j2:139-140`,
    `admin/_layout.html.j2:357,379`, `admin/user_detail.html.j2:8,25-27`,
    `admin/users.html.j2:52-53`, `admin/email.html.j2:47`,
    `admin/audit.html.j2:41`, `admin/overview.html.j2:89,116`,
    `admin/subscriptions.html.j2:47,48`.
  - External-source data echoed in admin tables (`admin/signals.html.j2:44-95`):
    `r.headline`, `r.title`, `r.employer_name`, `r.buyer_name`, `r.source_url`
    flow from JobTech / TED / Bolagsverket / scraped PoIT — controlled by
    third parties.
  - Stored subscription names are interpolated into a JS context inside
    `onsubmit="return confirm('Radera prenumerationen {{ sub.name }}?');"`
    (`app/subscriptions.html.j2:60`) — even with autoescape on, single quotes
    are not encoded for JS contexts.
  - Same JS-context injection for admin user email at
    `admin/user_detail.html.j2:120` (`onsubmit="return confirm('… {{ subject.email }} …');"`).

  Mitigation by CSP (`script-src 'self' …`) blocks `<script>` tags but does
  **not** block event handlers on injected tags (e.g. `<img src=x onerror=…>`),
  so XSS is exploitable.
- **Fix:** Replace the templates instantiation with an explicit autoescape
  policy that includes `.j2`-suffixed templates, e.g.:

      Jinja2Templates(
          directory=str(TEMPLATE_DIR),
          autoescape=select_autoescape(
              enabled_extensions=("html", "htm", "xml", "html.j2", "xml.j2"),
              default_for_string=True,
          ),
      )

  Then audit the JS-context interpolations — e.g. replace
  `confirm('… {{ sub.name }}')` with a separate `data-name` attribute and
  `confirm('… ' + el.dataset.name)` (or `tojson` filter). Add an XSS unit
  test that asserts a `<script>` payload submitted via signup is escaped on
  every page that displays the user.

### P0-3. Resend webhook silently accepts unsigned requests when secret is unset
- **Where:** `src/vittring/api/webhooks.py:24-34`
- **What:** `_verify_signature` returns `None` when
  `settings.resend_webhook_secret is None`. Combined with the CSRF-exempt
  prefix `/api/webhooks/`, a misconfigured production server (forgot to fill
  `RESEND_WEBHOOK_SECRET`) lets anyone POST arbitrary `email.opened` /
  `email.clicked` events and corrupt `delivered_alerts` open/click metrics.
- **Fix:** When `settings.app_env == "production"` and the secret is missing,
  refuse with 503 ("webhook not configured"), and log a startup warning. Do
  not let unverified payloads reach the database in any environment that
  isn't local development.

### P0-4. CLI accepts plaintext password as positional argument
- **Where:** `src/vittring/cli/__main__.py:78-80` — `create-user EMAIL PASSWORD`.
- **What:** The password is visible in `ps`, in shell history, in `/proc`,
  and in any logs that capture argv (e.g. systemd journal if invoked from a
  unit). It is also documented in `__doc__`, which is printed on misuse.
- **Fix:** Read the password via `getpass.getpass()` (or `--password-stdin`),
  or generate a random one and print it to stderr only. Keep argv free of
  secrets.

---

## P1 — High (fix before broad release)

### P1-1. JWT cannot be revoked; password reset doesn't invalidate sessions
- **Where:** `src/vittring/security/tokens.py:19-29`,
  `src/vittring/api/auth.py:462-474`, `src/vittring/api/deps.py:17-31`.
- **What:** `decode_access_token` only checks the JWT signature/expiry. There
  is no `jti`, no per-user "tokens issued after" timestamp, no blacklist.
  After password reset (line 462) the previous JWT is still valid for up to
  15 minutes. CLAUDE.md §13 specifies "refresh tokens, rotation, revocation
  on logout" — none of that is implemented. Logout merely deletes the cookie.
- **Fix:** Add `users.tokens_valid_after` (timestamptz). Stamp it at signup,
  password change, password reset, 2FA enroll/disable, and admin force-
  logout. In `current_user_or_none`, reject tokens whose `iat <
  tokens_valid_after`. Optionally introduce a refresh-token table per spec.

### P1-2. CSRF middleware does not check Origin/Referer; SameSite=Lax cookie alone
- **Where:** `src/vittring/security/csrf.py:81-167`.
- **What:** The middleware uses double-submit only. SameSite=Lax cookies block
  most cross-site POSTs, but Lax permits top-level GET navigations and
  several embedding contexts; combined with a future CORS misconfig or a
  subdomain takeover (`*.karimkhalil.se`) the protection narrows. Defense in
  depth wants an Origin check.
- **Fix:** When the request method is unsafe, also require `Origin` (or
  `Referer`) to match the configured `app_base_url` host. Reject otherwise.

### P1-3. Rate-limiter and IP logging trust `X-Forwarded-For` blindly
- **Where:** `src/vittring/security/ratelimit.py:62-66`,
  `src/vittring/api/deps.py:71-79`, `src/vittring/api/auth.py:362`.
- **What:** `client_ip` returns the first comma-separated value without
  validating the proxy. An attacker can send `X-Forwarded-For: 1.2.3.4` to
  defeat IP-based rate limits (login, signup, password-reset).
  - Same value is persisted as `users.last_login_ip` (INET) and audit
    metadata, so the audit log records attacker-supplied IPs.
- **Fix:** Configure FastAPI/Uvicorn with `--forwarded-allow-ips=127.0.0.1`
  (Caddy is local) and rely on Starlette's trusted proxy parsing, or
  hard-code the trusted-proxy CIDR set in `client_ip`. Ignore the header
  unless the immediate peer is on the trusted list.

### P1-4. Password-reset rate limiter keys by IP, not email — enumeration risk
- **Where:** `src/vittring/api/auth.py:362`.
- **What:** The dependency closes over a key function that hashes by
  `x-forwarded-for / client.host`, but the limiter constant is named
  `PASSWORD_RESET_BY_EMAIL` (3/hour). The CLAUDE.md spec also calls for "3
  req/hour per email". Effectively, a single attacker rotating IPs (or
  spoofing X-Forwarded-For per P1-3) can enumerate which emails exist via
  reset request behavior plus timing.
  - Note: response body is the same template either way, but a timing
    side-channel (DB write + email send vs. no-op) leaks existence.
- **Fix:** Switch the key function to `lambda r: form-email lower-cased`
  (requires capturing the form earlier; or rate-limit inside the handler
  after form parsing). Optionally add a per-IP secondary limit. Equalize
  timing between "user exists" and "user does not" branches.

### P1-5. Login does not block deactivated (`is_active=False`) users
- **Where:** `src/vittring/api/auth.py:262-327`.
- **What:** The login flow happily issues a JWT to a user with
  `is_active=False` (e.g. a user who pressed "Radera kontot"). The JWT
  succeeds in `current_user_or_none` until the user hits a route that
  invokes `current_user`, which then 401s — but `current_user_or_none`
  returns the inactive user back to the layout (e.g. `OptionalUser` on
  `/auth/login` redirects to `/app`, only to bounce). It also lets the user
  trip the 2FA branch, etc.
- **Fix:** After credential check, also require `user.is_active is True`. If
  not, return the same generic "invalid credentials" message (do not leak
  status) and skip 2FA / cookie issuance.

### P1-6. TOTP brute force has no per-account lockout
- **Where:** `src/vittring/api/auth.py:300-311`,
  `src/vittring/security/totp.py:19-20`.
- **What:** `failed_login_count` is incremented only on password failure.
  When the password is correct but TOTP is wrong, the request just returns
  the form again; no counter, no lock. With IP rate limit at 10/min and
  `valid_window=1` (~3 codes accepted), a determined attacker who knows the
  password but not the TOTP can keep retrying indefinitely.
- **Fix:** Track `failed_2fa_count` (or reuse `failed_login_count`) and
  trigger the same 5-attempt → 15-minute lock. Audit-log every failed TOTP
  attempt.

### P1-7. Session is not rotated on auth state change
- **Where:** `src/vittring/api/auth.py:_set_session_cookie` is called only on
  login. On 2FA enable/disable and password reset there is no fresh cookie.
- **What:** Pre-login cookies (e.g. an unverified user's stale token) and
  post-2FA-enable tokens share lifetimes. If P1-1 is unfixed, a stolen
  token survives all subsequent security changes.
- **Fix:** Pair with P1-1: rotate the cookie after successful 2FA verify,
  password change/reset, and email verification.

### P1-8. Admin `redirect_to` validation is naive
- **Where:** `src/vittring/api/admin.py:884-886`.
- **What:** Allows any string `startswith("/admin")`. While modern browsers
  do not treat `/admin//evil.com` as cross-origin, a future change that
  trims the prefix or normalises differently is one regression away from an
  open redirect. Also, the route does not guard against header-injection
  payloads — Starlette filters CRLF, but this depends on framework behavior.
- **Fix:** Allowlist a small set of literal paths
  (`{"/admin/subscriptions", "/admin/users/{id}", …}`), or build the URL
  from the originating page (don't accept it from form input at all).

### P1-9. CSP allows `'unsafe-inline'` styles and `https://unpkg.com` scripts
- **Where:** `src/vittring/security/headers.py:15-26`.
- **What:** `style-src 'self' 'unsafe-inline'` enables every inline `<style>`
  block in the templates (and they are extensive). With XSS available
  (P0-2) this enables CSS-keylogger style attacks.
  `script-src 'self' https://js.stripe.com https://unpkg.com` whitelists the
  full `unpkg.com` host — any package hosted there is allowed to run.
- **Fix:** Replace inline `<style>` blocks with hashed/`nonce` strict CSP
  styles, or move CSS to `/static/`. Pin unpkg to an exact path or replace
  it with a self-hosted asset.

### P1-10. `assert_strong_password` does not implement HIBP top-1M check
- **Where:** `src/vittring/security/passwords.py:41-53`. CLAUDE.md §13 says
  "not in haveibeenpwned top-1M (use `pwnedpasswords` library)" — the code
  comment claims the auth router would do it; no router does.
- **Fix:** Wire up `pwnedpasswords` (or call the HIBP k-anonymity API) in
  signup, password reset, and admin user-create. Cache the result.

---

## P2 — Medium

### P2-1. Login does not reset `failed_login_count` on TOTP-required step
- **Where:** `src/vittring/api/auth.py:300-313`.
- **What:** After a correct password but missing/invalid TOTP, the function
  returns without resetting `failed_login_count`. Successive password-correct
  attempts against a TOTP-enabled account never roll the counter back to 0
  even after the user finally logs in successfully — once they enter the
  code, the reset happens; OK. But if the password is correct and 2FA is
  triggered without a code, prior wrong-password counts (which would have
  locked the account) remain untouched. Edge case — low impact but adds
  noise to lockout timing.
- **Fix:** Reset `failed_login_count` once the password verifies, before the
  TOTP gate. Move the lock logic to a separate counter for TOTP failures
  (P1-6).

### P2-2. `/health` is unauthenticated and exempt from CSRF (intended), but
       returns no rate limit
- **Where:** `src/vittring/api/health.py`, `src/vittring/security/csrf.py:35-37`.
- **What:** Cheap endpoint, low risk, but a single attacker hammering
  `/health` consumes CPU. Consider applying a default rate-limit dependency
  on the route.

### P2-3. `signal_type` accepted on `/app/signals/save` is not allowlisted
- **Where:** `src/vittring/api/account.py:385-432`.
- **What:** Only the form layer constrains `signal_type` to a string — any
  value is persisted into `saved_signals`. Low risk (DB unique constraint
  scopes it to the owner) but pollutes audit metadata and could be used to
  store XSS payloads that surface elsewhere if rendered (and per P0-2,
  rendering is unescaped).
- **Fix:** Validate against `{"job", "company_change", "procurement"}` and
  return 400 on anything else.

### P2-4. Stripe webhook leaks exception detail to caller
- **Where:** `src/vittring/api/billing.py:73`.
- **What:** `HTTPException(detail=f"invalid_signature: {exc}")` reflects the
  raw `stripe.SignatureVerificationError` message. Library-level details
  rarely contain secrets, but feeding error text back to potential
  attackers is undesirable.
- **Fix:** Return `detail="invalid_signature"` and log the inner exception
  with `structlog.get_logger().warning(...)`.

### P2-5. Resend webhook re-parses body via `request.json()` after manual read
- **Where:** `src/vittring/api/webhooks.py:39-42`.
- **What:** `await request.body()` is consumed once for HMAC verification,
  then `await request.json()` is called. Starlette caches body so this
  works, but if a future refactor moves to streaming, the second call
  raises. Also, the JSON parse is unguarded — a malformed payload throws
  an unhandled `json.JSONDecodeError` (becomes 500) instead of 400.
- **Fix:** `try: payload = json.loads(body) except json.JSONDecodeError:
  raise HTTPException(400, "invalid_json")`.

### P2-6. Email-verification and password-reset confirm endpoints are not
       rate-limited
- **Where:** `src/vittring/api/auth.py:187` (`GET /verify`), 
  `src/vittring/api/auth.py:426` (`POST /password-reset/confirm`).
- **What:** Tokens are 256-bit so brute force is infeasible, but a default
  rate limit is cheap defense in depth (and prevents accidental DoS via
  email-link scanners).
- **Fix:** Apply `DEFAULT_BY_IP` (already pre-instantiated) as a
  `Depends(rate_limit(...))`.

### P2-7. Admin `subscription_toggle` does not deactivate matching delivered
       alerts; reactivating leaks signals to a user who paused intentionally
- **Where:** `src/vittring/api/admin.py:855-887`.
- **What:** Operator-only — but worth noting the action lacks a confirm step
  and audit message does not include the prior state — only the final state
  (`"active": sub.active`).
- **Fix:** Capture and log `from`/`to` like `user_edit` does for plan changes.

### P2-8. Login error path doesn't reset cookie, so stale `vittring_session`
       cookie can persist when login form returns 401
- **Where:** `src/vittring/api/auth.py:282-287`.
- **What:** Failed login renders the form without `delete_cookie`. If the
  cookie is invalid/expired, the user keeps re-presenting it. Mostly a UX
  nit but combined with P1-7 means session state is sticky.
- **Fix:** On hard auth failure, `response.delete_cookie(ACCESS_TOKEN_COOKIE)`.

### P2-9. `/auth/2fa/disable` allows non-superusers without re-authentication
- **Where:** `src/vittring/api/auth.py:521-542`.
- **What:** A logged-in user can turn off 2FA without entering their TOTP
  or password. If the session token is stolen (via XSS — see P0-2), the
  attacker can pivot to permanently weaken the account.
- **Fix:** Require either current TOTP or current password before disabling
  2FA, and rotate the session.

### P2-10. Audit log entries can be written under user-supplied user ids
- **Where:** Many — every endpoint passes `user_id` from form data
  indirectly. Most flows route via authenticated user, but
  `gdpr_delete_request` (account.py:529-545) writes audit then deletes
  cookie; if cookies are tampered with later, ownership tracing assumes the
  recorded `user_id` is correct. No issue currently — informational.

### P2-11. ASGI CSRF middleware swallows malformed-form exceptions
- **Where:** `src/vittring/security/csrf.py:138-140`.
- **What:** The blanket `except Exception` masks decoding errors when the
  body is unparseable. Fine for security, but eats genuine crash signals.
  Not security per se — informational.

### P2-12. CLI exposes `__doc__` containing operator workflow on misuse
- **Where:** `src/vittring/cli/__main__.py:61-63`.
- **What:** Anyone running the binary on the host learns the available
  privileged commands. Acceptable for a server-only tool; flag only because
  the security policy wants minimum disclosure.
- **Fix:** Optional — keep but ensure the binary isn't world-executable.

---

## P3 — Nits / hygiene

- `src/vittring/security/passwords.py:24-26` pre-folds passwords with SHA-256
  before bcrypt. Comment is accurate; entropy ceiling 256 bits — fine. Note
  in docs that this is intentional, since switching libraries later would
  invalidate hashes.
- `src/vittring/api/templates.py:21` accesses `request.state.csrf_token` via
  `getattr(...)`; if the middleware ever changes attribute name, the token
  silently becomes empty (`""`) and CSRF still fires (mismatch). Worth
  centralising the attribute name as a constant.
- `src/vittring/api/auth.py:60-68` cookie is `Secure=True` unconditionally —
  good in prod but breaks local `http://` testing. Toggle on
  `settings.is_production`.
- `src/vittring/api/admin.py:1131-1133` builds JSONB-path query with
  `AuditLog.audit_metadata["source"].astext == source` — parameterised by
  SQLAlchemy, OK. Confirmed safe.
- `src/vittring/api/admin.py:937-988` builds `like = f"%{q.lower()}%"` and
  passes to `func.lower(...).like(like)` — OK because parameter binding is
  applied; SQL is not interpolated.
- `src/vittring/api/account.py:147-159` does substring filtering on
  user-controlled `q` against constant strings — no risk.
- `src/vittring/api/auth.py:521-542` `two_factor_disable` route is a POST
  but does not require a current TOTP code — duplicate of P2-9 in lower
  severity if P0-2 is closed.
- The whole project uses `lambda r: r.headers.get("x-forwarded-for", ...)`
  patterns inline; centralise into the existing `client_ip()` helper.
- `src/vittring/main.py:93-95` registers a generic `HTTPException` handler
  that overrides Starlette default — fine, but does not preserve `headers`
  (e.g. `Retry-After` from rate-limit). Pass `exc.headers` through.
- `src/vittring/api/admin.py:1235-1358` triggers ingest/digest jobs
  synchronously in the request thread with `asyncio.wait_for(...)`. Fine
  for an admin-only knob, but a slow ingest will block the worker. Move to
  an APScheduler one-shot job.

---

## Top-5 quick wins

1. **Enable Jinja2 autoescape for `.html.j2` templates.** A 4-line patch in
   `src/vittring/api/templates.py` closes P0-2 (the broadest XSS surface) in
   one shot. Add a regression test that renders signup output with
   `<script>` payloads.
2. **Sign or randomise the unsubscribe token.** Replace `int(t)` parsing in
   `src/vittring/api/unsubscribe.py` with a HMAC-signed payload — fixes
   P0-1 (mass-disable of every user's email digest) with ~15 lines.
3. **Refuse Resend webhook payloads when the secret is missing in
   production.** Add a startup check in `webhooks.py` (or `main.py`'s
   `lifespan`) to raise if `app_env == "production"` and
   `resend_webhook_secret is None`. Closes P0-3.
4. **Switch the password-reset rate limiter to key by email, and trust the
   forwarded-for header only when the peer is the local Caddy.** One key
   function change + one Uvicorn flag — closes both P1-3 and P1-4.
5. **Block `is_active=False` users at the login handler and rotate the
   session cookie on password reset / 2FA change.** ~10 lines combined,
   closes P1-5 and the worst part of P1-1/P1-7.
