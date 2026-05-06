# 07 — Accessibility audit

Read-only audit of the Vittring Jinja2 templates under
`src/vittring/api/templates/` and the brand stylesheet at
`src/vittring/static/css/brand.css`. The audit is grouped by the four
WCAG 2.1 principles (Perceivable, Operable, Understandable, Robust) and
closes with the top 10 quick wins.

Severity legend:

- **Blocker** — likely WCAG AA failure, blocks users who depend on
  assistive tech.
- **Major** — meaningful accessibility regression, fixable without
  redesign.
- **Minor** — polish, defensive markup, future-proofing.

---

## 1. Perceivable

### 1.1 Color contrast (WCAG 1.4.3 / 1.4.11)

The brand palette in `brand.css` is heavy on dark surfaces (`--v-night`
`#0F1410`, `--v-night-2` `#181E18`) with mid-grey text
(`--v-mist` `#C8CCC4`) and muted greys (`--v-ink-3` `#6B6256`,
`--v-ink-4` `#9A9082`). Eyeballed pairings against the WCAG 4.5:1
(normal) / 3:1 (large) thresholds:

| Foreground | Background | Estimated ratio | WCAG normal text | Notes |
|---|---|---|---|---|
| `--v-mist` `#C8CCC4` | `--v-night` `#0F1410` | ~12:1 | Pass | Default body text — fine. |
| `--v-mist` | `--v-night-2` `#181E18` | ~11:1 | Pass | Dashboard main column — fine. |
| `--v-paper` `#F5F1EA` | `--v-night` | ~16:1 | Pass | Heading text — fine. |
| `--v-ink-4` `#9A9082` | `--v-night` | **~5.6:1** | Pass (just) | Used heavily for `<small>`-class meta text. Borderline at smaller font sizes. |
| `--v-ink-4` | `--v-night-2` | **~5.0:1** | Pass (just) | Same caveat — used for footer copyright (12 px), `t-eyebrow`, dashboard meta. |
| `--v-ink-3` `#6B6256` | `--v-night` | **~3.0:1** | **Fail** at normal text | Used as ghost-button border and as the `t-eyebrow` tone in some places. Acceptable for non-text UI but **fails** if applied to body text. |
| `--v-signal` `#B8E04A` on `--v-signal-ink` `#2A3A0A` | — | ~10:1 | Pass | Primary CTA button (`v-button--signal`). Strong contrast. |
| `--v-signal` `#B8E04A` on `--v-night-3` `#232A23` | — | ~10:1 | Pass | Sidebar active-nav text. Fine. |
| `--v-amber` `#C8753E` on `--v-night-2` | — | **~3.6:1** | **Fail** for normal text | Used for warning badges, admin-mode active items, danger-button border. Borderline — only safe at >=18 pt or 14 pt bold. The admin sidebar `nav-item.active` (`color: var(--v-amber)`) is rendered at `font-size: 13px`, **failing AA**. |
| `--v-signal` `#B8E04A` on `--v-night` | — | ~10:1 | Pass | OK for accents. |
| `rgba(184,224,74,0.04)` highlight on `--v-night` | — | n/a | n/a | Priority-row tint is decorative; the priority indicator should not rely on it (already uses a solid 3 px left border, good). |
| Auth-error: `--v-amber` text on `rgba(200,117,62,0.1)` | — | **~3.5:1** vs effective bg | **Fail** | The 10 % alpha tint is essentially night-2 underneath; result is roughly the same as amber-on-night-2. Use a brighter foreground (e.g. `var(--v-amber-3)` `#F0DBC8`) for error copy. |
| `--v-ink-4` placeholder in dashboard search vs `--v-night-2` | — | ~5.0:1 | Pass | OK, but placeholder text should never be the only label. |

**Findings**

- **Blocker** — `admin/_layout.html.j2` `.nav-item.active` colors active
  sidebar text in `--v-amber` `#C8753E` on `--v-night-3` background at
  13 px. Estimated 3.4:1 — fails AA for normal text. Same issue for
  the chip-style active filter pill in the admin theme.
- **Major** — `auth/_auth_base.html.j2` `.auth-error` uses amber on a
  10 % amber tint. Hard to read for users with low vision; fails AA.
- **Major** — Dashboard meta lines (`var(--v-ink-4)` at 10–11 px in
  `.row .meta`, `.row .src`, `.preview-subtitle`, footer copyright) sit
  right at AA. Anything below 12 px in `--v-ink-4` should be lifted to
  `--v-mist` or made larger.
