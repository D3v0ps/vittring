# Design system för Vittring

Claude Code följer denna specifikation strikt — alla avvikelser kräver explicit godkännande.

---

## Designfilosofi

Vittring följer **Linear-stilen**: strikt, monokrom, professionell, lite tech-känsla — men utan att efterapa Linear själva. Designen ska kännas seriös och ägna sig åt sitt jobb. Inga "AI-iga" mönster.

### Anti-patterns — får INTE förekomma någonstans

- Lila eller blå gradients av något slag (purple-to-blue, indigo-to-pink etc.)
- Tailwinds default-färger (slate, zinc, neutral, gray) som primärpalett
- `rounded-2xl`, `rounded-3xl`, eller `shadow-xl`/`shadow-2xl`
- Floating cards med drop shadows
- Glasmorphism, frostat glas, blur-effekter
- Centrerade hero-sektioner med stor rubrik + CTA-knapp + tre feature-cards
- Pricing-kort med "Most Popular"-band
- Emojis i UI eller copy
- Lucide-ikoner för varje listpunkt eller feature
- Stock-illustrationer av abstrakta människor eller former
- "Trusted by"-loggrader
- Animerade gradient-bakgrunder
- `font-family: Inter` (för vanlig — det är vad alla AI-byggda sajter använder)
- Marketing-floskler: "Boost", "Unlock", "Supercharge", "AI-powered", "Next-gen"

---

## Färgpalett

**Skriv som CSS-variabler i `src/vittring/static/css/tokens.css`:**

```css
:root {
  /* Bakgrund */
  --color-bg: #FAFAF7;              /* Off-white huvudbakgrund */
  --color-bg-elevated: #FFFFFF;     /* Kort, paneler, modaler */
  --color-bg-subtle: #F2F1EC;       /* Hover, alternating rows */
  --color-bg-sunken: #EDECE6;       /* Inputs, disabled */

  /* Text */
  --color-text: #141414;            /* Primär text — nästan svart, inte rent svart */
  --color-text-muted: #5C5C58;      /* Sekundär text, labels */
  --color-text-subtle: #8A8A85;     /* Hjälptext, placeholders */
  --color-text-inverse: #FAFAF7;    /* Text på mörka ytor */

  /* Borders */
  --color-border: #DCDBD3;          /* Standard border */
  --color-border-strong: #B8B7AE;   /* Hover, fokus utan accent */
  --color-border-subtle: #E8E7E0;   /* Avdelare i listor */

  /* Accent — marinblå, sparsamt använd */
  --color-accent: #1B3A4B;          /* CTA-knappar, länkar, fokus */
  --color-accent-hover: #133040;
  --color-accent-subtle: #E8EEF1;   /* Bakgrund för pills, status */
  --color-accent-text: #1B3A4B;

  /* Semantiska — använd ENDAST där det krävs */
  --color-success: #2D5A3D;
  --color-success-bg: #E8EFE9;
  --color-warning: #8A6A1F;
  --color-warning-bg: #F4EDD9;
  --color-danger: #8B2C2C;
  --color-danger-bg: #F2E2E2;

  /* Mörka ytor (rubriker, top-bar) */
  --color-dark: #141414;
  --color-dark-text: #FAFAF7;
}
```

**Regler:**
- Använd alltid CSS-variabler, aldrig hex-koder direkt i komponenter.
- `--color-accent` används **bara** för: primära CTA-knappar, aktiva navlinkar, fokus-ringar, klickbara länkar i text. Inte som dekoration.
- Default för alla ytor är `--color-bg`. Höjd skapas genom borders, inte shadows.

---

## Typografi

**Font-files:** Self-hosted i `src/vittring/static/fonts/`. Ladda inte från Google Fonts CDN (privacy + speed).

```css
@font-face {
  font-family: 'Inter Tight';
  src: url('/static/fonts/InterTight-Regular.woff2') format('woff2');
  font-weight: 400; font-style: normal; font-display: swap;
}
@font-face {
  font-family: 'Inter Tight';
  src: url('/static/fonts/InterTight-Medium.woff2') format('woff2');
  font-weight: 500; font-style: normal; font-display: swap;
}
@font-face {
  font-family: 'Inter Tight';
  src: url('/static/fonts/InterTight-SemiBold.woff2') format('woff2');
  font-weight: 600; font-style: normal; font-display: swap;
}
@font-face {
  font-family: 'JetBrains Mono';
  src: url('/static/fonts/JetBrainsMono-Regular.woff2') format('woff2');
  font-weight: 400; font-style: normal; font-display: swap;
}

:root {
  --font-sans: 'Inter Tight', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace;
}
```

**Skala (modulär, 1.250 ratio från 16px bas):**

