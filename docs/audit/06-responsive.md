# 06 — Responsive / Mobile audit

Read-only audit of all templates under `src/vittring/api/templates/` and stylesheets in `src/vittring/static/css/`. Coverage: 100% of public, auth, app, and admin templates plus all three CSS files (`brand.css`, `tokens.css`, `main.css`).

Two parallel design tokens systems coexist: `tokens.css` (light / "Premium tech SaaS", referenced by `main.css` for the legacy auth/app shell pages such as `app/account.html.j2`, `app/subscriptions.html.j2`, `app/subscription_form.html.j2`) and `brand.css` (Variant B "Night", used by the public landing, pricing, dashboard, admin and the new auth shell). The dashboard uses inline-style overrides in `app/dashboard.html.j2`. Two layouts coexist: `_layout.html.j2` (public footer/nav, dark) and `admin/_layout.html.j2`, `app/dashboard.html.j2` (standalone, do NOT extend the public layout). Findings below are grouped by viewport breakpoint.

---

## > 1280 px (desktop)

Most pages render correctly. Notable items even at desktop:

- **`landing.html.j2` `.preview-annotation`** — positioned at `right: -24px; top: 100px;` (lines 70–76). The `-24px` causes the floating `↘ ny signal` tag to slightly overhang its parent, which is fine inside an overflow container, but its **parent grid cell is not `position: relative`** (line 204 inline `style="position: relative"` saves it). The annotation also sits in the right column without media-query overrides — at narrow widths it will collide with the preview-card content.
- **`dashboard.html.j2` `.digest-header` grid** (line 76): `grid-template-columns: 1.6fr 1fr 1fr 1fr;` with 4 columns and 32 px gaps. Down to ~1100 px it's fine; below it the stat-card numbers (`font-size: 40px`) start fighting for space. No media query at all — see < 980 px.
- **`admin/_layout.html.j2` `.stat-grid`** (line 108): `repeat(4, 1fr)` with 16 px gap — same issue, no media-query collapse.

## 980–1280 px (laptop / small desktop)

- **`landing.html.j2` `.hero-grid`** (line 5): collapses to `1fr` at `<= 980px`. So in the 980–1280 band the hero is two columns. Hero `h1` uses `clamp(56px, 7vw, 112px)`, which at 980 px yields ~68 px — this is borderline. With the right-side preview card competing for space at ~430 px width, the live ticker at line 180 has 60-px-wide time/type columns and the third column gets squeezed.
- **`dashboard.html.j2` topbar** (line 47): three flex children (date block / search / button group). The search has `flex: 1; max-width: 480px; margin: 0 32px;`. At ~1024 px, with the 240-px sidebar consuming horizontal space, the right-side button row ("Exportera CSV" + "Ny prenumeration") remains nowrap — total can push past viewport on the smallest laptops. No media query handles wrapping.
- **`admin/_layout.html.j2`** topbar (line 59): same setup. With the 240 px admin sidebar plus left padding of 32 px on the topbar plus `{{ user.email }}` shown in full, narrow laptops can clip the email.
- **`subs-list-row`** (`main.css` line 1708): `grid-template-columns: minmax(0, 1.7fr) minmax(0, 1.6fr) auto minmax(120px, auto) auto;`. Below 1100 px this gets cramped; collapse only triggers at 880 px, leaving a problematic band 880–1100 px where the date column is squeezed and `subs-list-actions` (Duplicera + Radera) wraps awkwardly.
- **`landing.html.j2` `.faq-grid`** (line 115): 1fr / 1.6fr until 880 px. At 980 px the left column becomes ~370 px wide and the heading `font-size: 48px` (line 382) breaks awkwardly. A breakpoint at 1024 px would help.

## 720–980 px (tablet portrait)

