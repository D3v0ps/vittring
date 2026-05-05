# UI / UX / Copy / Quality Audit — Vittring

Date: 2026-05-05.
Branch: `claude/create-claude-md-5y5EA`.
Scope: meta-layer review across landing, auth, app shell, subscription form, email templates, settings, legal, layout, design tokens. Concurrent agents own the in-flight redesigns of those areas; this audit focuses on bugs, dead-ends, cross-cutting inconsistencies and copy that the per-area agents will not catch.

The findings below are ordered from **must-fix-before-anyone-touches-the-product** to **nice-to-have**. Each finding includes file path + element, what is wrong, what to do, and rough impact.

---

## 1. Critical (P0)

### 1.1 Every state-changing form is broken — CSRF middleware blocks them all

- **Files:** `src/vittring/security/csrf.py:51`–`84` and every template containing a `<form method="post">`:
  - `src/vittring/api/templates/_layout.html.j2:23` (logout)
  - `src/vittring/api/templates/auth/login.html.j2:30`
  - `src/vittring/api/templates/auth/signup.html.j2:15`
  - `src/vittring/api/templates/auth/2fa_enable.html.j2:29`
  - `src/vittring/api/templates/auth/password_reset_request.html.j2:24`
  - `src/vittring/api/templates/auth/password_reset_confirm.html.j2:14`
  - `src/vittring/api/templates/app/account.html.j2:109` (2FA disable), `:148` (account delete)
  - `src/vittring/api/templates/app/subscriptions.html.j2:59` (delete subscription)
  - `src/vittring/api/templates/app/subscription_form.html.j2:16` (create subscription)
- **What is wrong:** `CSRFMiddleware` requires every non-`SAFE_METHODS` request to send the CSRF token in both the `vittring_csrf` cookie *and* a matching `x-csrf-token` header. None of the templates render a hidden field, no JS reads the cookie and attaches it to form posts, and standard `<form method="post">` submissions cannot set custom headers. **Result: signup, login, logout, 2FA enable/disable, password reset, subscription create, subscription delete, account delete — every authenticated action — returns 403 `csrf_token_invalid`.** The app is non-functional end-to-end.
- **What to do:**
  1. Switch the CSRF check to read either a hidden `csrf_token` form field *or* the header (synchronizer-token pattern as documented in CLAUDE.md §13).
  2. Inject the token into the Jinja environment (e.g. via `request.cookies["vittring_csrf"]` or a `globals.csrf_token`) and add `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">` to every POST form.
  3. Issue the cookie *before* rendering forms, not only on the response after the GET.
  4. Add an integration test covering each form.
- **Impact:** **Critical / blocking.** Nothing else matters until this is fixed.

### 1.2 Successful login dead-ends unverified users with raw JSON error

- **Files:** `src/vittring/api/auth.py:325` (`login` redirects to `/app`); `src/vittring/api/deps.py:44`–`51` (`current_verified_user` raises 403); `src/vittring/api/account.py:22`–`51` (`/app` requires verified).
- **What is wrong:** A user signs up, loses the verification email (or hits the “provisioning fail” path noted at `auth.py:157`–`168`), can still log in with correct credentials, and is redirected to `/app`, which throws `HTTPException(403, "email_not_verified")` — handled by `_http_handler` in `main.py:86`–`87` as `JSONResponse({"detail":"email_not_verified"}, 403)`. The user sees a literal JSON blob; there is no path back to “please verify” and no way to resend the verification email.
- **What to do:**
  1. After a successful password match, branch on `user.is_verified`: if false, set the cookie and redirect to a new `/auth/check-email?resend=1` page that lets them request a new verification email.
  2. Add a `POST /auth/verify/resend` endpoint (rate-limited per email) that re-issues the token and email.
  3. Render a friendly HTML page for `email_not_verified` instead of JSON; alternatively gate `/app` to redirect rather than 403.
- **Impact:** **High.** Anyone whose verification email goes to spam is locked out with no recovery loop.

### 1.3 Welcome email is never sent

- **Files:** `src/vittring/api/auth.py:84`–`171` (signup) sends only `verify.html.j2`. `src/vittring/delivery/templates/welcome.html.j2` exists but no code path renders or sends it. CLAUDE.md §21 lists Welcome among required templates.
- **What is wrong:** New users are dropped into a verification-only flow. There is no “welcome / kom igång” email after verification.
- **What to do:** In `verify_email` (auth.py:187), after marking `is_verified=True`, render `welcome.html.j2` (with `dashboard_url`) and send it. Audit-log a `WELCOME_SENT` action.
- **Impact:** **High.** Onboarding gap; misses the moment of highest engagement.

