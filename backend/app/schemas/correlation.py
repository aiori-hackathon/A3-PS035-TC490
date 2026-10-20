"""
NEXORA correlation domain models for Phase 05.

Defines typed schemas for:
  - SymptomCategory: descriptive symptom classifications (observations, not diagnoses)
  - CorrelatedSymptom: a single classified symptom with supporting evidence
  - CorrelationRelationship: relationship between two correlated components
  - CorrelatedIncident: a group of correlated observations forming a potential incident
  - CorrelationResult: complete output of the correlation engine for one snapshot

DESIGN INVARIANTS:
  - SymptomCategory values are observations, not root-cause labels.
    (e.g. OSPF_ADJACENCY_LOST is observed, not diagnosed as LINK_FAILURE)
  - CorrelatedIncident does NOT include injected fault type, ground-truth location,
    scenario names, or root-cause predictions.
  - Each correlated observation is explained with an auditable reason.
  - An incident with insufficient information remains explicitly INCOMPLETE.
  - Multiple independent incident groups are supported within one CorrelationResult.
  - ENGINE_VERSION is embedded for reproducibility.

Note on thresholds:
  - PACKET_LOSS_THRESHOLD_PCT and LATENCY_ELEVATED_THRESHOLD_MS are configurable
    defaults based on lab baseline observations (baseline: ~0.0% loss, ~0.3ms RTT).
  - These are NOT statistically validated thresholds — they are starting points
    chosen conservatively for the NEXORA lab environment.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Configurable thresholds (documented, not hardcoded as "truth")
# ---------------------------------------------------------------------------

PACKET_LOSS_THRESHOLD_PCT: float = 5.0
"""Packet loss percentage above which PACKET_LOSS_ELEVATED is flagged.

Default: 5.0% (NEXORA lab baseline: 0.0%).
Rationale: 5% provides a margin above polling noise while detecting real loss.
This is NOT a statistically validated SLA threshold.
"""

LATENCY_ELEVATED_THRESHOLD_MS: float = 10.0
"""Average RTT above which LATENCY_ELEVATED is flagged (milliseconds).

