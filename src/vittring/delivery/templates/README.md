# Email templates

Jinja2 templates rendered by `vittring.delivery.email.render` and sent via
Resend by `vittring.delivery.email.send_email`. All templates extend
`_base.html.j2` for the shared layout.

## Design constraints

These are emails, not web pages. Constraints:

- **Layout via tables.** No flexbox, no grid. Width is fixed at 600px max.
- **Inline styles.** A `<style>` block in `<head>` is included for
  responsive/preheader concerns, but every visual property is duplicated
  inline because some clients strip `<style>`.
- **System font stack.** `-apple-system, BlinkMacSystemFont, 'Segoe UI',
  Roboto, sans-serif` for body, monospace stack for dates/codes. No web
  fonts — they fail unpredictably across clients.
- **Solid background colours only.** No `background-image` on the body —
  several clients strip it.
- **No JavaScript.** No external CSS files.
- **Light only.** `color-scheme: light` is asserted; the design assumes a
  light surface.

## Tested clients

We design and visually test against:

- **Gmail web** (Chromium, Firefox)
- **Apple Mail desktop** (macOS)
- **Outlook 2021** (Windows desktop, MSO rendering engine)

Quick sanity checks on Outlook.com web and iOS Mail are appreciated but
not blocking.

## Templates and data shapes

### `_base.html.j2`

Shared layout. Defines blocks:

- `preheader` — hidden inbox preview line.
- `header_meta` — short string shown right-aligned in the header band
  (mono, small caps). Use for date or email category.
- `content` — the main card body.
- `footer_extra` — the line above the legal address.

Common context variables consumed by the base layout:

| key               | type | required | source                                             |
| ----------------- | ---- | -------- | -------------------------------------------------- |
| `subject`         | str  | yes      | also used as the default preheader                 |
| `from_address`    | str  | no       | shown in the footer next to the legal address      |
| `contact_address` | str  | no       | physical address for the legal footer line         |

### `digest.html.j2` and `digest.txt.j2`

Daily signal digest. Multipart/alternative — both renderers receive the
same context built by `vittring.jobs.digest.run_daily_digest`.

| key                | type            | description                                                              |
| ------------------ | --------------- | ------------------------------------------------------------------------ |
| `subject`          | str             | also used as preheader fallback                                          |
| `from_address`     | str             | shown in footer                                                          |
| `total`            | int             | total signal count across all sections, used in the headline             |
| `digest_date`      | str             | localized Swedish date (e.g. `tisdag 5 maj`), shown in header band       |
| `sections`         | list[Section]   | one per matching subscription that has at least one item                 |
| `manage_url`       | str             | absolute URL to the subscriptions page                                   |
| `unsubscribe_url`  | str             | absolute URL with one-click unsubscribe token                            |
| `contact_address`  | str             | physical legal address for the footer                                    |

`Section`:

| key                 | type          |
| ------------------- | ------------- |
| `subscription_name` | str           |
| `items`             | list[Item]    |

`Item`:

| key          | type        | description                                                               |
| ------------ | ----------- | ------------------------------------------------------------------------- |
| `kind_label` | str         | `Jobb`, `Upphandling`, `Ny VD`, `Styrelseändring`, `Bolagsändring`, etc.  |
| `title`      | str         | bold one-line headline                                                    |
| `detail`     | str \| None | optional muted second line                                                |
| `source_url` | str \| None | optional link rendered as `Läs mer`                                       |
| `date_label` | str         | mono date stamp (`05 maj 09:30`)                                          |

The badge colour for each item is decided in the template by mapping
`kind_label` to a muted background colour:

- `Jobb` -> `#E8EFFA` (accent)
- `Upphandling` -> `#F8F1DD` (highlight)
- `Ny VD` / `Styrelseändring` / `Bolagsändring` -> `#DCFCE7` (success)
- otherwise -> `#F5F5F4` (neutral)

### `welcome.html.j2`

Sent after signup.

| key             | type        |
| --------------- | ----------- |
| `subject`       | str         |
| `from_address`  | str         |
| `full_name`     | str \| None |
| `dashboard_url` | str         |

### `verify.html.j2`

Email verification link.

| key            | type |
| -------------- | ---- |
| `subject`      | str  |
| `from_address` | str  |
| `email`        | str  |
| `verify_url`   | str  |

### `reset_password.html.j2`

Password reset link.

| key            | type |
| -------------- | ---- |
| `subject`      | str  |
| `from_address` | str  |
| `email`        | str  |
| `reset_url`    | str  |

## Previewing a render locally

The `render()` helper just pulls the template through Jinja2 — you can
invoke it with any context dictionary:

```bash
python -c "from vittring.delivery.email import render; print(render('digest.html.j2', subject='Vittring', total=12, digest_date='tisdag 5 maj', sections=[{'subscription_name':'Lagerarbetare Storstockholm','items':[{'kind_label':'Jobb','title':'Bring söker — Lagermedarbetare','detail':'Stockholm · Heltid','source_url':'https://example.com/1','date_label':'05 maj 09:30'}]}], manage_url='https://vittring.se/app/subscriptions', unsubscribe_url='https://vittring.se/unsubscribe?t=abc', from_address='hej@vittring.se', contact_address='Vittring c/o Karim Khalil, Sverige'))"
```

Pipe the output to a file and open it in a browser, or paste it into the
Resend "Send test" preview UI for a closer-to-real rendering. For
plain-text:

```bash
python -c "from vittring.delivery.email import render; print(render('digest.txt.j2', total=12, digest_date='tisdag 5 maj', sections=[], manage_url='...', unsubscribe_url='...', contact_address='Vittring c/o Karim Khalil, Sverige'))"
```

For pixel-accurate compatibility checks, send a test through Resend and
forward to a Litmus or Email on Acid trial.
