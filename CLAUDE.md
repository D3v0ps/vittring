# CLAUDE.md — Vittring

Production-grade SaaS for monitoring three open-data signals and alerting Swedish staffing-company sales teams. This document is the single source of truth for how the system is designed, built, deployed, and operated. Treat every section as a constraint, not a suggestion.

---

## 1. What this is

Vittring monitors three signals from open Swedish and EU government data and emails alerts to sales teams at Swedish staffing companies (bemanningsföretag):

1. **New job postings** — JobTech Dev (Arbetsförmedlingen)
2. **Company changes** — Bolagsverket (board, CEO, address, remarks, liquidation)
3. **Public procurements** — TED (EU) and Swedish national sources

**Target customer:** salespeople and account managers at Swedish staffing companies.

**Value proposition (used on landing page and in marketing copy):**
> "Vet vilket företag som behöver personal innan dina konkurrenter kontaktar dem."

---

## 2. Language and tone

- All user-facing copy (UI, email, errors, landing page, legal pages) is in **Swedish**, professional, direct.
- Use staffing-industry vocabulary: yrkesroller, ramavtal, kollektivavtal, KAM, konsultchef, underleverantör.
- No emoji. No marketing slogans. No English loanwords where Swedish exists.
- Internal code, comments, and commits in English.

---

## 3. Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Web framework | FastAPI |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Background jobs | APScheduler |
| Email | Resend |
| Templates | Jinja2 |
| Frontend | Plain HTML + HTMX (no React) |
| Auth | FastAPI-Users with JWT + email verification + 2FA (pyotp) |
| Payments | Stripe Checkout + Customer Portal |
| Logging | structlog (JSON output to journald) |
| Errors | Sentry |
| Uptime | UptimeRobot (free tier) pinging /health |
| Testing | pytest, pytest-asyncio, httpx, factory-boy |
| Lint/format | Ruff (lint + format) |
| Type checking | mypy strict |
| Pre-commit | pre-commit framework |
| CI/CD | GitHub Actions |

---

## 4. Domain, server, and infrastructure

