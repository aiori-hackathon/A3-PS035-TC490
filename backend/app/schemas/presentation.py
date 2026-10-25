"""
Presentation-layer schemas and response contracts for NEXORA Track B (Phase 10).

These schemas wrap or annotate core domain models for operator console display.
Key Invariants:
- Explicit data source tagging (never claim archived telemetry is live).
- Read-only data representations.
- Structured error envelopes.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.evidence import EvidenceRecord
from app.schemas.probe import ProbeRequest
from app.schemas.topology import NetworkLink, Router, RouterStatus


class DataSourceMode(str, Enum):
    """Lineage mode of the data returned by the presentation API."""

    CERTIFIED_LIVE_RUN = "CERTIFIED_LIVE_RUN"
    ARCHIVED_REPLAY = "ARCHIVED_REPLAY"
    CANONICAL_SPECIFICATION = "CANONICAL_SPECIFICATION"
    CERTIFIED_ARCHIVE_NOT_ON_DEVICE = "CERTIFIED_ARCHIVE_NOT_ON_DEVICE"
    PENDING_TRACK_A_CAPTURE = "PENDING_TRACK_A_CAPTURE"


class ScenarioCategory(str, Enum):
    """Classification of scenarios: certified live experiments vs historical benchmarks."""

    CERTIFIED_LIVE_EXPERIMENT = "CERTIFIED_LIVE_EXPERIMENT"
    BENCHMARK_EVALUATION = "BENCHMARK_EVALUATION"


class ScenarioAvailability(str, Enum):
    """Availability of archived telemetry data."""

    AVAILABLE = "AVAILABLE"
    CERTIFIED_CAPTURE_NOT_YET_AVAILABLE_ON_THIS_DEVICE = (
        "CERTIFIED_CAPTURE_NOT_YET_AVAILABLE_ON_THIS_DEVICE"
    )
    UNAVAILABLE_PENDING_CAPTURE = "UNAVAILABLE_PENDING_CAPTURE"


class SubsystemStatus(str, Enum):
    """Operational readiness status of an individual subsystem."""

    READY = "READY"
    STANDBY = "STANDBY"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


class SystemReadinessResponse(BaseModel):
    """Comprehensive readiness response for NEXORA operator console."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="ready", description="Overall system health status.")
    service_name: str = Field(description="Name of the backend service.")
    version: str = Field(description="Backend version string.")
    environment: str = Field(description="Runtime environment (development, staging, prod).")
    data_source_mode: DataSourceMode = Field(
        default=DataSourceMode.ARCHIVED_REPLAY,
        description="Operating data mode of this backend instance.",
    )
    ground_truth_isolation_active: bool = Field(
        default=True,
        description="Confirms injected ground truth labels are strictly isolated from inference.",
    )
    subsystems: dict[str, SubsystemStatus] = Field(
        description="Readiness status per architectural component.",
    )
    available_certified_scenarios: list[str] = Field(
        default_factory=list,
        description="Available certified live experiments (e.g. ['F1_LINK_FAILURE']).",
    )
    available_benchmark_scenarios: list[str] = Field(
        default_factory=list,
        description="Available benchmark evaluation scenarios.",
    )
    available_archived_scenarios: list[str] = Field(
        description="All scenario keys available for presentation.",
    )
    checked_at: datetime = Field(
        description="UTC timestamp when readiness check was evaluated.",
    )
    disclaimer: str = Field(
        default=(
            "MacBook 2 presentation node running in read-only replay & verification mode. "
            "FRRouting emulation containerlab is isolated to MacBook 1."
        ),
        description="Operational context disclaimer.",
    )


class LinkHealthStatus(str, Enum):
    """Calculated operational health of a network link."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class TopologyStatusSummary(BaseModel):
    """Summary metrics of router and link operational health."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    data_source: DataSourceMode
    is_live: bool = False
    is_replay: bool = True
    total_routers: int = 5
    routers_up: int
    routers_down: int
    routers_unknown: int
    total_links: int = 5
    links_healthy: int
    links_degraded: int
    links_down: int
    links_unknown: int
    router_statuses: dict[str, RouterStatus]
    link_statuses: dict[str, LinkHealthStatus]
    evaluated_at: datetime


