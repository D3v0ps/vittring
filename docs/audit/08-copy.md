# 08 — Copy & brand voice audit

Read-only audit of the Swedish copy across the public site, auth pages,
in-app surfaces, admin console and email templates. Scope:

- `src/vittring/api/templates/_layout.html.j2`
- `src/vittring/api/templates/public/{landing,pricing,legal_privacy,legal_terms,unsubscribe}.html.j2`
- `src/vittring/api/templates/auth/{_auth_base,login,signup,2fa_enable,check_email,password_reset_request,password_reset_confirm,verify_failed,verify_ok}.html.j2`
- `src/vittring/api/templates/app/{dashboard,_stub,subscriptions,subscription_form,account}.html.j2`
- `src/vittring/api/templates/admin/{_layout,overview,users,user_detail,user_new,subscriptions,signals,audit,system,email}.html.j2`
- `src/vittring/delivery/templates/{_base,digest.html,digest.txt,welcome,verify,reset_password}.html.j2`

The brand spec (see `CLAUDE.md` §2) calls for Swedish that is professional,
direct and terse — staffing-industry vocabulary, no marketing jargon, no
emojis, no English loanwords where Swedish exists, sentence-case headings,
proper Swedish typography.

---

## 1. Source exclusivity (HARD RULE)

> "Vittring monitors three signals from open Swedish and EU government data"
> — but the upstream provider names are NEVER named in user-facing copy.

### Status: clean.

A targeted scan of every public-facing template for `JobTech`,
`Bolagsverket`, `TED`, `PoIT`, `Arbetsförmedlingen`, `ted.europa.eu`,
`jobsearch.api.jobtechdev.se`, `poit.bolagsverket.se` and `af.se` returned
**zero hits** in any rendered copy.

The closest neutral references that remain are healthy and source-agnostic
(they describe the underlying object, not the upstream pipe). They are
listed below for completeness — none requires changes:

| File | Line | Excerpt | Verdict |
|---|---|---|---|
| `src/vittring/api/templates/public/legal_terms.html.j2` | 15 | "källorna är offentliga API:er och kungörelser" | OK — generic, does not name a source |
| `src/vittring/api/templates/public/landing.html.j2` | 173 | "Vittring scannar tre offentliga register dygnet runt" | OK — count + nature, no provider |
| `src/vittring/api/templates/public/landing.html.j2` | 389 | "Svenska och europeiska myndighetskällor via öppna API:er" | OK — generic |
| `src/vittring/api/templates/app/subscription_form.html.j2` | 137 | "Branschklassificering från SCB" | Edge case — SCB is the issuer of SNI codes, not a Vittring data source. Acceptable factual reference. |
| `src/vittring/api/templates/app/subscription_form.html.j2` | 188-189 | "EU:s upphandlingsklassificering. CPV är EU:s standardklassificering för upphandlingar." | OK — describes the CPV taxonomy itself |

**Action: none required.**

If a future change adds copy referencing source providers, the search
patterns above should be added to a CI lint step.

---

## 2. Voice and register

The brand voice is mostly on-target — terse, confident, no emoji, no
"AI-powered / Boost / Supercharge / Next-gen / Game changer" violations
were found in any rendered template.

A few weak spots remain.

### 2.1 Footer tagline uses an English business term

| File | Line | Current | Problem |
|---|---|---|---|
| `src/vittring/api/templates/_layout.html.j2` | 103 | `Sales intelligence för bemanningsbranschen.` | "Sales intelligence" is unnecessary anglicism — the rest of the site is Swedish. |

**Suggested replacement:** `Säljunderrättelse för bemanningsbranschen.`
or, more naturally: `Säljunderlag för bemanningsbranschen — varje morgon.`

### 2.2 Anglicized verb in hero lede

| File | Line | Current | Problem |
|---|---|---|---|
| `src/vittring/api/templates/public/landing.html.j2` | 173 | "Vittring scannar tre offentliga register dygnet runt." | "scannar" is an anglicism; Swedish uses "söker av", "genomsöker", "bevakar". |

**Suggested replacement:** `Vittring genomsöker tre offentliga register
dygnet runt.` or `Vittring bevakar tre offentliga register dygnet runt.`
(Prefer "bevakar" — it ladders with the brand verb "bevakning".)

