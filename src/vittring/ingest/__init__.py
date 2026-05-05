"""Data ingestion adapters for the three signal sources."""

from vittring.ingest.base import IngestAdapter, IngestResult, run_ingest

__all__ = ["IngestAdapter", "IngestResult", "run_ingest"]
