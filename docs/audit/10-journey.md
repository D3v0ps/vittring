# End-to-end User Journey Audit — Vittring

Date: 2026-05-05
Branch: `claude/create-claude-md-5y5EA`
Scope: a real-time walkthrough of the path a Swedish staffing-company KAM travels from `https://vittring.karimkhalil.se/` to full activation, then through the failure modes (lockout, bounced email, plan upgrade, deletion). Each milestone is anchored at a wall-clock offset (T+0min, T+1min, T+5min, …, T+14d) and references the exact files that decide what the user sees. Findings are split into "What works", "What fails", and "What's missing" so they can be triaged.

The goal is not to relitigate the bugs already covered in `docs/ui-audit.md` — those are referenced inline; the goal is to surface the gaps a *journey* perspective makes obvious and that a per-screen audit would not catch.

---

## Timeline

### T+0min — anonymous lands on `/`

- **Files:** `src/vittring/api/public.py:14`–`20`, `src/vittring/api/templates/public/landing.html.j2`, `src/vittring/api/templates/_layout.html.j2:62`–`84` (sticky nav), `:90`–`135` (footer).
- **What the user sees:** A radar-themed dark hero with the H1 "En radar för köpsignaler.", lede "Vittring scannar tre offentliga register dygnet runt.", two CTAs (`Starta provperiod` → `/auth/signup`, `Se live demo` → `/app`), a live ticker, a 3-step "Hur det fungerar", three source cards, a testimonial, FAQ with five accordion items, a final CTA block.
- **Works:**
  - Hero copy aligns with CLAUDE.md §1 value proposition.
  - Visual radar motif and live ticker create a strong "this is monitored, not static" feel within 5 seconds.
  - FAQ pre-empts the four obvious B2B questions (legality, freshness, residency, cancellation).
- **Fails:**
  - The "Se live demo" button on `landing.html.j2:177` points at `/app`. For an anonymous visitor this triggers `current_verified_user` (`api/deps.py:44`), which raises `HTTPException(401, "not_authenticated")` → rendered by `main.py:93`–`95` as the JSON blob `{"detail":"not_authenticated"}`. The user gets a literal JSON page on the public landing CTA.
  - The footer "Företag → Om Vittring" link (`_layout.html.j2:116`) loops back to `/` — there is no real "About" page, so it is functionally dead.
  - "Funktioner" in the top nav (`_layout.html.j2:73`) jumps to `/#features` — works on the landing page, but on `/pricing` and the legal pages the same nav fragment is broken (no `#features` element on those pages).
- **Missing:**
  - No data-source attribution on the landing copy (call-out for JobTech / Bolagsverket / TED was deliberately removed in commit `bec98c5`, but the FAQ still implies "öppna API:er" without naming any). For a Swedish B2B sale, naming Arbetsförmedlingen + Bolagsverket is a credibility multiplier.
  - No live "antal användare" / "antal signaler igår" social proof beyond a hard-coded `LH` testimonial.
  - No keyboard-focused skip link to main; landing nav is sticky and dense for screen-readers.

### T+1min — clicks "Priser"

- **Files:** `src/vittring/api/public.py:23`–`27`, `src/vittring/api/templates/public/pricing.html.j2`.
- **Works:**
  - Three-tier grid is clear, "Mest valda" pill on Team is good ranking.
  - All three CTA buttons go to `/auth/signup` (consistent).
  - Page itself loads under 1s — no JS, no third-party calls beyond Google Fonts.
- **Fails:**
  - **Trial-period inconsistency:** the page-level lede says "14 dagars provperiod på alla planer" (`pricing.html.j2:67`). However, the per-plan feature lists do **not** mention the trial bullet on Solo/Team/Pro — the price card body is identical to a static feature list. Nothing in the cards re-states the trial. (See `docs/ui-audit.md` §1.8 for the parallel finding on landing.)
  - There is no toggle for monthly/annual even though the CSS `.toggle` class is defined (`pricing.html.j2:36`–`47`). Annual billing with 10 % off is in CLAUDE.md §7 but invisible to the user.
  - Tagline on Pro reads "För bemanningsföretag i skala" — no concrete user count or seat math; the seat count (15) is hidden inside a feature bullet rather than headlined.
- **Missing:**
  - No "FAQ for pricing" (e.g., what currency, what about VAT, what happens after the trial). The pricing page leaves the user one rage-click away from giving up.
  - No "Boka samtal" / sales-led path even for Pro, despite CLAUDE.md positioning the product to sales teams that often want a personal demo.

### T+2min — clicks legal/privacy

