# Auth flow audit

**Scope:** every path between anonymous and authenticated.
**Sources read:** `src/vittring/api/auth.py`, `src/vittring/api/deps.py`, `src/vittring/api/account.py`, `src/vittring/api/templates/auth/*`, `src/vittring/security/{tokens,passwords,totp,ratelimit}.py`, `src/vittring/audit/log.py`, `src/vittring/utils/errors.py`, `src/vittring/main.py`, `src/vittring/models/user.py`.

Constants pulled from `src/vittring/api/auth.py`:

- `ACCOUNT_LOCK_THRESHOLD = 5`
- `ACCOUNT_LOCK_DURATION = 15 minutes`
- `EMAIL_VERIFICATION_TTL = 24 hours`
- `PASSWORD_RESET_TTL = 1 hour`
- `TRIAL_DAYS = 14`
- Access-token JWT TTL = 15 minutes (`security/tokens.py:ACCESS_TOKEN_TTL`)
- Cookie name = `vittring_session`, `HttpOnly Secure SameSite=Lax`, `max_age=15*60`
- TOTP `valid_window=1` (so ±30 s tolerance) — `security/totp.py:verify_code`

---

## 1. Signup -> email verification

### Happy path

1. `GET /auth/signup` — anonymous user. Renders `auth/signup.html.j2` with `{title, error: None}`. If `OptionalUser` resolves, redirect 303 to `/app`.
2. `POST /auth/signup` — rate-limited via `SIGNUP_BY_IP` (5 req/h per IP).
   - `assert_strong_password(password)` — min 12 chars + tiny denylist.
   - Uniqueness check on `email` (CITEXT, case-insensitive).
   - Insert `User(plan="trial", trial_ends_at=now+14d, is_verified=False)`.
   - Generate verification token via `new_url_token()` (32 bytes urlsafe, sha-256-stored).
   - Insert `EmailVerificationToken(expires_at=now+24h)`.
   - Audit: `AuditAction.SIGNUP`.
   - Render `delivery/templates/verify.html.j2` and `send_email(...tags={"kind":"verify"})`.
   - 303 redirect to `/auth/check-email`.
3. `GET /auth/check-email` — renders `auth/check_email.html.j2` ("link valid 24h").
4. User clicks email link `GET /auth/verify?t=<plain>`:
   - Look up token by `hash_url_token(t)`.
   - If row exists, `used_at IS NULL`, `expires_at > now`: set `user.is_verified=True`, set `token.used_at=now`, audit `EMAIL_VERIFIED`. Render `auth/verify_ok.html.j2`.
   - Otherwise render `auth/verify_failed.html.j2` (HTTP 400).

### Edge cases

- **Resend send fails (`send_email` raises).** Wrapped in `try/except Exception` (auth.py:157-168). Caught, logged via `structlog.warning("signup_verify_email_failed")`, but the **DB transaction continues** and the user row + token row commit. Outcome: account exists, no email sent, user lands on `/auth/check-email` with no way to know nothing was sent. They cannot trigger a resend (no UI, no endpoint). Recovery requires admin action via `ADMIN_USER_VERIFICATION_RESEND`.
- **Already-verified user clicks the verify link again.** The token row's `used_at` was set to `now` on first use, so the second click hits the `used_at is not None` branch and renders `verify_failed.html.j2` ("Länken är ogiltig eller har gått ut"). Misleading — the user is already verified but sees a failure message.
- **Already-verified user clicks a *different* still-unused token (e.g. they had two outstanding tokens).** `is_verified` flips True idempotently, the second token gets consumed, screen shows success. Harmless but "verified" is set redundantly with no audit dedup.
- **Stale `is_verified=True` user signs up a second time with the same email.** Caught by the existence check; renders `auth/signup.html.j2` with the message "En användare med den e-postadressen finns redan." — leaks user existence to anyone who can hit signup, mirrored at the password-reset endpoint (see flow 4).
- **Token TTL boundary.** `expires_at < now` is a strict `<`. A request that arrives at the exact `expires_at` second still passes — micro-edge but non-issue.
- **Concurrent verify clicks (double-fire).** Two parallel requests for the same token: both read `used_at IS NULL`, both proceed, both set `used_at = now`. Second commit overwrites the first; harmless but a race.

### Bugs found