- **Minor** — `--v-ink-3` is used for a few icon strokes
  (`v-button--ghost` border `rgba(20,17,13,0.18)`); fine for
  non-essential UI but should be checked if it ever holds text.

### 1.2 Images and SVGs (WCAG 1.1.1)

All graphics in the templates are inline `<svg>` (radar dial, brand
mark, chart sparklines, arrow paths in nav icons). None of them carry
`<title>`, `aria-label`, `aria-labelledby`, or `aria-hidden="true"`.

- **Major** — Decorative SVGs (radar background dials in
  `landing.html.j2` lines 150–161 and 414–422; `auth/_auth_base.html.j2`
  lines 79–86; `pricing.html.j2` lines 53–60; `testimonial-block`
  lines 353–361) should each carry `aria-hidden="true"` and
  `focusable="false"` so screen readers skip them. They currently
  produce empty announcements ("Group, group, group…") in some
  readers.
- **Major** — Meaningful SVGs need an accessible name. The brand mark
  in `_layout.html.j2` (lines 64–69) and the duplicate in the footer
  (lines 95–100) sit inside a link with the visible text "Vittring";
  the SVG is decorative there, so `aria-hidden="true"` on the SVG is
  enough. The same logo in `dashboard.html.j2` (lines 152–156) and
  `_stub.html.j2` (lines 95–100) is also next to the word "Vittring",
  so decorative — but should still be marked as such.
- **Major** — The pricing-card check / dash icons (`pricing.html.j2`
  lines 83–89 etc.) convey "included / not included". They should be
  given `role="img"` plus `aria-label="Ingår"` / `aria-label="Ingår
  inte"`, or be replaced with text + a hidden visual cue.
- **Minor** — SVG icon strokes use `currentColor` (good — inherits the
  link colour) but fix `focusable="false"` to avoid IE11/older Edge
  tab-stops on SVGs.

### 1.3 Use of color (WCAG 1.4.1)

- **Major** — Dashboard `.row.priority` is communicated by both a 3 px
  signal-green left border *and* a tinted background, which is good.
  But the chip toggle in `.filter-bar` uses only colour to indicate
  selected state (`active` adds green text and a subtle background).
  Add an `aria-pressed`, a checkmark, or a visible label change.
- **Major** — The admin user table communicates `verified`, `active`
  and `locked` via colored `<span class="pip">` dots, with the only
  text alternative in a `title=""` attribute. Tooltips do not satisfy
  1.4.1; replace with visible text labels (already present elsewhere)
  or add `<span class="visually-hidden">Verifierad</span>`.
- **Major** — `admin/email.html.j2` lines 50–51 use a coloured
  bullet-glyph (`<span style="color: var(--v-signal);">●</span>`) plus
  the timestamp to communicate "opened". Use `aria-hidden` on the
  bullet and add a visible "Öppnad" / "Klickad" label so the meaning
  is not colour-only.

### 1.4 Reduced motion (WCAG 2.3.3)

`brand.css` defines an animated radar pulse:

```
@keyframes v-pulse { ... }
.v-radar-dot::before, .v-radar-dot::after { animation: v-pulse 2.4s … infinite; }
```

The dashboard, login aside, hero, final CTA and final-cta-radar all
re-use this dot or a similar SVG set. There is no
`@media (prefers-reduced-motion: reduce)` override anywhere in
`brand.css`, `tokens.css`, `main.css`, or any inline `<style>` block.

- **Major** — Add a global `@media (prefers-reduced-motion: reduce)`
  rule that disables `.v-radar-dot::before/::after` animation, removes
  the `transform: scale(...)` hover transitions on `.row`, `.btn`,
  `.v-button`, and the FAQ `details` `transform: rotate(45deg)`.

### 1.5 Form labels and field hints (WCAG 1.3.1, 3.3.2)

Most `<input>` elements have a real `<label for="…">` (`auth/login`,
`auth/signup`, `auth/2fa_enable`, `auth/password_reset_*`,
`admin/user_new`, `admin/user_detail`, `app/subscription_form`,
`app/account` — note the latter has no inputs).

- **Pass** — Login, signup, password-reset, 2FA-enable, password-reset
  confirm: every input is paired with a real `<label for>`.