### 1.4 Account deletion deletes the wrong cookie name

- **File:** `src/vittring/api/account.py:155`: `response.delete_cookie("vittring_session")`.
- **What is wrong:** That *is* `ACCESS_TOKEN_COOKIE` (deps.py:14), so it is correct, **but the CSRF cookie (`vittring_csrf`) is not cleared**, and the deletion flow only sets `is_active=False` + `deletion_requested_at` — there is no audit-log entry for the *user-facing* outcome (no second confirmation page, no “you have 30 days to undo” email). After deletion the user is redirected to `/`, but their access token was never revoked. Because `current_user_or_none` checks `is_active` only via `current_user`, the access cookie was deleted; that part works. However, the absence of a confirmation email is a regulatory risk (GDPR practice expects written confirmation of deletion).
- **What to do:** Send a “bekräftelse på begäran om radering” email; mention 30-day grace and how to abort by emailing support; clear `vittring_csrf` as well to be tidy.
- **Impact:** **Medium-high.** Compliance / trust signal.

### 1.5 Unsubscribe token is the literal user id (enumeration + impersonation)

- **Files:** `src/vittring/api/unsubscribe.py:17`–`36`; `src/vittring/jobs/digest.py:202`, `:414` (`_build_unsubscribe_url(base, str(user.id))`).
- **What is wrong:** The “one-click” unsubscribe link is `…/unsubscribe?t=<user_id>`. Anyone with a guess (or a leaked email forwarding chain) can pause every subscription for any user by iterating integers. The code comment in `unsubscribe.py` already concedes this should be a signed token.
- **What to do:** Generate an HMAC-signed token (same `app_secret_key` used for CSRF) that encodes `user_id` + a constant purpose string + an expiration. Validate signature server-side. Optionally store a per-user `unsubscribe_token` rotated on demand.
- **Impact:** **High security / abuse vector.** Also a credibility issue for a B2B paid product.

### 1.6 Signup template shows the wrong product description and wrong sources

- **File:** `src/vittring/api/templates/auth/signup.html.j2:42`–`53`.
- **What is wrong:** The brand-side panel says “Strukturerade prenumerationer på TED, Mercell och Visma Opic. En daglig sammanfattning rakt i inkorgen” and lists “Daglig sammanfattning kl. 07:00” and “SSO, 2FA och fakturabetalning”. Vittring does **not** ingest Mercell or Visma Opic (CLAUDE.md §1, §9), digest is **06:30** (CLAUDE.md §11), there is no SSO and Stripe billing is *deferred* (CLAUDE.md §7), so “fakturabetalning” is misleading. The headline “Bevakning av offentlig upphandling, utan brus.” undersells the product (procurement is one of three signals).
- **What to do:** Replace with a panel that mirrors the landing copy:
  - Sources line: “JobTech (Arbetsförmedlingen), Bolagsverket, TED.”
  - Time: “Daglig digest 06:30.”
  - Pill list: “Yrkesroller, kommuner, SNI-/CPV-koder”, “Daglig digest 06:30”, “Tvåfaktor och GDPR”.
  - Headline: e.g. “Tre offentliga datakällor, en kurerad morgon.”
  - Stat number: align with landing-page “~5 000 signaler/dygn”, not “12 547 nya upphandlingar idag”.
- **Impact:** **High.** First impression for a paying user; copy/feature mismatches kill credibility.

### 1.7 “Bekräftelse-mejl misslyckades” silently swallowed; user is sent to check-email anyway

- **File:** `src/vittring/api/auth.py:149`–`168`.
- **What is wrong:** If Resend rejects the verify email (domain not yet verified, network error, etc.) the exception is logged and ignored; the user is redirected to `/auth/check-email` and sees “Vi har skickat en bekräftelselänk” — which is false.
- **What to do:** When delivery fails, redirect to a dedicated page (or pass a flag to `check_email.html.j2`) that says “Vi kunde inte skicka bekräftelsemejlet just nu. Vi försöker igen automatiskt — eller mejla support på info@karimkhalil.se.” Optionally schedule a retry job.
- **Impact:** **High** for a bad-day failure mode.

### 1.8 Pricing tier in landing does not list the “14 dagars gratis provperiod” for Team / Pro

- **File:** `src/vittring/api/templates/public/landing.html.j2:179`–`215`. Solo lists “14 dagars provperiod” but Team/Pro do not.
- **What is wrong:** CLAUDE.md §7 explicitly says all plans have 14 days free. Inconsistent feature lists imply Solo is the only trial tier.
- **What to do:** Add the trial bullet to all three tiers, or move it to a single line under the grid.
- **Impact:** **Medium-high.** Costs conversions.

