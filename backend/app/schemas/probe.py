"""
Active probe domain models for the NEXORA diagnostic system.

Probes are bounded, read-only diagnostic operations executed by the system
during Phase 03 counterfactual verification. They are strictly limited to
predefined, safe operations that cannot modify router configuration or state.

DESIGN INVARIANTS:
- NO arbitrary shell command execution is permitted. The probe request contract
  does not contain a generic command or arguments field.
- All probe types are predefined in ProbeType enum. No dynamic type injection.
- Probes are approved-path only: source and destination must both be known
  topology components.
- Probe results produce EvidenceRecord references, not diagnostic conclusions.
- Probe timeout is bounded (MAX_PROBE_TIMEOUT_S = 30 seconds).
- No probe may modify router configuration, routing tables, or interface state.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Absolute maximum timeout enforced at contract level
MAX_PROBE_TIMEOUT_S: int = 30


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ProbeType(str, Enum):
    """Exhaustive set of allowed probe types.

    These are the ONLY probe operations the active probe planner may request.
    No other commands, scripts, or operations are permitted.

    PING: ICMP echo request series to a target IP/loopback.
    INTERFACE_STATE: Poll the operational state of a specific interface.
    OSPF_NEIGHBOUR: Query the OSPF adjacency state towards a specific neighbour.
    ROUTING_TABLE: Read the current RIB for a specific destination prefix.
    TRACEROUTE: ICMP traceroute to discover the current forwarding path.
    """

    PING = "PING"
    INTERFACE_STATE = "INTERFACE_STATE"
    OSPF_NEIGHBOUR = "OSPF_NEIGHBOUR"
    ROUTING_TABLE = "ROUTING_TABLE"
    TRACEROUTE = "TRACEROUTE"


class ProbeStatus(str, Enum):
    """Execution status of a probe request."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    TIMED_OUT = "TIMED_OUT"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Probe request
# ---------------------------------------------------------------------------


class ProbeRequest(BaseModel):
    """A request to execute a single bounded, read-only diagnostic probe.

    The probe contract deliberately excludes:
    - Generic command fields
    - Shell script fields
    - Configuration change fields
    - Interface state modification fields

    Only the defined ProbeType values are accepted.
    """

    model_config = ConfigDict(extra="forbid")

    probe_id: str = Field(
        description="Unique identifier for this probe request.",
        min_length=1,
    )
    incident_id: str = Field(
        description="Incident this probe is associated with.",
        min_length=1,
    )
    probe_type: ProbeType = Field(
        description="Type of probe to execute. Must be one of the approved ProbeType values.",
    )
    source_router: str = Field(
        description="Router ID from which the probe is executed.",
        pattern=r"^R[1-9][0-9]*$",
    )
    target_router: str | None = Field(
        default=None,
        description="Target router ID (if probe targets a specific router).",
        pattern=r"^R[1-9][0-9]*$",
    )
    target_address: str | None = Field(
        default=None,
        description="IPv4 target address for PING or TRACEROUTE probes. "
        "Must be a known topology address.",
        max_length=45,
    )
    target_interface: str | None = Field(
        default=None,
        description="Interface name for INTERFACE_STATE probes.",
        max_length=15,
    )
    target_prefix: str | None = Field(
        default=None,
        description="Destination IPv4 prefix for ROUTING_TABLE probes (e.g. '192.168.255.3/32').",
        max_length=18,
    )
    selection_reason: str = Field(
        description="Plain-language explanation of why this probe was selected "
        "by the active probe planner. Required for auditability.",
        min_length=1,
        max_length=512,
    )
    timeout_s: int = Field(
        default=5,
        ge=1,
        le=MAX_PROBE_TIMEOUT_S,
        description=f"Probe timeout in seconds. Hard maximum: {MAX_PROBE_TIMEOUT_S}s.",
    )
    requested_at: datetime = Field(
        description="UTC timestamp when this probe was requested.",
    )

    @field_validator("requested_at", mode="before")
    @classmethod
    def validate_utc_aware(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("requested_at must be a timezone-aware UTC datetime")
        return v

    @model_validator(mode="after")
    def validate_probe_has_target(self) -> ProbeRequest:
        """Ensure probe-type-specific target fields are provided."""
        if self.probe_type == ProbeType.PING and self.target_address is None:
            raise ValueError("PING probe requires target_address")
        if self.probe_type == ProbeType.TRACEROUTE and self.target_address is None:
            raise ValueError("TRACEROUTE probe requires target_address")
        if self.probe_type == ProbeType.INTERFACE_STATE and self.target_interface is None:
            raise ValueError("INTERFACE_STATE probe requires target_interface")
        if self.probe_type == ProbeType.OSPF_NEIGHBOUR and self.target_router is None:
            raise ValueError("OSPF_NEIGHBOUR probe requires target_router")
        if self.probe_type == ProbeType.ROUTING_TABLE and self.target_prefix is None:
            raise ValueError("ROUTING_TABLE probe requires target_prefix")
        return self


# ---------------------------------------------------------------------------
# Probe result
# ---------------------------------------------------------------------------


class ProbeResult(BaseModel):
    """The result of an executed probe.

    Probe results link back to EvidenceRecord IDs rather than embedding raw
    data directly. The actual observations are stored as typed EvidenceRecords
    (PingMeasurement, InterfaceObservation, etc.).
    """

    model_config = ConfigDict(extra="forbid")

    probe_id: str = Field(
        description="Matches ProbeRequest.probe_id.",
        min_length=1,
    )
    incident_id: str = Field(
        description="Incident this probe result is associated with.",
        min_length=1,
    )
    status: ProbeStatus = Field(
        description="Execution status of the probe.",
    )
    executed_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when probe execution began. None if still pending.",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when probe execution completed. None if still running.",
    )
    evidence_record_ids: list[str] = Field(
        default_factory=list,
        description="IDs of EvidenceRecord(s) produced by this probe.",
    )
    failure_reason: str | None = Field(
        default=None,
        description="Human-readable reason if status is FAILED, TIMED_OUT, or REJECTED.",
        max_length=512,
    )

    @model_validator(mode="after")
    def validate_failure_reason_present_on_failure(self) -> ProbeResult:
        terminal_failure_statuses = {
            ProbeStatus.FAILED,
            ProbeStatus.TIMED_OUT,
            ProbeStatus.REJECTED,
        }
        if self.status in terminal_failure_statuses and not self.failure_reason:
            raise ValueError(f"failure_reason is required when probe status is {self.status.value}")
        return self