### 2.3 "inbox" is used twice — Swedish is "inkorg" or "mejl"

| File | Line | Current | Problem |
|---|---|---|---|
| `src/vittring/api/templates/public/landing.html.j2` | 173 | "i din inbox 06:30" | English word in Swedish copy |
| `src/vittring/api/templates/public/landing.html.j2` | 291 | "06:30 ligger digesten i inboxen" | English word in Swedish copy |
| `src/vittring/api/templates/auth/_auth_base.html.j2` | 104 | "I din inbox" | English word in Swedish copy |

Note: `auth/check_email.html.j2:4` correctly uses "inkorg".

**Suggested replacement (consistent everywhere):** "inkorg" or "mejlbox".

### 2.4 "live demo" — English in a CTA

| File | Line | Current | Problem |
|---|---|---|---|
| `src/vittring/api/templates/public/landing.html.j2` | 177 | `Se live demo` | English phrase. |

**Suggested replacement:** `Visa demo` or `Se demon` or `Visa exempel`.

### 2.5 "dashboard" / "Dashboard" — capitalization & loan word

| File | Line | Current | Problem |
|---|---|---|---|
| `src/vittring/api/templates/_layout.html.j2` | 78 | "Till dashboarden →" | English loan with Swedish suffix; OK informally but inconsistent with the rest of the brand. |
| `src/vittring/api/templates/_layout.html.j2` | 109 | "Dashboard" (footer link) | Title-case English |
| `src/vittring/api/templates/admin/_layout.html.j2` | 362 | "↩ Dashboard" | Same issue, in admin |
| `src/vittring/api/templates/app/dashboard.html.j2` | 8 | `<title>Vittring — Dashboard</title>` | Title in `<title>` tag |

Recommended single Swedish term: **"Översikt"** (already used in nav — see
`dashboard.html.j2:169` "Översikt"). The footer/page-title uses for
"Dashboard" should match.

### 2.6 "Mest valda" pricing pill (capitalization)

| File | Line | Current | Comment |
|---|---|---|---|
| `src/vittring/api/templates/public/pricing.html.j2` | 17 | `content: 'Mest valda';` | Acceptable — it's a UI badge in mono caps. Keep, but ensure it renders uppercase by the CSS rule (it does, line 22). |

### 2.7 Stub language ("Kommer snart") — fine

`src/vittring/api/templates/app/_stub.html.j2:164` uses "Kommer snart" —
correct Swedish, on-tone.

---

## 3. Vocabulary consistency: prenumeration / filter / bevakning

The codebase mixes three terms. They are conceptually distinct but the UI
uses them interchangeably, which fragments the mental model:

- **prenumeration** — the saved object the user owns (canonical)
- **filter** — a sub-property of a prenumeration (the criteria)
- **bevakning** — the activity / outcome ("we monitor on your behalf")

### Inconsistencies found

| File | Line | Excerpt | Problem |
|---|---|---|---|
| `src/vittring/api/templates/app/subscriptions.html.j2` | 7 | `<h1>Dina filter</h1>` | The page header calls them "filter", but the table, the empty state, the CTA, and every other surface calls them "prenumerationer". Cognitive jolt. |
| `src/vittring/api/templates/app/subscriptions.html.j2` | 9 | "Definiera vad som matchar i den dagliga digesten." | Implicitly treats "filter" = "prenumeration". |
| `src/vittring/api/templates/app/subscription_form.html.j2` | 7 | `<h1>Bygg din bevakning</h1>` | Form for creating a "prenumeration" but headline says "bevakning". |
| `src/vittring/api/templates/public/pricing.html.j2` | 87, 106, 125 | "Delade filter och taggar" | "filter" used as a feature, distinct from "prenumeration" — fine here. |
| `src/vittring/api/templates/public/landing.html.j2` | 343 | "filtrerade och sorterade efter dina filter" | OK — "filter" used as a verb-derived noun. |

**Recommended convention (write this into a brand glossary):**

- "Prenumeration" = the saved unit. Always plural noun in lists, headings,
  navigation. Pricing rows, sidebar entries, account page row.
- "Filter" = a single criterion inside a prenumeration (kommun, SNI, CPV,
  keywords). Used inside the form and inside the sub-feature "Delade
  filter och taggar".