### 1.9 The “nyckelord” fields swap meaning silently when no signal type uses them

- **File:** `src/vittring/api/templates/app/subscription_form.html.j2:152`–`174` (data-needs="job procurement"); JS at line 296 hides the field if no relevant signal is checked, but the checkbox group only shows `Bolagsändringar` checked → all three step-3 keyword/CPV fields are hidden, the fallback `data-empty-state` shows generic “Välj en signaltyp ovan…” even though Bolagsändringar *is* selected. The user sees an empty step-3 with a confusing message.
- **What to do:** When step-3 fields are empty due to a valid signal selection (not “none”), show a context-specific message: “Inga finjusteringar för bolagsändringar — gå tillbaka och spara.”
- **Impact:** **Medium-high.** Form looks broken when the user selects only Bolagsändringar.

---

## 2. High (visual / UX / credibility)

### 2.1 Topbar nav is missing /pricing for logged-in users; “Inställningar” has no active state; no “Boka demo” for anon

- **File:** `src/vittring/api/templates/_layout.html.j2:18`–`33`.
- **Wrong:**
  - Logged-in nav has Översikt, Prenumerationer, Inställningar, Logga ut, avatar — no link to /pricing (a user on trial should be able to find it without the dashboard chrome).
  - Active class only handled for `/app` (exact) and `/app/subscriptions*`. The `/app/account` link is never highlighted.
  - The avatar comes *after* the logout button — an awkward order; convention is avatar/menu first, logout inside it.
  - Logout submits a tiny inline form with `style="display:inline"`, which renders as a blue ghost button next to a non-button link — visual hierarchy is muddled.
- **What to do:** Move the logout into a tiny dropdown rooted in the avatar, add the active class for `/app/account`, and surface “Priser” inside the avatar dropdown as “Hantera plan” (or keep in topbar for trial users only). For unauth, add an active class for `/pricing`.
- **Impact:** Medium-high.

### 2.2 Hero copy contradicts itself across pages

- Landing claims “Tre offentliga datakällor, en kurerad digest 06:30.” (`landing.html.j2:11`).
- Pricing intro keeps the same time, OK.
- Signup brand-side claims `kl. 07:00`. Login brand-side talks about an *“genomsnittlig tid att läsa dagens bevakning”* of `04:32` minutes (good copy) — but stat looks like a clock, not a duration; readers will think “04:32 AM”.
- **What to do:** Pick one canonical time (`06:30`) everywhere, and prefix duration figures with `~` and a unit (e.g. `~4 min` instead of `04:32`).
- **Impact:** Medium-high. Believability.

### 2.3 The dashboard “last digest” metric falls back to “Levereras 06:30” without a date

- **File:** `src/vittring/api/templates/app/dashboard.html.j2:79`–`87`.
- **Wrong:** If the user has no `recent_alerts`, the card reads `Senaste digest — — — Levereras 06:30`. That is two empty rows on a “premium” card. It also says “Levereras 06:30” without telling them on which day; “Levereras imorgon 06:30” (compute today vs after digest time) would be much more reassuring.
- **What to do:** Render “Imorgon kl 06:30” (or “Idag kl 06:30” if before that hour). Replace the value `—` with the relative day word.
- **Impact:** Medium.

### 2.4 Empty-state on dashboard duplicates the empty-state on /app/subscriptions

- **Files:** `src/vittring/api/templates/app/dashboard.html.j2:31`–`57` and `src/vittring/api/templates/app/subscriptions.html.j2:72`–`97`.
- **Wrong:** Two near-identical empty-states with subtly different illustrations and microcopy. If the dashboard sees no subscriptions and the user clicks “Kom igång”, they create a sub and land on the same empty-state on the subscriptions list page. There is also a copy disparity: dashboard says “digest 06:30 lagom innan första kaffet”, subscriptions list says “tre datakällor / daglig digest” — different tone.
- **What to do:** Pick one empty-state pattern, share the partial. Use the same illustration, copy, and CTA in both. Vittring is consistent or it is sloppy; right now it’s sloppy.
- **Impact:** Medium-high.

### 2.5 Login brand-side stat number could be misread as a clock

- **File:** `src/vittring/api/templates/auth/login.html.j2:62`–`63` (`04:32` next to `genomsnittlig tid att läsa…`).
- **Wrong:** `04:32` paired with `auth-brand-stat-num` font (large, mono) reads as `04:32` AM. Use `~4 min` or `4 min 32 s`. Same goes for the signup stat `12 547` — feels invented; better to use a *category* stat (“tre myndighetskällor, EU-säkrad data”) or remove.
- **What to do:** Replace clock-styled stats with units (`min`, `signaler / dygn`) or qualitative copy. Drop the `12 547`.
- **Impact:** Medium.