| Resource | Value |
|---|---|
| Application domain | `vittring.karimkhalil.se` |
| Server provider | Hetzner Cloud |
| Server type | CX23 (2 vCPU, 4 GB RAM, 40 GB SSD) |
| Server location | Falkenstein (Germany, EU) |
| Server IP | `62.238.37.54` |
| OS | Ubuntu 24.04 LTS |
| Reverse proxy + TLS | Caddy 2 (automatic Let's Encrypt) |
| Process management | systemd |
| Backups | Hetzner snapshots (daily, 7 retained) + nightly `pg_dump` to Hetzner Storage Box |
| DNS | hosted at one.com (karimkhalil.se zone) |

**No Docker.** Direct venv on the host. Simpler ops, fewer moving parts.

---

## 5. Email configuration

- **Provider:** Resend
- **From address:** `info@karimkhalil.se`
- **From name:** `Vittring`
- **Reply-to:** `info@karimkhalil.se`
- **Sending domain (for DKIM/SPF):** `karimkhalil.se`
- **Return-path subdomain:** `bounce.karimkhalil.se` (configured by Resend, requires CNAME)

Karim has an existing mailbox `info@karimkhalil.se` at one.com — replies to alert emails land there. The Resend setup adds outbound sending capability without disturbing the existing inbox.

### DNS records required at one.com (Karim adds these manually)

Claude Code must NOT attempt to modify DNS. Instead, on first run, Claude Code:

1. Creates a Resend domain via Resend API for `karimkhalil.se`.
2. Reads the required DNS records from Resend's response.
3. Prints them in a clear format with hostname, type, value, and TTL.
4. Halts and instructs Karim to add them at one.com.
5. On next run, polls Resend's verification endpoint until verified, then continues.

The records are typically:

- One MX record at `bounce.karimkhalil.se` (for return-path)
- One CNAME at `bounce.karimkhalil.se` (for return-path)
- One TXT at `resend._domainkey.karimkhalil.se` (DKIM)
- One TXT at `karimkhalil.se` (SPF — must MERGE with existing one.com SPF, do not overwrite)
- One TXT at `_dmarc.karimkhalil.se` (DMARC)

**Critical:** the SPF record on `karimkhalil.se` likely already exists for one.com's mail. Claude Code must instruct Karim to merge the `include:` clauses, not replace the record. Failing to do so breaks Karim's existing email.

---

## 6. Repository structure

```
vittring/
├── CLAUDE.md
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock                          # use uv for dependency management
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── .github/
│   └── workflows/
│       ├── ci.yml                   # lint, test, mypy on every push
│       └── deploy.yml               # deploy to prod on tag
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── src/vittring/
│   ├── __init__.py
│   ├── main.py                      # FastAPI app entry
│   ├── config.py                    # pydantic-settings
│   ├── db.py                        # async SQLAlchemy session + engine
│   ├── logging.py                   # structlog setup
│   ├── models/
│   │   ├── __init__.py
│   │   ├── company.py
│   │   ├── signals.py
│   │   ├── user.py
│   │   ├── subscription.py
│   │   └── audit.py                 # audit log
│   ├── schemas/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py                  # signup, login, verify, 2FA, password reset
│   │   ├── account.py               # profile, GDPR export/delete
│   │   ├── subscriptions.py
│   │   ├── alerts.py
│   │   ├── billing.py               # Stripe Checkout + webhook
│   │   ├── public.py                # landing page, legal pages
│   │   └── health.py                # /health, /ready
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── base.py                  # IngestAdapter ABC
│   │   ├── jobtech.py
│   │   ├── bolagsverket.py
│   │   └── ted.py
│   ├── matching/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   └── criteria.py
│   ├── delivery/
│   │   ├── __init__.py
│   │   ├── email.py                 # Resend client
│   │   ├── domain_setup.py          # Resend domain verification flow
│   │   └── templates/
│   │       ├── digest.html.j2
│   │       ├── digest.txt.j2
│   │       ├── verify.html.j2
│   │       ├── reset_password.html.j2
│   │       └── welcome.html.j2
│   ├── jobs/
│   │   ├── __init__.py
│   │   └── scheduler.py
│   ├── security/
│   │   ├── __init__.py
│   │   ├── totp.py                  # 2FA
│   │   ├── ratelimit.py
│   │   └── csrf.py
│   ├── audit/
│   │   ├── __init__.py
│   │   └── log.py                   # audit log writer
│   └── utils/
│       └── errors.py                # exception hierarchy
├── tests/
│   ├── conftest.py
│   ├── factories.py                 # factory-boy fixtures
│   ├── test_matching.py             # 100% coverage required
│   ├── test_jobtech.py
│   ├── test_bolagsverket.py
│   ├── test_ted.py
│   ├── test_email.py
│   ├── test_auth.py
│   ├── test_billing.py
│   └── test_api.py
├── deploy/
│   ├── Caddyfile
│   ├── systemd/
│   │   ├── vittring-api.service
│   │   └── vittring-scheduler.service
│   ├── logrotate/
│   │   └── vittring
│   └── unattended-upgrades/
│       └── 50unattended-upgrades
├── scripts/
│   ├── server_bootstrap.sh          # idempotent server setup, run as root once
│   ├── deploy.sh                    # zero-downtime deploy, run as vittring user
│   ├── backup.sh                    # nightly pg_dump → Storage Box
│   ├── restore.sh                   # restore from backup
│   └── verify_dns.py                # checks DNS records exist before continuing
├── docs/
│   ├── deployment.md
│   ├── data-sources.md
│   ├── gdpr.md
│   ├── runbook.md                   # incident response
│   └── architecture.md
└── legal/
    ├── privacy_policy.sv.md
    ├── terms_of_service.sv.md
    ├── dpa_template.sv.md
    └── cookie_policy.sv.md
```

---

## 7. Pricing (configure as Stripe products)

> **Status: deferred.** Stripe integration is postponed. Until billing is enabled, all signups land on a permanent trial plan with no payment required. Schema, code paths, and webhook handlers should still be designed so that enabling Stripe later is purely configuration (price IDs + webhook secret).

| Plan | Price | Filters | Seats | Sources |
|---|---|---|---|---|
| Solo | 1 500 SEK/mån | 5 | 1 | All three |
| Team | 2 500 SEK/mån | 20 | 5 | All three |
| Pro | 4 000 SEK/mån | Unlimited | 15 | All three + HubSpot integration |

All prices ex VAT. Annual billing optional with 10 % discount. 14-day free trial on all plans, no credit card required to start.

---

## 8. Database schema

```sql
CREATE TABLE companies (
  id BIGSERIAL PRIMARY KEY,
  orgnr VARCHAR(13) UNIQUE NOT NULL,
  name TEXT NOT NULL,
  sni_code VARCHAR(10),
  hq_municipality TEXT,
  hq_county TEXT,
  employee_count_band TEXT,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_companies_municipality ON companies(hq_municipality);
CREATE INDEX idx_companies_sni ON companies(sni_code);

CREATE TABLE job_postings (
  id BIGSERIAL PRIMARY KEY,
  external_id TEXT UNIQUE NOT NULL,
  company_id BIGINT REFERENCES companies(id) ON DELETE SET NULL,
  employer_name TEXT NOT NULL,
  headline TEXT NOT NULL,
  description TEXT,
  occupation_label TEXT,
  occupation_concept_id TEXT,
  workplace_municipality TEXT,
  workplace_county TEXT,
  employment_type TEXT,
  duration TEXT,
  published_at TIMESTAMPTZ NOT NULL,
  source_url TEXT,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_jobs_published ON job_postings(published_at DESC);
CREATE INDEX idx_jobs_company ON job_postings(company_id);
CREATE INDEX idx_jobs_municipality ON job_postings(workplace_municipality);

CREATE TABLE company_changes (
  id BIGSERIAL PRIMARY KEY,
  company_id BIGINT REFERENCES companies(id) NOT NULL,
  change_type TEXT NOT NULL,
  old_value JSONB,
  new_value JSONB,
  source_ref TEXT,
  changed_at TIMESTAMPTZ NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  -- GDPR: rows older than 30 days with no surfaced delivered_alert get personal data scrubbed nightly
  personal_data_purged_at TIMESTAMPTZ
);
CREATE INDEX idx_changes_company_changed ON company_changes(company_id, changed_at DESC);
CREATE INDEX idx_changes_purge_candidate ON company_changes(ingested_at) WHERE personal_data_purged_at IS NULL;

CREATE TABLE procurements (
  id BIGSERIAL PRIMARY KEY,
  external_id TEXT UNIQUE NOT NULL,
  buyer_orgnr VARCHAR(13),
  buyer_name TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  cpv_codes TEXT[] NOT NULL DEFAULT '{}',
  estimated_value_sek BIGINT,
  procedure_type TEXT,
  deadline TIMESTAMPTZ,
  source_url TEXT,
  source TEXT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_proc_deadline ON procurements(deadline);
CREATE INDEX idx_proc_cpv ON procurements USING GIN(cpv_codes);

CREATE TABLE users (
  id BIGSERIAL PRIMARY KEY,
  email CITEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name TEXT,
  company_name TEXT,
  plan TEXT NOT NULL DEFAULT 'trial',
  trial_ends_at TIMESTAMPTZ,
  stripe_customer_id TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  is_verified BOOLEAN NOT NULL DEFAULT FALSE,
  is_superuser BOOLEAN NOT NULL DEFAULT FALSE,
  totp_secret TEXT,                          -- nullable until 2FA enabled
  totp_enabled_at TIMESTAMPTZ,
  failed_login_count INTEGER NOT NULL DEFAULT 0,
  locked_until TIMESTAMPTZ,
  last_login_at TIMESTAMPTZ,
  last_login_ip INET,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deletion_requested_at TIMESTAMPTZ          -- 30-day grace period
);

CREATE TABLE subscriptions (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  name TEXT NOT NULL,
  signal_types TEXT[] NOT NULL,
  criteria JSONB NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_subs_user_active ON subscriptions(user_id) WHERE active;

CREATE TABLE delivered_alerts (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  subscription_id BIGINT REFERENCES subscriptions(id) ON DELETE CASCADE NOT NULL,
  signal_type TEXT NOT NULL,
  signal_id BIGINT NOT NULL,
  delivered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  opened_at TIMESTAMPTZ,
  clicked_at TIMESTAMPTZ,
  resend_message_id TEXT,
  UNIQUE(user_id, signal_type, signal_id)
);

CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,                       -- 'login', 'login_failed', 'password_change', 'gdpr_export', 'gdpr_delete', 'plan_change', 'subscription_created', etc.
  ip INET,
  user_agent TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_user_created ON audit_log(user_id, created_at DESC);
CREATE INDEX idx_audit_action_created ON audit_log(action, created_at DESC);

CREATE TABLE stripe_webhook_events (
  id TEXT PRIMARY KEY,                        -- Stripe event id, idempotency key
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  processed_at TIMESTAMPTZ,
  error TEXT,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE password_reset_tokens (
  token_hash TEXT PRIMARY KEY,
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ
);

CREATE TABLE email_verification_tokens (
  token_hash TEXT PRIMARY KEY,
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ
);
```

### Criteria JSONB shape

```json
{
  "occupations": ["Lagerarbetare", "Truckförare", "Chaufför C/CE"],
  "occupation_concept_ids": ["pBR2_VG3_NDr"],
  "municipalities": ["Stockholm", "Södertälje", "Botkyrka", "Huddinge"],
  "counties": ["Stockholms län"],
  "sni_codes": ["49410", "52100"],
  "keywords_any": ["bemanning", "interim", "konsult"],
  "keywords_none": ["heltid", "tillsvidare"],
  "min_postings_per_employer": 3,
  "exclude_employer_orgnrs": ["5560000000"],
  "cpv_codes": ["79600000", "79610000"],
  "min_procurement_value_sek": 500000
}
```

---

## 9. Data sources

### 9.1 JobTech Dev (Arbetsförmedlingen)

- **Search API base:** `https://jobsearch.api.jobtechdev.se`
- **Taxonomy API base:** `https://taxonomy.api.jobtechdev.se`
- **Auth:** none for public endpoints
- **Endpoints used:** `GET /search?published-after={iso}&limit=100&offset={n}`, `GET /ad/{id}`
- **Polling:** daily at 06:00 Europe/Stockholm
- **Window:** fetch postings published in last 26 hours (overlap to avoid gaps)
- **Dedupe:** on `external_id` (= JobTech `id`)
- **Rate limit:** stay under 5 req/sec
- **Mapping:** `employer.organization_number` → `companies.orgnr`. If null, store `employer_name` only and leave `company_id` null.
- **Backoff:** exponential on 5xx, max 5 retries, fail loud to Sentry

### 9.2 Bolagsverket

- Implement adapter in `src/vittring/ingest/bolagsverket.py` with a clean interface so the data-source backend can be swapped.
- **Primary backend:** Bolagsverket's official open-data endpoints (verify current availability at implementation time).
- **Fallback backend:** scrape Post- och Inrikes Tidningar (PoIT) kungörelser daily.
- **Polling:** daily at 07:00 Europe/Stockholm.
- **Tracked change types:** `ceo`, `board_member`, `address`, `name`, `remark`, `liquidation`, `sni`.
- **Personal data lifecycle:** names of board members and CEOs are personal data. Retain for max 30 days unless surfaced in a `delivered_alerts` row, in which case retention is `delivered_at + 30 days`. A nightly job (`scrub_personal_data`) sets `personal_data_purged_at` and nulls `old_value`/`new_value` for expired rows.

### 9.3 TED (Tenders Electronic Daily)

- **Base URL:** `https://api.ted.europa.eu/v3/notices/search`
- **Auth:** none
- **Filters:** `country=SE` and any of these CPV codes:
  - `79600000` — Recruitment services
  - `79610000` — Provision of personnel
  - `79620000` — Supply services of personnel including temporary staff
  - `79621000`, `79624000`, `79625000` — variants
  - `85000000` series — health and social work services
- **Polling:** daily at 08:00 Europe/Stockholm
- **Source value:** `'ted'`

### 9.4 Adapter interface

```python
# src/vittring/ingest/base.py
from abc import ABC, abstractmethod
from datetime import datetime
from collections.abc import AsyncIterator

class IngestAdapter[T](ABC):
    name: str  # 'jobtech', 'bolagsverket', 'ted'

    @abstractmethod
    async def fetch_since(self, since: datetime) -> AsyncIterator[T]: ...

    @abstractmethod
    async def persist(self, items: list[T]) -> int:
        """Returns number of NEW rows inserted (after dedupe)."""
```

All ingest jobs MUST report metrics to Sentry: rows fetched, rows new, errors, duration. If an ingest fails, the error is logged and re-raised — APScheduler retries on next interval.

---

## 10. Matching engine

- **Pure function:** `match(signal, criteria) -> bool`. No side effects, no database access inside the matcher itself.
- **Test coverage:** 100 % required for `src/vittring/matching/`. CI fails below 100 %.
- **Performance target:** match 5 000 new signals against all active subscriptions in under 30 seconds on the CX23.
- **Idempotency:** the `UNIQUE(user_id, signal_type, signal_id)` constraint on `delivered_alerts` is the source of truth. Insertion conflicts are silently ignored (`ON CONFLICT DO NOTHING`).
- **Ordering:** for each user, signals are grouped by subscription, then sorted by `published_at` / `changed_at` / `deadline` descending.

### Matching rules per signal type

| Signal | Matched against criteria fields |
|---|---|
| Job posting | `occupations`, `occupation_concept_ids`, `municipalities`, `counties`, `keywords_any`, `keywords_none`, `min_postings_per_employer`, `exclude_employer_orgnrs` |
| Company change | `sni_codes`, `municipalities`, `counties`, `change_types` |
| Procurement | `cpv_codes`, `municipalities` (via buyer), `min_procurement_value_sek`, `keywords_any`, `keywords_none` |

`keywords_any` matches if **any** keyword is in `headline + description` (case-insensitive). `keywords_none` excludes if **any** is present.

---

## 11. Email digest

- **Schedule:** daily at 06:30 Europe/Stockholm.
- **Volume:** one email per user per day, regardless of how many subscriptions match.
- **Subject format:** `Vittring — {N} nya signaler ({weekday} {date})`.
- **Both HTML and plain text** versions sent (multipart/alternative).
- **Layout:** sections grouped by subscription name. Within each section, signals grouped by type (jobs, changes, procurements).
- **Per item:** signal type marker, employer/buyer name (bold), headline, location, source link, date.
- **Footer:** link to manage subscriptions, unsubscribe link per subscription, unsubscribe-all link, physical address (required by anti-spam law).
- **From:** `Vittring <info@karimkhalil.se>`. Reply-to: `info@karimkhalil.se`.
- **Tracking:** open + click tracking via Resend webhooks. Persist to `delivered_alerts.opened_at` / `clicked_at`.
- **Bounce/complaint handling:** Resend webhooks update user status. Three hard bounces in 30 days → user marked `is_active=false`, account holder notified via in-app banner on next login.

---

## 12. Code conventions

- **Type hints everywhere.** Python 3.12 PEP 695 generic syntax (`class Foo[T]:`).
- **Pydantic v2** for all schemas. No raw dicts crossing module boundaries.
- **SQLAlchemy 2.0 mapped style** with `Mapped[...]` and `mapped_column(...)`.
- **Async everywhere.** SQLAlchemy async sessions, httpx async client, FastAPI async endpoints.
- **structlog only.** No `print()`. Bind context (user_id, signal_type, request_id) early.
- **Configuration:** pydantic-settings, secrets in `/etc/vittring/.env` (mode 600, owner vittring), never committed. `.env.example` lists all required vars.
- **Migrations:** every schema change has an Alembic migration with both `upgrade` and `downgrade`. No manual DDL in production.
- **Tests:** pytest with `asyncio_mode = "auto"`. DB fixtures use transactional rollback per test. Use factory-boy for test data.
- **Lint and format:** Ruff for both. Enforced via pre-commit and CI.
- **Type check:** mypy strict mode. Enforced in CI.
- **Imports:** absolute only (`from vittring.models.company import Company`).
- **Errors:** custom exception hierarchy in `src/vittring/utils/errors.py`. Never raise plain `Exception`.
- **Dependency management:** `uv` (not pip directly). `uv.lock` committed.
- **Pre-commit hooks:** ruff format, ruff check, mypy, detect-secrets.

---

## 13. Security

### Application
- bcrypt password hashing (cost factor 12).
- Password requirements: min 12 chars, not in haveibeenpwned top-1M (use `pwnedpasswords` library).
- JWT access tokens, 15-minute lifetime. Refresh tokens, 30-day lifetime, rotation on use, revocation on logout.
- HTTPS only, enforced by Caddy with HSTS preload.
- Cookies: `HttpOnly`, `Secure`, `SameSite=Lax`.
- CSRF protection on all state-changing form submissions (synchronizer token pattern).
- Content Security Policy: `default-src 'self'; script-src 'self' https://js.stripe.com; frame-src https://js.stripe.com https://hooks.stripe.com; img-src 'self' data:`.
- All SQL via SQLAlchemy parameterized queries — no raw f-string SQL.
- Stripe webhooks verified via signing secret.
- Resend webhooks verified via signing secret.
- 2FA (TOTP) optional for users, mandatory for `is_superuser` accounts.
- Account lockout: 5 failed logins → 15-minute lock. Notify user via email.
- Rate limiting:
  - `/auth/login`: 10 req/min per IP, 5 req/min per email
  - `/auth/signup`: 5 req/hour per IP
  - `/auth/password-reset`: 3 req/hour per email
  - All other endpoints: 100 req/min per IP

### Server
- UFW: deny incoming by default, allow 22/tcp, 80/tcp, 443/tcp only.
- fail2ban: SSH jail with 3 attempts → 1-hour ban.
- SSH: root login disabled, password auth disabled, only ed25519 keys, only `vittring` user.
- Automatic security updates via `unattended-upgrades`, configured to reboot if needed at 04:00.
- systemd units use sandboxing: `PrivateTmp=true`, `ProtectHome=true`, `ProtectSystem=strict`, `NoNewPrivileges=true`, `ReadWritePaths=/opt/vittring/var /var/log/vittring`.
- Postgres listens only on localhost.
- Caddy config restricts headers, enables HSTS preload, sets security headers (X-Frame-Options, X-Content-Type-Options, Referrer-Policy).

### Secrets
- All secrets in `/etc/vittring/.env`, mode 600, owner `vittring:vittring`.
- No secrets in repository, in CI logs, or in error messages.
- detect-secrets pre-commit hook scans every commit.

---

## 14. GDPR

- Personal data inventory in `docs/gdpr.md`. Updated whenever schema changes.
- Data residency: Hetzner Falkenstein (EU/Germany).
- Subprocessors: Resend (EU region), Stripe (Ireland), Sentry (EU region), Hetzner. Karim files DPAs with each.
- User rights:
  - Access: `/account/export` returns JSON of all data tied to user.
  - Rectification: profile editing endpoints.
  - Erasure: `/account/delete` schedules deletion. 30-day grace period (`deletion_requested_at` set), then hard delete via nightly job.
  - Portability: same as access, format is JSON.
  - Objection: granular subscription management.
- Bolagsverket personal data (officer names): nightly job purges entries older than 30 days that have not been surfaced in a delivered alert.
- Audit log retention: 24 months (legal requirement for accounting).
- Cookie banner: consent for non-essential cookies (analytics). Strictly necessary cookies (session, CSRF) do not require consent.
- Privacy policy and DPA template in `legal/`.

---

## 15. Environment variables (.env.example)

```
# App
APP_ENV=production
APP_SECRET_KEY=                       # 64-char random, generated on bootstrap
APP_BASE_URL=https://vittring.karimkhalil.se
TZ=Europe/Stockholm

# Database
DATABASE_URL=postgresql+asyncpg://vittring:CHANGEME@localhost:5432/vittring

# Email (Resend)
RESEND_API_KEY=re_xxx
RESEND_WEBHOOK_SECRET=
EMAIL_FROM_ADDRESS=info@karimkhalil.se
EMAIL_FROM_NAME=Vittring
EMAIL_REPLY_TO=info@karimkhalil.se
EMAIL_SENDING_DOMAIN=karimkhalil.se

# Stripe
STRIPE_SECRET_KEY=sk_live_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
STRIPE_PRICE_SOLO_MONTHLY=price_xxx
STRIPE_PRICE_TEAM_MONTHLY=price_xxx
STRIPE_PRICE_PRO_MONTHLY=price_xxx
STRIPE_PRICE_SOLO_ANNUAL=price_xxx
STRIPE_PRICE_TEAM_ANNUAL=price_xxx
STRIPE_PRICE_PRO_ANNUAL=price_xxx

# Sentry
SENTRY_DSN=
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1

# Data sources
JOBTECH_BASE_URL=https://jobsearch.api.jobtechdev.se
JOBTECH_TAXONOMY_URL=https://taxonomy.api.jobtechdev.se
TED_BASE_URL=https://api.ted.europa.eu/v3
BOLAGSVERKET_BACKEND=poit

# Backups
BACKUP_TARGET=local                   # 'local' or 'storagebox'
BACKUP_LOCAL_PATH=/var/backups/vittring
BACKUP_ENCRYPTION_PASSPHRASE=

# Hetzner Storage Box (only if BACKUP_TARGET=storagebox)
BACKUP_HOST=
BACKUP_USER=
BACKUP_SSH_KEY_PATH=/etc/vittring/backup_id_ed25519
BACKUP_REMOTE_PATH=/backups/vittring
```

---

## 16. Server bootstrap

This describes what `scripts/server_bootstrap.sh` does. The script is idempotent — running it twice is safe. Claude Code executes it via SSH on first deploy.

```
# Phase 1: System hardening
- Set hostname to 'vittring-prod-01'
- Set timezone to Europe/Stockholm
- apt update && apt upgrade -y
- Install: postgresql-16, caddy, python3.12, python3.12-venv, python3-pip,
  git, ufw, fail2ban, unattended-upgrades, logrotate, chrony,
  rsync, gnupg, build-essential, libpq-dev
- Install uv (modern Python package manager)
- Configure unattended-upgrades for security updates only, with auto-reboot at 04:00
- Configure UFW: default deny incoming, allow 22/tcp, 80/tcp, 443/tcp, enable
- Configure fail2ban with sshd jail
- Create user 'vittring' with sudo group, copy authorized_keys from root
- Test SSH login as vittring works
- Disable root SSH login (PermitRootLogin no)
- Disable password authentication (PasswordAuthentication no)
- Restart sshd

# Phase 2: PostgreSQL
- Configure postgresql.conf: listen_addresses='localhost', shared_buffers=1GB,
  effective_cache_size=2GB, max_connections=100
- Configure pg_hba.conf: local connections via md5
- Create user 'vittring' with random password (saved to /etc/vittring/.env)
- Create database 'vittring' owned by vittring
- Install citext extension

# Phase 3: Application directory
- mkdir -p /opt/vittring /var/log/vittring /etc/vittring
- chown vittring:vittring /opt/vittring /var/log/vittring
- chown root:vittring /etc/vittring && chmod 750 /etc/vittring
- Touch /etc/vittring/.env, chmod 640, chown root:vittring

# Phase 4: Caddy
- Write /etc/caddy/Caddyfile from deploy/Caddyfile, with vittring.karimkhalil.se as host
- systemctl enable --now caddy
- Verify Caddy obtains TLS cert (requires DNS to be configured)

# Phase 5: systemd
- Install /etc/systemd/system/vittring-api.service from deploy/systemd/
- Install /etc/systemd/system/vittring-scheduler.service from deploy/systemd/
- systemctl daemon-reload
- DO NOT start yet — application code must be deployed first

# Phase 6: Logrotate
- Install /etc/logrotate.d/vittring from deploy/logrotate/

# Phase 7: Backup SSH key
- Generate ed25519 key in /etc/vittring/backup_id_ed25519 if not exists
- Print public key for Karim to add to Hetzner Storage Box
- Halt and instruct Karim to enable Storage Box and add key

# Phase 8: Cron for backups
- Install /etc/cron.d/vittring-backup running scripts/backup.sh nightly at 02:00
```

The script must check each step's success before proceeding, log to stdout in a clear format, and exit non-zero on any failure.

---

## 17. Deploy workflow

`scripts/deploy.sh` runs as the `vittring` user on the server. Triggered manually via SSH or via GitHub Actions on tag push.

```
1. cd /opt/vittring
2. git fetch --tags
3. git checkout <tag>           # or 'main' for non-tagged deploys
4. uv sync --frozen             # install deps from uv.lock
5. uv run alembic upgrade head  # run migrations BEFORE restarting app
6. systemctl --user reload vittring-api          # graceful reload (FastAPI handles SIGHUP)
7. systemctl --user restart vittring-scheduler   # scheduler is fine to hard-restart
8. curl -fsS http://localhost:8000/health | grep -q '"status":"ok"' || exit 1
9. Log deploy to audit_log table
```

GitHub Actions deploys on tag push:

```yaml
# .github/workflows/deploy.yml
on:
  push:
    tags: ['v*']
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: 62.238.37.54
          username: vittring
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            cd /opt/vittring
            ./scripts/deploy.sh ${{ github.ref_name }}
```

Karim adds `DEPLOY_SSH_KEY` to GitHub Secrets (private key paired with a public key in `vittring`'s authorized_keys).

---

## 18. Backups

### Database
> **Storage Box status: deferred.** Until a Storage Box is provisioned, nightly `pg_dump` writes encrypted dumps to `/var/backups/vittring/` on the same server with the same retention policy. The `backup.sh` script supports both targets via `BACKUP_TARGET=local|storagebox`. Switching to Storage Box later is a config change.

- Nightly `pg_dump` at 02:00 Europe/Stockholm via cron.
- Output: `vittring-YYYY-MM-DD.sql.gz`, encrypted with `gpg --symmetric` using `BACKUP_ENCRYPTION_PASSPHRASE`.
- Pushed to Hetzner Storage Box via rsync over SSH (when enabled). Otherwise written to `/var/backups/vittring/`.
- Retention: 30 daily, 12 weekly (Sundays), 12 monthly (1st of month).
- Old backups pruned by retention policy.

### Server
- Hetzner snapshots: enabled, daily, 7 retained.
- Test restore quarterly (documented in `docs/runbook.md`).

### Restore
- `scripts/restore.sh <backup-file>` — pulls from Storage Box, decrypts, drops and recreates database, restores.

---

## 19. Monitoring and observability

### Errors — Sentry
- All Python exceptions captured.
- Performance traces at 10 % sample rate.
- User context (user_id, plan) bound to traces.
- Alerts: any error in production → email Karim.

### Uptime — UptimeRobot
- HTTPS check on `https://vittring.karimkhalil.se/health` every 5 minutes.
- Alert: SMS + email on downtime > 2 minutes.

### Logs
- structlog → stdout → systemd-journald.
- Query via `journalctl -u vittring-api -f`.
- Retention: 30 days local, then rotated.

### Metrics (lightweight)
- Each ingest job logs: rows fetched, rows new, errors, duration.
- Each digest job logs: users processed, emails sent, errors.
- Daily summary email at 09:00 to Karim with previous day's metrics.

### Health endpoints
- `GET /health` — returns 200 if app is up. Used by Caddy and UptimeRobot.
- `GET /ready` — returns 200 only if DB connection works and last successful ingest was within 25 hours. Used by deploy verification.

---

## 20. Prerequisites Karim must complete

Claude Code must verify these before starting work and halt with clear instructions if any are missing:

1. **DNS A-record:** `vittring.karimkhalil.se` → `62.238.37.54`. Verify via `dig +short vittring.karimkhalil.se`.
2. **SSH access:** Claude Code can SSH to `root@62.238.37.54` using Karim's local SSH key.
3. **Resend account:** API key in `/etc/vittring/.env` as `RESEND_API_KEY`.
4. **Sentry project:** DSN in `/etc/vittring/.env` (EU region).
5. **GitHub repository:** `D3v0ps/vittring` created. Deploy SSH key (private) added as `DEPLOY_SSH_KEY` secret; matching public key installed on server during bootstrap.
6. **Email DNS records:** Claude Code generates the list via Resend API on first run, prints them, halts. Karim adds them to one.com DNS, then re-runs.

**Deferred (not blocking initial deploy):**

- **Stripe account:** required only when billing is enabled. Schema and code paths are in place; needs `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and price IDs to activate.
- **Hetzner Storage Box:** required only for off-server backups. Until then, backups are written locally to `/var/backups/vittring/`.

---

## 21. Deliverables

The full system consists of these components.

### Application
1. Repo skeleton: `pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example`, `README.md`, `.pre-commit-config.yaml`, directory structure
2. `config.py` (pydantic-settings) and `logging.py` (structlog)
3. `db.py` with async engine, session factory, connection pool sized for CX23
4. SQLAlchemy models for every table in section 8
5. Alembic baseline migration covering all tables, with both upgrade and downgrade
6. `IngestAdapter` base class
7. JobTech adapter with retries, backoff, Sentry metrics
8. Bolagsverket adapter with `official` and `poit` backends behind same interface
9. TED adapter
10. Matching engine with 100 % test coverage
11. Email module with Jinja2 templates: digest, welcome, verify, password-reset
12. Resend domain verification flow (`delivery/domain_setup.py`)
13. APScheduler with all jobs: 3 ingests, digest, GDPR scrubbing, daily metrics email
14. FastAPI app with all routers
15. Auth: signup, login, email verification, password reset, 2FA via TOTP, account lockout
16. Subscription CRUD endpoints
17. Stripe Checkout + Customer Portal + idempotent webhook handler
18. GDPR endpoints: export, delete (with grace period)
19. Public landing page at `/` (HTML + HTMX, Swedish copy)
20. Account dashboard at `/app`
21. Legal pages: privacy, terms, DPA template, cookie policy (skeleton content in Swedish — Karim refines)
22. Audit log writer used by all sensitive actions
23. CSRF middleware
24. Rate-limiter middleware
25. Security headers middleware

### Tests
26. `test_matching.py` — 100 % coverage required
27. Adapter tests with VCR.py cassettes for HTTP fixtures
28. Auth flow tests (signup → verify → login → 2FA → reset)
29. Stripe webhook tests with fixture events
30. GDPR export/delete tests
31. End-to-end test: signup → create subscription → ingest → match → email sent (via Resend test mode)

### Infrastructure
32. `scripts/server_bootstrap.sh` — idempotent
33. `scripts/deploy.sh` — zero-downtime
34. `scripts/backup.sh` — encrypted, rotated
35. `scripts/restore.sh`
36. `scripts/verify_dns.py`
37. `deploy/Caddyfile` with security headers, HSTS preload
38. systemd unit files with sandboxing
39. `deploy/logrotate/vittring`
40. `deploy/unattended-upgrades/50unattended-upgrades`

### CI/CD
41. `.github/workflows/ci.yml` — ruff, mypy, pytest with coverage gate
42. `.github/workflows/deploy.yml` — deploy on tag push
43. Branch protection rules documented in `docs/deployment.md`

### Documentation
44. `docs/deployment.md` — how to deploy, rollback, debug
45. `docs/data-sources.md` — API contracts, mappings, taxonomy
46. `docs/gdpr.md` — personal data inventory, retention rules, subprocessor list
47. `docs/runbook.md` — incident response (down, slow, DB full, email failing, etc.)
48. `docs/architecture.md` — request flow, ingest flow, alert flow, deploy flow

---

## 22. Design system

All visual design follows the strict specification in `design-system.md`. No exceptions without explicit approval.

---

## 23. Definition of done

A feature is done when:

- Code is written with type hints, structlog logging, and Pydantic validation
- Tests cover happy path + at least 2 edge cases (100 % for matching engine)
- mypy strict passes
- ruff passes
- Migration written if schema changed
- Documentation updated if user-facing behavior changed
- Deployed to production via tag
- Health check passes post-deploy
- No new Sentry errors for 24 hours after deploy
