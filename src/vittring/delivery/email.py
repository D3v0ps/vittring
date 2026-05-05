"""Resend email client wrapper.

Renders Jinja2 templates against the shared environment, sends via Resend's
HTTP API, and returns the message id for persistence on ``delivered_alerts``
or ``audit_log`` rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from vittring.config import get_settings
from vittring.utils.errors import EmailError

logger = structlog.get_logger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(("html", "xml", "html.j2", "xml.j2")),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_name: str, **context: Any) -> str:
    template = _env.get_template(template_name)
    return template.render(**context)


@dataclass(frozen=True, slots=True)
class SentEmail:
    message_id: str
    to: str
    subject: str


async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    headers: dict[str, str] | None = None,
    tags: dict[str, str] | None = None,
) -> SentEmail:
    """Send via Resend HTTP API.

    Retries up to 5 times on transient errors. Failures raise ``EmailError``
    which the caller logs and surfaces to Sentry as appropriate.
    """
    settings = get_settings()
    payload: dict[str, Any] = {
        "from": f"{settings.email_from_name} <{settings.email_from_address}>",
        "to": [to],
        "reply_to": settings.email_reply_to,
        "subject": subject,
        "html": html,
        "text": text,
    }
    if headers:
        payload["headers"] = headers
    if tags:
        payload["tags"] = [{"name": k, "value": v} for k, v in tags.items()]

    auth_headers = {
        "Authorization": f"Bearer {settings.resend_api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=1, max=15),
            reraise=True,
        ):
            with attempt:
                response = await client.post(
                    "https://api.resend.com/emails",
                    json=payload,
                    headers=auth_headers,
                )
                if response.status_code >= 500:
                    response.raise_for_status()
                if response.status_code >= 400:
                    raise EmailError(
                        f"Resend rejected email: {response.status_code} {response.text}"
                    )
                data = response.json()
                message_id = data.get("id")
                if not message_id:
                    raise EmailError(f"Resend response missing id: {data!r}")
                logger.info("email_sent", to=to, subject=subject, message_id=message_id)
                return SentEmail(message_id=message_id, to=to, subject=subject)

    raise EmailError("send_email exhausted retries")  # pragma: no cover
