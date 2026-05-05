# Dashboard UX audit (in-app surface)

Read-only review of the authenticated app shell (`/app`, `/app/subscriptions`,
`/app/account`, plus stub routes). Auditor: read-only — no code changed.

Files in scope:

- `/home/user/vittring/src/vittring/api/templates/app/dashboard.html.j2`
- `/home/user/vittring/src/vittring/api/templates/app/subscriptions.html.j2`
- `/home/user/vittring/src/vittring/api/templates/app/subscription_form.html.j2`
- `/home/user/vittring/src/vittring/api/templates/app/account.html.j2`
- `/home/user/vittring/src/vittring/api/templates/app/_stub.html.j2`
- `/home/user/vittring/src/vittring/api/account.py`
- `/home/user/vittring/src/vittring/api/subscriptions.py`
- `/home/user/vittring/src/vittring/static/css/brand.css`

---

## 1. Dashboard (`/app`) — `dashboard.html.j2` + `account.dashboard()`

### 1.1 Sidebar navigation

| File:line | Link | Resolves? | Comment |
|---|---|---|---|
| `dashboard.html.j2:162` | `/app` (Digest) | yes | Active item — fine. |
| `dashboard.html.j2:166` | `/app` (Översikt) | "yes" — but it's the **same route** as Digest | Two different labels point to the same URL. Either remove "Översikt" or build a real overview page. |
| `dashboard.html.j2:170` | `/app/calendar` | yes — but renders `_stub.html.j2` "Kommer snart" | Dead-end placeholder. |
| `dashboard.html.j2:179` | `/app/subscriptions` (per-sub link) | yes — but **all rows go to the same list page**, not a per-subscription detail | Looks clickable, behaves identically. |
| `dashboard.html.j2:181` | `/app/subscriptions/new` (+ ny prenumeration) | yes | Fine. |
| `dashboard.html.j2:186` | `/app/saved` | stub | Dead-end. There is a real `saved_signals` table (`models/saved.py`) and a real toggle endpoint (`account.py:385`), but no page to view them. Star button works but the user can never see saved items. |
| `dashboard.html.j2:187` | `/app/archive` | stub | Dead-end. |
| `dashboard.html.j2:188` | `/app/tags` | stub | Dead-end. |
| `dashboard.html.j2:189` | `/app/account` | yes | Settings page. |
| `dashboard.html.j2:200` | POST `/auth/logout` | yes | Hits real handler (`auth.py:330`). |

**Observed:** four out of nine sidebar links lead to placeholder pages and one
duplicates the active route. **Expected:** every link in primary nav should
either work or be visibly disabled.

**Fix idea:** add a `disabled` modifier (e.g. lower opacity + `pointer-events:
none` + tooltip "Snart") for `Kalender / Sparade / Arkiv / Taggar` until those
pages are real. Better: ship a minimal real `/app/saved` page that lists rows
from `saved_signals` since the data already exists. Drop the duplicate
"Översikt" link or repurpose it for a future analytics page.

### 1.2 Topbar

#### 1.2.1 Search form (`dashboard.html.j2:217-222`, `account.py:171-191`)

- **Observed:** form GETs `/app?q=…`. The dashboard handler runs
  `_filter_signals(...)` only against the **hard-coded sample list** — it does
  not query `delivered_alerts`, `job_postings`, `company_changes`, or
  `procurements`. So search works visually for the demo data but does nothing
  meaningful for a real user.
- The value persists (template renders `value="{{ search_query }}"` at
  `dashboard.html.j2:219`) — good.
- **Expected:** search hits real data, ideally with full-text indices on
  `job_postings.headline/description`, `procurements.title/description`,
  `companies.name`.
- **Fix idea:** swap `_filter_signals(sample, q)` for a real query joined
  through `delivered_alerts` once the ingest pipelines populate signals. Until
  then, the filter chips in `dashboard.html.j2:275-278` ("Upphandlingar",
  "Jobb", "Bolagsändringar") are also non-functional decoration — they are
  spans, not links.

#### 1.2.2 CSV export (`dashboard.html.j2:224`, `account.py:329-378`)