# ---------------------------------------------------------------------------
# Phase 08 — Safe Active Probe Planning Domain Models
# ---------------------------------------------------------------------------


class ExecutionAuthorizationState(str, Enum):
    """Explicit authorization state of a planned diagnostic probe.

    All probes generated by the planner are strictly PROPOSED_NOT_EXECUTED.
    Live execution is never initiated by the planner.
    """

    PROPOSED_NOT_EXECUTED = "PROPOSED_NOT_EXECUTED"
    AUTHORIZED = "AUTHORIZED"
    REJECTED_UNSAFE = "REJECTED_UNSAFE"
    REJECTED_POLICY = "REJECTED_POLICY"
    UNSUPPORTED = "UNSUPPORTED"


class ProbeSafetyStatus(str, Enum):
    """Safety audit classification for a proposed probe."""

    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"


class ResourceImpact(str, Enum):
    """Estimated network and router resource consumption level."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ProbeCostEstimate(BaseModel):
    """Resource and overhead estimate for a planned probe."""

    model_config = ConfigDict(extra="forbid")

    packet_count: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Configured packet count (e.g. 5 for bounded PING).",
    )
    timeout_s: int = Field(
        default=5,
        ge=1,
        le=MAX_PROBE_TIMEOUT_S,
        description="Probe timeout duration in seconds.",
    )
    estimated_rtt_overhead_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Estimated round-trip time overhead in milliseconds.",
    )
    resource_impact: ResourceImpact = Field(
        default=ResourceImpact.LOW,
        description="Qualitative resource consumption level.",
    )
    relative_cost_score: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Normalized relative cost score (1.0 = baseline lightweight query).",
    )


class DiscriminatingOutcomes(BaseModel):
    """Predicted observations and hypothesis implications for possible outcomes."""

    model_config = ConfigDict(extra="forbid")

    observation_if_true: str = Field(
        description="Expected observation if the related candidate hypothesis is true.",
        min_length=1,
    )
    observation_if_false: str = Field(
        description="Expected observation if the related candidate hypothesis is false.",
        min_length=1,
    )
    hypotheses_supported_if_true: list[str] = Field(
        default_factory=list,
        description="Hypothesis IDs or descriptions supported if observation_if_true occurs.",
    )
    hypotheses_contradicted_if_true: list[str] = Field(
        default_factory=list,
        description="Hypothesis IDs or descriptions contradicted if observation_if_true occurs.",
    )
    hypotheses_supported_if_false: list[str] = Field(
        default_factory=list,
        description="Hypothesis IDs or descriptions supported if observation_if_false occurs.",
    )
    hypotheses_contradicted_if_false: list[str] = Field(
        default_factory=list,
        description="Hypothesis IDs or descriptions contradicted if observation_if_false occurs.",
    )


class PlannedProbe(BaseModel):
    """A safe, typed diagnostic probe recommendation generated by the probe planner.

    STRICT INVARIANT:
    execution_authorization is initialized to PROPOSED_NOT_EXECUTED.
    No live network execution is performed by creating or returning this model.
    """

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(
        description="Deterministic identifier for this planned probe recommendation.",
        min_length=1,
    )
    incident_id: str = Field(
        description="Incident identifier this probe plan addresses.",
        min_length=1,
    )
    snapshot_id: str | None = Field(
        default=None,
        description="Observation snapshot reference if derived from a specific snapshot.",
    )
    probe_request: ProbeRequest = Field(
        description="Bounded, read-only probe request specification.",
    )
    probe_type: ProbeType = Field(
        description="Type of read-only diagnostic probe.",
    )
    source_router: str = Field(
        description="Origin router ID executing the read-only probe.",
        pattern=r"^R[1-9][0-9]*$",
    )
    target_router: str | None = Field(
        default=None,
        description="Target router ID if applicable.",
        pattern=r"^R[1-9][0-9]*$",
    )
    target_address: str | None = Field(
        default=None,
        description="Target IPv4 address if applicable.",
    )
    target_interface: str | None = Field(
        default=None,
        description="Target interface name if applicable.",
    )
    target_prefix: str | None = Field(
        default=None,
        description="Target IPv4 destination prefix if applicable.",
    )
    target_component: str = Field(
        description="Canonical topology component ID (router ID or link ID).",
        min_length=1,
    )
    related_hypothesis_id: str | None = Field(
        default=None,
        description="Candidate hypothesis ID this probe is designed to verify or refute.",
    )
    related_fault_type: str | None = Field(
        default=None,
        description="Fault type string of the related candidate hypothesis.",
    )
    selection_reason: str = Field(
        description="Plain-language explanation of why this probe was chosen.",
        min_length=1,
        max_length=512,
    )
    discriminating_outcomes: DiscriminatingOutcomes = Field(
        description="Expected observations and resulting hypothesis updates for outcomes.",
    )
    safety_status: ProbeSafetyStatus = Field(
        default=ProbeSafetyStatus.SAFE,
        description="Safety verification outcome against approved topology and safety policy.",
    )
    safety_rationale: str = Field(
        default="Read-only operation on approved topology component; zero state mutation.",
        description="Audit explanation of safety compliance.",
    )
    cost: ProbeCostEstimate = Field(
        default_factory=ProbeCostEstimate,
        description="Operational and network overhead estimate.",
    )
    priority_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Deterministic heuristic utility score [0.0, 1.0] representing diagnostic value."
        ),
    )
    ranking_rationale: str = Field(
        description="Transparent explanation of the priority score derivation.",
        min_length=1,
    )
    execution_authorization: ExecutionAuthorizationState = Field(
        default=ExecutionAuthorizationState.PROPOSED_NOT_EXECUTED,
        description="Strict boundary: all planned probes are PROPOSED / NOT EXECUTED.",
    )


class ProbePlanReport(BaseModel):
    """Comprehensive, auditable report produced by the safe active probe planning engine."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(
        description="Incident identifier.",
        min_length=1,
    )
    snapshot_id: str | None = Field(
        default=None,
        description="Observation snapshot reference.",
    )
    planned_at: datetime = Field(
        description="UTC timestamp when the probe plan was generated.",
    )
    planner_version: str = Field(
        description="Version string of the probe planning engine.",
        min_length=1,
    )
    total_probes_evaluated: int = Field(
        ge=0,
        description="Total number of potential candidate probes evaluated.",
    )
    recommended_probes: list[PlannedProbe] = Field(
        default_factory=list,
        description="Ordered list of safe, approved probe recommendations.",
    )
    rejected_probes: list[PlannedProbe] = Field(
        default_factory=list,
        description="Probes rejected due to safety policy violations or unknown components.",
    )
    unsupported_probes: list[PlannedProbe] = Field(
        default_factory=list,
        description="Probes rejected due to missing or unsupported collector capabilities.",
    )
    competing_hypotheses_considered: list[str] = Field(
        default_factory=list,
        description="List of candidate hypothesis IDs evaluated for discrimination.",
    )
    ambiguities_addressed: list[str] = Field(
        default_factory=list,
        description="List of diagnostic ambiguities analyzed (e.g. F2 router vs link).",
    )
    is_abstention: bool = Field(
        default=False,
        description=(
            "True if the planner deterministically determined no safe probe is needed or possible."
        ),
    )
    abstention_reason: str | None = Field(
        default=None,
        description="Human-readable explanation if the planner abstains from recommending probes.",
    )
    summary: str = Field(
        description="High-level human-readable summary of the probe planning analysis.",
        min_length=1,
    )

    @field_validator("planned_at", mode="before")
    @classmethod
    def validate_utc_aware(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("planned_at must be a timezone-aware UTC datetime")
        return v