- **Pass** — Subscription-form fields all have explicit labels and
  field hints.
- **Major** — Dashboard search (`dashboard.html.j2` line 219) only has
  `aria-label="Sök bolag, CPV eller ort"` and `placeholder="Sök bolag,
  CPV, ort…"`. The aria-label is good, but the visible label is missing;
  consider a visible label or icon button so sighted keyboard users
  understand what the field does.
- **Major** — Admin filter inputs (`admin/users.html.j2` lines 14–15,
  `admin/audit.html.j2` lines 20, `admin/signals.html.j2` line 26,
  `admin/subscriptions.html.j2` line 14) have **no** `<label>` and no
  `aria-label`. Placeholder is the only cue. Same for the trigger /
  submit buttons that use only an emoji (`▶ Trigga`).
- **Major** — The 2FA secret display (`auth/2fa_enable.html.j2` line 9)
  is shown as `<code>` with `user-select: all`. Add a real
  "Kopiera"-knapp with `aria-label="Kopiera hemlig nyckel"` and an
  `aria-live` region that confirms the copy.

---

## 2. Operable

### 2.1 Semantic HTML (WCAG 1.3.1, 4.1.2)

- **Pass** — `_layout.html.j2` uses `<nav>`, `<main>`, `<footer>`
  correctly. Brand mark is a real `<a>` link.
- **Pass** — Dashboard uses `<aside>` for sidebar and `<main>` for
  feed. Auth grid uses `<aside>` for the testimonial column.
- **Major** — Dashboard `.dash-side` is `<aside>` but has no
  `aria-label`/`aria-labelledby`. Add `aria-label="Huvudnavigation"` so
  screen readers know what region they are in.
- **Major** — Public footer is a `<footer>` (good) but its column
  headings are styled `<div class="t-eyebrow">`. They should be
  `<h2>` or `<h3>` so they appear in the document outline.
- **Blocker** — The dashboard filter chips
  (`.filter-bar` lines 273–284) and the digest header chips
  (`.chip active`, lines 244–246) are rendered as
  `<span class="chip">`. They look like buttons (cursor: pointer,
  hover style, the "×" inside) but they are not interactive elements.
  Either make them `<button type="button">` (preferred) or `<a>` with
  a real href, and give the close × its own
  `<button aria-label="Ta bort filter">`.
- **Blocker** — Dashboard `.actions` open/HubSpot affordance:
  - `<button type="button" class="icon-btn" title="Skicka till HubSpot">↗ HubSpot</button>` — the visible text is the arrow + the word HubSpot which is fine, but the equivalent on lines 341 / 346 is **only** "↗" or "→" with a `title=""`. Tooltips are not accessible names. Add `aria-label` (Swedish: "Skicka till HubSpot", "Öppna källa"). The "★" save buttons have only the glyph; same fix needed (`aria-label="Spara signal"`).
- **Major** — `<span class="chip"><span class="x">×</span></span>`: the
  close glyph is rendered as a span inside a non-button. After making
  the chip a button, give the × an `aria-hidden="true"`.
- **Major** — Auth pages render the page heading as `<h1 class="auth-h1">{{ ... }}<em>tillbaka</em>.</h1>`. The
  `<em>` is used purely for italic display; that is allowed but
  ensure it is not also being relied on for emphasis.
- **Minor** — Several anchor tags wrap entire card-style elements (e.g.
  the dashboard sidebar nav links and the admin user table cells).
  Audit that the link only wraps the focusable target — currently OK.
- **Minor** — The unsubscribe page (`unsubscribe.html.j2`) does not have
  a confirmation `aria-live` region; the success state is
  static — fine for a redirected GET, but if we ever add HTMX, add a
  live region.

### 2.2 `<button>` vs `<a>` (WCAG 4.1.2)

- **Major** — `<a href="…" class="icon-btn primary">Öppna →</a>` is a
  link (correct, opens external content). But the same visual
  affordance is used for the chips (filter / status), the digest
  header pills, and the search submit (which is correctly a button).
  Audit each `.icon-btn` / `.chip` / `.btn`: any element that triggers
  a state change rather than navigation must be a `<button>`.
- **Pass** — Logout, save signal, delete signal, admin trigger /
  toggle are all real `<form>` POSTs with `<button type="submit">`.
  Good.