- **`landing.html.j2` `.hero-grid`** collapses to single column at 980 px (line 5). Good. But the **preview-annotation** still uses `position: absolute; right: -24px;` — once the hero stacks, the annotation can overflow the viewport on the right. There is no `@media` adjustment for `.preview-annotation` anywhere in the file.
- **`landing.html.j2` `.hero-h1`** uses `clamp(56px, 7vw, 112px)`. At 720 px viewport: `7vw = 50.4px`, but the `min` of 56 px kicks in. This means heading remains at 56 px on a 720 px viewport — the `<br>` between "En radar för" and "köpsignaler." likely keeps it tidy, but see < 480 px.
- **`landing.html.j2` `.testimonial-block`** (line 106): `padding: 64px;` — fixed 64 px on all sides. On a 720 px viewport, the inside content is only 592 px wide which is fine, but on smaller viewports below this it bleeds horizontally. No media query reduces padding.
- **`landing.html.j2` `.final-cta`** (line 132): `padding: 80px 64px;` — same fixed-padding issue. Combined with `font-size: clamp(48px, 6vw, 88px);` for the heading (line 137), at 720 px the `min` of 48 px kicks in and the heading "Sluta gissa. Börja vittra." can wrap weirdly inside the 64-px-padded box.
- **`pricing.html.j2` `.price-grid`** (line 4): collapses at `<= 920px` to 1fr. So 720–920 still serves three columns at ~210 px width — too narrow for `.price-amount .num` at 56 px font (line 27). Tighter breakpoint needed.
- **`dashboard.html.j2` and `admin/_layout.html.j2`** still render the **240-px sticky sidebar** with no off-canvas pattern. On a 720-px viewport the main content has only ~480 px usable, **and the topbar's three flex children no longer fit** (date block + 480-px-max search + button row with two buttons "Exportera CSV" and "Ny prenumeration"). The search will collapse to 0 because `flex: 1` competes with non-shrinking siblings. Critical issue.
- **`dashboard.html.j2` `.row` feed** (line 99): `grid-template-columns: 80px 100px 1fr 200px 120px;` — sums to 500 px of fixed columns plus the title flex. On phone-tablet this is unviewable; the row will horizontal-scroll the body.
- **`subscription_form.html.j2` `.sub-form-grid`** (`main.css` line 773): collapses at 980 px → good.
- **`.signal-options`** (line 870): `repeat(3, 1fr)` collapsing to 1fr at 720 px. Between 720 and ~640 px, the three signal-type cards have ~210 px each and the description text wraps to 4–5 lines; not broken but tight.

## 480–720 px (large phone / phone landscape)

- **`_layout.html.j2`** public nav: at `<= 720px`, `.v-nav-links` is `display: none;` (line 56). So the only visible nav items become brand on the left and `Logga in` + `Starta provperiod →` on the right. **No hamburger** is provided — discovery of `/pricing` and `#features` is impossible from mobile public pages.
- **`_layout.html.j2`** footer: `grid-template-columns: 1.5fr 1fr 1fr 1fr;` (line 92) **never collapses**. At 480 px viewport the four columns are forced together with 48 px gaps; everything overflows or compresses to unreadable. Critical.
- **`landing.html.j2`** hero section padding `64px 48px 80px;` (line 144) — 48 px each side burns 96 px before content. On 480 px, only 384 px remains. Same with the multiple `padding: 96px 48px;` sections (lines 269, 298, 350, 378, 412). All fixed 48 px horizontal — should clamp to 16–24 px on phones.
- **`landing.html.j2` `.preview-annotation`** at this size is firmly off-screen on the right of the preview-card.
- **`pricing.html.j2`** stacks vertically (good) but the `padding: 40px 32px;` per card (line 7) plus the 80 px outer hero padding (line 51) leaves ~416 px content width on 480 px viewport. The featured card's "Mest valda" tag at `top: -12px; left: 50%; transform: translateX(-50%);` is fine.
- **`dashboard.html.j2` `.dash-shell`** still grid 240 / 1fr on phone. **Sidebar consumes 50% of a 480-px screen.** The user gets a useless half-width main pane and a fully-readable sidebar — exactly inverted from what the sales user needs.
- **`admin/_layout.html.j2`** same issue, plus admin's tables (`table.t`) inside `.card` have NO horizontal-scroll wrapper. `users.html.j2` shows 9 columns; `audit.html.j2` shows 5 columns with `<pre>` JSON cells. Severe horizontal overflow guaranteed on phone.
- **`.subs-list-row`** collapses to 1fr at `<= 880px` (`main.css` line 1769). Good. But `subs-list-head` is `display: none;` — and the row no longer has labels for each cell. Users see a name, then a row of badges, then a status pill, then a date, then action buttons, with no headings. Hidden labels needed for screen readers and to disambiguate.
- **Auth pages** (`auth/_auth_base.html.j2`): the right brand pane is `display: none;` at `<= 880px` (line 52). Form column padding stays at `64px 48px;`. Fine.
- **`signup.html.j2` form** — at 480 px, fixed `padding: 64px 48px;` cuts content to 384 px. The 44-px-tall inputs and 14-px label font are usable; the email placeholder `namn@företag.se` may truncate inside the input on small screens because `font-size: 14px` and `padding: 0 14px;` allows ~26 chars.
- **Buttons:** `.btn-sm` in `main.css` has `height: 36px;` — below the 44×44 mobile tap-target minimum. Used on `subscriptions.html.j2` for Duplicera/Radera (line 58, 62) and on `account.html.j2` for "Se planer" (line 51). On phone these are below WCAG 2.5.5 (Target Size).
- **`.icon-btn`** in `dashboard.html.j2` (line 115): `padding: 5px 9px;` ≈ ~24 px tall. Way below tap-target. Used for the row hover actions ("★", "↗", "→", "Öppna →"). On touch devices these don't even appear (they are `opacity: 0` until `:hover`, line 112) — so on phone the actions are completely invisible.
- **`.chip`** in `dashboard.html.j2` (line 88): `padding: 6px 10px;` and `font-size: 11px` — taps near the `×` icon will hit the wrong target.
- **`auth-shell`** (`main.css` line 721): `padding: 0 var(--space-5);` (= 24 px). OK. But `auth-card` `padding: var(--space-7);` (= 48 px) is heavy at 480 px — internal width drops to ~340 px.