- **B-Signup-1 — silent email failure.** Resend error is swallowed. The user has no path to "resend verification email" from the UI. They will sit on `check_email.html.j2` indefinitely and assume the system is broken. CLAUDE.md §5 requires polling Resend until verified before continuing on first run, but there is no equivalent runtime fallback — only a structlog warning that nobody reads in real time.
- **B-Signup-2 — verified user sees "verification failed".** Double-click on the verify link (or browsers prefetching the URL) lands on `verify_failed.html.j2`. The handler should detect "token already used AND user already verified" and render the success page (or an "already verified" page).
- **B-Signup-3 — user enumeration via signup error.** "En användare med den e-postadressen finns redan." is a direct existence oracle.
- **B-Signup-4 — no rate limit on the verify endpoint.** `GET /auth/verify` is hit only with a valid `t`, but unbounded probes for tokens are possible (sha-256 hash check is fast). Tokens are 32 bytes so brute force is infeasible, but adding `DEFAULT_BY_IP` would still be hygiene.

### UX gaps

- No "send me a new verification link" button. Both `check_email.html.j2` and `verify_failed.html.j2` say "log in" or "contact support" — but a logged-in unverified user lands on `/app` -> 403 (see flow 9), so "log in" is a dead end.
- No countdown / "expires in 24h" indicator after the user clicks verify.
- `verify_failed.html.j2` is a single page covering three different failures (unknown token, used token, expired token). All three deserve different copy.
- The email-from-signup flow does not fall back to a non-Resend path (e.g. log a one-time token to the admin panel). For trial accounts during DNS warm-up this is a hard cliff.

---

## 2. Login (incl. 2FA branch)

### Happy path (no 2FA)