### 2.6 “Ny prenumeration” form lacks geographic/branscher hints for the case where Bolagsändringar is alone

- **File:** `src/vittring/api/templates/app/subscription_form.html.j2:79`–`140`.
- **Wrong:** Step 2 “Geografi & bransch” is the only step where the SNI input is reachable, but it uses `pattern="[0-9, ]*"` which silently rejects valid SNI codes containing dots (`49.410`). The field hint shows `49410, 52100` (no dot), but SCB writes them with a dot. Users who paste from SCB will see a mysterious browser validation tooltip.
- **What to do:** Either accept dots and normalize on save, or change the placeholder + hint to say “utan punkter”.
- **Impact:** Medium.

### 2.7 Subscription creation success silently redirects to list; no toast/snackbar/banner

- **Files:** `src/vittring/api/subscriptions.py:127`; `src/vittring/api/templates/app/subscriptions.html.j2`.
- **Wrong:** After POST success the user is redirected to `/app/subscriptions` with no flash message, so they have no positive feedback that anything saved. The new row is just there at the top.
- **What to do:** Implement a one-shot flash mechanism (e.g. `flash` cookie or a `?created=1` query) and render an `alert-info` banner: “Prenumerationen ’X’ skapades. Första digesten levereras imorgon kl 06:30.” Same pattern for delete, 2FA enable/disable, password reset, GDPR export.
- **Impact:** Medium-high. Trust + perceived speed.

### 2.8 “Inaktivera 2FA” has no confirmation step

- **File:** `src/vittring/api/templates/app/account.html.j2:109`–`111`.
- **Wrong:** A single click on “Inaktivera” disables 2FA. No confirm dialog, no password re-entry, no “mejl bekräftelse”. Compare with the deletion form which has `onsubmit="return confirm(…)"`.
- **What to do:** Either gate behind a confirm() or, better, require current password / TOTP re-verification. Send a notification email when 2FA is disabled (reauth-by-email).
- **Impact:** Medium-high. Security posture for a B2B SaaS.

### 2.9 “Hantera filter” button on dashboard goes to the same place as “Visa alla N”

- **File:** `src/vittring/api/templates/app/dashboard.html.j2:98`, `:163`–`168`.
- **Wrong:** Two buttons in close proximity that go to the same `/app/subscriptions`. The eyebrow says “Snabbåtgärd” next to “Skapa ny prenumeration” but the secondary `subs-summary` card already has a Hantera-link. Consolidate or differentiate.
- **What to do:** Drop the duplicate, or make one go to `/app/subscriptions/new` and the other to `/app/subscriptions`.
- **Impact:** Medium.

### 2.10 Logo / brand mark is text-only; no SVG or wordmark file

- **Files:** `_layout.html.j2:17` (`<a class="brand">Vittring</a>`); `auth-mark` everywhere.
- **Wrong:** For a “premium tech aesthetic” spec, the wordmark is plain text in Inter 600. The dot used on auth screens (`auth-mark-dot`) is fine, but inconsistent — on landing/topbar the dot is missing.
- **What to do:** Either:
  - Promote the auth-mark dot to the topbar wordmark for consistency, or
  - Commission a real wordmark SVG (this is the single biggest premium-feel uplift cost-vs-impact).
- **Impact:** Medium-high (brand-feel).

### 2.11 Hero digest preview shows a date that won’t match Sweden’s digest schedule

- **File:** `src/vittring/api/templates/public/landing.html.j2:30` (`Tis 5 maj · 06:30`).
- **Wrong:** Today *is* tisdag 5 maj 2026 — fine for the screenshot — but it’s baked in. As soon as the date drifts, the hero looks fake. Either generate the date from `now()` server-side or label it `EXEMPEL`.
- **What to do:** Pass a server-formatted Swedish date to the template and substitute it; or add a small `EXEMPEL` badge.
- **Impact:** Medium.

### 2.12 “Avregistrerad” page leaves user with no obvious link to log in / re-enable

- **File:** `src/vittring/api/templates/public/unsubscribe.html.j2`.
- **Wrong:** No card, no CTA back to `/auth/login`, no Vittring brand mark. Looks like a plain HTML 1996 page wrapped in the topbar.
- **What to do:** Match the auth-state pattern (icon + heading + lead + button). Add a “Aktivera prenumerationer igen” button linking to `/auth/login`.
- **Impact:** Medium.

### 2.13 Plan badge for `trial` is the same accent style as `pro`