- **Major** — Pricing toggle on `pricing.html.j2`:
  `<div class="toggle"><button>...</button></div>` — the buttons have
  no `type="button"`, are not inside a form, and have no `aria-pressed`
  state. Fix: add `type="button"` (default-submit can break JS-less
  fallbacks) and `aria-pressed="true|false"`.

### 2.3 Keyboard navigation (WCAG 2.1.1, 2.4.7)

- **Blocker** — Dashboard `.row .actions` is `opacity: 0` until
  `.row:hover` (`dashboard.html.j2` lines 112–113). Keyboard users
  cannot reveal them. Add a sibling rule:
  `.row:focus-within .actions { opacity: 1; }` and consider
  `prefers-reduced-motion` to disable the opacity transition. Same
  pattern likely applies to admin tables (`tr:hover td` is just a
  visual, but if buttons inside ever get the opacity treatment).
- **Blocker** — There is **no skip-to-content link**. With a 240 px
  sidebar full of nav items, keyboard users must tab through every
  link to reach the digest feed. Add
  `<a href="#main-content" class="skip-link">Hoppa till huvudinnehåll</a>`
  as the first child of `<body>` and a visible `:focus` style.
  `<main>` should carry `id="main-content"`.
- **Major** — `:focus-visible` styles. `brand.css` defines no global
  `:focus-visible` rule. Most inputs have
  `border-color: var(--v-signal)` on focus (good) but interactive
  elements like `.icon-btn`, `.nav-item`, `.chip`, `.btn`, `.v-button`,
  the FAQ `<summary>`, pricing toggle, footer links and brand link
  rely on the browser default outline. On the dark backgrounds the
  default outline is often invisible. Add a global rule:

  ```
  :focus-visible {
    outline: 2px solid var(--v-signal);
    outline-offset: 2px;
    border-radius: 2px;
  }
  ```

- **Major** — `<details>` summary in the FAQ (`landing.html.j2`)
  removes its native marker (`::-webkit-details-marker { display: none }`)
  and overrides `cursor: pointer`. Default `<summary>` keyboard
  behaviour is preserved by browsers, but the visible focus ring
  should be tested explicitly.
- **Major** — Several visible interactive elements have no obvious
  focus state in dark mode: the dashboard nav links rely only on a
  background change on hover; the same rule needs to fire for
  `:focus-visible`.
- **Minor** — No `tabindex` overrides found — DOM order matches visual
  order. Good.

### 2.4 Focus order and traps (WCAG 2.4.3, 2.1.2)

- **Pass** — No JS-based modal or trap was found.
- **Minor** — Subscription form preview is in an `<aside>` to the right
  of the form and outside the `<form>`. Tab order goes form → aside,
  which is fine.

### 2.5 Hover-only affordances (WCAG 2.1.1, 2.5.7)

See 2.3 — the most critical issue is `.row .actions` being
opacity-gated on hover. Also:

- **Major** — `.v-button:hover { background: var(--v-night); }` is
  the only state change for the primary button. Pair it with an
  identical `:focus-visible` change so keyboard users see the same
  affordance.

### 2.6 Skip link (WCAG 2.4.1)

- **Blocker** — No skip link anywhere. See 2.3.

---

## 3. Understandable

### 3.1 Language (WCAG 3.1.1, 3.1.2)

- **Pass** — Every template root carries `<html lang="sv">`. No mixed
  inline-language fragments need `lang="…"` annotations; "HubSpot",
  "Logout", etc. are accepted Swedish loanwords or proper nouns.

### 3.2 Heading hierarchy (WCAG 1.3.1, 2.4.6)