- **Observed:** `/app/export.csv` always returns a CSV. For a fresh account it
  returns header only — `delivered_at,signal_type,signal_id,subscription_id,opened_at,clicked_at` —
  no body rows. That is technically valid but the browser silently downloads
  what looks like a broken file.
- The `Content-Disposition` filename is hard-coded to `vittring-export.csv`
  with no date/user suffix.
- **Expected:** when there are zero rows, either return HTTP 204 + a flash
  banner ("Inget att exportera ännu") or include a single comment row like
  `# Inga levererade signaler ännu`. Filename should include
  `vittring-export-YYYY-MM-DD.csv`.
- **Fix idea:** count first; if `len(rows) == 0`, redirect back to `/app` with
  a flash. Add timestamp to filename.

#### 1.2.3 "+ Ny prenumeration" CTA (`dashboard.html.j2:225`)

- Resolves to `/app/subscriptions/new`. Works. Plan-limit check happens on
  POST (`subscriptions.py:81-93`), not on the dashboard CTA — clicking from
  the topbar of a Solo plan with 5 subs takes the user to a form that will
  reject submission. Mildly user-hostile.
- **Fix idea:** disable the CTA (or swap to an "Uppgradera"-link) when the
  user is at plan limit.

### 1.3 Per-row action buttons

#### 1.3.1 Star save (`dashboard.html.j2:299-304` / `334-339`)

- **Observed:** form POSTs to `/app/signals/save` with hidden `signal_type`
  and `signal_id`. Handler at `account.py:385-436` correctly inserts/deletes
  a `SavedSignal` row. The route returns
  `RedirectResponse(f"/app#saved-{signal_id}")` — anchor lands on the row.
- **Critical bug:** the form sends `signal_type=signal.kind_class`, where
  `kind_class` is `"upph" | "jobb" | "bolag"` (`account.py:54-143`). Real
  `signal_type` codes used in the matching engine and in `delivered_alerts`
  are `"job" | "company_change" | "procurement"`
  (`matching/criteria.py:9`, `models/subscription.py:34`). The starred rows
  therefore get persisted with **mismatched type names** and will never join
  back to a real signal. Compounding: the `signal.id` here (1..10) collides
  with real `job_postings.id` once ingest starts.
- The button has no visual "starred" state — every visit shows a plain ★,
  even when the row is already saved. The toggle is silent: nothing in the
  UI tells the user it succeeded.
- **Expected:** correct type names, fill `★` when saved (gold) vs hollow `☆`
  when not, and confirm with an aria-live message.
- **Fix idea:** map `kind_class → signal_type` server-side before insert;
  pass `is_saved` per row from the dashboard query and toggle button class
  accordingly; add `aria-pressed`.

#### 1.3.2 HubSpot button (`dashboard.html.j2:305-309` / `340-344`)

- **Observed:** Pro-plan users see a `<button type="button">` with `title=
  "Skicka till HubSpot"` and **no handler** — clicking does nothing. Non-Pro
  users get a link to `/pricing`.
- **Expected:** the Pro CTA either opens a modal, posts to a route, or is
  hidden until the integration ships. Right now Pro users get a button that
  silently no-ops.
- **Fix idea:** until HubSpot is wired, render the gate for *all* plans
  pointing to a "Kontakta oss"-page, OR remove the button entirely. Don't
  ship a dead button to paying customers.

#### 1.3.3 "Öppna →" (`dashboard.html.j2:310-314` / `345-349`)

- **Observed:** when `signal.url` is set, opens in a new tab. **Every
  sample signal in `_example_signals()` has `url=None`** — so all rows
  silently route to `/app/saved`, which is itself a stub page. End-to-end:
  the primary CTA on every visible row leads to a "Kommer snart" placeholder.
