"""
NEXORA correlation package — Phase 05.

Provides topology-aware incident correlation components:
- EvidenceGraph: evidence ↔ component dependency graph
- TemporalCorrelator: configurable temporal windowing
- CorrelationEngine: deterministic incident grouping engine
"""

from app.correlation.engine import CorrelationEngine
from app.correlation.evidence_graph import EvidenceGraph, EvidenceRelationship, RelationshipType
from app.correlation.temporal import (
    DEFAULT_WINDOW_SECONDS,
    OSPF_DEAD_TIMER_BUFFER_SECONDS,
    POLLING_JITTER_SECONDS,
    ObservationWindow,
    TemporalCorrelator,
    TemporalGroup,
)

__all__ = [
    "CorrelationEngine",
    "DEFAULT_WINDOW_SECONDS",
    "EvidenceGraph",
    "EvidenceRelationship",
    "ObservationWindow",
    "OSPF_DEAD_TIMER_BUFFER_SECONDS",
    "POLLING_JITTER_SECONDS",
    "RelationshipType",
    "TemporalCorrelator",
    "TemporalGroup",
]