| Page / template | Hierarchy | Issues |
|---|---|---|
| `public/landing.html.j2` | h1 (hero) → h2 (How it works) → h2 (Tre signaltyper) → details>summary (no h-levels) → h2 (FAQ heading) → h2 (Final CTA) | OK; only one h1. The FAQ summary text is not a heading, which is correct. |
| `public/pricing.html.j2` | h1 (Tre planer) → no h2/h3 | Pricing card titles are `<div class="price-name">` — should be `<h2>` per card so the AT can list the plans. **Major**. |
| `public/legal_terms.html.j2` / `legal_privacy.html.j2` | h1 → h2 → h2 → h2 | Pass. |
| `auth/_auth_base.html.j2` (login, signup, etc.) | h1 (page) | Pass. |
| `app/dashboard.html.j2` | h5 (sidebar group label) appears **before** h1 (digest count) in DOM | **Major**: the sidebar uses `<h5>` ("Idag", "Prenumerationer", "Bibliotek") and the page h1 lives later. h5s are skipping levels. Solution: lower the sidebar group labels to `<div class="nav-section-title" role="presentation">` styled the same, or raise the digest h1 to h1 and sidebar groups to `<h2>` *or* hide the sidebar groups from the outline. Easiest: convert sidebar group labels to non-heading elements. |
| `app/subscriptions.html.j2` | h1 → h2 (empty state) | OK; no h2 when list is non-empty, which is fine. |
| `app/subscription_form.html.j2` | h1 → h2 (per step card) → h3 (preview aside) | OK. |
| `app/account.html.j2` | h1 → h3 sections | **Major**: skips h2. The card-section heads use `<h3>` directly under `<h1>`. Promote them to `<h2>`. |
| `auth/2fa_enable.html.j2` | h1 only | OK. |
| `admin/_layout.html.j2` | topbar `<h1>` (`Användare` etc.) plus page `<h1>` in `page-header` | **Blocker**: every admin page renders **two h1 elements** — one in the topbar (line 67–69) and one in the page header (e.g. `users.html.j2` line 8). One must become `<p class="topbar-title">` or be demoted. |
| `admin/overview.html.j2` | h1 (page) → div.section-title (no heading element) → h2 (card-h2 in subgrid cards) | **Major**: `.section-title` ("Plan", "Aktivitet") is a `<div>` styled as a heading. Should be `<h2>`. Also h5s in sidebar (see dashboard). |
| `admin/email.html.j2` | h1 → h2 → table | OK (besides duplicate h1). |
| `admin/system.html.j2` | h1 → h2 (card-h2) per card | OK (besides duplicate h1). |
| `admin/audit.html.j2` | h1 → table | OK (besides duplicate h1). |
| `admin/signals.html.j2` | h1 → tabs (links, no h2 between) | OK. |
| `admin/user_detail.html.j2` | h1 → h2 (card-h2) → div.section-title (Prenumerationer, Senaste aktivitet, Senaste leveranser) | **Major**: `.section-title` is a div — promote to `<h2>`. |
| `admin/user_new.html.j2` | h1 only | OK (besides duplicate h1). |
| `app/_stub.html.j2` | h1 (stub-title), no other h | OK; the topbar shows the stub title in a span which is fine. |

### 3.3 Link text (WCAG 2.4.4, 2.4.9)

- **Major** — "Öppna →" is borderline; users navigating by link list
  hear *Öppna, Öppna, Öppna…*. Replace with descriptive text such as
  "Öppna {{ signal.title }}" via `aria-label` (preserve visible
  "Öppna →"):
  `<a aria-label="Öppna {{ signal.title }}">Öppna →</a>`. Same pattern
  for the bare "→" / "↗" arrows in the non-priority rows.
- **Major** — Footer links "Om Vittring", "Kontakt", "Priser",
  "Dashboard", "Starta provperiod" appear three times each (sitemap +
  footer + nav). Each link text is OK, but mark up the footer
  navigation with `<nav aria-label="Sidfot">` so AT can distinguish it
  from the main nav.
- **Minor** — Several "Hör av dig direkt" / "Kontakta support" CTAs
  reuse `mailto:` — fine. "Kontakt" alone is a bit thin but
  contextual.

### 3.4 Errors and feedback (WCAG 3.3.1, 3.3.3, 4.1.3)

- **Blocker** — Form errors are rendered as plain
  `<div class="auth-error">{{ error }}</div>` (login, signup, password
  reset confirm, 2FA enable, sub form alert). They are not in an
  `aria-live` region and are not associated with the offending input
  via `aria-describedby`. After a failed submit, screen readers do
  not announce the error.
  - Wrap the error block in
    `<div role="alert">` (assertive — appropriate for submission
    errors).
  - Add `aria-describedby` from the relevant input to the error id.
  - Better still, render per-field errors next to each input.
- **Major** — Toasts / save confirmations: there is **no** toast
  pattern on save. After "Spara signal" or "Pausa prenumeration",
  the page is re-rendered (server-side redirect). That is actually
  accessible — the new page heading announces context. But:
  - `admin/system.html.j2` line 17 renders `{% if flash %}<div class="alert">…</div>` — add `role="status"` for ok / `role="alert"` for error so the flash is announced.
  - `admin/user_detail.html.j2` line 16 — same issue.
