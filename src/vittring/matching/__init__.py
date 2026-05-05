"""Subscription matching engine.

All public entry points are re-exported here. The implementation is split
into ``criteria`` (typed input model) and ``engine`` (pure predicates).
"""

from vittring.matching.criteria import Criteria, SignalType
from vittring.matching.engine import (
    match_company_change,
    match_job_posting,
    match_procurement,
)

__all__ = [
    "Criteria",
    "SignalType",
    "match_company_change",
    "match_job_posting",
    "match_procurement",
]