- **Files:** `src/vittring/api/public.py:30`–`34`, `src/vittring/api/templates/public/legal_privacy.html.j2`, `legal_terms.html.j2`.
- **Works:** content is short (≤200 words), in Swedish, links to `info@karimkhalil.se`, and references the `legal/privacy_policy.sv.md` master document.
- **Fails:**
  - There is no `/legal/cookies` route or template even though CLAUDE.md §6 lists `cookie_policy.sv.md` as a deliverable. Cookie banner / consent (CLAUDE.md §14) is also not present anywhere.
  - The privacy page references "Inställningar → Exportera mina data", but the actual button label on `app/account.html.j2:139` is "Exportera JSON" — minor copy drift.
  - No "DPA template" link on the privacy page even though it's in `legal/dpa_template.sv.md` (CLAUDE.md §6) — a B2B prospect at a staffing company will ask for the DPA.
- **Missing:**
  - Subprocessors are listed but no "PUB-avtal datum" or version. A Swedish DSO will ask.
  - No back-link to `/`. The user must use the browser back button or click the logo.

### T+3min — clicks "Avregistrera" link in a hypothetical email footer

- **Files:** `src/vittring/api/unsubscribe.py:17`–`36`, `src/vittring/api/templates/public/unsubscribe.html.j2`.
- **Fails:**
  - The token is the literal user id (`digest.py:414` calls `_build_unsubscribe_url(base, str(user.id))`). Anyone who can guess an integer can pause every subscription for any user (see `docs/ui-audit.md` §1.5 — repeated here because in the journey context this is also the only "GET state-changing" route the public can hit).
  - Success page has no "ångra" / re-activate path. The user is told "Logga in för att aktivera dem igen" but cannot do that anonymously — they would need to be already logged in *or* trust the reactivation works after sign-in. There is no in-app banner that says "Dina prenumerationer är pausade — aktivera dem".
- **Missing:** no audit-log entry on unsubscribe (compare `subscription_created` audit hits — there is no symmetric `subscription_paused_via_email`).

---

### T+5min — clicks "Starta provperiod" → `/auth/signup`

- **Files:** `src/vittring/api/auth.py:75`–`171`, `src/vittring/api/templates/auth/signup.html.j2`, `auth/_auth_base.html.j2`.
- **Form fields:** email (required), full_name (optional), company_name (optional), password (required, `minlength=12`).
- **Works:**
  - HTML5 `minlength=12` mirrors the server-side `MIN_PASSWORD_LENGTH=12` in `security/passwords.py:21`.
  - `assert_strong_password` rejects three obvious top-of-list passwords (`auth.py:99`–`106`).
  - Error states render server-side with a styled alert `.auth-error` (`_auth_base.html.j2:39`–`43`).
  - Right-side aside provides social proof (testimonial + ~5 000 signals/dygn).
- **Fails:**
  - **The pwned-passwords HIBP check promised in CLAUDE.md §13 is not implemented.** The docstring of `assert_strong_password` says "the full HIBP top-1M check via the pwnedpasswords library is invoked asynchronously by the auth router (network call) — this function handles the deterministic, in-memory rules." But `auth.py` never calls anything from `pwnedpasswords`. A user can register with `Passw0rd123!`. Result: claim in the privacy/security copy ("modern lösenordsregler") is partially false.
  - The signup form has **no client-side strength meter** and no "min 12 chars" hint visible until you type 11 chars and submit. The helper text "Minst 12 tecken. Använd gärna en lösenfras." (`signup.html.j2:23`) is a single line that some users will skim past.
  - There is no "Jag accepterar villkoren" checkbox. CLAUDE.md §14 talks about consent for non-essential cookies and GDPR; depending on jurisdiction reading, an explicit ToS/privacy checkbox is best practice for a paid B2B SaaS.
  - **Email verification can fail silently.** `auth.py:149`–`168` catches every exception from `send_email` (Resend domain not verified, transient API error) and logs a warning, but the user is still redirected to `/auth/check-email` (`auth.py:170`) which says "Vi har skickat en bekräftelselänk." — a lie for the user (see `docs/ui-audit.md` §1.7).
  - **Welcome email is never sent.** `delivery/templates/welcome.html.j2` is on disk but no code path renders it (verified via `grep -rn "welcome" src/`). Onboarding misses the moment of highest engagement (right after verification).
  - The `existing` email check (`auth.py:108`–`117`) leaks account existence — the error message "En användare med den e-postadressen finns redan." is a textbook user-enumeration vector for spear-phishing.
  - On success the signup endpoint redirects to `/auth/check-email` but does **not** set the session cookie. So even after the verify link is clicked the user must log in once before seeing `/app`. Reasonable, but inconsistent with the `_set_session_cookie` flow used after login (`auth.py:325`–`326`).
- **Missing:**
  - No "Resend verification link" CTA on `auth/check_email.html.j2` (it just has a static "Inget mejl? Kolla skräpposten" line on line 6).
  - No throttle on the "resend" path because it does not exist — so once the verify email goes to spam the user has no recourse but to mail support.

