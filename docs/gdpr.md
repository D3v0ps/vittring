# GDPR

Personal-data inventory, retention rules, and data-subject rights for Vittring.
Reviewed against GDPR articles 5, 13, 15-17, 20, and 30 (records of processing).

## Data residency

All primary processing happens at Hetzner Online GmbH, Falkenstein, Germany (EU).
The application server, the Postgres database, and the daily snapshots all live
in `fsn1`. Encrypted nightly backups go to a Hetzner Storage Box in the same
region. No personal data leaves the EU.

## Subprocessors

| Subprocessor | Purpose | Location |
|---|---|---|
| Hetzner Online GmbH | Hosting (compute, storage, backups) | Germany (EU) |
| Resend | Transactional email delivery | EU region (Frankfurt) |
| Sentry | Error tracking | EU region (Frankfurt) |
| Stripe Payments Europe Ltd | Payments (activated when billing goes live) | Ireland (EU) |

A current list with DPA links is kept on the public legal page at
`/legal/subprocessors`. Customers are notified by email at least 30 days before
a new subprocessor goes live.

## Personal-data inventory

### `users`

| Field | Purpose | Retention |
|---|---|---|
| `email` | Login, alert delivery | While account active. Deleted 30 days after `deletion_requested_at`. |
| `full_name` | Email salutation, support | Same as email. |
| `company_name` | Billing, support | Same as email. |
| `password_hash` | Auth (argon2id) | Same as email. |
| `last_login_ip` | Security audit | Same as email. |
| `totp_secret` | 2FA | Same as email; cleared immediately on user-initiated 2FA disable. |

### `audit_log`

| Field | Purpose | Retention |
|---|---|---|
| `user_id` | Trace actor for security events | 24 months (Bokföringslagen / accounting law). |
| `ip` | Forensic trail | 24 months. |
| `user_agent` | Forensic trail | 24 months. |
| `metadata` (JSON) | Action-specific context | 24 months. |

The 24-month retention is tied to Sweden's accounting requirements for
auditable system events touching billing. Rows older than 24 months are deleted
nightly.

### `company_changes`

This table stores the JSON payload of each Bolagsverket change. The
`old_value` and `new_value` columns can contain officer names (natural persons).

| Field | Purpose | Retention |
|---|---|---|
| `old_value`, `new_value` (JSON) | Diff for matching and email rendering | 30 days from `ingested_at` by default. |
| Same, when surfaced in an alert | Same as above | `delivered_at + 30 days` (extended). |

The scrub job runs nightly: rows past their retention threshold have their
JSON columns replaced with `{"redacted": true}`. Aggregate fields (`change_type`,
`orgnr`, `effective_date`) stay; the row is preserved for audit.

### `delivered_alerts`

| Field | Purpose | Retention |
|---|---|---|
| `user_id` | Link delivery to recipient | Cascade-deleted with the user. |
| `signal_type`, `signal_id` | Idempotency and audit | Cascade-deleted with the user. |
| `delivered_at` | Drives the extended retention on `company_changes` | Cascade-deleted with the user. |

No raw PII is stored on `delivered_alerts`; it's a join table.

## User rights

| Right | How served |
|---|---|
| Access (Art. 15) | `GET /app/account/export` returns a JSON bundle of every row in `users`, `audit_log`, `delivered_alerts`, and active subscriptions for the requesting user. |
| Rectification (Art. 16) | Profile editing on `/app/account` updates `users` directly. |
| Erasure (Art. 17) | `POST /app/account/delete` sets `deletion_requested_at` and triggers a confirmation email. The 30-day grace allows accidental-deletion recovery; after that the record and all cascading data are hard-deleted. |
| Portability (Art. 20) | Same as access — the JSON export is machine-readable. |
| Restriction / objection | Handled manually via support; rare for this product. |

Requests via email (`info@karimkhalil.se`) are honoured within one calendar
month, in line with Art. 12(3).

## Cookies

Vittring sets only strictly necessary cookies in v0.1. No analytics,
no tracking, no third-party cookies.

| Cookie | Purpose | Flags |
|---|---|---|
| `vittring_session` | Authenticated session token | `HttpOnly`, `Secure`, `SameSite=Lax` |
| `vittring_csrf` | CSRF double-submit token | `Secure`, `SameSite=Strict` |

Because both cookies are strictly necessary for the service to function, no
consent banner is required under ePrivacy. The cookie list is published at
`/legal/cookies`.

## Logging and Sentry

Application logs (structlog → journald) and Sentry events are stripped of email
addresses and IPs by a Sentry `before_send` hook. The hook walks the event
payload and replaces matches of common PII patterns (email, IPv4, IPv6) with
`[redacted]`. User IDs are kept, since they're opaque integers.
