"""Shared Jinja2 environment for HTML page templates."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
