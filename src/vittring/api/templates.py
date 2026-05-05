"""Shared Jinja2 environment for HTML page templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup

TEMPLATE_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@pass_context
def csrf_input(context: dict[str, Any]) -> Markup:
    """Render the hidden CSRF input. Use as ``{{ csrf_input() }}`` in forms."""
    request = context.get("request")
    token = getattr(request.state, "csrf_token", "") if request is not None else ""
    return Markup(
        f'<input type="hidden" name="csrf_token" value="{token}" />'
    )


@pass_context
def csrf_token(context: dict[str, Any]) -> str:
    """Return the raw CSRF token. Use when scripting fetch() calls in JS."""
    request = context.get("request")
    if request is None:
        return ""
    return getattr(request.state, "csrf_token", "")


templates.env.globals["csrf_input"] = csrf_input
templates.env.globals["csrf_token"] = csrf_token
