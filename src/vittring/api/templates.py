"""Shared Jinja2 environment for HTML page templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context, select_autoescape
from markupsafe import Markup

TEMPLATE_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# FastAPI's bundled Jinja2Templates wrapper does not expose ``autoescape``
# as a constructor argument across versions, so we set it on the underlying
# environment after construction. Default ``select_autoescape`` only escapes
# ``.html``/``.htm``/``.xml``; we use ``.html.j2`` so we add ``.j2`` and force
# escaping for string templates as well, closing the broad XSS surface.
templates.env.autoescape = select_autoescape(
    enabled_extensions=("html", "htm", "xml", "j2"),
    default_for_string=True,
)


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
