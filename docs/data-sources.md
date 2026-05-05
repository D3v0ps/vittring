# Data sources

API contracts and field mappings for the three open-data signals Vittring ingests.
All adapters live under `src/vittring/ingest/` and conform to the `IngestAdapter`
protocol (async generator yielding normalised dataclasses, with a `fetch_since(ts)`
entry point).

## JobTech (Arbetsförmedlingen)

New job postings published by Swedish employers.

| Property | Value |
|---|---|
| Base URL | `https://jobsearch.api.jobtechdev.se` |
| Auth | None (open data) |
| Schedule | Daily 06:00 Europe/Stockholm |
| Page size | 100 |
| Rate limit | 4 requests/second (we self-throttle) |

### Endpoint

```
GET /search?published-after=<iso8601>&limit=100&offset=<n>
```

`published-after` is the watermark from the previous successful run, stored in
`ingest_state.last_published_at`. The adapter pages until `total < offset + limit`
and persists in batches of 100.

### Field mapping

| Source path | Target column | Notes |
|---|---|---|
| `hit.id` | `jobs.external_id` | Unique per JobTech, stable. |
| `hit.employer.organization_number` | `companies.orgnr` | Used to upsert the company; some hits lack this. |
| `hit.headline` | `jobs.headline` | Trimmed, no normalisation. |
| `hit.description.text` | `jobs.description` | May be empty; never null on persist. |
| `hit.occupation.label` | `jobs.occupation_label` | Human-readable Swedish title. |
| `hit.occupation.concept_id` | `jobs.occupation_concept_id` | Taxonomy id; used by matching engine. |
| `hit.workplace_address.municipality` | `jobs.municipality` | Free text; not normalised. |
| `hit.workplace_address.region` | `jobs.region` | E.g. "Stockholms län". |
| `hit.publication_date` | `jobs.published_at` | Parsed as UTC. |
| `hit.source_links[0].url` | `jobs.source_url` | First link only; usually the platsbanken URL. |

### Failure modes

- 5xx from JobTech: tenacity retries 3 times with exponential backoff, then the
  ingest run is marked failed and Sentry gets an event. Watermark is not advanced.
- Pagination beyond `total`: API returns 200 with empty hits; loop terminates cleanly.

## Bolagsverket (PoIT)

Company changes — board, CEO, address, name, remarks, liquidations, SNI codes.

| Property | Value |
|---|---|
| Default backend | PoIT (`https://poit.bolagsverket.se/poit/api/kungorelse/sok`) |
| Auth | None for PoIT |
| Schedule | Daily 06:00 Europe/Stockholm, after JobTech |

### Tracked change types

The adapter normalises Bolagsverket's `arendetyp` field into a fixed set of
`ChangeType` enum values:

| `arendetyp` value | `ChangeType` |
|---|---|
| `verkställande direktör` | `ceo` |
| `styrelseledamot`, `styrelsesuppleant`, `ordförande` | `board_member` |
| `adress` | `address` |
| `firmanamn`, `bifirma` | `name` |
| `särskild anmärkning` | `remark` |
| `likvidation`, `konkurs` | `liquidation` |
| `verksamhet (SNI)` | `sni` |

Unknown `arendetyp` values are logged at WARN and dropped.

### Personal-data retention (important)

Officer names appear in the JSON `old_value` and `new_value` columns of
`company_changes`. Per `docs/gdpr.md`, those rows are scrubbed nightly:

- Default retention: 30 days from `ingested_at`.
- Extended retention if the row was surfaced in a delivered alert: `delivered_at + 30 days`.

The scrub job replaces the `old_value`/`new_value` JSON with `{"redacted": true}`
in place; the row itself is kept for audit and aggregate reporting.

## TED (EU procurements)

Public procurement notices from the EU Tenders Electronic Daily.

| Property | Value |
|---|---|
| Base URL | `https://api.ted.europa.eu/v3/notices/search` |
| Country filter | `SE` |
| Schedule | Daily 06:00 Europe/Stockholm |

### CPV filter

We only fetch notices with at least one of these CPV codes (staffing-relevant):

```
79600000   Recruitment services
79610000   Placement services of personnel
79620000   Supply services of personnel including temporary staff
79621000   Supply services of office personnel
79624000   Supply services of nursing personnel
79625000   Supply services of medical personnel
85000000   Health and social work services (and 85xxxxxx descendants)
```

### Multilingual fields

Many TED fields are language-keyed maps. The adapter prefers `swe`, falls back
to `eng`, and stores the chosen language alongside the value:

```python
def pick(value: dict[str, str]) -> tuple[str, str]:
    for lang in ("swe", "eng"):
        if lang in value:
            return value[lang], lang
    # take whatever's there, deterministic by key sort
    lang = sorted(value)[0]
    return value[lang], lang
```

Stored as `procurements.title`, `procurements.title_lang` and the same pattern
for `description`.