- **Expected:** real signals have source URLs (JobTech ad, TED notice,
  Bolagsverket reference). Sample data should still link somewhere
  meaningful (e.g. `/legal/terms` or a sample modal explaining "this is
  example data").
- **Fix idea:** put plausible mock URLs on the sample data, or render the
  button as disabled + label "Exempeldata".

### 1.4 Empty state — brand-new user

- A fresh user with **no subscriptions and no delivered alerts** still sees
  10 sample signals (`account.py:42-144` runs unconditionally), three
  hard-coded stat cards (`account.py:219-225`: "214 nya signaler",
  "99,5% brus", "7 konverteringar"), the chip filter `Storstockholm,
  SNI 53.* / 52.*` (`account.py:227`), and the heading "Lager & logistik ·
  Storstockholm" (`account.py:214`).
- The sidebar "Prenumerationer" group renders the empty list + only the
  "+ ny prenumeration" link (`dashboard.html.j2:178-182`).
- **No banner explains** any of this is fake. New users have no way to know
  the rows are mock data.
- **Expected:** a welcoming, instructive empty state that:
  1. Acknowledges they have zero subscriptions.
  2. Explains the dashboard will populate after first ingest + match.
  3. Links to "Skapa första prenumerationen" prominently.
- **Fix idea:** render a banner above the feed:
  `"Detta är exempeldata — dina egna signaler dyker upp efter första ingest
  (kl 06:30 dagen efter att du skapat din första prenumeration)."` — only
  when `len(subscriptions) == 0` *or* `delivered_alerts.count() == 0`.

### 1.5 Sample-data leakage (#5 in the brief)

The `_example_signals()` factory at `account.py:42-144` is **always** called
regardless of user state. Issues:

1. References real Swedish companies (Postnord, Schenker, Ahlsell, DSV, DHL,
   Bring, Norrlands Logistik) with **fake events** ("ny VD Helena Berg",
   "nytt säte i Södertälje"). This is reputational risk: a customer could
   take action on fabricated information about a real company. Stat cards
   ("99,5% brus av 4 982 inkomna") imply a working pipeline that does not
   exist.
2. The `digest_focus` literal `"Lager & logistik · Storstockholm"`
   (`account.py:214`) implies the user has filters they never created.
3. Active-filter chips `"Storstockholm", "SNI 53.* / 52.*"` (`account.py:227`)
   are decorative — they don't persist, can't be removed, and don't mirror
   anything in the user's actual subscriptions.
4. The static "● Synkad 06:30" indicator (`dashboard.html.j2:215`,
   `account.py:210`) implies a successful sync that has not happened.

**Expected:** sample data is gated behind a feature flag or only shown to
demo accounts. Stats come from real queries against `delivered_alerts`
(count, week delta) and `audit_log` (last sync from latest ingest job).
Active-filter chips reflect actual saved chip-filter state in URL or
session.

**Recommended banner copy (Swedish, brief):**

> *Detta är exempeldata. Dina egna signaler dyker upp här efter första
> ingest (kl 06:30 svensk tid). Skapa en prenumeration för att börja
> bevaka.*

Render only when `delivered_alerts.count(user) == 0`.

### 1.6 Responsive behavior

`dashboard.html.j2` declares a hard 240px sidebar + 1fr main grid at line 17:

```css
.dash-shell { display: grid; grid-template-columns: 240px 1fr; min-height: 100vh; }
```

There are **zero `@media` queries** in either `dashboard.html.j2`,
`_stub.html.j2`, or `brand.css` (verified via grep). At narrow widths:

- The sidebar stays at 240px; the digest-header grid (`1.6fr 1fr 1fr 1fr`,
  line 76) compresses until stat-card numbers (40px display font, line 80)
  overflow. Confirmed brittle for any viewport <980px.
- The feed `.row` grid (`80px 100px 1fr 200px 120px`, line 99) totals 500px
  fixed plus the 1fr title + 32px gutters; below ~880px content width the
  title column collapses to <100px and wraps awkwardly.
- The topbar (`flex` with hard 32px padding, line 48) wraps the search box
  under the date but preserves both action buttons, often pushing them off
  screen.
- The subscription form's `.sub-form-grid` (CSS not in `brand.css`, defined
  in tokens.css per layout) and the live preview aside likely collapse at
  the same breakpoints.

**Expected:** breakpoints at 1100px (collapse stat cards from 4-up to
2-up), 900px (sidebar → off-canvas drawer behind a hamburger button),
640px (digest-header to single column, row grid to vertical card layout).

**Fix idea:** add a `<style>`-block media query in both `dashboard.html.j2`
and `_stub.html.j2` that converts the shell to single-column ≤900px and
stacks rows ≤640px. The duplicated CSS in two templates is itself a smell —
should move to `brand.css`.