- **Files:** `app/dashboard.html.j2:18`–`24`; `app/account.html.j2:55`–`61`.
- **Wrong:** The plan badge uses `badge-accent` for *every* plan, including the trial. A trial user with limited features should see a softer “Provperiod” badge (use `badge-highlight` or `badge-neutral`) and a paid plan should be `badge-accent`. Today, every account looks like a Pro account.
- **What to do:** Branch on plan in the badge class, with a clear visual difference between trial / paid.
- **Impact:** Medium-high.

### 2.14 Pricing page has “Team — populär” inside the tier name string

- **File:** `src/vittring/api/templates/public/pricing.html.j2:29`.
- **Wrong:** The “populär” marker is encoded into the visible text as `Team — populär`, but the landing page uses `featured` class to styling-mark the same tier. Mixing strategies; the pricing-page badge looks like a typo. Use a separate `<span class="badge badge-highlight">Populär</span>` next to `Team`.
- **What to do:** Move “Populär” to a dedicated badge in both pages and just title the tier `Team`.
- **Impact:** Medium.

### 2.15 “14 dagars provperiod” count is silently wrong for users who created the account at 23:59

- **File:** `src/vittring/api/auth.py:125` (`trial_ends_at = now + 14d`); display: `app/account.html.j2:67`.
- **Wrong:** The trial end is a UTC timestamp displayed without time zone. A user signing up at 22:00 UTC on 5 May sees “Provperiod aktiv till 2026-05-19”, which is correct in UTC but feels off-by-one for a Swedish customer who signed up *late evening 5 May*. Show the date in `Europe/Stockholm`.
- **What to do:** Convert all displayed timestamps with `astimezone(zoneinfo.ZoneInfo("Europe/Stockholm"))` (already the configured TZ in `.env.example`).
- **Impact:** Medium.

---

## 3. Medium (polish opportunities)

### 3.1 Landing FAQ has only four questions; ToS/Privacy assumed

- **File:** `landing.html.j2:225`–`251`.
- Add: “Hur ofta uppdateras data?”, “Vad händer om en datakälla är nere?”, “Kan jag ändra plan senare?”, “Får jag faktura?”.
- Impact: low-medium.

### 3.2 Pricing page CTA banner repeats the landing’s — duplicate copy

- `pricing.html.j2:97`–`108` is essentially the same as `landing.html.j2:253`–`268`. Lower priority but a place to differentiate (“Se demo” vs “Starta provperiod”).

### 3.3 Verify-failed page lacks a “send me a new link” button

- `auth/verify_failed.html.j2`. Currently sends them to login. Should expose a one-click resend (rate-limited).

### 3.4 Password reset request shows the form even after submission redirect

- `auth/password_reset_request.html.j2`. The same template handles both states by `submitted` flag. The “submitted” path is great; the “initial” path lacks a fixed-height layout so the layout shifts when one state replaces the other (mostly noticeable on slow connections).

### 3.5 No “senast inloggad” info anywhere — security best-practice

- `account.html.j2`. Add a small "Senast inloggad: 2026-05-04 09:12 från 81.2.x.x" row in the security section. The data already exists (`user.last_login_at`, `user.last_login_ip`).

### 3.6 Subscription form has no inline validation for empty `signal_types`

- The submit button is correctly disabled by JS, but if JS is broken (CSP, etc.), the server returns a `422` from FastAPI's pydantic — the user sees nothing. Add server-side rendering of the error.

### 3.7 Hero meta dots are decorative but lack `aria-hidden`

- `landing.html.j2:18`–`20`. The `<span class="dot"></span>` has no semantics; harmless but cluttered for screen readers without `aria-hidden="true"`.

### 3.8 The avatar in the topbar shows uppercase letter only; no menu

- `_layout.html.j2:26`. It's just a styled span — not interactive. Either make it a button to a popover (logout, account, sign out) or drop the click-affordance look (smaller / non-circular).

### 3.9 “Skapa konto” heading vs landing CTA “Starta provperiod” — verbal mismatch

- `auth/signup.html.j2:10`. Match: change to “Starta din provperiod” or change landing CTA to “Skapa konto”.

### 3.10 “Karim” is named on legal pages, not on the public landing

- `legal_terms.html.j2:20`, `legal_privacy.html.j2:7` mention Karim by first name. The landing page never names the operator. For a Swedish premium SaaS, an “Om oss / Bakgrund” section linking to one paragraph about Karim adds trust; nameless legal blurbs feel fly-by-night.

### 3.11 Empty state tip dots use `<span class="dot">` but the rest of the design uses bullets/checkmarks

- `dashboard.html.j2:53`–`55`. Mix of bullet-styles across the app; pick one.