Default: 10.0ms (NEXORA lab baseline: ~0.3–0.8ms).
Rationale: 10ms provides a clear signal above loopback noise in a containerized lab.
This is NOT a production network threshold.
"""

SYSLOG_WARNING_SEVERITIES: frozenset[str] = frozenset(
    ["EMERGENCY", "ALERT", "CRITICAL", "ERROR", "WARNING"]
)
"""Syslog severity levels that trigger a LOG_WARNING symptom."""

CORRELATION_ENGINE_VERSION: str = "nexora-correlation-v0.5.0"
"""Version string for the correlation engine. Embedded in all results."""


# ---------------------------------------------------------------------------
# Symptom categories
# ---------------------------------------------------------------------------


class SymptomCategory(str, Enum):
    """
    Descriptive categories for observable network symptoms.

    These are classified observations, NOT root-cause labels.
    A single root cause may produce multiple symptoms.
    A symptom does NOT imply knowledge of the underlying fault.

    IMPORTANT:
    - ROUTER_UNREACHABLE means: observed no response from the router.
      It does NOT mean: the router hardware has failed.
    - OSPF_ADJACENCY_LOST means: the OSPF adjacency state is not FULL.
      It does NOT mean: a physical link has failed.
    - COLLECTION_FAILURE means: evidence collection failed for a component.
      It does NOT mean: the component is down.
    """

    ROUTER_UNREACHABLE = "ROUTER_UNREACHABLE"
    """Router container is not reachable for evidence collection."""

    INTERFACE_DOWN = "INTERFACE_DOWN"
    """Network interface is observed in operational DOWN state."""

    OSPF_ADJACENCY_LOST = "OSPF_ADJACENCY_LOST"
    """Expected OSPF adjacency is missing or in DOWN state."""

    OSPF_ADJACENCY_DEGRADED = "OSPF_ADJACENCY_DEGRADED"
    """OSPF adjacency is in a non-FULL, non-DOWN transitional state."""

    ROUTE_CHANGED = "ROUTE_CHANGED"
    """A route exists but uses a different next-hop than baseline."""

    ROUTE_MISSING = "ROUTE_MISSING"
    """An expected route prefix is absent from the routing table."""

    PACKET_LOSS_ELEVATED = "PACKET_LOSS_ELEVATED"
    """Measured packet loss exceeds the configured threshold."""

    LATENCY_ELEVATED = "LATENCY_ELEVATED"
    """Measured average RTT exceeds the configured threshold."""

    LOG_WARNING = "LOG_WARNING"
    """A WARNING-or-worse syslog event was observed."""

    COLLECTION_FAILURE = "COLLECTION_FAILURE"
    """Evidence collection attempt failed for a component."""

    TOPOLOGY_DEVIATION = "TOPOLOGY_DEVIATION"
    """Observed topology differs from the expected baseline topology."""

    HEALTHY = "HEALTHY"
    """Component appears healthy in this observation."""


# ---------------------------------------------------------------------------
# Correlated symptom
# ---------------------------------------------------------------------------


class CorrelatedSymptom(BaseModel):
    """A single classified symptom with supporting evidence."""

    model_config = ConfigDict(extra="forbid")

    symptom_id: str = Field(
        description="Unique identifier for this symptom within an incident.",
        min_length=1,
    )
    category: SymptomCategory = Field(
        description="Symptom classification category.",
    )
    affected_component: str = Field(
        description="Component ID this symptom concerns (router_id, link_id, or interface node).",
        min_length=1,
    )
    description: str = Field(
        description="Human-readable description of the observed symptom.",
        min_length=1,
        max_length=512,
    )
    supporting_evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence record IDs that produced this symptom classification.",
    )
    is_direct_observation: bool = Field(
        description=(
            "True if this symptom is directly observed (e.g. interface query returned DOWN). "
            "False if it is derived from absence of expected evidence."
        ),
    )
    observed_at: datetime | None = Field(
        default=None,
        description="Timestamp of the observation that produced this symptom.",
    )
    measurement_value: float | None = Field(
        default=None,
        description=(
            "Numerical measurement value where applicable (e.g. packet_loss_pct, rtt_ms). "
            "None for non-numerical symptoms."
        ),
    )
    threshold_used: float | None = Field(
        default=None,
        description=(
            "Threshold that was crossed to trigger this symptom (where applicable). "
            "Documented for transparency."
        ),
    )


# ---------------------------------------------------------------------------
# Correlation relationship
# ---------------------------------------------------------------------------


class CorrelationRelationship(BaseModel):
    """
    A documented relationship between two symptoms or components in an incident.

    This records WHY two observations were placed in the same incident group.
    It does not claim causation.
    """

    model_config = ConfigDict(extra="forbid")

    from_component: str = Field(
        description="Source component or symptom ID.",
    )
    to_component: str = Field(
        description="Target component or symptom ID.",
    )
    relationship_kind: str = Field(
        description=(
            "Type of relationship: 'PHYSICAL_TOPOLOGY', 'OSPF_TOPOLOGY', "
            "'TEMPORAL', 'SHARED_ROUTER', 'SHARED_LINK', or 'INDIRECT'."
        ),
        max_length=32,
    )
    supporting_evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence IDs that support this relationship.",
    )
    explanation: str = Field(
        description="Plain-English explanation of why this relationship was identified.",
        max_length=512,
    )


# ---------------------------------------------------------------------------
# Correlated incident
# ---------------------------------------------------------------------------


class CorrelatedIncident(BaseModel):
    """
    A group of correlated observations that may share a common context.

    IMPORTANT SCOPE LIMITS:
    - This is NOT a diagnosis. It is a grouping of related observations.
    - The 'symptoms' field classifies observations, not fault types.
    - No fault_type, fault_location, or confidence score is included.
    - Missing information is explicitly represented.
    - A root-cause ranking is NOT attempted (that is Phase 06).

    An incident with insufficient information has status='INCOMPLETE'
    and an explicit missing_information list.
    """

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(
        description="Stable, neutral incident identifier (e.g. 'ci-20261019-001').",
        min_length=1,
    )
    status: str = Field(
        description=(
            "Correlation status: 'GROUPED' (correlated observations), "
            "'ISOLATED' (single ungrouped symptom), "
            "'INCOMPLETE' (insufficient evidence to correlate), "
            "'HEALTHY' (no abnormalities detected)."
        ),
        max_length=16,
    )
    correlation_window_start: datetime = Field(
        description="UTC start of the observation window for this incident.",
    )
    correlation_window_end: datetime = Field(
        description="UTC end of the observation window for this incident.",
    )
    affected_routers: list[str] = Field(
        default_factory=list,
        description=(
            "Router IDs implicated by observations in this incident. "
            "This is a candidate list from correlation, not a diagnosis."
        ),
    )
    affected_links: list[str] = Field(
        default_factory=list,
        description=(
            "Link IDs implicated by observations in this incident. "
            "This is a candidate list from correlation, not a diagnosis."
        ),
    )
    symptoms: list[CorrelatedSymptom] = Field(
        default_factory=list,
        description="Classified symptom observations within this incident.",
    )
    relationships: list[CorrelationRelationship] = Field(
        default_factory=list,
        description=(
            "Documented relationships between symptoms and components that "
            "justify placing them in the same incident group."
        ),
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="All evidence record IDs included in this incident group.",
    )
    supporting_observations: list[str] = Field(
        default_factory=list,
        description="Plain-English descriptions of key supporting observations.",
    )
    contradictory_observations: list[str] = Field(
        default_factory=list,
        description="Plain-English descriptions of observations that appear inconsistent.",
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Plain-English descriptions of relevant evidence that was not collected.",
    )
    correlation_explanation: str = Field(
        description=(
            "Step-by-step plain-English explanation of how this incident group "
            "was formed. Auditable account of the correlation logic applied."
        ),
        max_length=4096,
    )
    engine_version: str = Field(
        default=CORRELATION_ENGINE_VERSION,
        description="Version of the correlation engine that produced this incident.",
    )

    @field_validator("correlation_window_start", "correlation_window_end", mode="before")
    @classmethod
    def validate_utc_aware(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("Correlation window timestamps must be timezone-aware UTC.")
        return v


# ---------------------------------------------------------------------------
# Correlation result
# ---------------------------------------------------------------------------


class CorrelationResult(BaseModel):
    """
    Complete output of the Phase 05 correlation engine for one evidence snapshot.

    Contains one or more CorrelatedIncident groups. Multiple independent groups
    may be present if unrelated symptoms are detected in the same collection run.
    """

    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(
        description="Unique correlation result identifier.",
        min_length=1,
    )
    snapshot_id: str = Field(
        description="ID of the EvidenceSnapshot this result was produced from.",
        min_length=1,
    )
    produced_at: datetime = Field(
        description="UTC timestamp when correlation was completed.",
    )
    engine_version: str = Field(
        default=CORRELATION_ENGINE_VERSION,
        description="Correlation engine version.",
    )
    incidents: list[CorrelatedIncident] = Field(
        default_factory=list,
        description=(
            "Correlated incident groups. May contain zero or more incidents. "
            "Zero incidents indicates a healthy baseline snapshot."
        ),
    )
    total_evidence_records: int = Field(
        ge=0,
        description="Total evidence records processed in this correlation run.",
    )
    anomalous_record_count: int = Field(
        ge=0,
        description="Number of records that indicated a non-healthy observation.",
    )
    duplicate_records_removed: int = Field(
        ge=0,
        description="Number of logically duplicate records removed before correlation.",
    )
    ground_truth_isolation_verified: bool = Field(
        description=(
            "True if the correlation engine confirmed no ground-truth labels "
            "are present in the input snapshot."
        ),
    )
    correlation_notes: list[str] = Field(
        default_factory=list,
        description="General notes about this correlation run (warnings, limitations).",
    )

    @field_validator("produced_at", mode="before")
    @classmethod
    def validate_utc_aware(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("produced_at must be timezone-aware UTC.")
        return v