### 1.7 Logout flow

- **Form** at `dashboard.html.j2:200-203`, `_stub.html.j2:143-146`,
  `account.html.j2` (extends `_layout.html.j2` — N/A here), and
  `subscriptions.html.j2` (also via layout) are all `<form method="post"
  action="/auth/logout">`.
- **CSRF:** `{{ csrf_input() }}` is present in both dashboard and stub —
  good. The macro is registered at `templates.py:36`.
- **Handler** at `auth.py:330-344` audits the action then `RedirectResponse
  ("/", 303)` and `response.delete_cookie(ACCESS_TOKEN_COOKIE)` where
  `ACCESS_TOKEN_COOKIE = "vittring_session"` (`deps.py:14`).
- **Issue:** `delete_cookie` is called without specifying the `path`,
  `domain`, `secure`, or `samesite` attributes. If the session cookie was
  set with `path=/` and `samesite=Lax` (typical) the bare deletion may not
  expire the cookie in all browsers. Verify in
  `_set_session_cookie(...)` (`auth.py:59-...`) that defaults match.
- **Fix idea:** mirror `set_cookie`'s attributes in `delete_cookie`:
  ```python
  response.delete_cookie(
      ACCESS_TOKEN_COOKIE, path="/", samesite="lax", secure=True
  )
  ```

### 1.8 Filter chips (decorative)

`dashboard.html.j2:275-283` renders `Alla typer / Upphandlingar / Jobb /
Bolagsändringar` as `<span class="chip">` — no `<a>`, no form. The active
state is hard-coded. The "+ filter" chip on line 283 is also a no-op span.

**Fix idea:** wire each chip to a query parameter, e.g. `?type=jobb`, and
make `_filter_signals` honor the type. Or remove the chips entirely if
filtering is out of scope for v1.

---

## 2. Subscriptions list (`/app/subscriptions`) — `subscriptions.html.j2`

### 2.1 Empty state (lines 73-99)

- **Observed:** clean empty state with three example badges (Lagerarbetare
  Storstockholm, Truckförare Skåne län, Konsultchefer norra Sverige) and a
  primary CTA. Copy explains what a subscription is. **This is the strongest
  empty state in the app** and a model for the dashboard to follow.
- **Minor:** the badges are static (no click handler). Making them
  click-to-prefill would be a nice 5-minute upgrade.
- **Fix idea:** wrap each badge as
  `<a href="/app/subscriptions/new?example=lager-storstockholm">…</a>` and
  parse the prefill server-side or via JS.

### 2.2 Status pip rendering (lines 46-52)

- **Observed:** binary `Aktiv / Pausad`. The schema (`subscription.py:36`)
  exposes `active: bool` but there is **no UI to toggle active/paused** —
  the only actions are Duplicera, Radera. So `Pausad` can never appear via
  the UI; it would only show if pausing was set out-of-band.
- **Expected:** offer a pause toggle next to delete, since the column
  exists.
- **Fix idea:** add a `<form method="post" action="/app/subscriptions/{id}/toggle-active">`
  with a small switch component.

### 2.3 Delete confirmation (lines 59-63)

- **Observed:** `onsubmit="return confirm('Radera prenumerationen {{ sub.name
  }}?');"`. Native browser dialog. CSRF input present.
- The dialog interpolates `sub.name` directly into a JS string. If a
  user names their subscription with a single quote (`'`), the JS breaks.
- **Fix idea:** server-side, escape single quotes before passing to the
  template, or move to a styled modal that reads the name from a `data-`
  attribute.

### 2.4 Sidebar context

- `subscriptions.html.j2` extends `_layout.html.j2` (the **public/marketing**
  layout), not the `dash-shell`. The user signs in to a dark dashboard,
  clicks "Prenumerationer" or "Inställningar", and lands on the **public
  light theme** — which is also missing the dashboard sidebar. This is a
  serious context break.
- **Fix idea:** introduce a shared `app_layout.html.j2` that contains the
  dark `dash-side` + topbar from `dashboard.html.j2` + `_stub.html.j2` (the
  CSS is currently duplicated three times) and have all `/app/*` views
  extend it.

---