- "Bevakning" = the activity verb. Used in marketing copy ("vi bevakar"),
  in tooltips ("Bevakning aktiv"), and in hint copy. Never used for the
  saved object itself.

### Fixes

| File | Line | Change |
|---|---|---|
| `app/subscriptions.html.j2` | 7 | `Dina filter` → `Dina prenumerationer` |
| `app/subscription_form.html.j2` | 7 | `Bygg din bevakning` → `Skapa prenumeration` (matches form CTA at line 220) |
| `app/subscription_form.html.j2` | 54 | `Realtids-bevakning av rekryteringsbehov` → `Bevakning av rekryteringsbehov` (drop the dangling, also-anglicized "realtids-" — see §7) |

---

## 4. Tone consistency

Brand spec: landing should be **bold and confident**, auth should feel
**calm and assuring**, admin should feel **operational and precise**.

| Surface | Verdict | Notes |
|---|---|---|
| Landing (`public/landing.html.j2`) | Bold/confident — on-tone | Em-dash usage, em-styled italics, "Sluta gissa. Börja vittra." closer is on-brand. |
| Pricing (`public/pricing.html.j2`) | On-tone | Calm but firm. |
| Legal (`legal_*`) | On-tone | Plainspoken, factual, professional. Good. |
| Auth pages | Slightly **too loud** in places — see below |
| App / dashboard | Mostly precise but mixes tones — see below |
| Admin | Operational, terse — on-tone |

### 4.1 Auth pages: lower the marketing volume

`auth/_auth_base.html.j2:88-95` reuses the landing testimonial verbatim in
the auth side panel. That's OK but feels like a marketing pitch sneaking
into a sign-in form. The brand brief calls for "calm and assuring" on auth.

**Suggested fix (lines 88-89):** drop the "FRÅN VÅRA TIDIGA ANVÄNDARE"
eyebrow and the emphatic italic. Keep one short, low-key reassurance:

```
Vittring bevakar tre offentliga register åt dig. Du får bara träffar
som matchar dina filter, varje morgon kl 06:30.
```

Also `auth/login.html.j2:9` — `Logga in för att se dagens digest.` — too
casual. Suggested: `Logga in för att se dagens signaler.` (matches the
sidebar nav "Digest <count>" but reads better in a sentence.)

### 4.2 App copy is mostly fine, two snags

| File | Line | Current | Note |
|---|---|---|---|
| `app/dashboard.html.j2` | 367-368 | "— Slut på dagens digest. Nästa hämtning {{ next_sync_time }} imorgon. —" | Tone OK; "hämtning" is a slight tech leak. Suggest `Nästa uppdatering imorgon kl {{ next_sync_time }}.` |
| `app/dashboard.html.j2` | 362 | "Dagens digest är tom — kom tillbaka imorgon." | Acceptable, friendly. |

### 4.3 Admin tone — on-target

Admin copy across all `admin/*.html.j2` is appropriately operational
and precise. Tone is good. The only minor remark is `overview.html.j2:9` —
`Total kontroll över plattformen.` — slightly grandiose. Consider
`Drift, användare och leveranser i en vy.`

---

## 5. Capitalization (sentence case vs Title Case)

Swedish convention: sentence case for headings and labels. Title Case is
reserved for proper nouns and English-derived UI labels (sparingly).

### Title-case headings that should be sentence case

| File | Line | Current | Suggested |
|---|---|---|---|
| `_layout.html.j2` | 73 | `Funktioner` | OK (single word) |
| `_layout.html.j2` | 106 | `Produkt` | OK (single word) |
| `_layout.html.j2` | 114 | `Företag` | OK (single word) |
| `_layout.html.j2` | 122 | `Juridik` | OK (single word) |
| `auth/_auth_base.html.j2` | 100 | `Signaler / dygn` | OK |
| `app/account.html.j2` | 130 | `Data &amp; integritet` | OK |
| `admin/overview.html.j2` | 81 | `Senaste användare` | OK (sentence case) |
| `admin/overview.html.j2` | 104 | `Senaste audit` | OK |
| `admin/system.html.j2` | 21 | `Schemaläggare` | OK |
| `admin/audit.html.j2` | 8 | `Audit-logg` | OK |

### All-caps eyebrow labels — appropriate as monospace eyebrows