## < 480 px (small phone, including 320 px iPhone SE)

- **`landing.html.j2`**: at 320 px viewport, the 48-px horizontal section padding leaves only 224 px of content. `clamp(56px, 7vw, 112px)` for hero h1 still resolves to 56 px (its `min`); 56 px / 224 px = lines that wrap awkwardly. The heading `<br>` between "En radar för" and "köpsignaler." gives a forced break, but the text is still tight.
- The **`.testimonial-quote`** uses `clamp(28px, 3.4vw, 42px)` — at 320 px → `min` of 28 px. The block's fixed `padding: 64px;` though leaves only ~192 px content width. Wraps badly; in worst case the radar SVG (520 × 520, `right: -120px; top: -120px;`) protrudes beyond the rounded-corner edges.
- **`pricing.html.j2`**: hero `padding: 80px 48px 48px;` plus card `padding: 40px 32px;` plus the `clamp(56px, 7vw, 96px)` heading which floors to 56 px — readable but very tight.
- **`dashboard.html.j2`** is unusable below 480 px. The 240-px sidebar leaves ~80 px for the main pane on iPhone SE. The topbar wraps onto multiple lines, search shrinks to nothing, and the feed table forces horizontal scroll.
- **`admin/users.html.j2`** has 9 columns at fixed widths (no `min-width` per column but text content forces overflow). Without a `.table-wrap { overflow-x: auto }` wrapper, the column widths collapse and content overlaps.
- **Footer** (`_layout.html.j2`) — four columns force minimum widths to honor the text "Integritetspolicy" / "Användarvillkor" → horizontal overflow of the entire footer on screens below ~480 px.
- **Smallest font sizes:**
  - `.t-eyebrow` is 11 px (`brand.css` line 91). With letter-spacing 0.12em and uppercase, readable but borderline.
  - `.preview-pill` 9 px (`landing.html.j2` line 63) — too small.
  - `.preview-time` 10 px (line 59) — too small.
  - Several inline 10 px / 11 px mono labels throughout dashboard. WCAG recommends ≥ 12 px for body, ≥ 14 px ideal. Mono text at 10 px is hard to read on phones.

## Cross-cutting concerns