## 3. Subscription form (`/app/subscriptions/new`) — `subscription_form.html.j2`

### 3.1 Layout

- Extends `_layout.html.j2` — same theme break as §2.4.

### 3.2 Visibility toggling (`data-needs`)

- **Observed:** the script at lines 297-314 reads `data-needs="job
  procurement company_change"` (line 90) and shows/hides the field if any
  active checkbox value matches. It also `disabled = true` hidden inputs
  so they don't post.
- **Verified consistent values:** form checkboxes use `value="job" |
  "company_change" | "procurement"` (lines 51, 60, 69) — matches the
  matching engine's `SignalType` literal (`matching/criteria.py:9`). Good.
- **Edge case (lines 102-112):** `Län` field is `data-needs="job
  company_change"` — but procurements also have a `municipalities` field
  via the buyer (mentioned in CLAUDE.md §10). If a user picks only
  procurement, they can set `municipalities` (line 90, includes
  `procurement`) but not `counties`. Inconsistent — either both or
  neither.

### 3.3 Live preview (lines 421-482)

- Reads form values, builds prose from a templated sentence. Functional and
  pleasant.
- **Bug:** `buildProse()` adds `'i ' + (muns || cnts)` (lines 366-371). If
  `muns` is set but `cnts` is also set, only `muns` shows — county info is
  silently dropped. Cosmetic but mismatched with the filters list (which
  shows both).
- **Bug:** the sentence concatenates with raw spaces and runs `replace(/\s+
  /g, ' ')`. If a user enters trailing punctuation in occupations or
  keywords, you get sentences like `"Jobbannonser för roller som
  Truckförare, in i hela Sverige"`. Defensible for v1 but worth a note.
- **Tip text** (lines 472-481) is adaptive — nice touch.

### 3.4 Validation

- **Server-side** (`subscriptions.py:60-127`): no validation that
  `signal_types` is non-empty. The `Annotated[list[str], Form()]` will
  raise 422 if absent (FastAPI default), which produces a generic error,
  not the friendly Swedish message the user expects. The client disables
  the submit button at line 329, but JS-disabled users can still POST a
  bare form.
- **Server-side: name length** is enforced only by the `maxlength="120"`
  HTML attribute (line 38). No backend check.
- **Server-side: SNI / CPV** input pattern is enforced only via HTML
  `pattern="[0-9, ]*"` (lines 134, 185). The handler accepts and trims any
  string; non-numeric tokens silently pass.
- **`min_procurement_value_sek`** (lines 196-204) — `int(...)` raises
  `ValueError` on bad input (e.g. `"50 000"` with a non-breaking space) →
  500. Should be caught and re-rendered with `error="…"`.
- **Plan limit** (`subscriptions.py:81-93`) returns 402 + the form with the
  red error banner — clean. But the form clears the user's input on a 402
  re-render because it doesn't re-populate fields from POST. Annoying for
  someone who typed a long config and got slapped with the limit.
- **Fix idea:** add a Pydantic schema for the form, validate, return
  field-level errors, and pre-populate the form on re-render.

### 3.5 Aside preview hidden on narrow viewports

- The `.sub-form-grid` has no documented mobile fallback in `brand.css`.
  Likely defined in `tokens.css` or inline; if not, the live preview will
  squeeze the form to <300px wide.

---

## 4. Account / settings (`/app/account`) — `account.html.j2`

### 4.1 Profile section (lines 14-42)

- **Observed:** read-only — no "Edit"-link. There is no `POST /account
  /update` route. Per CLAUDE.md §14 "Rectification: profile editing
  endpoints" — this is a **GDPR gap**. Users cannot rectify name or
  company_name without contacting support.
- **Fix idea:** add a `<form method="post" action="/app/account/update">`
  for `full_name` and `company_name`; require re-verification on email
  change.

### 4.2 Plan section (lines 44-90)

- **Observed:** clean. "Trial" gets a clear CTA "Uppgradera" → `/pricing`.
  Trial expiry uses `(user.trial_ends_at - user.created_at).days` (line 64)
  to derive days, but never shows "X dagar kvar" — only the absolute end
  date. Less actionable.
- **Fix idea:** show "X dagar kvar" alongside the date when trial is
  active.

