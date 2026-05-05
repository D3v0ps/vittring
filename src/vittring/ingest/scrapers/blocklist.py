"""Domains added here will be skipped by every scraper on the next cycle.

Maintain manually when an opt-out request is received.
"""

from __future__ import annotations

BLOCKED_DOMAINS: set[str] = set()