### T+5min30s — submits signup with weak password

- **Files:** `auth.py:98`–`106`, `signup.html.j2:20`–`24`.
- **What happens:** server returns 400 with the form re-rendered and the error "Lösenordet måste vara minst 12 tecken." or "Lösenordet är för vanligt — välj något annat." Form values are NOT preserved (the email/name/company inputs are blank again). Friction.
- **Missing:** sticky form values across error round-trips (only the password should be cleared, not the rest).

---

### T+6min — submits valid signup

- DB row created with `is_verified=False`, `is_active=True`, `plan='trial'`, `trial_ends_at = now + 14 days`. `EmailVerificationToken` row created with 24h TTL. Audit row `SIGNUP` written. Verify email queued through Resend.
- User redirects to `/auth/check-email`.
- **Works:**
  - The check-email page (`check_email.html.j2`) is brief and tells the user "Klicka på den för att aktivera kontot — länken är giltig i 24 timmar."
  - Trial expiry is on the DB row at signup time, so the timer is deterministic and easy to surface ("provperiod aktiv till YYYY-MM-DD").
- **Fails:**
  - As noted, if Resend hasn't been verified yet (CLAUDE.md §5 prerequisite), the email is dropped on the floor and the user gets a false "we sent it" message.
  - There is no link from `/auth/check-email` back to `/auth/signup` — if the user mistyped their email there is no fix path other than to start over. (And the email already exists — see enumeration concern above — so they can't even sign up again with the typo'd address easily.)
- **Missing:** confirmation copy that says "Vi mejlar `email@x.se`" (showing the email address you entered, so users notice typos at this step).

---

### T+8min — opens inbox, clicks "Bekräfta e-post"

- **Files:** `auth.py:187`–`226`, `delivery/templates/verify.html.j2`, `auth/templates/auth/verify_ok.html.j2`, `verify_failed.html.j2`.
- **Works:**
  - `auth.py:188`–`207` correctly checks expiration, single-use (`used_at`), and existence; on success it sets `is_verified=True`, marks the token used, writes an audit row, and renders a success page.
  - `verify_ok.html.j2` has a clear "Logga in →" CTA.
- **Fails:**
  - **Click-twice scenario:** the second click expires-out (token `used_at` is set), so the user sees `verify_failed.html.j2` saying "Länken är ogiltig eller har gått ut. Logga in så skickar vi en ny verifieringslänk." But "Logga in" does **not** auto-resend a verification link — there is no resend logic anywhere in the code. The copy promises functionality that doesn't exist.
  - **Domain-not-verified scenario:** if Resend has not finished domain verification when the verify email was attempted (CLAUDE.md §5), the user never received a link in the first place. They'll click links in older test emails or be stuck. There is no admin-side way to manually re-issue a verification link except via `/admin` (and the admin user has to be `is_superuser=True` AND verified — circular if Karim is the first user).
  - **Verification flow does not log them in.** Even after clicking the verify link, the user has to type their password again. Users are accustomed to one-click verification establishing a session (Stripe, Linear, etc.). This adds a friction step right at the point of highest intent.
- **Missing:**
  - No welcome email after verification (see T+5min item).
  - No banner on `verify_ok.html.j2` saying "Provperioden gäller till YYYY-MM-DD".
  - No retry/regenerate-token endpoint at `POST /auth/verify/resend` (which `docs/ui-audit.md` §1.2 also flags).

---

### T+9min — first login

- **Files:** `auth.py:233`–`327`, `templates/auth/login.html.j2`.
- **Works:**
  - Plumbing is correct: rate limiting (`LOGIN_BY_IP` + `LOGIN_BY_EMAIL`), failed-login counter, lockout at 5 attempts, audit-log entries (`LOGIN`, `LOGIN_FAILED`, `ACCOUNT_LOCKED`), TOTP branching, session cookie issued via `_set_session_cookie`.
  - Login error text is helpfully ambiguous ("Fel e-post eller lösenord.") — does not enumerate accounts.
  - 2FA support gracefully appears as a second field via `require_2fa` flag.
