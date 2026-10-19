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
