# Design system för Vittring

> **Revision: 2026-05-05.** Den första versionen av detta dokument var överrestriktiv och resulterade i en utseendet som kändes generiskt och tomt. Den har ersatts. Vittring är en premium tech-produkt och ska se ut därefter.

---

## Filosofi

Vittring är ett seriöst verktyg för säljteam som tar sitt jobb på allvar. Designen ska kännas:

- **Modern** — som Linear, Vercel, Stripe, Resend. Inget 2015-aktigt.
- **Substantiell** — sidan ska ha tyngd. Generösa storlekar, tydlig hierarki, riktig produkt-preview.
- **Distinkt** — inte ännu en "blue SaaS" med Tailwind-defaults. En egen accent, en egen typografisk identitet.
- **Trovärdig** — vi säljer förtroende. Polerade detaljer, tydliga proportioner, inga halvvägs-genomförda element.

### Anti-patterns vi fortfarande undviker

- Stockillustrationer av abstrakta människor / former
- "Trusted by"-loggrader (vi har inte 50 logos att visa upp; falska sådana vore värre än ingen)
- AI-genererade bilder eller emojis i UI-text (i copyn)
- Marketing-floskler: "AI-powered", "Next-gen", "Boost", "Supercharge"
- 5 olika gradients i samma vy
- 3-kort-mönstret med ikoner överallt — 3 feature-kort är OK om de tjänar ett syfte

---

## Färger

CSS-variabler i `src/vittring/static/css/tokens.css`. Aldrig hex-värden direkt i komponenter.

- `--color-bg` (`#FAFAF9`) — varm off-white huvudbakgrund
- `--color-bg-elevated` (`#FFFFFF`) — kort, modaler
- `--color-bg-dark` (`#0B1220`) — CTA-banner, eventuella mörka sektioner
- `--color-accent` (`#0F2A3D`) — djup marin, primär brand
- `--color-accent-bright` (`#2E6CDB`) — brandblå för CTA-knappar och länkar
- `--color-highlight` (`#C2A65A`) — varm guld, sparsamt för att markera viktigt

Semantiska färger (success/warning/danger) är dämpade nyanser, aldrig grälla.

---

## Typografi

- **Inter** via Google Fonts (vikt 400/500/600/700). Det är vanligt — men välimplementerat slår det allt annat.
- **JetBrains Mono** för datum, organisationsnummer, summor, koder.
- Display-rubriker (`h1`) går ned till `--tracking-tighter` (`-0.04em`) — tight letter-spacing är en del av premium-känslan.
- Brödtext: 16px / 1.65 line-height för läsbarhet.
- `font-feature-settings: "cv11", "ss01", "ss03"` — Inter har subtila stylistiska set som höjer kvaliteten.

Skala: 12, 14, 16, 18, 20, 24, 30, 36, 48, 60, 72px (`--text-xs` → `--text-6xl`).

---

## Spacing och radius

Spacing från 4px upp till 128px (`--space-1` → `--space-10`). Generösa marginaler ovan/under sektioner — tomrum är polerat när det är medvetet.

Radius:
- 6px för knappar och inputs (`--radius-sm`/`--radius-md`)
- 14px för kort (`--radius-lg`)
- 20px för stora paneler / hero-element (`--radius-xl`)
- Ingen oändlig 2xl-rundning — tappar precision

---

## Skuggor

Subtila och skiktade. Endast `--shadow-xs`/`--shadow-sm`/`--shadow-md`/`--shadow-lg`. Aldrig 4-px gula glow-skuggor eller andra dekorativa effekter.

`--shadow-glow` används som focus-ring för CTA-knappar (4px halo i accentfärgen).

---

## Hero-sektioner

Två-kolumns hero på desktop:
- Vänster: eyebrow + h1 (60-72px) + lead + två CTA + meta-rad
- Höger: konkret produkt-preview (mejldigest) i en card med subtil skugga

På mobil staplas det.

Bakgrund: subtil `radial-gradient` av accentfärgen i ena hörnet — mycket dämpat, ger djup utan att vara skrikigt.

---

## Sektioner

Varje sektion har en `section-head`:
- Eyebrow (mono, uppercase, accent-färgad, med horisontell linje innan)
- H2 (28-36px, tracking-tight)
- Lead-paragraf (muted, 18px)

Tunna `section-divider` mellan sektioner.

---

## Komponenter

- **Knappar:** primary (mörk), accent (brandblå), secondary (vit, border), ghost. Alla har subtil skugga och `transform: translateY(-1px)` på hover.
- **Kort:** vit bakgrund, 1px border, 14px radius, generös padding (32px). Hover lyfter med skugga.
- **Pricing-grid:** tre kolumner i ett delat kort med interna borders. Mellersta tier har subtil gradient-bakgrund för att markera "rekommenderad".
- **Email-digest preview:** stiliserad som ett mejlfönster med mac-style trafikljus i toppen. Real text och badges för konkretion.
- **CTA-banner:** mörk bakgrund med radial-gradient, vit text, kontrasterande knappar.
- **FAQ:** vertikal stack med tunna borders, fett spörsmål, muted svar.

---

## Layout

- Container default: 1200px
- Container narrow: 720px (för långa textstycken som FAQ)
- Container wide: 1440px (sällan, för väldigt breda dashboards)

Topbar är sticky med backdrop-blur — modernt och fungerellt (du ser alltid var du är).

---

## Acceptanskriterier

Innan en ny sida går live:

1. Den ska se ut som en **riktig SaaS från 2026**, inte som en HTML-tutorial.
2. Ingen tom-sektion — om inget viktigt finns där, ta bort sektionen.
3. Hero ska ha en konkret visuell pjäs (preview, screenshot, eller demonstration). Aldrig bara text + två knappar.
4. Typografin ska ha tydlig hierarki — eyebrow → H1 → lead → body.
5. Footer ska vara funktionell men inte luftig — länkar, copyright, klart.
6. Alla CTA-knappar fungerar och leder rätt.
7. Tab-navigering fungerar, focus är synlig (`box-shadow` ring i accentfärg).
8. Designen håller på 1440px+ skärmar — ingen tom luft till vänster/höger.
