"""
NEXORA Safe Active Probe Planning Engine (Phase 08).

Provides deterministic, fail-closed diagnostic probe planning:
- Answers: "What safe read-only observation would best help confirm or distinguish hypotheses?"
- Plans are strictly PROPOSED / NOT EXECUTED.
- Full topology-aware discrimination for router vs link ambiguities (e.g. F2).
"""

from __future__ import annotations

from app.probes.planner import PLANNER_VERSION, ProbePlanner
from app.probes.policy import ProbeSafetyPolicy
from app.probes.ranking import ProbeRankingEngine
from app.schemas.probe import (
    DiscriminatingOutcomes,
    ExecutionAuthorizationState,
    PlannedProbe,
    ProbeCostEstimate,
    ProbePlanReport,
    ProbeSafetyStatus,
)

__all__ = [
    "PLANNER_VERSION",
    "DiscriminatingOutcomes",
    "ExecutionAuthorizationState",
    "PlannedProbe",
    "ProbeCostEstimate",
    "ProbePlanReport",
    "ProbePlanner",
    "ProbeRankingEngine",
    "ProbeSafetyPolicy",
    "ProbeSafetyStatus",
]
