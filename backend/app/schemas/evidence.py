"""
Evidence domain models for the NEXORA diagnostic system.

Evidence records represent raw or normalized observations collected from
the experimental five-node FRRouting / OSPFv2 network laboratory.

DESIGN INVARIANTS:
- A missing observation (NOT_COLLECTED) MUST NOT be interpreted as a failure.
  Missing data and observed failures are distinct states.
- All timestamps are timezone-aware UTC datetimes.
- Raw log text is preserved but never executed or interpreted as a command.
- Evidence records never contain ground-truth fault injection labels.
- source_type and collection_method fields provide full data provenance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class EvidenceSourceType(str, Enum):
    """Origin source category of a collected observation."""

    SYSLOG = "SYSLOG"
    SNMP_POLL = "SNMP_POLL"
    OSPF_API = "OSPF_API"
    ACTIVE_PING = "ACTIVE_PING"
    ROUTING_TABLE = "ROUTING_TABLE"
    INTERFACE_POLL = "INTERFACE_POLL"
    OPERATOR_ANNOTATION = "OPERATOR_ANNOTATION"
    ACTIVE_TRACEROUTE = "ACTIVE_TRACEROUTE"


class CollectionMethod(str, Enum):
    """How this evidence was collected."""

    PASSIVE_SYSLOG = "PASSIVE_SYSLOG"
    PERIODIC_POLL = "PERIODIC_POLL"
    TRIGGERED_PROBE = "TRIGGERED_PROBE"
    MANUAL_ENTRY = "MANUAL_ENTRY"


class ObservationStatus(str, Enum):
    """Collection status for an observation attempt.

    OBSERVED: Data was successfully collected.
    UNKNOWN: Status cannot be determined (device unreachable, partial data).
    NOT_COLLECTED: Collection was not attempted (outside scope or window).
    COLLECTION_FAILED: Collection was attempted but failed with an error.
    """

    OBSERVED = "OBSERVED"
    UNKNOWN = "UNKNOWN"
    NOT_COLLECTED = "NOT_COLLECTED"
    COLLECTION_FAILED = "COLLECTION_FAILED"


class SyslogSeverity(str, Enum):
    """Standard syslog severity levels (RFC 5424)."""

    EMERGENCY = "EMERGENCY"
    ALERT = "ALERT"
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    NOTICE = "NOTICE"
    INFO = "INFO"
    DEBUG = "DEBUG"


# ---------------------------------------------------------------------------
# Base evidence record
# ---------------------------------------------------------------------------


class EvidenceRecord(BaseModel):
    """Common fields shared by all evidence observations.

    This is the base contract. Specific evidence types extend this.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(
        description="Globally unique identifier for this evidence record.",
        min_length=1,
    )
    incident_id: str | None = Field(
        default=None,
        description="Incident ID this evidence is associated with. "
        "None if collected outside incident context (background polling).",
    )
    source_router: str = Field(
        description="Router ID that generated or was polled for this observation.",
        pattern=r"^R[1-9][0-9]*$",
    )
    source_interface: str | None = Field(
        default=None,
        description="Interface name this observation pertains to, if applicable.",
    )
    event_type: str = Field(
        description="Semantic event type label (e.g. 'OSPF_NEIGHBOUR_DOWN').",
        min_length=1,
        max_length=64,
    )
    observed_at: datetime = Field(
        description="UTC timestamp when the event occurred at the source "
        "(device clock, normalised to UTC).",
    )
    collected_at: datetime = Field(
        description="UTC timestamp when this observation was ingested by the collector.",
    )
    source_type: EvidenceSourceType = Field(
        description="Category of the data source.",
    )
    collection_method: CollectionMethod = Field(
        description="How this data was collected.",
    )
    collection_status: ObservationStatus = Field(
        default=ObservationStatus.OBSERVED,
        description="Whether collection succeeded or explains why data may be absent.",
    )
    raw_reference: str | None = Field(
        default=None,
        description="Opaque reference (e.g. log file path + line number) to the raw "
        "source data. Used for auditing only. MUST NOT be executed or parsed as code.",
        max_length=512,
    )

    @field_validator("observed_at", "collected_at", mode="after")
    @classmethod
    def validate_utc_aware(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError(
                f"Timestamps must be timezone-aware UTC datetimes. Got naive datetime: {v!r}"
            )
        return v.astimezone(UTC)


# ---------------------------------------------------------------------------
# Specific evidence types
# ---------------------------------------------------------------------------


class SyslogEvent(EvidenceRecord):
    """A single syslog message emitted by an FRRouting process.

    The raw_message field is stored as an opaque string for auditing only.
    It MUST NOT be parsed as a command, executed, or used to construct
    queries without sanitisation.
    """

    model_config = ConfigDict(extra="forbid")

    severity: SyslogSeverity = Field(
        description="Syslog severity level.",
    )
    process_name: str = Field(
        description="FRR daemon that emitted the log (e.g. 'ospfd', 'zebra').",
        max_length=32,
    )
    message_id: str | None = Field(
        default=None,
        description="Structured syslog message ID if available.",
        max_length=64,
    )
    raw_message: str = Field(
        description="Original log line text. Stored for audit. Not executed.",
        max_length=4096,
    )


class InterfaceObservation(EvidenceRecord):
    """A polled observation of a network interface state."""

    model_config = ConfigDict(extra="forbid")

    observed_status: str = Field(
        description="Observed interface status string from the device "
        "(e.g. 'up', 'down', 'admin-down').",
        max_length=32,
    )
    speed_mbps: int | None = Field(
        default=None,
        ge=0,
        description="Observed link speed in Mbps. None if not reported.",
    )
    error_count: int | None = Field(
        default=None,
        ge=0,
        description="Interface error counter at time of observation. None if not reported.",
    )


class OSPFObservation(EvidenceRecord):
    """An observation of OSPF adjacency state for a specific neighbour."""

    model_config = ConfigDict(extra="forbid")

    neighbour_router_id: str = Field(
        description="OSPF Router-ID of the observed neighbour (dotted decimal).",
    )
    neighbour_address: str = Field(
        description="IP address of the observed OSPF neighbour interface.",
    )
    adjacency_state: str = Field(
        description="OSPF adjacency state string as reported by FRR (e.g. 'Full', 'Down', 'Init').",
        max_length=32,
    )
    dead_timer_remaining_s: float | None = Field(
        default=None,
        ge=0.0,
        description="Seconds remaining on the OSPF dead timer. None if not available.",
    )

    observed_interface_config: dict[str, Any] | None = Field(
        default=None,
        description="Actual FRR show ip ospf interface json entry; never expected configuration.",
    )
    interface_config_observed_at: datetime | None = None


class PingAttemptFailure(EvidenceRecord):
    """An attempted probe with no measured statistics; requests are not results."""

    target_address: str
    source_address: str | None = None
    probe_source: str
    requested_packets: int = Field(ge=1, le=20)
    collection_status: Literal[ObservationStatus.COLLECTION_FAILED] = (
        ObservationStatus.COLLECTION_FAILED
    )


class PingMeasurement(EvidenceRecord):
    """Result of a bounded diagnostic ICMP ping probe.

    Probes are strictly read-only and bounded (see probe.py for request contract).
    Measured zero replies retain the actual transmission/loss counts. Execution
    without statistics produces PingAttemptFailure, never fabricated measurements.
    No response alone does not establish a router or link failure.
    """

    model_config = ConfigDict(extra="forbid")

    target_address: str = Field(
        description="IPv4 address or loopback address that was pinged.",
        max_length=45,
    )
    packets_sent: int = Field(
        ge=1,
        le=1000,
        description="Number of ICMP echo requests sent.",
    )
    packets_received: int = Field(
        ge=0,
        description="Number of ICMP echo replies received.",
    )
    packet_loss_pct: float = Field(
        ge=0.0,
        le=100.0,
        description="Packet loss percentage. Must be in [0.0, 100.0].",
    )
    rtt_min_ms: float | None = Field(
        default=None,
        ge=0.0,
        description="Minimum round-trip time in milliseconds. None if all packets lost.",
    )
    rtt_avg_ms: float | None = Field(
        default=None,
        ge=0.0,
        description="Average round-trip time in milliseconds. None if all packets lost.",
    )
    rtt_max_ms: float | None = Field(
        default=None,
        ge=0.0,
        description="Maximum round-trip time in milliseconds. None if all packets lost.",
    )
    probe_source: str = Field(
        description="Router ID that executed this probe.",
        pattern=r"^R[1-9][0-9]*$",
    )

    # Additive fields: legacy observations keep None rather than invented values.
    packets_lost: int | None = Field(default=None, ge=0)
    source_address: str | None = None
    rtt_unit: Literal["ms"] = "ms"
    rtt_mdev_ms: float | None = Field(default=None, ge=0)

    @field_validator("packets_received")
    @classmethod
    def validate_received_le_sent(cls, v: int, info: Any) -> int:
        sent = info.data.get("packets_sent")
        if sent is not None and v > sent:
            raise ValueError(f"packets_received ({v}) cannot exceed packets_sent ({sent})")
        return v

    @field_validator("packet_loss_pct")
    @classmethod
    def validate_loss_consistency(cls, v: float, info: Any) -> float:
        sent = info.data.get("packets_sent")
        received = info.data.get("packets_received")
        if sent is not None and received is not None and sent > 0:
            expected_loss = round(100.0 * (sent - received) / sent, 1)
            reported_loss = round(v, 1)
            # Allow ±1% tolerance for rounding
            if abs(expected_loss - reported_loss) > 1.0:
                raise ValueError(
                    f"packet_loss_pct {v} is inconsistent with "
                    f"sent={sent}, received={received} "
                    f"(expected ~{expected_loss}%)"
                )
        return v


class RouteObservation(EvidenceRecord):
    """An observation of a single route entry in a router's RIB."""

    model_config = ConfigDict(extra="forbid")

    destination_prefix: str = Field(
        description="Destination network prefix (e.g. '192.168.255.3/32').",
    )
    next_hop_address: str | None = Field(
        default=None,
        description="Next-hop IPv4 address. None for directly connected or null routes.",
    )
    next_hop_interface: str | None = Field(
        default=None,
        description="Outgoing interface for this route. None if not determinable.",
    )
    route_type: str = Field(
        description=(
            "Route protocol type as reported by FRR (e.g. 'O' for OSPF, 'C' for connected)."
        ),
        max_length=8,
    )
    metric: int | None = Field(
        default=None,
        ge=0,
        description="Route metric / cost. None if not reported.",
    )
    is_present: bool = Field(
        description="True if this route was present in the RIB at observation time. "
        "False if it was expected but absent.",
    )


class TracerouteHop(BaseModel):
    """A single hop observed in an active traceroute probe."""

    model_config = ConfigDict(extra="forbid")

    hop_number: int = Field(
        ge=1,
        description="Hop index, 1-based.",
    )
    hop_address: str | None = Field(
        default=None,
        description="IP address of responding router interface. None if unresponsive.",
    )
    rtt_ms: float | None = Field(
        default=None,
        ge=0.0,
        description="Round-trip time in milliseconds. None if unresponsive.",
    )
    is_unreachable: bool = Field(
        default=False,
        description="True if hop timed out or ICMP unreachable.",
    )


class TracerouteObservation(EvidenceRecord):
    """Result of a bounded diagnostic traceroute probe."""

    model_config = ConfigDict(extra="forbid")

    target_address: str = Field(
        description="Destination IPv4 address that was traced.",
        max_length=45,
    )
    probe_source: str = Field(
        description="Router ID that executed this traceroute.",
        pattern=r"^R[1-9][0-9]*$",
    )
    hops: list[TracerouteHop] = Field(
        default_factory=list,
        description="Observed hops along the path.",
    )
    total_hops: int = Field(
        default=0,
        ge=0,
        description="Number of observed hops.",
    )
    destination_reached: bool = Field(
        default=False,
        description="Whether the target destination was reached.",
    )