1. `GET /auth/login` — if already logged in, 303 to `/app`. Else render `auth/login.html.j2` with `{error: None, require_2fa: <unset>, email_value: <unset>}`.
2. `POST /auth/login` — rate-limited via `LOGIN_BY_IP` (10/min) and **inside the handler** `LOGIN_BY_EMAIL.take(email)` (5/min).
3. Look up user by email (CITEXT).
4. Verify password with `bcrypt.checkpw` (passwords are pre-folded via SHA-256+b64 to dodge bcrypt's 72-byte cap — `security/passwords.py`).
5. If `user.locked_until > now` -> render `auth/login.html.j2` with the lockout message, **HTTP 403**. (Note: this branch only runs if the password verified — see Bug B-Login-3.)
6. If `user.totp_secret` is set: see 2FA branch below.
7. Reset `failed_login_count=0`, `locked_until=None`, set `last_login_at`, `last_login_ip`. Audit `LOGIN`.
8. 303 to `/app`. `_set_session_cookie` writes the JWT cookie.

### 2FA branch (`require_2fa`)

- After password is verified, if `user.totp_secret` exists and either no `totp` was submitted or the code does not verify: re-render `auth/login.html.j2` with `require_2fa=True` and `email_value=email`.
  - First visit (no `totp` submitted): status `200 OK`, no `error` shown.
  - Subsequent failed code: status `401 UNAUTHORIZED`, `error="Ange giltig 2FA-kod."`.
- Code verified -> proceed to step 7 above.

### Logout

- `POST /auth/logout` requires `CurrentUser` (active). Audit `LOGOUT`. Delete `vittring_session` cookie. 303 -> `/`.

### Edge cases

- **TOTP exactly at rotation boundary.** `pyotp.TOTP.verify(code, valid_window=1)` accepts the prior, current, and next 30-second window — so a code submitted at the second boundary works either side. This is correct.
- **User with `is_active=False` (e.g. GDPR-delete requested) tries to log in.** `verify_password` succeeds, the locked-out check skips (`locked_until` is `None`), 2FA check passes, login succeeds, cookie issued. Then `current_user` will reject with 401 (`user.is_active is False`) on the next request — but the `LOGIN` audit row was just written. Effectively: logins for deactivated users are silently broken halfway. See Bug B-Login-2.
- **Email not verified.** Login succeeds and issues the cookie. Then `/app` requires `current_verified_user`, returns HTTP 403 JSON `{"detail":"email_not_verified"}` (see flow 9).
- **Locked-out user resets password.** `password_reset_confirm` clears `failed_login_count=0` and `locked_until=None` (auth.py:463-464). Lock effectively cleared. Behavior intended but not announced anywhere.
- **Locked-out user just keeps trying.** Each failed attempt resets the lock window: `locked_until = now + 15min` is assigned on every increment past the threshold (auth.py:265-266). So the lock is **effectively rolling**, not a one-shot 15-minute window. The handler increments `failed_login_count` even after the lock is in place, since the locked check happens after the password check.
- **`LOGIN_BY_EMAIL` bucket fills up.** `LOGIN_BY_EMAIL.take(email)` raises `RateLimitExceededError` -> the dependency wrapper is **not used here** (it's called directly inside the handler) so the exception propagates as a 500-equivalent VittringError JSON (see Bug B-Login-1).
- **Stripe / billing future-state:** trial expiry is not checked at login. Once trials end, `trial_ends_at < now` users still log in. (Not in scope; CLAUDE.md §7 says billing is deferred.)

### Bugs found

- **B-Login-1 — `LOGIN_BY_EMAIL.take` not wrapped.** auth.py:255 calls `LOGIN_BY_EMAIL.take(str(email))` outside the rate-limit dependency. When the bucket empties the raised `RateLimitExceededError` is caught by the global `VittringError` handler in `main.py:86` and returned as HTTP 400 `{"detail":"ratelimitexceedederror"}` JSON — *not* a 429 with `Retry-After`, and not the friendly login template. Mobile/HTMX flows see a JSON blob.
- **B-Login-2 — login allowed for inactive users.** Once `user.is_active=False`, the login path still completes, sets `LOGIN` audit row, sets the cookie. Subsequent request is 401. Should reject earlier and explain to the user why (e.g. "kontot är inaktiverat").
- **B-Login-3 — locked-out check runs after password verify.** auth.py:289: `if user.locked_until and user.locked_until > now`. This block is reached only when `verify_password` returned True. A locked-out account that retries with the *correct* password will see the lockout message — fine. But a locked-out account retrying with *wrong* passwords: increments `failed_login_count` on every miss (silently — the lock is being extended), audits `LOGIN_FAILED`, and never tells the user the account is locked. UX wise the user sees "Fel e-post eller lösenord" repeatedly without learning the real reason.
- **B-Login-4 — rolling lockout window.** Each subsequent failed attempt past 5 resets `locked_until = now + 15min` (auth.py:265-266 runs whenever count >= threshold). This effectively pins the user out indefinitely if the attacker keeps trying — DoS-able. Also writes a duplicate `ACCOUNT_LOCKED` audit row per failed attempt above the threshold.
- **B-Login-5 — first-failed-2FA returns 200.** auth.py:310: `status_code=status.HTTP_401_UNAUTHORIZED if totp else status.HTTP_200_OK`. The first time we redirect to the 2FA prompt (no totp submitted) we return 200; that's fine for browsers, but caches/proxies could store an authenticated-looking page since the password was already accepted. Minor.
- **B-Login-6 — no audit row for 2FA-required state.** When the user passes password but is asked for 2FA, nothing is logged. Subsequent failed 2FA attempts are also not audited as a separate `2FA_FAILED` action — they're indistinguishable from password failures.

### UX gaps

- The login template uses a single `error` slot for "wrong password", "locked", "needs 2FA". When the lock message is shown the form still asks for password — there's no countdown for when the lock lifts.
- Logout button must be a `POST` form. `_layout.html.j2` would need a CSRF-protected form; that should be verified (out of scope here).
- After password reset, the user is redirected to `/auth/login` with no flash message ("ditt lösenord är uppdaterat — logga in").
- No "remember this device" for 2FA. Users with TOTP enabled type a code on every fresh JWT (every 15 minutes if they let the cookie expire).

---

## 3. Logout

### Happy path

`POST /auth/logout` -> requires `CurrentUser`. Audit `LOGOUT`. Delete `vittring_session` cookie. 303 -> `/`.

### Edge cases

- **Anonymous logout.** `CurrentUser` raises 401. Returns JSON `{"detail":"not_authenticated"}` instead of just clearing the cookie — see UX gap.
- **Stale JWT after server restart.** `app_secret_key` in `.env` is stable across restarts, so JWTs survive. If the secret were rotated, `decode_access_token` raises and the user is treated as anonymous on next request — they remain "logged in" only client-side until then.
- **No refresh-token / revocation.** CLAUDE.md §13 calls for "Refresh tokens, 30-day lifetime, rotation on use, revocation on logout." None of that is implemented — there is only a 15-minute access JWT and no refresh path. Logout deletes the cookie but cannot invalidate any other open session because there is no server-side session record.

### Bugs found

- **B-Logout-1 — refresh tokens not implemented.** Spec calls for them. Today users get logged out hard every 15 minutes. (Treat as a P1 spec gap.)
- **B-Logout-2 — anonymous logout returns JSON 401.** Should be idempotent: clear the cookie and 303 to `/` regardless.

### UX gaps

- No "you have been logged out" toast on `/`.
- No "log out everywhere" / device list (would require refresh-token table).

---

## 4. Password reset request -> reset confirm

### Happy path

1. `GET /auth/password-reset` — renders `password_reset_request.html.j2` with `submitted=False`.
2. `POST /auth/password-reset` — rate-limited via `PASSWORD_RESET_BY_EMAIL` keyed on `x-forwarded-for` *or* the request `client.host`. **Note:** the limiter is keyed on **IP**, not email, despite the constant name.
   - Look up user by email.
   - If user exists: insert `PasswordResetToken(expires_at=now+1h)`, audit `PASSWORD_RESET_REQUESTED`, send email via `reset_password.html.j2`.
   - **Always** re-render `password_reset_request.html.j2` with `submitted=True` ("Om e-postadressen finns hos oss har vi skickat en länk").
3. User clicks `GET /auth/password-reset/confirm?t=<plain>` — renders `password_reset_confirm.html.j2` with the token in a hidden field.
4. `POST /auth/password-reset/confirm` (Form: `t`, `password`):
   - Look up token by `hash_url_token(t)`. Reject if missing, used, or expired -> render confirm template with error, HTTP 400.
   - `assert_strong_password(password)` -> on failure render confirm with WeakPasswordError text.
   - Update user: `password_hash`, `failed_login_count=0`, `locked_until=None`. Mark token `used_at=now`. Audit `PASSWORD_RESET_COMPLETED`.
   - 303 -> `/auth/login`.

### Edge cases

- **Reset for nonexistent email (timing attack).** When user is None the handler skips token creation, audit, and `send_email`, then returns the same template. The response time differs significantly: existing users incur a bcrypt-free path but do incur a network round-trip to Resend, while nonexistent users complete immediately. `send_email` over the network is the dominant time cost. Easily timed (likely 200-800 ms vs. <30 ms). See Bug B-Reset-1.
- **Reuse already-used token.** `used_at IS NOT NULL` -> error message rendered. Correct.
- **Expired token.** `expires_at < now` -> error message. Correct.
- **Token reused after lockout-then-reset combo.** After a successful reset, `used_at` is set; the token is permanently dead. Correct.
- **Multiple outstanding tokens.** Each `POST /auth/password-reset` adds a new row. Older tokens remain valid until they hit `expires_at`. No invalidation of prior tokens.
- **Rate-limit key naming bug.** The limiter is named `PASSWORD_RESET_BY_EMAIL` (capacity=3, window=1h) but the dependency keys it on IP. CLAUDE.md §13 requires "3 req/hour per email". Today an attacker rotating IPs can request resets for many emails at the spec's per-email cap each.
- **No CAPTCHA on `POST /auth/password-reset`.** Any valid email triggers an email send to a real inbox.
- **Rate-limited reset request returns ugly response.** Same as B-Login-1 path: depending dependency raises HTTPException with `Retry-After`, but it's a JSON body, not a re-render of the form.
- **Password reset clears 2FA?** No. The user keeps their TOTP secret. (Probably correct, but undocumented — a stolen-laptop scenario where the attacker has the TOTP app cached but no password is well handled; the inverse case where a user lost their TOTP device is *not* handled here at all.)
- **Reset for `is_active=False` user.** Reset still runs and sets a new password — but logging in still fails post-reset because `current_user` rejects inactive users. The reset succeeded in the DB but the user is locked out at a different layer.
- **Reset email send fails.** Unlike signup, there is **no try/except** around `send_email` in `password_reset_request`. Any Resend error propagates as 500 — leaks the existence of the email address (timing/error oracle), and crashes the request after the token is committed. See Bug B-Reset-2.

### Bugs found

- **B-Reset-1 — timing-attack oracle on email existence.** The branch divergence at auth.py:374 means existing emails take ~400 ms more than missing emails. Mitigation: always do the same work (or sleep), or queue the actual send.
- **B-Reset-2 — uncaught Resend error.** auth.py:402 `await send_email(...)` is not wrapped. A transient Resend 5xx returns a 500 to the user *and* leaks "this email exists" via the differing error.
- **B-Reset-3 — rate-limit key is IP, not email.** Spec demands 3/hour/email. Today it's 3/hour/IP — a botnet bypasses it trivially.
- **B-Reset-4 — old reset tokens remain valid.** Issuing a new token does not mark prior tokens used. A user clicking an older email after requesting a second still goes through. Generally fine, but worth documenting.
- **B-Reset-5 — rate-limit dependency lambda is brittle.** auth.py:362 `lambda r: r.headers.get("x-forwarded-for", r.client.host if r.client else "?")` returns the **default** only when the header is missing entirely. If the header is present but empty, it returns the empty string — same key for every empty-header request. Also doesn't strip whitespace or take the first hop the way `client_ip()` does.
- **B-Reset-6 — no inline CSRF-or-Honeypot to prevent enumeration via timing.** Non-blocking, but worth listing.

### UX gaps

- After successful reset the user is dumped on `/auth/login` with no flash. Users routinely re-type the old password.
- The "submitted" page is templated as a *separate* render of the same template. A user who navigates back can re-submit with the same email; no visual confirmation of "we sent it". A standalone success page would be clearer.
- No "use a backup code" path if the user has lost their TOTP device. Today that user is locked out for good. (This intersects with 2FA disable too.)

---

## 5. 2FA enable / disable

### Happy path — enable

1. `GET /auth/2fa/enable` — `CurrentUser` required. Generates a fresh secret if `user.totp_secret is None`, else reuses it (so reloading the page does not invalidate an in-progress setup). Renders `auth/2fa_enable.html.j2` with `{secret, uri, error: None}`.
2. `POST /auth/2fa/enable` — Form: `secret` (echo'd via hidden field), `code`.
   - `verify_code(secret, code)` (`valid_window=1`).
   - On failure: re-render with `error="Fel kod."` HTTP 400.
   - On success: persist `user.totp_secret = secret`, `user.totp_enabled_at = now`. Audit `TWO_FACTOR_ENABLE`. 303 -> `/app/account`.

### Happy path — disable

`POST /auth/2fa/disable` — `CurrentUser` required. If `is_superuser`, raises `HTTPException(400, "2fa_required_for_superusers")`. Else clears `totp_secret`, `totp_enabled_at`. Audit `TWO_FACTOR_DISABLE`. 303 -> `/app/account`.

### Edge cases

- **Stale secret after disable+enable.** Disable nulls `totp_secret`. A second `GET /auth/2fa/enable` generates a new secret. Old TOTP authenticator entries become stale.
- **User submits a different `secret` value than the one shown.** The form trusts the hidden field. An attacker who can write to the form (not really a thing, given `CurrentUser` and CSRF) could enable 2FA with a secret of their choice — but they're already authenticated as the user, so the threat model is "user enables 2FA with a known secret" -> not actually a vulnerability, but the design has the secret round-tripping through the client when it could live in a server-side session.
- **TOTP code at rotation boundary.** `valid_window=1` covers ±30 s. Codes submitted right at `:00` or `:30` are accepted in either window.
- **Disable for superuser.** Raises HTTPException 400 `{"detail":"2fa_required_for_superusers"}`. JSON, not a friendly Swedish message.
- **Disable without 2FA enabled in the first place.** `totp_secret` is None already; we set it to None and write a `TWO_FACTOR_DISABLE` audit row. Spurious audit row.
- **No re-authentication required to disable.** Once the user has a session cookie, a single CSRF-protected POST disables 2FA — there is no "enter your password" or "enter a TOTP code one last time" step. CLAUDE.md §13 calls this out as "mandatory for superusers"; for non-superusers the interactive UX gap is that an attacker with the session cookie can drop 2FA.
- **Re-enable does not require old code.** `GET /auth/2fa/enable` happily generates a new secret if one is set; saving overwrites `totp_secret`. So if an attacker has the cookie, they can rotate the user's TOTP to one they control without needing the old code.
- **Email confirmation absent.** No email is sent on enable or disable. Users will not notice tampering until the next login.

### Bugs found

- **B-2FA-1 — disable does not require step-up auth.** A session-cookie-only attacker can disable 2FA with one POST. Add a password-or-TOTP confirmation.
- **B-2FA-2 — re-enable can rotate secret without requiring the existing code.** Same root cause as B-2FA-1.
- **B-2FA-3 — superuser disable returns JSON-only error.** Should re-render the account page with a friendly message.
- **B-2FA-4 — no email notification on enable/disable.** Spec §13: "2FA (TOTP) optional for users, mandatory for superusers". Notification is implied by best practice; not implemented.
- **B-2FA-5 — secret echoed via hidden form field.** Minor: a user pressing back-button or sharing a screenshot leaks the secret. Server-side session storage for the in-progress secret is cleaner.
- **B-2FA-6 — superusers can sign up via the public form.** Not in this flow per se, but: `POST /auth/signup` creates `is_superuser=False` users, but if a superuser is created via admin and lacks TOTP, login does not enforce setup. There is no "first login -> force 2FA" flow for superusers.

### UX gaps

- No "scan this QR" image — the `2fa_enable.html.j2` shows the URI as text, not a QR. The `helper` recommends scanning, but there's nothing to scan.
- No backup / recovery codes printed on enable. Users who lose their phone are bricked.
- No path to "I lost my device" recovery. Combined with no backup codes, this is a hard cliff.
- After enable, user lands on `/app/account` with no flash confirmation.

---

## 6. Account lockout (5 failed logins, 15-minute lock)

See flow 2. Reproducing the headline issues:

- **Threshold: 5.** `ACCOUNT_LOCK_THRESHOLD = 5`.
- **Duration: 15 minutes.** `ACCOUNT_LOCK_DURATION = timedelta(minutes=15)`.
- **Rolling lock (B-Login-4):** every failed attempt past 5 re-pins `locked_until = now + 15m`. Net effect: continued attacks keep the user locked indefinitely.
- **No notification email.** Spec §13: "Notify user via email." Today there's a `LOGIN_FAILED` and `ACCOUNT_LOCKED` audit row, but no email is sent.
- **Lock cleared by password reset.** `password_reset_confirm` zeros `failed_login_count` and nulls `locked_until` (auth.py:463-464). This is the documented escape hatch.
- **Lock cleared by admin action.** `AuditAction.ADMIN_USER_UNLOCK` is defined. Likely lives in admin router; not part of public auth surface.
- **Locked user with correct password sees lockout message.** UX-correct. With wrong password they see "Fel e-post eller lösenord" forever (B-Login-3).
- **JSON 403 vs. template.** When the locked check renders the template, status is 403 — but the template render path uses CSRF-protected POST and the response body is HTML. Curl/HTMX clients get HTML 403; OK.

### Bugs found

- B-Login-3, B-Login-4 (above).
- **B-Lockout-1 — no email notification.** Spec violation.
- **B-Lockout-2 — `ACCOUNT_LOCKED` audit row written every increment.** auth.py:265-273 inserts an `ACCOUNT_LOCKED` audit on each failed login >= 5. Should fire once per lockout episode.

### UX gaps

- No "you have N attempts left" hint as the threshold approaches.
- No on-page "your account is locked until HH:MM" timer.
- The lockout-message template is the same login template — re-renders the password field as if a retry were possible.

---

## 7. Email verification token: expiration and reuse

### Properties

- TTL: **24 hours** (`EMAIL_VERIFICATION_TTL = 24h`).
- Storage: `email_verification_tokens.token_hash = sha256(plain)`. Plain not stored.
- Single-use: enforced via `used_at` column.
- Cleanup: **no nightly cleanup job**. Expired/used rows remain in the DB forever. Slow growth, but not zero.

### Failure handling

A single template (`verify_failed.html.j2`) covers:

1. Token not found (forged or typo).
2. Token already used.
3. Token expired.

All return HTTP 400.

### Bugs found

- **B-VerifyToken-1 — no nightly purge.** No periodic delete of `email_verification_tokens` where `expires_at < now() - interval '7 days'`. Adds DB growth.
- B-Signup-2 — verified user clicking again sees failure (above).
- **B-VerifyToken-2 — no resend endpoint.** A user with an expired token cannot self-serve a new one. Must contact support or admin.
- **B-VerifyToken-3 — token in URL leaks via Referer.** Standard concern. CLAUDE.md §13 sets a CSP but does not set `Referrer-Policy` directly; it's listed under "security headers" (X-Frame-Options, X-Content-Type-Options, Referrer-Policy) in §13/§5. Verify that the Caddy config sets `Referrer-Policy: same-origin` or stricter. (Out of scope to verify here, but worth listing.)

### UX gaps

- Failure page is generic. Three causes deserve three messages.

---

## 8. Password reset token: expiration and reuse

### Properties

- TTL: **1 hour** (`PASSWORD_RESET_TTL = 1h`).
- Storage: `password_reset_tokens.token_hash = sha256(plain)`.
- Single-use: enforced via `used_at`.
- Cleanup: **no nightly cleanup**.

### Reuse

After a successful reset, `used_at = now`. The token is permanently dead. On reuse the confirm endpoint renders the confirm template with error "Ogiltig eller utgången länk." HTTP 400.

### Issuing multiple tokens

Each `POST /auth/password-reset` inserts a new row. Older rows remain valid until their own `expires_at`. That means a user who clicks on an *older* email in their inbox after asking for a second link still successfully resets. Probably OK for UX; surprising for security audits.

### Bugs found

- B-Reset-1, B-Reset-2, B-Reset-3, B-Reset-4 (above).
- **B-ResetToken-1 — no nightly purge.** Same as VerifyToken-1.
- **B-ResetToken-2 — token visible in browser history.** GET URL `?t=...` ends up in history. The POST then submits it as a hidden field. A "single-use" guarantee means the history value is dead, but it's still in the URL bar. Standard mitigation: redirect-to-cookie pattern (set a short-lived cookie on the GET, redirect to a `?` page that POSTs from the cookie).

### UX gaps

- The error-overloaded confirm template (B-Reset / Failure) does not distinguish between "expired link" and "already used link" — both could be addressed with "request a new link" CTA.
- No flash on `/auth/login` after success.

---

## 9. Dead-end: verified=False user logs in successfully -> hits `/app`

### Trace

1. Login completes; cookie issued; 303 to `/app`.
2. `GET /app` is a `dashboard` handler with `user: CurrentVerifiedUser` (account.py:170).
3. `current_verified_user` (deps.py:44-51) raises `HTTPException(403, "email_not_verified")`.
4. The global handler in `main.py:93-95` returns:

   ```json
   { "detail": "email_not_verified" }
   ```

   with HTTP 403. **Plain JSON.** No template, no link to "send me a new verification email", no Swedish copy.

5. `EmailNotVerifiedError` (the `VittringError` subclass in `utils/errors.py:48`) is **never raised** anywhere — the dependency uses `HTTPException` directly. So the `_vittring_handler` exception handler in `main.py:86-91` never fires for this case either.

### Bugs found

- **B-DeadEnd-1 — verified=False post-login lands on JSON 403.** Hard block, no recovery affordance, English-ish detail string. Should redirect to `/auth/check-email` with a "we sent you a link, click here to resend" page; or render a friendly Swedish error page.
- **B-DeadEnd-2 — `EmailNotVerifiedError` is dead code.** Either wire it up (raise it in the dep and add a `_email_not_verified_handler`), or delete it. Currently the type is exported but unused.
- **B-DeadEnd-3 — every `/app/*` route inherits this dead-end.** `dashboard`, `calendar_stub`, `saved_stub`, `archive_stub`, `tags_stub`, `export.csv`, `signals/save`, `account_page`, `account/export`, `account/delete`, `subscriptions/*`, `billing/*`. All return JSON 403 to an unverified user.

### UX gaps

- The login flow does not check `is_verified` and route the user to a verification-resend page directly. This is the single biggest dead-end in the app.

---

## Cross-cutting observations

- **Audit gaps.** No audit row for: 2FA-required state, 2FA-failed code, locked-out attempt with correct password, email-verify-double-click, password-reset for unknown email, password-reset rate-limited, login rate-limited, `is_active=False` login attempt.
- **Audit duplication.** `ACCOUNT_LOCKED` is written on every increment past threshold (B-Lockout-2).
- **Friendly-error inconsistency.** Auth flows mostly re-render templates; HTTPException paths return JSON. Failure modes mix HTML 400/401/403 (re-renders) with JSON 400/401/403 (deps + admin). A user on a slow connection or a non-browser client gets wildly different experiences.
- **No CAPTCHA / Turnstile.** Signup, login, and password-reset are CAPTCHA-less; the only protection is per-IP/per-email token buckets, all in-process.
- **No CSRF on logout-redirect-after-anonymous.** Logout is POST-only and CSRF-protected (good); but anonymous logout returns JSON, not a 303 (B-Logout-2).
- **No refresh tokens.** Spec calls for 30-day refresh w/ rotation. Today the access-token JWT is the only credential, lifetime 15 minutes.
- **Trial expiry not enforced.** `trial_ends_at` is set but never checked in any auth path.
- **Time-of-check / time-of-use windows.** Account lockout, token expiry, JWT expiry all have ±1 second slop. Acceptable.

---

## Prioritized fix list

### P0 — must fix before any prod traffic

| ID | Title | Why |
|---|---|---|
| B-DeadEnd-1 | Verified=False user lands on JSON 403 after login | Top dead-end; signups will hit it within 5 minutes of launch. Friendly resend-page or flow into `/auth/check-email`. |
| B-Signup-1 | Resend send failure swallowed; no resend path | New signups silently get no email. Coupled with B-DeadEnd-1, the user cannot recover. |
| B-Reset-2 | Uncaught Resend exception in password-reset request | Returns 500 *and* leaks email existence. Wrap in try/except like signup does. |
| B-Reset-1 | Timing-attack oracle on password-reset | Reveals registered emails to anyone who can time HTTP requests. Always do same work. |
| B-Login-1 | `LOGIN_BY_EMAIL` rate-limit returns 400 JSON, not 429 | Real users hit it under password managers' auto-fill retries. Convert to dependency or catch-and-render. |
| B-Reset-3 | Password-reset rate limit keyed on IP, not email | Spec violation. Easy bypass for credential-stuffers. |
| B-Login-2 | Login completes for `is_active=False` users | Audit shows successful login then next request 401s. Reject up front. |

### P1 — fix in first hardening pass

| ID | Title | Why |
|---|---|---|
| B-Login-3 | Locked-out users with wrong password see "wrong password" forever | UX + makes B-Login-4 invisible to the user. |
| B-Login-4 | Rolling lockout window | Allows attacker to lock a user out indefinitely. Should be a fixed window. |
| B-Lockout-1 | No "your account was locked" email | Spec violation. |
| B-Lockout-2 | Duplicate `ACCOUNT_LOCKED` audit rows | Pollutes audit log; complicates dashboards. |
| B-Logout-1 | Refresh tokens not implemented | Spec violation; users get logged out hard every 15 min. |
| B-2FA-1 | Disable 2FA does not require step-up auth | Cookie-only attacker drops 2FA. |
| B-2FA-2 | Re-enable rotates secret without old code | Same root cause. |
| B-2FA-4 | No email on 2FA enable/disable | Tampering goes unnoticed. |
| B-Signup-2 | Already-verified user sees "verification failed" | Common UX trap (browser prefetch / double-click). |
| B-Signup-3 | User enumeration in signup error | Standardize on a generic message and let email confirm whether the address is taken via the email itself. |

### P2 — fix during onboarding-polish phase

| ID | Title | Why |
|---|---|---|
| B-DeadEnd-2 | `EmailNotVerifiedError` is dead code | Either use it or delete it; don't leave dead branches. |
| B-Login-5 | First failed-2FA returns HTTP 200 | Cache-correctness; minor. |
| B-Login-6 | No 2FA-required audit row | Audit completeness. |
| B-Reset-4 | Old reset tokens stay valid after a new one is issued | Defense in depth; document or invalidate. |
| B-Reset-5 | Reset rate-limit lambda is brittle on missing headers | Use `client_ip()`. |
| B-2FA-3 | Superuser disable returns JSON | Render the account page with a friendly message. |
| B-2FA-5 | TOTP secret echoed via hidden form field | Server-side session storage cleaner. |
| B-2FA-6 | No "first-login forces 2FA setup" for superusers | Spec wants 2FA mandatory for superusers. |
| B-VerifyToken-2 | No "resend verification" endpoint | Pairs with B-Signup-1 / B-DeadEnd-1. |
| B-VerifyToken-1 / B-ResetToken-1 | No nightly purge of token tables | Slow DB growth. Add to scheduler. |

### P3 — nice to have

| ID | Title | Why |
|---|---|---|
| B-Logout-2 | Anonymous logout returns JSON 401 | Should be idempotent: clear cookie and 303 home. |
| B-Signup-4 | No rate-limit on `/auth/verify` | Hygiene. |
| B-2FA — backup codes | No backup/recovery codes printed on 2FA enable | Lost-device path is otherwise impossible. |
| B-2FA — QR code | Show a real QR image, not the URI as text | Currently users must read the URI manually. |
| B-Login — flash on reset complete | After password reset, login page has no "your password is updated" message | Eliminates confusion. |
| B-Login — "remember device" for 2FA | Users prompted for TOTP every 15 min | Combine with refresh tokens. |
| B-VerifyToken-3 / B-ResetToken-2 | Tokens visible in URL/history/Referer | Standard mitigations: redirect-to-cookie pattern, strict `Referrer-Policy`. |
| B-Cross — Audit completeness | Missing audit rows for several rate-limited / 2FA / inactive-user events | Compliance + ops visibility. |
| B-Cross — Trial expiry not enforced | `trial_ends_at` ignored everywhere | Will matter once billing turns on. |