class RouterDetailResponse(BaseModel):
    """Detailed view of a single router in the topology."""

    model_config = ConfigDict(extra="forbid")

    router: Router
    connected_link_ids: list[str]
    expected_peer_router_ids: list[str]
    current_health: RouterStatus
    data_source: DataSourceMode
    is_live: bool = False


class LinkDetailResponse(BaseModel):
    """Detailed view of a single point-to-point link in the topology."""

    model_config = ConfigDict(extra="forbid")

    link: NetworkLink
    health_status: LinkHealthStatus
    endpoint_a_status: RouterStatus
    endpoint_b_status: RouterStatus
    data_source: DataSourceMode
    is_live: bool = False


class SnapshotSummary(BaseModel):
    """Catalog entry for an archived evidence snapshot."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    scenario_key: str
    name: str
    description: str
    category: ScenarioCategory = ScenarioCategory.CERTIFIED_LIVE_EXPERIMENT
    availability: ScenarioAvailability = ScenarioAvailability.AVAILABLE
    certified_fault_id: str | None = None
    target_component: str | None = None
    captured_at: datetime | None = None
    record_count: int = 0
    incident_ids: list[str] = Field(default_factory=list)
    data_source: DataSourceMode = DataSourceMode.ARCHIVED_REPLAY
    is_live: bool = False
    unavailable_reason: str | None = None


class IncidentSummary(BaseModel):
    """Summary of a correlated incident."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    snapshot_id: str
    scenario_key: str
    affected_routers: list[str]
    affected_links: list[str]
    evidence_count: int
    correlation_window_start: datetime
    correlation_window_end: datetime | None
    correlation_explanation: str
    score_label: str = "Rule Alignment Score"
    score_interpretation: str = (
        "Deterministic heuristic score in [0.0, 1.0] derived from fault rule matching."
    )
    data_source: DataSourceMode = DataSourceMode.ARCHIVED_REPLAY
    is_live: bool = False


class EvidenceQueryResponse(BaseModel):
    """Paginated or filtered list of evidence records."""

    model_config = ConfigDict(extra="forbid")

    total_count: int
    limit: int
    offset: int
    items: list[EvidenceRecord]
    applied_filters: dict[str, Any]
    data_source: DataSourceMode = DataSourceMode.ARCHIVED_REPLAY


class RankedProbeRecommendation(BaseModel):
    """Single ranked probe recommendation adhering to Phase 08 planner contracts."""

    model_config = ConfigDict(extra="forbid")

    probe_id: str
    rank: int
    probe_type: str = Field(
        description=(
            "Probe check type (INTERFACE_STATE, OSPF_NEIGHBOUR, ROUTING_TABLE, PING, TRACEROUTE)."
        )
    )
    source_router: str
    target_router: str | None = None
    target_interface: str | None = None
    target_prefix: str | None = None
    target_address: str | None = None
    safety_status: str = Field(
        default="ALLOWLIST_VALIDATED",
        description="Safety status: SAFE_READ_ONLY, ALLOWLIST_VALIDATED.",
    )
    ranking_rationale: str
    relative_cost: int = Field(default=1, description="Relative execution cost weight.")
    expected_discriminating_outcomes: list[str] = Field(default_factory=list)
    missing_evidence_addressed: list[str] = Field(default_factory=list)
    timeout_s: float = 5.0
    execution_authorization: str = Field(
        default="PLANNED — NOT EXECUTED",
        description="Always 'PLANNED — NOT EXECUTED'. Automated execution is hard-disabled.",
    )


