# Vittring

Bevakning av tre öppna datasignaler — nya jobbannonser (JobTech), bolagsändringar (Bolagsverket) och offentliga upphandlingar (TED) — för säljteam på svenska bemanningsföretag.

> "Vet vilket företag som behöver personal innan dina konkurrenter kontaktar dem."

## Documentation

- `CLAUDE.md` — single source of truth: architecture, schema, deploy, security, GDPR.
- `docs/deployment.md` — how to deploy and roll back.
- `docs/data-sources.md` — API contracts and field mappings.
- `docs/gdpr.md` — personal data inventory and retention rules.
- `docs/runbook.md` — incident response.
- `docs/architecture.md` — request, ingest, alert, and deploy flows.

## Local development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pre-commit install
cp .env.example .env       # fill in local values
uv run alembic upgrade head
uv run uvicorn vittring.main:app --reload
```

Run tests, lint, and type-checks:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

## License

Proprietary. All rights reserved.
