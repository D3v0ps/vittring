"""e-Avrop scraper.

Discovery + parse for ``https://www.e-avrop.com``. The actual HTML structure
of e-Avrop's listing and detail pages will probably need iteration once we
see real fixtures — this implementation uses a defensive set of selectors
and falls through gracefully when fields are missing rather than crashing
the whole ingest run.

Compliance plumbing (robots.txt, rate limit, blocklist, audit log) lives in
:class:`BaseScraper`. We just call :meth:`BaseScraper.fetch` for every URL
and let the base class enforce policy.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import structlog
from selectolax.parser import HTMLParser, Node

from vittring.ingest._persist import insert_ignore
from vittring.ingest.scrapers.base import BaseScraper
from vittring.models.signals import Procurement
from vittring.schemas.ingest import ProcurementItem

logger = structlog.get_logger(__name__)


CPV_RE = re.compile(r"\b(\d{8})\b")
ORGNR_RE = re.compile(r"\b(\d{6}-\d{4}|\d{10})\b")
VALUE_SEK_RE = re.compile(
    r"(\d[\d\s ]{2,})\s*(?:kr|sek|kronor|tkr|mkr|miljoner)",
    re.IGNORECASE,
)


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    return node.text(strip=True)


def _first_text(tree: HTMLParser | Node, selectors: list[str]) -> str:
    for sel in selectors:
        node = tree.css_first(sel)
        if node is not None:
            text = _text(node)
            if text:
                return text
    return ""


def _parse_swedish_date(text: str) -> datetime | None:
    """Parse common Swedish date formats: ``YYYY-MM-DD`` or ``DD MMM YYYY``."""
    text = text.strip()
    if not text:
        return None
    # ISO ``2026-06-12`` or ``2026-06-12 14:00``.
    iso = re.match(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?", text)
    if iso:
        date_part = iso.group(1)
        time_part = iso.group(2) or "00:00"
        try:
            return datetime.fromisoformat(f"{date_part}T{time_part}").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None
    months = {
        "jan": 1, "januari": 1, "feb": 2, "februari": 2, "mar": 3, "mars": 3,
        "apr": 4, "april": 4, "maj": 5, "jun": 6, "juni": 6,
        "jul": 7, "juli": 7, "aug": 8, "augusti": 8, "sep": 9, "september": 9,
        "okt": 10, "oktober": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    }
    swedish = re.match(r"(\d{1,2})\s+([A-Za-zåäöÅÄÖ]+)\s+(\d{4})", text)
    if swedish:
        day = int(swedish.group(1))
        month_name = swedish.group(2).lower()
        year = int(swedish.group(3))
        month = months.get(month_name)
        if month is None:
            return None
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _parse_value_sek(text: str) -> int | None:
    match = VALUE_SEK_RE.search(text or "")
    if not match:
        return None
    raw = match.group(1).replace(" ", "").replace(" ", "")
    try:
        amount = int(raw)
    except ValueError:
        return None
    lowered = (text[match.end():] + " " + (match.group(0) or "")).lower()
    if "mkr" in lowered or "miljoner" in lowered:
        amount *= 1_000_000
    elif "tkr" in lowered:
        amount *= 1_000
    return amount


class EavropScraper(BaseScraper[ProcurementItem]):
    name = "eavrop"
    base_url = "https://www.e-avrop.com"
    domain = "www.e-avrop.com"
    source_value = "eavrop"

    # /upphandlingar, /annonser and / on www.e-avrop.com are wrappers — the
    # first 404s, the second is a login-walled iframe, the third is the front
    # page. The actual public procurement list lives at
    # /e-Upphandling/Default.aspx (active) and /e-Upphandling/planedComing.aspx
    # (planned). Each row is an <a href="/{customer}/visa/upphandling.aspx?id=N">
    # which the substring filter in _extract_detail_urls already accepts.
    LISTING_PATHS = ("/e-Upphandling/Default.aspx", "/e-Upphandling/planedComing.aspx")

    async def list_urls(self) -> list[str]:
        """Fetch the public listing page and extract detail-page URLs.

        Tries a few common Swedish procurement-portal listing paths; the
        first path that returns a 2xx with anchor tags pointing to detail
        pages wins. We accept any same-host link that looks like a tender
        page (heuristic: ``/upphandling/`` or ``/annons/`` segment).
        """
        for path in self.LISTING_PATHS:
            url = self.base_url + path
            body, meta = await self.fetch(url)
            if body is None:
                logger.debug(
                    "eavrop_listing_skipped",
                    url=url,
                    reason=meta.get("robots_decision") or meta.get("error"),
                )
                continue
            urls = self._extract_detail_urls(body, base=url)
            if urls:
                logger.info("eavrop_listing_ok", url=url, found=len(urls))
                return urls
        logger.warning("eavrop_listing_empty")
        return []

    def _extract_detail_urls(self, html: str, *, base: str) -> list[str]:
        tree = HTMLParser(html)
        out: list[str] = []
        seen: set[str] = set()
        for anchor in tree.css("a[href]"):
            href = anchor.attributes.get("href")
            if not href:
                continue
            full = urljoin(base, href)
            parsed = urlparse(full)
            if parsed.netloc and parsed.netloc != self.domain:
                continue
            path = parsed.path.lower()
            if "/upphandling" not in path and "/annons" not in path:
                continue
            # Skip the listing pages themselves.
            if path in {"/upphandlingar", "/annonser"} or path.endswith("/sok"):
                continue
            if full in seen:
                continue
            seen.add(full)
            out.append(full)
            if len(out) >= 50:
                break
        return out

    def parse(self, body: str, url: str) -> ProcurementItem | None:
        """Extract a procurement record from a single detail page.

        Returns ``None`` if the page does not look like a procurement page —
        the orchestrator skips silently. Non-fatal: logs and returns None on
        any unexpected structure.
        """
        try:
            tree = HTMLParser(body)
        except Exception as exc:
            logger.warning("eavrop_parse_failed", url=url, error=str(exc))
            return None

        title = _first_text(
            tree,
            [
                "h1.tender-title",
                "h1.annons-title",
                "main h1",
                "article h1",
                "h1",
            ],
        )
        if not title:
            return None

        buyer_name = _first_text(
            tree,
            [
                ".buyer-name",
                ".kopare",
                ".upphandlande-organisation",
                "[data-buyer]",
                ".organisation",
            ],
        )

        description = _first_text(
            tree,
            [
                ".tender-description",
                ".annons-beskrivning",
                ".beskrivning",
                "section.description",
                "article p",
            ],
        )
        if description and len(description) > 1500:
            description = description[:1500].rsplit(" ", 1)[0] + "…"

        deadline_raw = _first_text(
            tree,
            [
                ".deadline-date",
                "[data-deadline]",
                ".sista-anbudsdag",
                ".anbudsdag",
                "time.deadline",
            ],
        )
        deadline = _parse_swedish_date(deadline_raw)

        full_text = tree.text(separator=" ", strip=True) if tree.body else ""
        cpv_codes = list(dict.fromkeys(CPV_RE.findall(full_text)))[:8]
        orgnr_match = ORGNR_RE.search(buyer_name + " " + full_text[:500])
        buyer_orgnr = (orgnr_match.group(1).replace("-", "") if orgnr_match else None)
        estimated_value_sek = _parse_value_sek(full_text[:5000])

        external_id = self._derive_external_id(tree, url)

        return ProcurementItem(
            external_id=external_id,
            buyer_orgnr=buyer_orgnr,
            buyer_name=buyer_name or "Okänd köpare",
            title=title,
            description=description or None,
            cpv_codes=cpv_codes,
            estimated_value_sek=estimated_value_sek,
            procedure_type=None,
            deadline=deadline,
            source_url=url,
            source=self.source_value,
        )

    @staticmethod
    def _derive_external_id(tree: HTMLParser, url: str) -> str:
        meta = tree.css_first('meta[name="annonsId"]')
        if meta is not None:
            value = meta.attributes.get("content") or ""
            if value.strip():
                return f"eavrop:{value.strip()}"
        # Fall back to the URL's last path segment + query string for
        # idempotent dedup. URLs are stable enough for a first pass.
        parsed = urlparse(url)
        slug = parsed.path.rstrip("/").rsplit("/", 1)[-1] or "root"
        if parsed.query:
            slug = f"{slug}?{parsed.query}"
        return f"eavrop:{slug}"

    async def fetch_since(self, since: datetime) -> AsyncIterator[ProcurementItem]:
        urls = await self.list_urls()
        for url in urls:
            body, _meta = await self.fetch(url)
            if body is None:
                continue
            try:
                item = self.parse(body, url)
            except Exception as exc:
                logger.warning("eavrop_parse_unhandled", url=url, error=str(exc))
                continue
            if item is None:
                continue
            yield item

    async def persist(self, items: list[ProcurementItem]) -> int:
        if not items:
            return 0
        rows = [
            {
                "external_id": item.external_id,
                "buyer_orgnr": item.buyer_orgnr,
                "buyer_name": item.buyer_name,
                "title": item.title,
                "description": item.description,
                "cpv_codes": item.cpv_codes,
                "estimated_value_sek": item.estimated_value_sek,
                "procedure_type": item.procedure_type,
                "deadline": item.deadline,
                "source_url": item.source_url,
                "source": self.source_value,
            }
            for item in items
        ]
        return await insert_ignore(Procurement, rows, conflict_cols=["external_id"])