class SafeProbePlanResponse(BaseModel):
    """
    Read-only presentation plan of safe diagnostic probes adhering to Phase 08 integration contract.
    """

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    status: str = Field(
        default="PROVISIONAL",
        description="Provisional recommendations pending Phase 08 planner.",
    )
    recommendations: list[ProbeRequest] = Field(default_factory=list)
    ranked_probes: list[RankedProbeRecommendation] = Field(default_factory=list)
    total_recommended_probes: int = 0
    total_plan_cost: int = 0
    allowlist_verified: bool = True
    execution_status: str = Field(
        default="PLANNED — NOT EXECUTED",
        description="Authoritative probe plan execution status.",
    )
    information_gain: str = Field(
        default="UNAVAILABLE_PENDING_PHASE_08_PLANNER",
        description="Information gain metric status.",
    )
    entropy_reduction_bits: float | None = Field(
        default=None,
        description="Entropy reduction is computed solely by Phase 08 planner.",
    )
    planner_source: str = Field(
        default="Phase 07 Counterfactual Verifier (Provisional)",
        description="Upstream engine producing provisional recommendations.",
    )
    safety_guardrail: str = Field(
        default="STRICT_READ_ONLY_GUARDED",
        description="Safety protocol state.",
    )
    execution_permitted: bool = Field(
        default=False,
        description="Execution is disabled until human authorization and dedicated backend exists.",
    )
    execution_blocked_reason: str = Field(
        default=(
            "Active probe execution is disabled. Requires authorized Track A execution engine."
        ),
        description="Reason why execution is blocked.",
    )
    notes: list[str] = Field(default_factory=list)
    contract_status: str = Field(
        default="PROVISIONAL_ADAPTER_PREVIEW",
        description="Contract integration readiness status.",
    )
    data_source: DataSourceMode = DataSourceMode.ARCHIVED_REPLAY


class AuditableEvidenceCertificateResponse(BaseModel):
    """
    Auditable Evidence Certificate presentation model adhering to Phase 09 integration contract.
    """

    model_config = ConfigDict(extra="forbid")

    certificate_id: str
    incident_id: str
    snapshot_id: str
    snapshot_digest: str | None = Field(
        default=None,
        description="SHA-256 digest of neutral source snapshot (or None if unverified/absent).",
    )
    source_run_id: str | None = None
    fault_type: str = Field(description="Predicted root cause fault type.")
    fault_location_component_id: str = Field(description="Component ID (e.g. L12, R3).")
    fault_location_kind: str = Field(description="Location kind (LINK, ROUTER, INTERFACE).")
    heuristic_score: float = Field(
        description="Deterministic rule alignment score in [0.0, 1.0].",
    )
    score_label: str = Field(
        default="Rule Alignment Score",
        description="Always 'Rule Alignment Score'. Never probability.",
    )
    counterfactual_verdict: str = Field(
        description=(
            "Counterfactual verification verdict (SUPPORTED, CONTRADICTED, INSUFFICIENT_EVIDENCE)."
        ),
    )
    explanation: str = Field(description="Evidence-backed root cause explanation.")
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradictory_evidence_ids: list[str] = Field(default_factory=list)
    missing_observations: list[str] = Field(default_factory=list)
    collector_failures: list[str] = Field(default_factory=list)
    evidence_coverage_pct: float = Field(default=0.0)
    sufficiency_met: bool = Field(default=False)
    recommended_safe_checks: list[str] = Field(default_factory=list)
    provenance_integrity_status: str = Field(
        default="STRUCTURALLY_VALID_LOCAL_CAPTURE",
        description=(
            "Distinction: STRUCTURALLY_VALID_LOCAL_CAPTURE, PROVENANCE_VERIFIED, "
            "or AWAITING_CERTIFIED_ARCHIVE_TRANSFER."
        ),
    )
    provenance_details: str = Field(
        default="Evaluation telemetry captured from local containerlab observation dataset.",
    )
    limitations: list[str] = Field(default_factory=list)
    causation_disclaimer: str = Field(
        default=(
            "A SUPPORTED diagnosis indicates rigorous mathematical consistency with "
            "observed evidence and counterfactual rules, but is not absolute "
            "philosophical proof of causation."
        ),
    )
    is_certified: bool = False
    data_source: DataSourceMode = DataSourceMode.ARCHIVED_REPLAY
    generated_at: datetime


class DetailError(BaseModel):
    """Structured error envelope."""

    model_config = ConfigDict(extra="forbid")

    detail: str
    error_code: str
    component: str | None = None