- **Major** — `subscription_form.html.j2` already has
  `<p ... id="submit-hint" aria-live="polite">` on line 218 — good
  pattern. Replicate it for password-strength hints and 2FA-code
  validation.
- **Minor** — Confirm dialogs use native `confirm()` (logout, delete,
  hard-delete). Native confirms are accessible by default; keep them
  or upgrade to a labelled custom dialog later.

### 3.5 Predictable behaviour (WCAG 3.2.2, 3.2.3)

- **Pass** — No `onchange` form submission auto-triggers found.
- **Pass** — Filter dropdowns require a visible "Filtrera" submit.

---

## 4. Robust

### 4.1 Valid markup and ARIA (WCAG 4.1.1, 4.1.2)

- **Major** — `aria-current="page"` is **not used** on any active nav
  link. The `.nav-item.active` class is purely visual. Add
  `aria-current="page"` to the active link in:
  - `_layout.html.j2` top-bar links (Funktioner, Priser).
  - `dashboard.html.j2` sidebar (Digest item is hard-coded as
    `class="nav-item active"`).
  - `_stub.html.j2` sidebar (`{% if active == 'calendar' %}active{% endif %}` — add the same conditional for `aria-current`).
  - `admin/_layout.html.j2` sidebar (`{% if active_nav == 'users' %}active{% endif %}`).
- **Major** — Status pips use `aria-hidden="true"` (good in
  `app/account.html.j2` lines 103, 115; `subscriptions.html.j2` lines
  47, 51) but not in `admin/users.html.j2` (line 55) or
  `admin/user_detail.html.j2`. Either ensure consistent
  `aria-hidden="true"` or add a visible text label per row (preferred).
- **Major** — `dashboard.html.j2` data attributes
  (`data-screen-label="Dashboard"`) on `<body>` are harmless but unused
  by AT. Remove if not consumed by analytics.
- **Minor** — `<details><summary>` in the FAQ and audit JSON cells use
  custom markers; that is fine. Just ensure `:focus-visible` on
  `<summary>` is styled.
- **Minor** — Forms POSTing to themselves render the CSRF token via
  `{{ csrf_input() }}`; they all rely on hidden inputs which are not
  user-visible — good.

### 4.2 Custom widgets

- **Major** — Filter chips `<span class="chip">` (see Operable). After
  conversion to `<button>`, add `aria-pressed="true|false"`.
- **Major** — The pricing toggle has no ARIA. Add `role="group"`
  around the toggle, `aria-pressed` on the buttons, and a
  visually-hidden announcement of the active state.
- **Major** — The dashboard `.search` wraps an icon `<span aria-hidden="true">⌕</span>`
  (good) but the submit button text is the unicode "↵" with
  `aria-label="Sök"` (good). Audit everywhere "→", "↗", "⌕" appear:
  every standalone glyph that is not next to descriptive text needs an
  accessible name.

### 4.3 `<title>` and document outline

- **Pass** — Every page sets a meaningful `<title>{{ title }} —
  Vittring</title>` (or per-page string).
- **Major** — `app/dashboard.html.j2` sets a static title
  `<title>Vittring — Dashboard</title>`; better to include the digest
  count or active filter for context, e.g.
  `Vittring — Dashboard ({{ digest_count }} signaler)`.

### 4.4 Tables

- **Pass** — All admin tables use `<thead>` and `<th>` correctly. Add
  `<caption>` (visually hidden) for AT consumers, e.g. `<caption class="visually-hidden">Användare och deras planer</caption>`.

---

## Top 10 quick wins

These are ordered by impact / effort. Each is a focused change that
removes a specific WCAG AA risk without redesign.

1. **Add a skip-to-content link.** First child of `<body>` in
   `_layout.html.j2`, `app/dashboard.html.j2`, `admin/_layout.html.j2`,
   `app/_stub.html.j2`, `auth/_auth_base.html.j2`. Style with a
   visible `:focus` pop-down. Give `<main>` the matching `id`.

2. **Add `aria-current="page"` on every active nav link** in the
   public top-bar, dashboard sidebar, admin sidebar, and stub
   sidebar. Pure template change, no CSS.

3. **Convert the dashboard `.row .actions` opacity rule** from
   `:hover` only to `:hover, :focus-within`. One CSS rule unlocks
   keyboard access to the Save / HubSpot / Open buttons.