### 3.12 The “Hantera prenumerationer” email footer button in the digest links to `/app/subscriptions` — but a logged-out recipient lands on the login page

- The login page has no return-to context after auth. Add `?next=/app/subscriptions`.

### 3.13 Footer (`site-footer`) has only three links and a copyright

- `_layout.html.j2:40`–`50`. Add: blog (when there is one), status page, “För säljteam” / “Om Vittring” marketing pages.

### 3.14 Footer copyright reads `© 2026 Karim Khalil`

- Should be `© 2026 Karim Khalil. Alla rättigheter förbehållna.` to match Swedish legal convention; or just `© 2026 Vittring av Karim Khalil`.

### 3.15 The 2FA enable page exposes the otpauth URI in plain text

- `auth/2fa_enable.html.j2:24`. Showing the URI is technically the manual fallback, but the *common* path is a QR code. There is no QR code rendered. Add a server-side `qrcode[pil]` rendered SVG or use a CSP-allowed `data:` URL.

### 3.16 No consent banner for analytics / cookies (CLAUDE.md §14 requires one)

- Strictly necessary cookies (session, CSRF) are exempt, but if any analytics is added later there must be a banner. Stub a non-blocking banner now to avoid a future P0.

### 3.17 The signup form does not show password strength feedback in real time

- `auth/signup.html.j2:30`. The `password-requirements` hint is static. Live feedback (length met / not, common password caught) would reduce server bounces.

### 3.18 The email digest footer line `f"{contact_address}"` is fine but lacks `MAILTO:`

- `delivery/templates/_base.html.j2:81`. Make the from-address linkable; many MUAs already do this, but explicit `<a href="mailto:…">` is more correct.

---

## 4. Low / nice-to-have

- **4.1** Animate the digest preview on hover (subtle scale 1.005, longer dur). Right now it’s static.
- **4.2** Add a “last updated” field to the legal pages, currently hardcoded to today.
- **4.3** Add a `prefers-color-scheme: dark` opt-in for the app shell — a premium tech aesthetic basically requires dark mode for power users.
- **4.4** A “Demo dataset” or sandbox account for unverified visitors — view a static dashboard.
- **4.5** Per-subscription email schedule (some users want weekly, some daily).
- **4.6** Localise dates everywhere via `babel`-style formatting (Swedish: `5 maj`, not `05 maj`).
- **4.7** Add a “Status” page (uptime, last successful ingest by source) under `/status`.
- **4.8** Add `<link rel="canonical">` and `<meta name="description">` for SEO on /, /pricing.
- **4.9** Add `og:image` with a real preview screenshot.
- **4.10** Reduce the number of `<style style="…">` inline overrides in templates (e.g. `landing.html.j2:217`, `:261`, etc.) by promoting them to classes — currently fights the CSP `style-src 'self' 'unsafe-inline'` is allowed but inline styles dilute the design system.
- **4.11** Pricing page lists ROT/RUT mention in FAQ — that is residential VAT relief, irrelevant for B2B staffing companies; replace with “F-skatt och momsregistrerad fakturering”.
- **4.12** Add `loading="lazy"` to any future hero images and ensure `decoding="async"` on assets.

---

## 5. Cross-cutting recommendations

### 5.1 Button sizes / weights

- Three sizes (`btn-sm`, default, `btn-lg`) plus inline button-styled `<a>`s are used inconsistently:
  - Landing `Starta provperiod` is `btn-accent btn-lg`.
  - Pricing tier CTA is the *same* class but used inside a 360px-wide tier — visually too big.
  - Auth submit is `btn-primary btn-lg` (full-width, height 52). Reasonable.
  - Topnav `Logga ut` is `btn-ghost btn-sm` — fine, but it sits next to a pseudo-link `Inställningar`, mismatching weights.
- **Recommendation:** Document a button-size *purpose* matrix (CTA = lg, secondary = default, in-table actions = sm). Audit every template against it.

### 5.2 Color contrast

- `--color-text-subtle` (`#94A3B8`) on `--color-bg` (`#FAFAF9`): contrast ratio ≈ 2.94:1 — **fails WCAG AA for normal text** (needs 4.5:1). Used for `.subtle` (size sm but still normal weight): every metric-card-meta, signal-row-date, sub-preview-list-label, etc. Either darken to `#64748B` (≈ 4.6:1) or restrict `.subtle` to non-essential decorative text.
- `--color-text-muted` (`#475569`) on bg: ≈ 8.2:1 — fine.
- White-on-bright-blue (`#FFFFFF` on `#2E6CDB`): ≈ 4.7:1 — pass for normal text, AA for large text. OK.
- `--color-warning` (`#B45309`) on `--color-warning-bg` (`#FEF3C7`): ≈ 4.5:1 — borderline. Bump warning text to `#92400E` for safety.
- `auth-brand-eyebrow` (`#2E6CDB`) on `--color-bg-dark` (`#0B1220`): ≈ 5.4:1 — pass.
- `submit-hint` for warnings uses `--color-warning` on a near-white card — borderline; ensure it’s accompanied by an icon for non-color-dependent recognition.