- **No safe-area-inset support.** No `env(safe-area-inset-bottom)` / `env(safe-area-inset-top)` anywhere. iOS notch and home-indicator overlap will obscure the sticky `.topbar` and the `.dash-side` user card at the bottom.
- **No `prefers-reduced-motion`.** `v-pulse` keyframes (`brand.css` line 146) and `.feature-card` translate transitions ignore the OS reduced-motion preference. Probably fine, but documented.
- **Tables (`.table` `main.css` line 289 and `table.t` admin)** have no horizontal-scroll wrappers. Critical.
- **Sticky sidebar without collapse** in dashboard and admin. Users on phones cannot use the product at all.
- **No `<meta>` viewport-fit=cover** so iOS won't render under the notch — fine, intentional.
- **Tap targets**: btn `height: 44px` is correct, but `.btn-sm` 36 px, `.icon-btn` ~24 px, `.chip` ~24 px, dashboard nav items at ~32 px height, FAQ summary clickable but the `.plus` is small. Fail WCAG 2.5.5 in many places.
- **The `.search` input** in dashboard (line 53–69): no responsive shrink/hide. On phone it should collapse to an icon-only button revealing a fullscreen overlay.
- **Hero CTA buttons** (`hero-cta` / `final-cta`): use `flex-wrap: wrap` so they will wrap, but `v-button--lg` is `padding: 16px 24px; font-size: 15px;` — single button is ~190 px wide. On 320 px viewport with 48 px padding, two buttons cannot fit and stacking does work — OK.
- **Forms on mobile**: inputs are `height: 44px;` (good), labels 11 px uppercase mono (`auth/_auth_base.html.j2` line 23) which is small but readable.
- **Admin filter-bar** (`admin/_layout.html.j2` line 233): `flex-wrap: wrap;` — good. The select+input+button fits on phones.
- **Inline `<style>` blocks** in landing/pricing/dashboard/admin/auth_base mix media-query strategies and override `main.css` variables with `brand.css`. Two design systems in one app makes consistent breakpoints impossible without consolidation.

---

## Summary of severity

| Severity | Issue | Files |
|---|---|---|
| Critical | Dashboard sidebar never collapses; phone unusable | `app/dashboard.html.j2` lines 17, 19–25 |
| Critical | Admin sidebar never collapses + admin tables overflow | `admin/_layout.html.j2` lines 18, 20–26 + all `admin/*.html.j2` tables |
| Critical | Public footer 4-column grid never collapses | `_layout.html.j2` lines 90–129 |
| Critical | Public nav links hidden < 720 px with no hamburger replacement | `_layout.html.j2` line 55–57 |
| High | Dashboard topbar (date / search / actions) doesn't wrap | `app/dashboard.html.j2` lines 47–69 |
| High | Dashboard `.row` 5-column grid forces horizontal scroll | `app/dashboard.html.j2` lines 98–104 |
| High | `.preview-annotation` floats off-screen on phones | `public/landing.html.j2` lines 70–76 |
| High | `.btn-sm` and `.icon-btn` below 44×44 tap target | `main.css` line 152, `app/dashboard.html.j2` line 115 |
| Medium | `.subs-list` 880-px collapse loses column labels | `main.css` line 1769 |
| Medium | `.faq-grid` 1fr/1.6fr awkward 880–1024 band | `public/landing.html.j2` line 115 |
| Medium | Fixed 48 px section padding on phones (landing, pricing) | `public/landing.html.j2` 144, 269, 298, 350, 378, 412 |
| Low | 9–11 px font sizes (`.preview-pill`, `.preview-time`) | `public/landing.html.j2` 63, 59 |
| Low | No `prefers-reduced-motion` honored | `brand.css` line 146 |
| Low | No iOS safe-area-inset | global |

---

## Top-3 concrete fixes (CSS snippets)

These are read-only suggestions — drop them into `main.css` (or the relevant `<style>` block) when the team is ready to implement.

### 1. Dashboard + admin sidebar → off-canvas drawer below 980 px

Add to `app/dashboard.html.j2` and `admin/_layout.html.j2` `<style>` blocks, plus a small JS toggle.

