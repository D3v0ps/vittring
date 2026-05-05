"""Resend domain verification flow.

On first deploy this module:

1. Calls Resend's domain endpoint to ensure ``EMAIL_SENDING_DOMAIN`` is
   registered.
2. Reads back the required DNS records (MX/CNAME/TXT for return-path, DKIM,
   SPF, DMARC).
3. Either prints them to stdout for the operator to add at one.com, or polls
   verification status until ``verified``.

The script is idempotent — re-running after Karim adds the records simply
flips the status to verified and exits.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx
import structlog

from vittring.config import get_settings
from vittring.utils.errors import DomainNotVerifiedError

logger = structlog.get_logger(__name__)

RESEND_BASE = "https://api.resend.com"


class DomainStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    NOT_STARTED = "not_started"


@dataclass(frozen=True, slots=True)
class DnsRecord:
    name: str
    type: str
    value: str
    ttl: int = 3600


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_settings().resend_api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }


async def _list_domains(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    resp = await client.get(f"{RESEND_BASE}/domains", headers=_auth_headers())
    resp.raise_for_status()
    return resp.json().get("data", [])  # type: ignore[no-any-return]


async def _create_domain(client: httpx.AsyncClient, name: str) -> dict[str, Any]:
    resp = await client.post(
        f"{RESEND_BASE}/domains",
        headers=_auth_headers(),
        json={"name": name, "region": "eu-west-1"},
    )
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


async def _get_domain(client: httpx.AsyncClient, domain_id: str) -> dict[str, Any]:
    resp = await client.get(f"{RESEND_BASE}/domains/{domain_id}", headers=_auth_headers())
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


async def _verify_domain(client: httpx.AsyncClient, domain_id: str) -> None:
    resp = await client.post(
        f"{RESEND_BASE}/domains/{domain_id}/verify", headers=_auth_headers()
    )
    resp.raise_for_status()


def _to_records(payload: dict[str, Any]) -> list[DnsRecord]:
    return [
        DnsRecord(
            name=r["name"],
            type=r["type"],
            value=r["value"],
            ttl=r.get("ttl", 3600),
        )
        for r in payload.get("records", [])
    ]


def _print_records(domain: str, records: list[DnsRecord]) -> None:
    """Print DNS records in a copy-pasteable format for one.com."""
    print(f"\n=== DNS records to add at one.com for {domain} ===\n")
    print(f"{'TYPE':<8}{'NAME':<48}{'TTL':<8}VALUE")
    print("-" * 100)
    for r in records:
        print(f"{r.type:<8}{r.name:<48}{r.ttl:<8}{r.value}")
    print(
        "\nNOTE: If a TXT record on the apex (karimkhalil.se) already exists for SPF,\n"
        "MERGE the include: clauses — do not replace the existing record.\n"
    )


async def ensure_domain_verified(*, wait: bool = False, max_wait_seconds: int = 600) -> DomainStatus:
    """Make sure the configured sending domain is registered and verified.

    If ``wait`` is True, polls Resend until verification succeeds or the
    timeout elapses. Otherwise returns immediately with the current status.
    """
    settings = get_settings()
    domain = settings.email_sending_domain

    async with httpx.AsyncClient(timeout=30.0) as client:
        domains = await _list_domains(client)
        match = next((d for d in domains if d.get("name") == domain), None)
        if match is None:
            created = await _create_domain(client, domain)
            domain_id = created["id"]
            records = _to_records(created)
            _print_records(domain, records)
            logger.info("resend_domain_created", domain=domain, id=domain_id)
        else:
            domain_id = match["id"]

        # Trigger a verification attempt and read back current status.
        await _verify_domain(client, domain_id)
        info = await _get_domain(client, domain_id)
        status = DomainStatus(info.get("status", DomainStatus.PENDING).lower())

        if status is DomainStatus.VERIFIED:
            logger.info("resend_domain_verified", domain=domain)
            return status

        records = _to_records(info)
        _print_records(domain, records)

        if not wait:
            raise DomainNotVerifiedError(
                f"Resend domain {domain} not verified yet (status={status}). "
                "Add the printed DNS records at one.com and re-run."
            )

        deadline = asyncio.get_event_loop().time() + max_wait_seconds
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(15)
            info = await _get_domain(client, domain_id)
            status = DomainStatus(info.get("status", DomainStatus.PENDING).lower())
            logger.info("resend_domain_poll", domain=domain, status=status)
            if status is DomainStatus.VERIFIED:
                return status

        raise DomainNotVerifiedError(
            f"Domain {domain} did not verify within {max_wait_seconds}s"
        )