`SENASTE 60 MIN`, `VAD VI BEVAKAR`, `JURIDIK`, `PRISER · MAJ 2026`, etc.
These are styled as `t-eyebrow` (mono, letter-spaced, uppercase). The
all-caps is **rendering**, not source — source is sentence case in the
code. OK.

### Verdict: no Title Case violations.

The Swedish headings throughout are all in sentence case. The only
all-caps are the deliberately-styled `t-eyebrow` and `t-mono` labels,
which are a design-system convention rather than a copy issue.

---

## 6. Punctuation

### 6.1 Quotation marks

Swedish best practice is to use either `»…«` (Swedish/German chevrons) or
`"…"` (typographic curly). The codebase uses straight ASCII `"` in two
load-bearing testimonials and the typographic curly `”…”` elsewhere.

| File | Line | Current | Issue |
|---|---|---|---|
| `public/landing.html.j2` | 364 | `"Vi har gått från att jaga rykten…"` | ASCII straight quotes |
| `auth/_auth_base.html.j2` | 89 | `"Vi har gått från att jaga rykten…"` | ASCII straight quotes |
| `app/dashboard.html.j2` | 236 | `”{{ search_query }}”` | Curly quotes — correct |
| `app/dashboard.html.j2` | 360 | `”{{ search_query }}”` | Correct |
| `legal_privacy.html.j2`, `legal_terms.html.j2`, `auth/*` | — | use straight ASCII inside `<em>` for short emphasized phrases | Acceptable since the `<em>` already provides typographic emphasis. No fix needed. |

**Action:** in the two testimonial blocks, swap `"…"` → `”…”`. Also
consider `»…«` per the design system if Karim wants the colder look.

### 6.2 Em-dash vs hyphen — clean

A scan of `_layout`, `landing`, `pricing`, and `auth/_auth_base` shows
proper U+2014 em-dashes (`—`) used consistently as separator and
parenthetical. No instances of " - " (hyphen-as-em-dash) in body copy.

### 6.3 Number ranges — no violations found

A scan for `\d-\d` patterns in copy (excluding CSS, dates, SVG paths,
class names) returned zero hits. No "5-10" hyphenated ranges.

### 6.4 Other punctuation

- **Triple-dot ellipses** (`…`) used correctly in placeholders (e.g.
  `placeholder="Sök bolag, CPV, ort…"` — `dashboard.html.j2:220`). Good.
- **Decimal comma** correctly used (`99,5 %` — `landing.html.j2:286`).
- **Percent sign** has a thin space before it (`99,5 %`). Correct
  Swedish typography.

---

## 7. Compound words and hyphenation

Swedish is famously compound-heavy. The brand spec calls these out:
"bemanningsbranschen", "konsultchef" — must be one word.

### Status: mostly clean.

A scan for split-compound bugs (`bemannings-branschen`, `konsult-chef`,
etc.) returned **zero hits**. All occurrences of "bemanningsbranschen",
"bemanningsföretag", "rekryteringsbehov", "bolagshändelser",
"konsultchefer" are correctly compounded.

### Two suspect hyphenations to revisit

| File | Line | Current | Issue |
|---|---|---|---|
| `app/subscription_form.html.j2` | 54 | `Realtids-bevakning av rekryteringsbehup` | "Realtids-bevakning" is a wrong split — Swedish writes this either as one word "realtidsbevakning" or as two "bevakning i realtid". The hyphenated form is anglicism. |
| `auth/2fa_enable.html.j2` | 4 | `authenticator-app` | This is the conventional Swedish form (compound noun with English component gets a hyphen). OK. |
| `app/account.html.j2` | 97 | `Tvåfaktorsautentisering med en authenticator-app.` | Same — OK. |

**Suggested replacement for `subscription_form.html.j2:54`:**
`Bevakning av rekryteringsbehov i realtid.` (combines fix from §3 and §7).

---

## 8. Em-dash usage (U+2014 vs hyphen)