```css
/* === Mobile-friendly app shell === */
@media (max-width: 980px) {
  .dash-shell, .admin-shell { grid-template-columns: 1fr; }

  .dash-side, .admin-side {
    position: fixed;
    inset: 0 auto 0 0;
    width: min(86vw, 320px);
    height: 100dvh;
    transform: translateX(-100%);
    transition: transform 0.22s ease;
    z-index: 100;
    box-shadow: 0 16px 40px rgba(0,0,0,0.5);
  }
  .dash-side.is-open, .admin-side.is-open { transform: translateX(0); }

  .dash-scrim {
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.5);
    z-index: 99;
    opacity: 0; pointer-events: none;
    transition: opacity 0.22s ease;
  }
  .dash-scrim.is-open { opacity: 1; pointer-events: auto; }

  /* Hamburger button (placed in topbar before the date block) */
  .dash-burger {
    display: inline-flex; align-items: center; justify-content: center;
    width: 44px; height: 44px;
    background: transparent; border: 1px solid var(--v-night-3);
    border-radius: 6px; color: var(--v-mist);
    margin-right: 8px;
  }
}
@media (min-width: 981px) { .dash-burger, .dash-scrim { display: none; } }

/* Topbar wraps on phones; search becomes second-row full-width */
@media (max-width: 720px) {
  .topbar {
    height: auto;
    padding: 12px 16px;
    flex-wrap: wrap;
    gap: 8px;
  }
  .topbar > *:not(.search) { flex: 0 0 auto; }
  .topbar .search { order: 99; flex: 1 1 100%; margin: 0; }
  .feed .row {
    grid-template-columns: 1fr auto;
    grid-template-rows: auto auto;
    gap: 4px 12px;
    padding: 12px 16px;
  }
  .feed .row .time { grid-column: 1; grid-row: 1; }
  .feed .row .pill-kind { grid-column: 2; grid-row: 1; justify-self: end; }
  .feed .row > div:nth-of-type(1) { grid-column: 1 / -1; grid-row: 2; }
  .feed .row .src, .feed .row .actions { display: none; }
}
```

### 2. Public footer + nav: hamburger drawer + stacked footer

Add to `_layout.html.j2` `<style>` block.

```css
/* Hamburger for the public nav */
.v-nav-burger {
  display: none;
  width: 44px; height: 44px;
  background: transparent;
  border: 1px solid rgba(200, 204, 196, 0.2);
  border-radius: var(--r-2);
  color: var(--v-mist);
  align-items: center; justify-content: center;
}

@media (max-width: 720px) {
  .v-nav { padding: 12px 16px; }
  .v-nav-actions { gap: 8px; }
  .v-nav-actions .v-button:not(.v-button--signal) { display: none; }
  .v-nav-burger { display: inline-flex; }

  /* Sliding panel revealed by JS toggling .is-open on .v-nav-panel */
  .v-nav-panel {
    position: fixed;
    inset: 60px 0 auto 0;
    background: var(--v-night);
    border-bottom: 1px solid var(--v-night-3);
    padding: 16px;
    display: none;
    flex-direction: column; gap: 4px;
  }
  .v-nav-panel.is-open { display: flex; }
  .v-nav-panel a {
    padding: 12px;
    color: var(--v-mist);
    border-radius: var(--r-2);
    font-size: 16px;
  }
  .v-nav-panel a:hover { background: var(--v-night-3); color: var(--v-paper); }
}

/* Footer collapses */
@media (max-width: 880px) {
  footer .footer-grid { grid-template-columns: 1fr 1fr !important; gap: 32px !important; }
}
@media (max-width: 480px) {
  footer { padding: 48px 20px 24px !important; }
  footer .footer-grid { grid-template-columns: 1fr !important; gap: 28px !important; }
}
```

(The footer's grid is currently inline-styled, so this requires moving the footer's inline `style="display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr;"` to a class such as `.footer-grid` first.)

### 3. Admin tables wrapper + tap-target compliance

Add to `main.css` (and admin layout `<style>`).

```css
/* Horizontal-scroll wrapper for any wide table on small screens */
.table-wrap {
  width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  border-radius: var(--radius-lg);
}
.table-wrap > table { min-width: 720px; }

/* Wrap each admin table in <div class="table-wrap">…</div>;
   apply min-width tuned per page (audit: 800px, users: 960px, signals: 1100px). */

/* Restore tap targets to 44 px on touch */
@media (pointer: coarse), (max-width: 720px) {
  .btn-sm { height: 44px; padding: 0 var(--space-4); }
  .icon-btn {
    min-height: 44px; min-width: 44px;
    padding: 8px 10px;
    /* Keep visible on touch — desktop hover-fade is hostile on phones */
    opacity: 1 !important;
  }
  .row { padding-block: 12px; }
  .chip { min-height: 32px; padding: 8px 12px; font-size: 12px; }

  /* Reveal subs-list head labels per row using ::before with the column name */
  .subs-list-row > * { position: relative; padding-left: 96px; }
  .subs-list-row > *::before {
    position: absolute; left: 0; top: 0;
    content: attr(data-label);
    font-size: 11px;
    font-weight: 500;
    color: var(--color-text-muted);
    text-transform: uppercase;
    letter-spacing: var(--tracking-wide);
  }
  /* Templates would need data-label="Namn" on each cell. */
}
```

---