### 4.3 Security / 2FA (lines 92-124)

- **Observed:** form submits `POST /auth/2fa/disable` directly with **no
  confirmation dialog**. Disabling 2FA is a destructive security action;
  it should require confirmation (current TOTP code or password).
  `auth.py:521` is `@router.post("/2fa/disable")` — verify it actually
  re-prompts; if not, this is a meaningful security regression.
- The "Aktivera" link (line 121) is `<a href>` — fine, it's a GET.
- **Fix idea:** require current TOTP token in the disable form, or at
  least an `onsubmit` confirm.

### 4.4 GDPR — Export (lines 134-140, `account.py:458-526`)

- **Observed:** `GET /app/account/export` returns
  `JSONResponse(payload, headers={"Content-Disposition": f"attachment;
  filename=vittring-export-{user.id}.json"})`. Works.
- The audit row is written **before** the response is returned — but the
  audit `await` runs inside the request, so on commit it persists. Fine.
- The `audit_metadata` field is read off the AuditLog row at line 506 —
  verify the model attribute is named that (it's the JSON column rename
  for the `metadata` clash with SQLAlchemy DeclarativeMeta).
- The export is a single in-memory JSON build. For a power user with 10k+
  delivered alerts this could OOM the worker on the CX23. **Streaming**
  recommended via `StreamingResponse`.
- The button is a `<a class="btn">` not a `<button type="submit">` — works
  for a GET, but the export **mutates** state by writing an audit row. Any
  bot/preloader hitting the link writes an audit. This is the GET-with-side-
  effects anti-pattern.
- **Fix idea:** switch to `<form method="post">`; or move audit write to
  POST-only and have the GET only fetch.

### 4.5 GDPR — Delete (lines 141-154, `account.py:529-545`)

- **Confirmation copy:** "Är du säker? Kontot inaktiveras nu och raderas
  slutgiltigt om 30 dagar." — accurate, but uses `confirm()`. Default
  browser dialogs are unstyled and dismissible by Enter. For an
  irreversible action, a styled modal with a typed confirmation
  ("Skriv RADERA för att bekräfta") is industry standard.
- The handler at `account.py:529-545` sets `deletion_requested_at`,
  `is_active = False`, audits, deletes the cookie, and redirects to `/`.
  **It does not commit the session** — relies on the dependency-injected
  session auto-commit. If `commit_on_session_close=False`, the deletion
  never persists. Worth verifying in `db.py`.
- The handler also calls `response.delete_cookie("vittring_session")` with
  no path argument — same concern as §1.7.
- **Fix idea:** typed confirmation modal; verify session commit; mirror
  cookie attributes.

---

## 5. Stub pages (`_stub.html.j2`)

### 5.1 Layout duplication

- The stub template duplicates ~150 lines of the dashboard's sidebar +
  topbar CSS. Any sidebar style fix has to be made in two places.
- **Fix idea:** extract to `brand.css` or to a shared partial.

### 5.2 Active state inconsistency

- Stubs receive `active="calendar"|"saved"|…` and conditionally apply
  `.active` to the right `nav-item` (`_stub.html.j2:105-117`). The
  dashboard template (`dashboard.html.j2:162`) hard-codes the active state
  on Digest. So if you navigate to `/app/saved` and back to `/app`, the
  `Saved` link doesn't keep its hover affordance. Cosmetic.

### 5.3 No "Notify me when ready" capture

- Stubs say "Kommer snart" but offer no email-me-when-ready capture or
  date estimate. A user who clicks four sidebar items and hits four
  identical placeholders forms a "this app is unfinished" impression.
- **Fix idea:** hide stub links from the sidebar in production, OR add a
  "Få besked när det är klart"-checkbox that toggles a flag on the user.

---

## 6. Cross-cutting issues