4. **Promote icon-only buttons** (`★ Spara`, `↗ HubSpot`, `→ Öppna`,
   `× close-chip`) to carry `aria-label="Swedish text"` instead of
   `title=""`. Tooltips are not accessible names.

5. **Make filter chips and digest pills real `<button type="button">`
   elements** (or `<a>` with hrefs that toggle a query parameter).
   Add `aria-pressed` for toggle state.

6. **Wrap form-error blocks** (`auth-error`, `alert error`) in
   `role="alert"` and the success/info flashes in `role="status"` so
   they are announced after redirects. Associate inputs with their
   error via `aria-describedby`.

7. **Add a global `:focus-visible` rule** in `brand.css`:
   `outline: 2px solid var(--v-signal); outline-offset: 2px;` so every
   interactive element gets a visible focus ring on dark backgrounds.

8. **Add `@media (prefers-reduced-motion: reduce)`** in `brand.css`
   that disables `.v-radar-dot` pulses, `transform` transitions on
   `.row`, `.btn`, `.v-button`, `.faq-list .plus`, and any
   `transition: transform`.

9. **Mark decorative SVGs** (radar dials, sparklines, icon paths next
   to descriptive text) with `aria-hidden="true"` and
   `focusable="false"`. Give meaningful icons (pricing
   include/exclude) `role="img"` plus `aria-label`.

10. **Fix the duplicate-h1 problem in admin pages.** Demote the topbar
    `<h1>` in `admin/_layout.html.j2` to `<p class="topbar-title">`
    (or `<span>`), keep the page-header `<h1>`. Also promote
    `<div class="section-title">` to `<h2>` and fix the
    `app/account.html.j2` h1→h3 skip by lifting card heads to `<h2>`.

---

## Files referenced

- /home/user/vittring/src/vittring/api/templates/_layout.html.j2
- /home/user/vittring/src/vittring/api/templates/auth/_auth_base.html.j2
- /home/user/vittring/src/vittring/api/templates/auth/login.html.j2
- /home/user/vittring/src/vittring/api/templates/auth/signup.html.j2
- /home/user/vittring/src/vittring/api/templates/auth/2fa_enable.html.j2
- /home/user/vittring/src/vittring/api/templates/auth/password_reset_request.html.j2
- /home/user/vittring/src/vittring/api/templates/auth/password_reset_confirm.html.j2
- /home/user/vittring/src/vittring/api/templates/auth/check_email.html.j2
- /home/user/vittring/src/vittring/api/templates/auth/verify_ok.html.j2
- /home/user/vittring/src/vittring/api/templates/auth/verify_failed.html.j2
- /home/user/vittring/src/vittring/api/templates/public/landing.html.j2
- /home/user/vittring/src/vittring/api/templates/public/pricing.html.j2
- /home/user/vittring/src/vittring/api/templates/public/legal_terms.html.j2
- /home/user/vittring/src/vittring/api/templates/public/legal_privacy.html.j2
- /home/user/vittring/src/vittring/api/templates/public/unsubscribe.html.j2
- /home/user/vittring/src/vittring/api/templates/app/dashboard.html.j2
- /home/user/vittring/src/vittring/api/templates/app/account.html.j2
- /home/user/vittring/src/vittring/api/templates/app/subscriptions.html.j2
- /home/user/vittring/src/vittring/api/templates/app/subscription_form.html.j2
- /home/user/vittring/src/vittring/api/templates/app/_stub.html.j2
- /home/user/vittring/src/vittring/api/templates/admin/_layout.html.j2
- /home/user/vittring/src/vittring/api/templates/admin/overview.html.j2
- /home/user/vittring/src/vittring/api/templates/admin/users.html.j2
- /home/user/vittring/src/vittring/api/templates/admin/user_new.html.j2
- /home/user/vittring/src/vittring/api/templates/admin/user_detail.html.j2
- /home/user/vittring/src/vittring/api/templates/admin/subscriptions.html.j2
- /home/user/vittring/src/vittring/api/templates/admin/signals.html.j2
- /home/user/vittring/src/vittring/api/templates/admin/audit.html.j2
- /home/user/vittring/src/vittring/api/templates/admin/email.html.j2
- /home/user/vittring/src/vittring/api/templates/admin/system.html.j2
- /home/user/vittring/src/vittring/static/css/brand.css
- /home/user/vittring/src/vittring/static/css/tokens.css
