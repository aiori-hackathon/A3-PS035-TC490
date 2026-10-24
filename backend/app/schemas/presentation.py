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

    ARCHIVED_REPLAY = "ARCHIVED_REPLAY"
    CANONICAL_SPECIFICATION = "CANONICAL_SPECIFICATION"
    LIVE_LAB_EMULATION = "LIVE_LAB_EMULATION"


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
    available_archived_scenarios: list[str] = Field(
        description="Available scenario keys for demo replay (e.g. ['baseline', 'F1', ...]).",
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
    captured_at: datetime
    record_count: int
    incident_ids: list[str]
    data_source: DataSourceMode = DataSourceMode.ARCHIVED_REPLAY
    is_live: bool = False


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


class SafeProbePlanResponse(BaseModel):
    """Read-only presentation plan of safe diagnostic probes."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    recommendations: list[ProbeRequest]
    safety_guardrail: str = Field(
        default="STRICT_READ_ONLY_GUARDED",
        description="Safety protocol state.",
    )
    execution_permitted: bool = Field(
        default=False,
        description="Execution is disabled until human authorization and dedicated backend exists.",
    )
    notes: list[str]


class DetailError(BaseModel):
    """Structured error envelope."""

    model_config = ConfigDict(extra="forbid")

    detail: str
    error_code: str
    component: str | None = None