```css
:root {
  --text-xs: 12px;    /* Hjälptext, captions, metadata */
  --text-sm: 14px;    /* Sekundär text, labels, formulär-labels */
  --text-base: 16px;  /* Brödtext, default */
  --text-md: 18px;    /* Större brödtext, lead-paragraf */
  --text-lg: 22px;    /* H3, sub-rubriker */
  --text-xl: 28px;    /* H2, sektion-rubriker */
  --text-2xl: 36px;   /* H1, sidrubriker */
  --text-3xl: 48px;   /* Hero-rubrik på landningssida */

  --leading-tight: 1.2;
  --leading-snug: 1.4;
  --leading-normal: 1.5;
  --leading-relaxed: 1.65;

  --tracking-tight: -0.02em;
  --tracking-normal: 0;
}
```

**Typografi-regler:**
- Rubriker har alltid `letter-spacing: -0.02em` och `line-height: 1.2`.
- Brödtext har `line-height: 1.65` för läsbarhet.
- **Aldrig font-weight 700** — använd 600 som maximum. Tyngre vikter ser för aggressiva ut i Inter Tight.
- Monospace används för: orgnummer, datum/tid, koder, API-endpoints, summor i kronor i tabeller.
- **Sentence case överallt**, aldrig Title Case eller ALL CAPS. Undantag: SCREAMING_CONSTANTS i kod-block.
- Mätbar text på landningssida: max 720px bredd, max 75 tecken per rad.

---

## Layout och spacing

```css
:root {
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --space-7: 48px;
  --space-8: 64px;
  --space-9: 96px;

  --radius-sm: 4px;       /* Small UI element (badge, tag) */
  --radius-md: 6px;       /* Buttons, inputs, kort */
  --radius-lg: 8px;       /* Större paneler */
  --radius-full: 999px;   /* Pills, avatars */

  --container-narrow: 720px;   /* Text-tunga sidor */
  --container-default: 1080px; /* Standard-app, dashboard */
  --container-wide: 1280px;    /* Tabeller, listvyer */
}
```

**Layoutregler:**
- Aldrig `border-radius` över 8px på något (förutom pills/avatars).
- Aldrig `box-shadow` förutom på fokus-ringar.
- Höjd och separation skapas med `1px solid var(--color-border)`, inte med shadows.
- Vertikal rytm: använd 24px och 32px som primära avstånd mellan sektioner.
- Inga centrerade layouts på landningssidor — vänsterställd, max 720px för text.

---

## Komponenter — exakta specifikationer

### Knappar

```css
.btn {
  display: inline-flex; align-items: center; justify-content: center;
  height: 36px; padding: 0 16px;
  border-radius: var(--radius-md);
  font-family: var(--font-sans); font-size: var(--text-sm); font-weight: 500;
  letter-spacing: -0.005em;
  border: 1px solid transparent;
  cursor: pointer;
  transition: background-color 100ms ease, border-color 100ms ease;
}

/* Primär — bara EN per vy, för huvudaction */
.btn-primary {
  background: var(--color-accent);
  color: var(--color-text-inverse);
  border-color: var(--color-accent);
}
.btn-primary:hover { background: var(--color-accent-hover); }

/* Sekundär — för icke-primära actions */
.btn-secondary {
  background: var(--color-bg-elevated);
  color: var(--color-text);
  border-color: var(--color-border);
}
.btn-secondary:hover { border-color: var(--color-border-strong); background: var(--color-bg-subtle); }

/* Ghost — för text-actions, "Avbryt", inline-actions */
.btn-ghost {
  background: transparent;
  color: var(--color-text-muted);
  border-color: transparent;
}
.btn-ghost:hover { background: var(--color-bg-subtle); color: var(--color-text); }

/* Fokus — synlig keyboard-navigation */
.btn:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}
```

**Aldrig:** gradients på knappar, ikoner inuti knappar utan funktion, "shadow" på knappar.

### Inputs

```css
.input {
  width: 100%;
  height: 36px; padding: 0 12px;
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-family: var(--font-sans); font-size: var(--text-sm);
  color: var(--color-text);
  transition: border-color 100ms ease;
}
.input:hover { border-color: var(--color-border-strong); }
.input:focus {
  outline: none;
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px var(--color-accent-subtle);
}
.input::placeholder { color: var(--color-text-subtle); }
```

### Kort (paneler för innehåll)

```css
.card {
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 24px;
}
/* Aldrig shadow. Höjd skapas av border + ev. annan bakgrund. */
```

### Tabeller (för larm-listor, prenumerationer, audit log)

```css
.table {
  width: 100%; border-collapse: collapse;
  font-size: var(--text-sm);
}
.table th {
  text-align: left; font-weight: 500;
  color: var(--color-text-muted);
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border);
}
.table td {
  padding: 14px 16px;
  border-bottom: 1px solid var(--color-border-subtle);
  color: var(--color-text);
}
.table tr:hover td { background: var(--color-bg-subtle); }
.table .mono { font-family: var(--font-mono); font-size: 13px; }
```

### Badges/Pills (status-markeringar)