The design uses em-dashes liberally for stylistic separators ("Vittring —
{N} nya signaler", "Klart, daterat — direktlänkat", "Stockholm — Ramavtal
lager"). All instances inspected use the correct U+2014.

Specifically verified clean in:
- `_layout.html.j2` (footer, brand cluster)
- `public/landing.html.j2` (hero, source cards, testimonial, FAQ, final CTA)
- `auth/_auth_base.html.j2` (testimonial)
- `delivery/templates/digest.html.j2:13` (heading separator)

**No issues.**

---

## 9. Numbers, units, time

### 9.1 Time format

Swedish standard is `HH:MM` (colon), not `HH.MM` (dot).

| File | Line | Current | Verdict |
|---|---|---|---|
| `public/landing.html.j2` | 173, 291 | `06:30` | Correct |
| `auth/_auth_base.html.j2` | 103 | `06:30` | Correct |
| `public/pricing.html.j2` | 86, 105, 124 | `06:30` | Correct |
| `app/subscriptions.html.j2` | 70 | `kl 06:30` | Correct |
| `app/dashboard.html.j2` | 213-216 | `{{ today_weekday }} {{ today_date }}` | Renders via Jinja — depends on backend |

**No issues.**

### 9.2 Money

| File | Line | Current | Verdict |
|---|---|---|---|
| `public/pricing.html.j2` | 79, 98, 117 | `1 500 kr`, `2 500 kr`, `4 000 kr` | Correct — non-breaking-style space (actual char on disk is regular space; for production-grade typography, a U+00A0 NBSP would be marginally better between `1 500` and `kr`) |
| `public/landing.html.j2` | 241 | `12 mkr · CPV 79620000` | "mkr" is a Swedish convention for million SEK. Acceptable. Note: the alternative "MSEK" or "12 Mkr" exist; keep "mkr" lowercase as in this file. |

**Suggested non-blocking improvement:** if Karim wants production-grade
typography, replace the regular spaces in `1 500 kr`, `2 500 kr`, `4 000
kr` and the "kr"/"mkr" suffix-gap with U+00A0 (non-breaking space). Not
required.

### 9.3 Other numbers

- `99,5 %` (`landing.html.j2:286`) — decimal comma + thin space + percent.
  Correct Swedish convention.
- `+18% v/v` (`landing.html.j2:219`) — percent **without** space.
  Inconsistent with `99,5 %`. Suggest `+18 % v/v` for parity. Also `v/v`
  is jargon; consider `+18 % vecka över vecka` or simply `+18 % senaste
  veckan`.

---

## 10. CTA wording

Brand spec: every primary button is a verb.

### Verdict: mostly compliant.

| Surface | CTA | Verdict |
|---|---|---|
| Landing hero | `Starta provperiod →` | Verb — OK |
| Landing hero | `Se live demo` | Verb — OK (but "live demo" is English; see §2.4) |
| Landing final | `Starta provperiod →` | OK |
| Landing final | `Boka samtal` | Verb — OK |
| Pricing card 1 | `Välj Solo →` | Verb — OK |
| Pricing card 2 | `Välj Team →` | Verb — OK |
| Pricing card 3 | `Välj Pro →` | Verb — OK |
| Pricing footnote | `Hör av dig direkt` | Verb — OK |
| Auth | `Skapa konto →` | Verb — OK |
| Auth | `Logga in →` | Verb — OK |
| Auth | `Bekräfta och logga in →` | Verb — OK |
| Auth | `Skicka återställningslänk →` | Verb — OK |
| Auth | `Spara nytt lösenord →` | Verb — OK |
| Auth | `Aktivera tvåfaktor →` | Verb — OK |
| Auth | `Till inloggning →` | Preposition CTA — non-verb but conventional. OK in finalstate templates. |
| App | `Ny prenumeration` (`app/subscriptions.html.j2:16`, `dashboard.html.j2:225`) | **Noun** — should be "Skapa prenumeration" or "+ Lägg till prenumeration". Two surfaces affected. |
| App | `Skapa första prenumerationen` (`subscriptions.html.j2:90`) | Verb — OK |
| App | `Skapa prenumeration` (`subscription_form.html.j2:220`) | Verb — OK |
| App | `Exportera CSV` (`dashboard.html.j2:224`) | Verb — OK |
| App account | `Exportera JSON`, `Radera kontot` | Verb — OK |
| Admin | `+ Skapa användare` | Verb — OK |
| Admin | `Filtrera`, `Rensa`, `Pausa`, `Aktivera`, `Spara` | Verb — OK |
| Admin | `Snabbåtgärder` (section heading) | Noun — fine, it's a label |

### Fixes

| File | Line | Change |
|---|---|---|
| `app/subscriptions.html.j2` | 16 | `Ny prenumeration` → `Skapa prenumeration` |
| `app/dashboard.html.j2` | 225 | `+ Ny prenumeration` → `+ Skapa prenumeration` (and update the sidebar link "+ ny prenumeration" on lines 181 and `_stub.html.j2:124` for parity) |

---

## 11. Top 10 weakest sentences — with replacements

These are the highest-leverage rewrites in priority order. Numbering tracks
the sections above.

### #1 — `_layout.html.j2:103` (footer tagline)
```
Sales intelligence för bemanningsbranschen.
```
**→** `Säljunderlag för bemanningsbranschen — varje morgon.`

### #2 — `public/landing.html.j2:173` (hero lede)
```
Vittring scannar tre offentliga register dygnet runt. Du får det som
rör dig — i din inbox 06:30, eller som push i appen.
```
**→** `Vittring bevakar tre offentliga register dygnet runt. Det som rör
dig hamnar i din inkorg kl 06:30 — eller som notis i appen.`

### #3 — `public/landing.html.j2:291` (step 3 desc)
```
06:30 ligger digesten i inboxen. Klart, daterat, direktlänkat.
```
**→** `Klockan 06:30 ligger digesten i inkorgen. Klar, daterad,
direktlänkad.`

### #4 — `public/landing.html.j2:177` (secondary CTA)
```
Se live demo
```
**→** `Visa demon`

### #5 — `app/subscriptions.html.j2:7` (page heading)
```
Dina filter
```
**→** `Dina prenumerationer`

### #6 — `app/subscription_form.html.j2:7` (form heading)
```
Bygg din bevakning
```
**→** `Skapa prenumeration` (parity with submit button on line 220)

### #7 — `app/subscription_form.html.j2:54` (signal option meta)
```
Realtids-bevakning av rekryteringsbehov
```
**→** `Bevakning av rekryteringsbehov i realtid`

### #8 — `auth/_auth_base.html.j2:89` (testimonial in auth side panel)
```
"Vi har gått från att jaga rykten till att ringa kunder samma morgon
som de annonserar — tre samtal om dagen, alla kvalificerade."
```
**→** Replace with calmer reassurance copy:
`Vittring bevakar tre offentliga register åt dig. Du får bara träffar
som matchar dina filter — varje morgon kl 06:30.`
Also drop the eyebrow `FRÅN VÅRA TIDIGA ANVÄNDARE` from line 88.

### #9 — `auth/login.html.j2:9` (sub-line)
```
Logga in för att se dagens digest.
```
**→** `Logga in för att se dagens signaler.`

### #10 — `app/dashboard.html.j2:367-368` (end-of-feed footer)
```
— Slut på dagens digest. Nästa hämtning {{ next_sync_time }} imorgon. —
```
**→** `— Slut på dagens digest. Nästa uppdatering imorgon kl
{{ next_sync_time }}. —`

---

## 12. Summary — issues by severity

| Severity | Count | Examples |
|---|---|---|
| Source-exclusivity violations | 0 | clean |
| English loanwords / anglicisms | 6 | "Sales intelligence", "scannar", "inbox" ×3, "live demo" |
| Vocabulary inconsistency (prenumeration / filter / bevakning) | 3 | `subscriptions.html.j2:7`, `subscription_form.html.j2:7`, `subscription_form.html.j2:54` |
| Tone mismatches | 2 | auth-page testimonial loudness, "Total kontroll" in admin |
| Quotation-mark style | 2 | both testimonial blocks use ASCII `"…"` |
| Capitalization | 0 | all-caps eyebrows are intentional design-system styling |
| Compound-word splits | 1 | "Realtids-bevakning" |
| Em-dash usage | 0 | clean |
| Number/unit formatting | 1 | `+18% v/v` lacks space before `%`, jargon |
| CTA noun-only | 2 | "Ny prenumeration" appears twice |
| Loose typographic improvements | 3 | NBSP between `1 500` and `kr`; `”…”` vs `»…«`; `kl` consistency |

The site is overall well-written. The biggest leverage rewrites are the
top three (hero lede, footer tagline, step 3) which appear above the
fold on the public landing.

---

*Auditor: read-only. No code changes made.*
