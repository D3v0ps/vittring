"""e-Avrop scraper.

The public e-Avrop site (https://www.e-avrop.com) wraps every announcement
inside a session-walled ``<iframe>`` whose inner endpoint
(``leverantor/annons/procurement.aspx``) returns ``500`` to anonymous
clients. The outer detail page itself contains only login/navigation
chrome — no ``<h1>``, no procurement metadata.

Fortunately the listing table at ``/e-Upphandling/Default.aspx`` already
exposes every field we need (title, buyer, CPV codes, deadline) directly
in the row, so we parse rows in place and never visit detail pages.

Compliance plumbing (robots.txt, rate limit, blocklist, audit log) lives
in :class:`BaseScraper`. We only call :meth:`BaseScraper.fetch` for the
listing page and let the base class enforce policy.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

import structlog
from selectolax.parser import HTMLParser, Node

from vittring.ingest._persist import insert_ignore
from vittring.ingest.scrapers.base import BaseScraper
from vittring.models.signals import Procurement
from vittring.schemas.ingest import ProcurementItem

logger = structlog.get_logger(__name__)


CPV_RE = re.compile(r"\b(\d{8})\b")


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    return node.text(strip=True)


def _parse_swedish_date(text: str) -> datetime | None:
    """Parse common Swedish date formats: ``YYYY-MM-DD`` or ``DD MMM YYYY``."""
    text = text.strip()
    if not text:
        return None
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


class EavropScraper(BaseScraper[ProcurementItem]):
    name = "eavrop"
    base_url = "https://www.e-avrop.com"
    domain = "www.e-avrop.com"
    source_value = "eavrop"

    # /e-Upphandling/planedComing.aspx exposes "planned" procurements but
    # uses a different 6-column schema with no anchor links, no procurement
    # ID, and no deadline — only title, buyer, CPV and planned year. It's
    # genuinely useful early-warning data; needs its own parser path before
    # we can ingest. Tracked separately.
    LISTING_PATHS = ("/e-Upphandling/Default.aspx",)

    # Listing rows have five columns: Rubrik, Publicerad, Organisation,
    # Område (CPV codes), Anbud-/Ansökningsdag (deadline). The deadline
    # cell may carry a trailing relative-time hint ("I dag", "I morgon")
    # after a "|" separator that we strip.
    _ROW_SELECTOR = "tr.rowline"
    _COL_TITLE = 0
    _COL_BUYER = 2
    _COL_CPV = 3
    _COL_DEADLINE = 4

    async def fetch_since(self, since: datetime) -> AsyncIterator[ProcurementItem]:
        """Walk the public listing pages and yield one item per row.

        Detail pages are session-walled iframes that return ``500`` to
        anonymous clients (verified 2026-05). Listing rows already carry
        every field the matching engine needs, so we extract there and
        skip detail-page round-trips entirely.
        """
        for path in self.LISTING_PATHS:
            url = self.base_url + path
            body, _meta = await self.fetch(url)
            if body is None:
                logger.debug("eavrop_listing_skipped", url=url)
                continue
            count = 0
            for item in self._extract_listing_items(body):
                count += 1
                yield item
            logger.info("eavrop_listing_ok", url=url, found=count)

    def _extract_listing_items(self, html: str) -> Iterator[ProcurementItem]:
        try:
            tree = HTMLParser(html)
        except Exception as exc:  # selectolax raises generic exceptions
            logger.warning("eavrop_parse_failed", error=str(exc))
            return

        seen: set[str] = set()
        for tr in tree.css(self._ROW_SELECTOR):
            tds = tr.css("td")
            if len(tds) <= self._COL_DEADLINE:
                continue

            anchor = tds[self._COL_TITLE].css_first("a[href]")
            if anchor is None:
                continue
            href = anchor.attributes.get("href") or ""
            # Listing rows link to either /{customer}/visa/upphandling.aspx
            # (regular tenders) or /{customer}/visa/RFI.aspx (request-for-
            # information rounds). RFIs are pre-procurement signals — sales
            # teams care about them, so we ingest both.
            if "/visa/" not in href.lower() or ".aspx?id=" not in href.lower():
                continue
            title = anchor.text(strip=True)
            if not title:
                continue

            full_url = urljoin(self.base_url + "/", href.lstrip("/"))
            external_id = self._external_id_from_url(full_url)
            if external_id in seen:
                continue
            seen.add(external_id)

            buyer_name = _text(tds[self._COL_BUYER]) or "Okänd köpare"
            cpv_codes = list(
                dict.fromkeys(CPV_RE.findall(_text(tds[self._COL_CPV])))
            )[:8]
            deadline_text = _text(tds[self._COL_DEADLINE]).split("|", 1)[0].strip()
            deadline = _parse_swedish_date(deadline_text)

            yield ProcurementItem(
                external_id=external_id,
                buyer_orgnr=None,
                buyer_name=buyer_name,
                title=title,
                description=None,
                cpv_codes=cpv_codes,
                estimated_value_sek=None,
                procedure_type=None,
                deadline=deadline,
                source_url=full_url,
                source=self.source_value,
            )

    @staticmethod
    def _external_id_from_url(url: str) -> str:
        # Path is /{customer}/visa/{kind}.aspx where {kind} is "upphandling"
        # or "RFI"; the integer id query param is unique within {kind} but
        # collides across kinds (e.g. RFI 4163 vs upphandling 4163), so we
        # encode both into the external_id.
        parsed = urlparse(url)
        eid = (parse_qs(parsed.query).get("id", [""])[0] or "").strip()
        last = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        kind = last.split(".", 1)[0].lower() if last else ""
        if eid and kind:
            return f"eavrop:{kind}:{eid}"
        if eid:
            return f"eavrop:{eid}"
        return f"eavrop:{last or 'root'}"

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