- **Fails:**
  - **The "verified=False" dead-end at `/app`** (`docs/ui-audit.md` §1.2 reproduced here in journey context): if the user successfully logs in but `is_verified=False` (e.g., they never received the verify email), `auth.py:325` redirects to `/app`, which depends on `CurrentVerifiedUser` (`api/deps.py:44`–`51`), which raises `HTTPException(403, "email_not_verified")`, which `main.py:94` returns as raw JSON `{"detail":"email_not_verified"}`. The user sees a literal JSON blob with no nav and no recovery path. *Worst possible activation experience.*
  - **Lockout copy is mute.** When `user.locked_until > now`, `auth.py:289`–`298` returns a 403 + the copy "Kontot är tillfälligt låst på grund av för många misslyckade försök." But it does not say *how long* the lock lasts. The user has no idea whether to wait 15 min or contact support. There is also no email sent to the user when their account locks (CLAUDE.md §13 says "Notify user via email" but `auth.py:266`–`273` only writes audit + sets `locked_until`).
  - **TOTP-required branching does not preserve the password.** Logic at `auth.py:300`–`311`: when `totp_secret` is set and no `totp` was submitted, the response re-renders `login.html.j2` with `require_2fa=True`. But the `password` field is not pre-filled (and shouldn't be), so the user types their password twice on every 2FA login. The `email_value` is preserved, password is not — that's correct security-wise, but the UX could prefer a session-bound flow ("first verify password, *then* show only the TOTP screen") so the user types each thing once.
- **Missing:**
  - No "Stay signed in" / "Remember device" affordance — every login is 15-min cookie + 30-day refresh per CLAUDE.md §13. The user will be logged out repeatedly with no warning.
  - No "Forgot 2FA / lost device" recovery path at all. `auth.py:521`–`542` lets the user disable TOTP only when already logged in. If they lose their phone, they're locked out forever (the `is_superuser` branch on `auth.py:527`–`531` does not help end users).

---

### T+10min — dashboard first impression

- **Files:** `api/account.py:166`–`236`, `templates/app/dashboard.html.j2`.
- **What the user sees on day one:**
  - A populated dashboard. `_example_signals()` (`account.py:42`–`144`) renders 5 priority + 5 other sample rows mocking Postnord, Schenker, Region Stockholm, Ahlsell etc. — the same list as the landing page preview.
  - Stats: 214 / 7 dygn, 99.5 % förkastat brus, 7 konverteringar (all hard-coded — `account.py:219`–`226`).
  - Filter chips: `Storstockholm`, `SNI 53.* / 52.*` (hard-coded — `account.py:227`).
  - Sidebar links to subscriptions (empty until they create one), Saved/Archive/Tags (all stubs), Inställningar (real).
- **Works:**
  - Shipping a pre-populated dashboard is a smart "demo-on-rails" technique — empty states for new SaaS are notorious activation killers, and the user immediately sees what the product *will* feel like in 24 h.
  - Plan-aware HubSpot button (`dashboard.html.j2:305`–`309`): trial/solo/team users get a link to `/pricing` titled "Pro-funktion — uppgradera"; pro users get a button (currently no handler — see Fail).
  - Sidebar shows the user's initials + plan label + "Logga ut" form, not just the email.
- **Fails:**
  - **Sample data masquerades as live data.** `dashboard.html.j2:215`–`216` says "● Synkad {{ last_sync_time }}" which is hard-coded to "06:30" — even if the user just signed up at 14:32 it shows 06:30. There is no banner saying "Vi visar exempeldata medan din första prenumeration sätts upp", which is misleading — and arguably a regulatory issue if the user thinks "Postnord söker 18 truckförare" is a real signal they can act on right now.
  - The "Öppna →" buttons on sample rows go to `/app/saved` (`dashboard.html.j2:313`) because `signal.url` is None on examples. `/app/saved` is a stub ("Kommer snart"). Click-through dead-end.
  - Stats `214 signaler / 7 dygn`, `+18% v/v`, `7 konverteringar` are all hard-coded — same lie as above. A Swedish KAM will ask "konverteringar ackumuleras hur?", and there is no answer.
  - Sidebar "Översikt" link points at `/app` but lacks an `active` state distinct from "Digest", so the active-row visually contradicts the page (both items active).
  - "+ ny prenumeration" (`dashboard.html.j2:181`) is in `subscriptions` section under sidebar — but there is **no** sidebar item for "Ny prenumeration" before the subscriptions list is non-empty in `app/_stub.html.j2:124`. So a user who lands on `/app/saved` first cannot see how to create a subscription at all. (You'd need to know to click the dashboard "+ Ny prenumeration" button in the topbar.)
- **Missing:**
  - No first-run modal ("Välkommen — skapa din första prenumeration så börjar vi bevaka idag.").
  - No empty-state CTA inside the feed itself; only the topbar `+ Ny prenumeration` button.
  - No notice of trial countdown ("13 dagar kvar av provperioden") on the dashboard. The countdown lives only on `/app/account` (`account.html.j2:60`–`71`).

---

### T+11min — clicks "+ Ny prenumeration"

- **Files:** `api/subscriptions.py:51`–`128`, `templates/app/subscription_form.html.j2`.
- **Works:**
  - Three-step card layout (Identitet → Geografi → Nyckelord) with progress badges 1/2/3.
  - Live preview pane with prose generated client-side from the form values (`subscription_form.html.j2:289`–`482`).
  - Field hiding driven by `data-needs` attributes — only relevant fields show for chosen signal types.
  - Validation: name required, signal_types min 1 (JS disables submit), comma-separated lists are split on the server.
- **Fails:**
  - **Plan limits surface as 402 errors only on submit.** `subscriptions.py:81`–`93` checks plan limit against count. But there is no warning before the user fills out the entire form. Trial = 5 subs, so the 6th attempt makes them fill in everything before seeing "Din plan tillåter max 5 prenumerationer."
  - The "Bolagsändringar"-only path: if user checks only `Bolagsändringar`, all step-3 fields hide and step-3 shows the generic empty-state "Välj en signaltyp ovan…" — but a signal type *is* selected (see `docs/ui-audit.md` §1.9). Looks broken.
  - **Validation gap on signal_types.** The Pydantic-style backend trusts the form. If a user crafts a POST body with `signal_types=foo`, no validation rejects it; it is stored verbatim. The matching engine then ignores the row. Silent dead subscription.
  - The form action is `/app/subscriptions/` with a trailing slash (`subscription_form.html.j2:16`). The list view route is `/app/subscriptions/` (also trailing slash, `subscriptions.py:33`) — but the redirect after create goes to `/app/subscriptions` (no slash, `subscriptions.py:127`). FastAPI handles the redirect, but in journey terms there is a trailing-slash mismatch the team should normalize.
  - There is no "Spara som utkast" — if the user gets distracted, the form values are lost.
- **Missing:**
  - No "Använd förslag" buttons. CLAUDE.md §1 names six target staffing yrkesroller (lagerarbetare, truckförare, chaufför C/CE, etc.); the form forces the user to type each as plain text.
  - No yrkesroll auto-complete from the JobTech taxonomy (CLAUDE.md §9.1 names the taxonomy API explicitly). For a user new to JobTech vocabulary this is the single biggest activation ramp the product could offer.
  - No CPV-code search or human-readable description ("79620000 — Provision of personnel").
  - No "save as template" or example subscriptions for the staffing industry (e.g., "Lagerarbetare Storstockholm" preset).

---

### T+15min — first digest expectation

- **Files:** `jobs/digest.py`, `delivery/templates/digest.html.j2`, `digest.txt.j2`, `jobs/scheduler.py:74`–`81`.
- **Works:**
  - Cron 06:30 Europe/Stockholm (`scheduler.py:75`).
  - Multipart HTML+text email, deduped via `delivered_alerts` unique key (`digest.py:340`–`343`).
  - Footer has both an unsubscribe link and a "Hantera prenumerationer" link.
  - Subject format: "Vittring — N nya signaler (weekday date)".
- **Fails:**
  - **Day-zero digest is empty.** A user who signs up at 14:32 today gets their first digest at 06:30 tomorrow — and the lookback window is 26 h (`digest.py:43` `LOOKBACK_HOURS = 26`). If ingest ran at 06:00, only the last 26 h of signals are loaded, none yet matched against the new subscription. So the user's first email might be: nothing.
  - **No email is sent at all when the digest count is zero** (`digest.py:386`–`389` skips users when `total == 0`). For a brand-new user this means **no day-one signal**: they signed up, verified, created a subscription, and got radio silence.
  - The digest unsubscribe link is the user-id token vulnerability noted at T+3min.
  - **No "first-week empty"** copy. If the user's filters are too narrow, they get nothing every day with no in-product feedback.
- **Missing:**
  - "Welcome digest" / "tomorrow's preview" sent immediately on first subscription create that says "Här är 5 exempel-signaler som hade matchat din prenumeration igår". Powerful trust-building moment.
  - No in-app notification when a digest *was* sent ("06:30 idag — 12 signaler. [Öppna]").
  - No daily summary even when zero matches ("Inget för dig idag — 4 200 signaler genomgångna, alla förkastade.") — so the user has no proof the system is alive.

---

### T+24h — receives first real digest

- **Files:** `delivery/templates/digest.html.j2:1`–`96`, `_base.html.j2`, `digest.txt.j2`.
- **Works:**
  - Section headings per subscription, signal-type badges (Jobb / Upphandling / Bolagsändring), date label, source link, "Hantera prenumerationer" CTA, unsubscribe link in footer.
  - HTML-table layout for Outlook compatibility — the email will render correctly in most clients.
  - Plain-text version is generated alongside HTML.
- **Fails:**
  - **No personalisation at all.** The H1 is just "12 nya signaler — Lagerarbetare Storstockholm". No "Hej Lina" salutation, no "Du har 13 dagar kvar av provperioden" countdown, no link to extend or upgrade.
  - **No "open in dashboard" deep-link per signal.** Each item has only a `source_url` (Arbetsförmedlingen / TED). A KAM cannot one-click "spara den här signalen" or "öppna detaljvyn i Vittring" — they have to manually navigate to `/app` and find the signal. This is the most-used interaction in the product, and it doesn't exist in email.
  - The HTML layout is light (white) while the dashboard is dark. Brand inconsistency. Some users will mentally fail to connect the email and the app on day one.
- **Missing:**
  - List-Unsubscribe header (RFC 8058) — important for Gmail/Yahoo bulk-sender compliance from 2024.
  - Reply-to handling: `auth.py:`/`digest.py` use `info@karimkhalil.se` as From and Reply-to. Replies go to Karim's mailbox — fine for a small ops team but not scalable.
  - No "View web version" link.

---

### T+25h — saves a signal

- **Files:** `account.py:385`–`436` (toggle save), `models/saved.py` (referenced).
- **Works:**
  - Toggle endpoint: insert if missing, delete if present. Audit-logs both directions. CSRF-protected via `csrf_input()`.
  - Redirect targets `/app#saved-{id}` so the page jumps back to the row visually.
- **Fails:**
  - **The star button does nothing visible.** It's a `<form method="post">` with `★` as the button text (`dashboard.html.j2:299`–`304`). After submit the page reloads and lands on `#saved-N`, but there is no toggled-on state — the button still says `★`, no badge, no class change. The user can't tell whether they saved or unsaved.
  - **Saved page (`/app/saved`) is a stub.** The user just saved a row but cannot see it in `/app/saved` (it's the "Kommer snart" placeholder, `account.py:274`–`288`, `_stub.html.j2`).
  - HubSpot button: free/trial/solo/team see a link to `/pricing`; Pro users see a `<button type=button>` with no JS handler (`dashboard.html.j2:306`). Click → nothing happens. Silent dead-end.
- **Missing:**
  - Saved counter on the dashboard hard-coded to `2` (`account.py:217`).
  - Toast / inline confirmation after saving.
  - "Skicka till HubSpot" actual integration on Pro plans.

---

### T+1d — clicks "Inställningar" in sidebar

- **Files:** `account.py:443`–`451`, `templates/app/account.html.j2`.
- **Works:**
  - Layout reuses the public `_layout.html.j2` (light header, narrow content) — different from the dark dashboard. Inconsistent but functional.
  - Sections: Profil (read-only), Plan (with countdown for trial), Säkerhet (2FA enable/disable), Data & integritet (Exportera JSON + Radera kontot).
  - GDPR export endpoint (`account.py:458`–`526`) returns user record, subscriptions, delivered_alerts, audit_log as a JSON download — covers all four SAR-required categories.
  - `confirm()` dialog before deletion.
- **Fails:**
  - **Profile is read-only.** `account.py:443`–`451` and `account.html.j2:23`–`41` render `dt/dd` blocks for email/name/company. There is no edit endpoint at all (no `POST /app/account/profile`). The user cannot change their name, company, or email. CLAUDE.md §14 mentions rectification rights ("profile editing endpoints") — these are missing.
  - **2FA enable button** (`account.html.j2:121`) takes the user to `/auth/2fa/enable` which lives in the auth router (`auth.py:481`–`518`). On success it redirects back to `/app/account` (`auth.py:518`). But there is no QR code rendered on `auth/2fa_enable.html.j2:7`–`10` — only the textual secret + the URI string. The copy says "Skanna QR-koden i din authenticator-app eller mata in nyckeln manuellt" — but there is no QR. Most users who don't manually paste secrets will be stuck.
  - **GDPR export is a synchronous JSON dump.** For a power user with 10k delivered_alerts the request will hang the worker for several seconds. No async / email-with-link pattern.
  - **No 2FA backup codes.** When the user enables TOTP, there is no list of recovery codes shown. If they lose their phone they're locked out (see T+9min reflection).
- **Missing:**
  - No "Byt e-post" flow.
  - No "Byt lösenord" form on settings (the only path to set a new password is via password reset email — wasteful for an authenticated user).
  - No "Senast inloggad" or "Aktiva sessioner" surface (last_login_at / last_login_ip are stored on the user row, `models/user.py`, but never shown).
  - No notification preferences (only "all subscriptions on" / "unsubscribe everything"). User cannot pause email digests for a vacation week.
  - No team / seat management surface even though plans advertise multi-user.

---

### T+2d — clicks "Uppgradera" on `/app/account`

- **Files:** `account.html.j2:87`, `api/billing.py`.
- **Flow:** `/pricing` → user clicks `Välj Team →` → links to `/auth/signup` (which is wrong if already signed up). There is **no** `/billing/checkout` interactive flow yet because Stripe is gated.
- **Works:** the `_ensure_enabled()` guard at `billing.py:19`–`24` raises 503 with `"billing_not_enabled"` — at least the system is honest.
- **Fails:**
  - **The CTA flow is broken end-to-end.** The pricing card buttons hard-code `/auth/signup` (`pricing.html.j2:91`, `:110`, `:129`). For an already-logged-in user this redirects to `/app` (`auth.py:78`) — but the user *meant* to upgrade. There is no "Buy now" / "Upgrade" path that lands a logged-in user in checkout.
  - When (eventually) a user POSTs to `/billing/checkout`, FastAPI returns a JSON 503 `{"detail":"stripe_checkout_not_yet_implemented"}` — raw JSON, no friendly page.
  - The trial-ending email (e.g., "din provperiod går ut om 3 dagar") **does not exist**. There is no scheduled job for this (verified in `jobs/scheduler.py`). When the trial expires, behavior is undefined: `current_verified_user` only checks `is_active` and `is_verified`, not trial-expired. A trial user keeps full access forever until billing is enabled.
- **Missing:**
  - "Vill du fortsätta?" email at trial-day 11.
  - In-app banner on `/app` for trial-ending users.
  - Friendly 503 page for billing endpoints with copy "Stripe-checkout är temporärt inaktiverad — hör av dig till info@karimkhalil.se så ordnar vi en faktura tills vidare."
  - Annual plan toggle that the pricing page CSS is ready for but never wired up.

---

### T+3d — receives a digest, then clicks "Avregistrera" in the email footer

- **Files:** `digest.py:202`, `:414` (token = `str(user.id)`), `unsubscribe.py:17`–`36`.
- **What happens:** every subscription for that user is set `active=False`. Page renders "Klart. Vi skickar inte mer."
- **Fails (already noted):**
  - No "ångra" button.
  - User-id-as-token security risk.
  - The "ok" message claims "Logga in för att aktivera dem igen" but there is no UI hint inside the app for this — the user must navigate to `/app/subscriptions`, find each one, and there is no bulk "Aktivera alla" toggle (only "Radera").
- **Missing:**
  - Re-engagement email that says "Vi har pausat dina prenumerationer. Var det avsiktligt?".
  - In-app banner "Dina prenumerationer är pausade" on next login.

---

### T+5d — forgets password

- **Files:** `auth.py:351`–`414`, `templates/auth/password_reset_request.html.j2`, `password_reset_confirm.html.j2`, `delivery/templates/reset_password.html.j2`.
- **Works:**
  - Generic copy ("Om e-postadressen finns hos oss…") avoids enumeration.
  - 1-hour token TTL, single-use, audit-logged.
  - Failed-login counter and lockout cleared on password reset (`auth.py:463`–`464`).
- **Fails:**
  - The `password_reset_confirm.html.j2:11`–`13` shows the same minimum-length helper but does not mention the "not in HIBP top-1M" rule (because that rule isn't actually enforced, see T+5min). Inconsistent expectations.
  - **No "Just changed your password" notification email.** A best-practice for credential-change events. After the reset POST succeeds, only the audit log records it — no email.
- **Missing:**
  - Rate limiter for the *confirm* endpoint (only the request endpoint is throttled — `auth.py:362`).
  - 2FA prompt on password reset confirm. If TOTP is enabled and someone steals access to the user's email, they can take over the account; pairing the password-reset confirmation with a 2FA challenge would close that window.

---

### T+6d — lockout from too many failed logins

- **Files:** `auth.py:262`–`287`.
- **Works:** Counter, lockout window, `ACCOUNT_LOCKED` audit row.
- **Fails:**
  - No email to the user ("Ditt konto är låst i 15 minuter — ignorera om du själv är orsaken").
  - No way to unlock except wait — no "kontakta support / svara på det här mejlet" path.
  - Lockout copy doesn't tell the user *when* they can try again (see T+9min reflection).

---

### T+7d — bounced email handling

- **Files:** `api/webhooks.py:37`–`69`.
- **Works:** Signature verification (`_verify_signature`), opened/clicked tracking persists to `delivered_alerts`.
- **Fails:**
  - **Bounce handling is a TODO.** Lines 64–67 explicitly say `# TODO(bounce-policy): aggregate hard bounces over 30d window and flag users.is_active=false on threshold per CLAUDE.md §11.` So a user with a wrong email gets retried indefinitely; Resend / our reputation suffer; the user never knows.
  - There is no in-app banner "Vi kan inte leverera mejl till din adress — uppdatera den i Inställningar."
- **Missing:**
  - 3-bounce policy enforcement.
  - User-side notification.
  - Audit-log of bounce / complaint events.

---

### T+14d — soft-delete & 30-day grace period

- **Files:** `account.py:529`–`545`, `jobs/gdpr.py:69`–`88`.
- **Works:**
  - `gdpr_delete_request` sets `is_active=False`, `deletion_requested_at = now`, audit-logs `GDPR_DELETE_REQUESTED`, redirects to `/`.
  - Nightly `purge_deleted_users` deletes rows older than 30 days.
  - `confirm()` dialog on the form (`account.html.j2:150`).
- **Fails:**
  - **No confirmation email.** GDPR best-practice (and several DSO interpretations of the law) require written confirmation of an erasure request including the grace period. Currently the user gets nothing.
  - **No "ångra" surface in the product.** The copy says "Innan dess kan du återaktivera via support." — meaning the user has to email Karim. No self-serve restore link.
  - The clearing of cookies is partial: `delete_cookie("vittring_session")` runs (`account.py:544`), but `vittring_csrf` is not cleared (see `docs/ui-audit.md` §1.4).
  - There is no test that purge runs only on rows with `deletion_requested_at IS NOT NULL` — easy to break by a future migration.
- **Missing:**
  - Email "Bekräftelse på radering" with a tokenized "Avbryt radering" link valid 30 days.
  - In-app banner if the soft-deleted user logs back in within the grace period: "Kontot är schemalagt för radering om N dagar. Klicka för att avbryta."

---

## Top 5 friction points

1. **The verified=False dead-end.** A successful login that lands a user on a JSON `{"detail":"email_not_verified"}` page is the single most damaging activation moment in the product. Fix order #1 (also `docs/ui-audit.md` §1.2). One-click verification should also issue a session cookie so the user is signed in by clicking the link.
2. **Resend-fail / verify-link silently dropped.** Combined with #1, this is the worst-case path: user signs up → no email arrives → tries to log in → gets JSON. There is **no way for the user to recover without operator intervention** (`auth.py:149`–`168`, no resend endpoint).
3. **Sample-data dashboard pretends to be live.** The day-zero KAM thinks "Postnord söker 18 truckförare" is a real lead; sees the timestamp 14:32 (today) and the "synkad 06:30" pill. A staffing salesperson making prospect-calling decisions on demo data is a credibility detonator.
4. **Plan upgrade is a 503 wall.** Every "Uppgradera" CTA either redirects to `/auth/signup` (which redirects already-logged-in users away) or hits `/billing/checkout` and returns raw JSON 503. There is no friendly "Stripe är på väg — kontakta oss" page. (See T+2d.)
5. **Saved-signal star is invisible feedback.** The most-used micro-interaction in the daily flow ("är det här värt en uppföljning?") returns a full page reload with no visible state change, into a `/app/saved` page that is a "Kommer snart" stub. The product looks broken right where it should feel snappy.

## Top 5 delight opportunities

1. **One-click verification = signed-in.** Make `/auth/verify` set the session cookie and redirect to `/app`. Three steps collapse to one.
2. **First-day "preview digest".** When the first subscription is created, immediately render a digest of yesterday's matching signals as an email and on-page "tomorrow you would have received this" preview. Turns the 24-hour dead zone into a wow moment.
3. **JobTech taxonomy autocomplete in the subscription form.** CLAUDE.md §9.1 already names the taxonomy API — wire it to a `<datalist>` so the user picks "Lagerarbetare" or "Truckförare" from the canonical list, not from imagination. Single biggest activation lever for staffing users new to JobTech.
4. **Staffing-industry preset subscriptions.** Ship 5 ready-made subscriptions ("Lagerarbetare Storstockholm", "Truckförare Skåne län", "Konsultchefer norra Sverige", "Vården region Stockholm", "IT-konsulter Mälardalen") that a user can adopt with one click. Replaces the "what do I even type" cold start.
5. **Trust-building stats in the digest.** Replace the empty-skip behavior with "Idag har Vittring gått igenom 4 982 signaler — inga matchade dina filter. Justera bevakningen?" Even on dry days the user sees the radar is alive. Pair with an end-of-week "veckosammandrag" showing matched / discarded / saved.

---

## Cross-references

- Per-screen UX bugs: `docs/ui-audit.md` (especially §1.1 CSRF, §1.2 verified dead-end, §1.4 cookie cleanup, §1.5 unsubscribe enumeration, §1.7 Resend failure swallowed, §1.9 Bolagsändringar empty step-3).
- Responsive issues: `docs/audit/06-responsive.md`.
- Source files inspected: `src/vittring/api/public.py`, `auth.py`, `account.py`, `subscriptions.py`, `billing.py`, `unsubscribe.py`, `webhooks.py`, `deps.py`, `templates.py`, `main.py`, `security/passwords.py`, `security/ratelimit.py`, `security/csrf.py`, `jobs/digest.py`, `jobs/gdpr.py`, `jobs/scheduler.py`; templates under `api/templates/{public,auth,app}` and `delivery/templates/`.