| # | Issue | Severity |
|---|---|---|
| C1 | `dashboard` and `_stub` duplicate the topbar + sidebar CSS instead of sharing a layout | medium |
| C2 | Sample data is rendered for *every* user including production — fabricated events about real Swedish companies | high |
| C3 | Saved-signal `signal_type` mismatch (`upph/jobb/bolag` vs `job/company_change/procurement`) | high (data integrity) |
| C4 | Sidebar links to four stub pages that say "Kommer snart" | medium |
| C5 | Search bar filters mock data only | medium |
| C6 | No mobile / tablet layout — zero `@media` queries | high (any phone visit is broken) |
| C7 | Profile is read-only — GDPR rectification gap | high (compliance) |
| C8 | GET-with-side-effects on `/app/account/export` (writes audit) | medium |
| C9 | HubSpot button on Pro plan does nothing | medium |
| C10 | "Öppna →" on every sample row goes to a stub | medium |

---

## Prioritized list

### P0 — must fix before any external user sees the dashboard

1. **C2 / §1.5 Sample-data leakage.** Hide or banner-flag fake signals.
   Either gate `_example_signals()` behind `if user.email.endswith("@vittring.se")`
   or render with a clear "EXEMPELDATA" overlay.
2. **C3 / §1.3.1 Star-save type mismatch.** Map `kind_class → signal_type`
   before insert. Audit existing rows and reset.
3. **C6 / §1.6 No responsive layout.** At minimum, collapse sidebar to
   off-canvas at <900px.
4. **C7 / §4.1 Profile rectification.** Add `POST /app/account/update`.

### P1 — fix this sprint

5. **§1.1 Sidebar dead links.** Either ship `/app/saved` (data exists) or
   visually disable.
6. **§1.4 New-user empty state.** Banner explaining sample data + clear
   "Skapa första prenumerationen" CTA.
7. **§4.5 GDPR delete dialog.** Replace `confirm()` with typed-confirmation
   modal.
8. **§1.7 / §4.5 Cookie-deletion attributes.** Mirror set/delete.
9. **§3.4 Form re-population on plan-limit error.** Don't trash user input.
10. **§4.4 Export GET → POST.** Stop writing audit on GET.

### P2 — polish this quarter

11. **C1 / §5.1 Layout consolidation.** One `app_layout.html.j2`.
12. **§1.2.1 Wire search to real data.**
13. **§1.8 Filter chips clickable + persisted in query.**
14. **§2.2 Pause/resume toggle for subscriptions.**
15. **§4.3 Require TOTP / password to disable 2FA.**

---

## Polish wins (each ≤ 15 minutes)

1. **Add days-left to trial badge.** `account.html.j2:64` — interpolate
   `(user.trial_ends_at - now).days` next to the date.
2. **Filename timestamp on CSV export.** `account.py:376` — change to
   `vittring-export-{user.id}-{date}.csv`.
3. **Disable "+ Ny prenumeration" topbar CTA at plan limit.**
   `dashboard.html.j2:225` — gate on `subscriptions|length >= plan_limit`.
4. **Fix "Översikt" duplicate route.** `dashboard.html.j2:166` — either
   remove or repurpose to `/app#stats`.
5. **Make subscriptions empty-state badges clickable prefills.**
   `subscriptions.html.j2:94-96` — wrap in `<a>`.
6. **Strip the static "Synkad 06:30" pill until ingest is real.**
   `dashboard.html.j2:215`.
7. **Set `aria-pressed` on the star button** + change icon to filled when
   saved. Adds ~6 lines to `dashboard.html.j2:303`.
8. **Hide HubSpot button on free/Solo/Team plans entirely** instead of
   linking to `/pricing`. `dashboard.html.j2:305-309`.
9. **Add `target="_blank" rel="noopener"` consistency** — present on lines
   311 and 346 already, but add to other external links.
10. **Add `loading="lazy"` to the Google Fonts link** in dashboard +
    stub — the duplicated font load runs on every page.
11. **Wrap the delete-subscription confirm name in
    `{{ sub.name|escape }}`** for the JS string at
    `subscriptions.html.j2:60`.
12. **Trim trailing periods in `buildProse()`** — `subscription_form.html
    .j2:390` — when occupations or keywords end in punctuation.
13. **Replace `<span class="chip">+ filter</span>` with a real button or
    drop it.** `dashboard.html.j2:283`.
14. **Show a flash message after star save** — currently silent.
    `account.py:434-436` already redirects with anchor; pair with a
    session flash + 3-second toast.
15. **Replace stub-page descriptions with a single `data-stub` lookup
    table.** Removes four near-identical handlers in `account.py:257-322`.