### 5.3 Typography hierarchy

- Inter 400/500/600/700 + JetBrains Mono is loaded *every* page including legal pages where mono is unused. Trim Mono to pages that need it (preload only on app/digest).
- `h1` in `landing.html.j2` uses `clamp(2.5rem, 5.5vw, 4.25rem)` — bigger than `h1` defined in tokens (`--text-4xl = 3rem`). The `h1` in app pages uses `clamp(1.75rem, 3vw, 2.5rem)`. The reset in main.css line 34 sets `h1 { font-size: var(--text-4xl) }`. Three different h1 sizes in the codebase. Pick a scale and define it as classes (`.display-1`, `.display-2`).

### 5.4 Mobile responsiveness gaps

- **Topbar nav** does not collapse on mobile. At <500px the four-link nav crashes into the brand mark. Add a hamburger or hide secondary links.
- **Subscription form right-rail preview** becomes static under 980px (`sub-form-aside { position: static; }`) — fine, but the preview card is the height of the full main column, so on a 600px-tall mobile viewport, the user has to scroll past it before reaching the form. Move it *below* the form on mobile or hide it (button to expand).
- **Auth brand-side panel** is hidden under 980px — good. But the form gets centered with `min-height: calc(100vh - 65px)` which causes a strange empty band beneath the auth card on tall mobile screens.
- **Subs-list grid** (`subs-list.html.j2`) collapses to a single column at 880px and stacks all data; the actions row drops to the bottom, but `Duplicera` and `Radera` end up touching — add gap at small width.
- **Stats strip** at 720px collapses 4→2; the mono number `06:30` may wrap awkwardly on very small screens (≤340px). Use `white-space: nowrap` on `stat-num`.

### 5.5 Error message tone (Swedish)

Current strings:

- `auth.py:115`: “En användare med den e-postadressen finns redan.” — fine, calm.
- `auth.py:285`: “Fel e-post eller lösenord.” — fine, neutral.
- `auth.py:295`: “Kontot är tillfälligt låst på grund av för många misslyckade försök.” — needs context: tell the user when the lock expires (“försök igen om 15 minuter”).
- `auth.py:306`: “Ange giltig 2FA-kod.” — feels robotic; better “Koden stämde inte. Försök igen.”
- `subscriptions.py:90`: “Din plan tillåter max {N} prenumerationer.” — okay; better “Du har redan {N} prenumerationer (max för planen Solo). Uppgradera för fler.”
- `unsubscribe.html.j2`: “Kunde inte avregistrera” — fine but cold; add a mailto.
- CSV-token error JSON `{"detail":"csrf_token_invalid"}` — once (1.1) is fixed, surface a polite Swedish HTML page instead.
- `password_reset_confirm.html.j2`: “Ogiltig eller utgången länk.” — give a recovery action: a button to request a new reset link.
- `passwords.py:31`: “Lösenordet måste vara minst 12 tecken.” — fine.
- `passwords.py:34`: “Lösenordet är för vanligt — välj något annat.” — fine; use “— välj ett annat”.

**General rule:** every error needs *what happened*, *why* (when relevant), and *what to do next*. Audit each.

### 5.6 Loading states

- No spinner / disabled-on-submit treatment on any form. Adding `aria-busy` + `disabled` on submit during in-flight POST gives the form a spine.
- Submit button on subscription form already disables when no signal type — good pattern; extend to all forms.

### 5.7 Inline styles

- `landing.html.j2:217`, `landing.html.j2:261`, `landing.html.j2:263`, `pricing.html.j2:8`, `pricing.html.j2:60`, `pricing.html.j2:103`, `auth/login.html.j2:51`, etc., contain `style="…"` overrides. Each is a small scratch in the design-system veneer; promote them all to classes.

### 5.8 HTMX present, never used

- `_layout.html.j2:12` loads htmx 2.0.4 from unpkg.com. No `hx-*` attribute is used in any template. Either drop the script (saves a request and fits CSP cleaner) or commit to using it for at least one interactive flow (e.g. live preview in subscription form, currently vanilla JS).

---

## 6. Onboarding gap analysis

Path traced from a real anonymous visitor through to first digest:

1. **`/`** — fine. Hero, stats, features, sources, pricing, FAQ, CTA. No “Boka demo” modal — visitor must email.
2. **`/pricing`** — fine. Three tiers. Each CTA is `Välj <tier>` but they all link to `/auth/signup` with no plan in the URL. The signup form does not capture which plan was clicked → the user lands on `trial` regardless. **Gap:** persist `plan=team` query and pre-set on signup.
3. **`/auth/signup`** — works (modulo CSRF P0). Brand-side copy is wrong (1.6). No checkbox for accepting `Användarvillkor` / `Integritetspolicy` — **GDPR + ToS gap**. Add a required checkbox: “Jag godkänner användarvillkoren och integritetspolicyn”.
4. **POST /auth/signup** — creates user with trial, sends verify email, redirects to `/auth/check-email`. Good.
5. **Verify email arrives (or not)** — if not, *no resend mechanism* (1.2 / 3.3). If user dismissed it, they have no recovery.
6. **`/auth/verify?t=…`** — marks `is_verified=True`. Renders `verify_ok.html.j2`. **Does not log the user in** — the cookie was never set during verify. They must click “Logga in”, retype password.
   - **Suggested change:** set the access cookie on successful verify, redirect to `/app` directly with a one-time welcome banner.
7. **`/auth/login`** — works.
8. **`/app`** — empty state visible. Two CTAs: “Kom igång” (`/app/subscriptions/new`) and “Se planer” (`/pricing`). “Se planer” for a brand-new user is an awkward suggestion; replace with “Läs så funkar matchningen” linking to a help doc that doesn’t yet exist.
9. **`/app/subscriptions/new`** — the form (modulo 1.9). Submission redirects to the list page with no confirmation (2.7).
10. **First digest at 06:30** — no preview / “First digest expected …” message anywhere; user has zero feedback that it’s scheduled. Add a card on the dashboard: “Din första digest landar imorgon 06:30 (om vi hittar matchande signaler).”
11. **`/app/account`** — works. No “last login” surface. No “Resend verification” option (would never be needed if 1.2 is fixed).
12. **Logout** — works (modulo CSRF P0). Redirects to `/`.

**Dead ends found:**

- a) Unverified user logs in → JSON 403.
- b) Lost verification email → no resend.
- c) Plan picked on /pricing not persisted into signup.
- d) Verified user not auto-logged-in.
- e) Subscription created → no flash.
- f) Account deleted → no confirmation email; no path to abort except support email.
- g) ToS / Privacy not actively accepted at signup.

---

## 7. Quick wins (each <10 minutes)

1. **Add active class for `/app/account`** in `_layout.html.j2:22`. (1 line.)
2. **Fix signup brand-side copy** — replace TED/Mercell/Visma + 07:00 + SSO with the correct sources/time/features (1.6).
3. **Fix login brand-side stat unit** — `~4 min` instead of `04:32`.
4. **Add 14-day trial bullet to Solo, Team, Pro** in `landing.html.j2` and `pricing.html.j2`.
5. **Move “Populär” to a separate badge** in `pricing.html.j2:29` rather than inside the tier name.
6. **Add `aria-hidden="true"`** to decorative `<span class="dot">` elements.
7. **Show trial dates in Europe/Stockholm** in `account.html.j2:67` and `dashboard.html.j2:26`.
8. **Friendlier 2FA mismatch error** — change `auth.py:306` string to “Koden stämde inte. Försök igen.”
9. **Drop unused htmx script** in `_layout.html.j2:12` (or commit to using it; either way one is right, both is wrong).
10. **Replace plain unsubscribe.html.j2 with auth-state pattern** — copy the verify_ok structure.

---

## Top-level summary

The single most damaging issue is **1.1 (CSRF middleware blocks every form)** — until templates render the CSRF token in a hidden input, *no user can sign up, log in, log out, create a subscription, change settings, or delete their account.* That alone makes the product non-shippable.

The second-most-damaging cluster is the **onboarding dead-ends** (1.2–1.7): unverified users land on a JSON 403; verification failures are silent; the welcome email is never sent; the unsubscribe token is the user id; and the signup brand-side panel claims features that don’t exist (TED+Mercell+Visma, SSO, 07:00). Each is a 5–30-minute fix and each kills a paying customer’s first impression.

After the criticals, the work is largely cosmetic — flash messages, trial-badge differentiation, copy alignment between landing and signup, mobile responsiveness for the topbar, dark mode someday, a real wordmark. Vittring is *very close* to the premium feel its design system aims at; what it lacks is the last 10 % of polish — and that 10 % is what the whole product is selling.