```css
.badge {
  display: inline-flex; align-items: center;
  height: 22px; padding: 0 8px;
  border-radius: var(--radius-full);
  font-size: 12px; font-weight: 500;
  letter-spacing: -0.005em;
}
.badge-neutral { background: var(--color-bg-sunken); color: var(--color-text-muted); }
.badge-accent { background: var(--color-accent-subtle); color: var(--color-accent-text); }
.badge-success { background: var(--color-success-bg); color: var(--color-success); }
.badge-warning { background: var(--color-warning-bg); color: var(--color-warning); }
.badge-danger { background: var(--color-danger-bg); color: var(--color-danger); }
```

### Navigation (top bar i dashboard)

- Höjd: 56px
- Bakgrund: `var(--color-bg-elevated)`
- Border-bottom: `1px solid var(--color-border)`
- Vänster: ordmarkering "Vittring" i 18px Inter Tight 500
- Höger: e-postadress + meny-trigger
- **Inga ikoner** i navigation förutom user-avatar (initialer i cirkel, 28px)

### Larm-rad (kärnkomponent — så här ser ett mejlat larm ut i dashboard)

```html
<div class="alert-row">
  <div class="alert-row-meta">
    <span class="badge badge-neutral">Jobb</span>
    <span class="alert-row-date mono">04 maj 14:32</span>
  </div>
  <h3 class="alert-row-title">ICA Sverige AB söker 12 truckförare</h3>
  <p class="alert-row-detail">
    Västerhaninge · Heltid · Tillsvidareanställning
  </p>
  <a href="..." class="alert-row-link">Läs annonsen ↗</a>
</div>
```

```css
.alert-row {
  padding: 20px 0;
  border-bottom: 1px solid var(--color-border-subtle);
}
.alert-row-meta { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; }
.alert-row-date { color: var(--color-text-subtle); font-size: 12px; }
.alert-row-title { font-size: var(--text-md); font-weight: 500; margin: 0 0 4px; letter-spacing: -0.015em; }
.alert-row-detail { color: var(--color-text-muted); font-size: var(--text-sm); margin: 0 0 8px; }
.alert-row-link { color: var(--color-accent); font-size: var(--text-sm); text-decoration: none; }
.alert-row-link:hover { text-decoration: underline; }
```

---

## Landningssidan — specifika regler

- **Inget centrerat hero.** Vänsterställd rubrik, max 720px bred container, generösa marginaler ovan/under.
- **Inget "Get started for free"-knappspam.** Max två CTA i hela hero-sektionen.
- **Långt textinnehåll.** Skrivet som argumenterande text, inte bullet-listor med ikoner. Förklara *varför* säljaren behöver Vittring i prosaform.
- **Skärmdumpar > illustrationer.** Visa faktisk produkt (mejldigest, dashboard) — inte stiliserade abstrakta former.
- **Pricing visas i en enkel tabell**, inte tre flytande kort. Tre kolumner i samma kort/border.
- **Footer är tråkig.** Logotyp, länkar (juridiskt, kontakt, status), copyright. Ingen newsletter-signup, inget social-media-pyssel.

---

## Email-design (digest-mejlet)

Eftersom mejlet är produkten, inte bara en notis, måste det också följa designsystemet. Tabellbaserad HTML (för email-klienter) men med samma typografi och färger.

- **Bakgrund:** `#FAFAF7` (off-white)
- **Innehållsbredd:** 600px, vänsterställd
- **Header:** "Vittring" som ordmark i toppen, 14px små caps är inte tillåtet — vanlig case 18px
- **Sektioner:** rubriker per prenumeration i 16px medium, signaler under som ett enkelt staplat format med 1px subtila avdelare
- **Inga färgade boxar.** Vit bakgrund, vänsterställd text.
- **Källänkar i marinblå**, understruken vid hover (men hover är begränsat i e-post — bara sätt color)
- **Footer:** liten 12px text med avregistreringslänk, kontaktinfo, fysisk adress (krävs av lag)

---

## Acceptanskriterier för all UI

Innan en sida/komponent är klar måste den passera dessa kontroller:

1. Inga gradients någonstans (sök CSS efter `linear-gradient`, ska ge 0 träffar).
2. Inga `box-shadow` förutom på `:focus-visible`.
3. Inga `border-radius` över 8px (förutom pills/avatars med `--radius-full`).
4. Inga emojis i HTML (sök efter unicode-emojis, ska ge 0 träffar).
5. Inga importer från Google Fonts, jsdelivr eller andra CDNs för fonts.
6. All text använder `--font-sans` eller `--font-mono`, ingen direkt `font-family` med specifikt namn.
7. Alla färger refererar CSS-variabler, inga inline hex-koder.
8. Sidan ska se rimlig ut även med inaktiverat CSS — semantisk HTML först, styling sedan.
9. Tab-navigering fungerar genom hela sidan, fokus är synligt.
10. Kontrastkrav: alla text/bakgrund-kombinationer klarar WCAG AA (4.5:1 för normal text, 3:1 för stora rubriker).
