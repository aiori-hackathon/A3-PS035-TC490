"""
NEXORA Fault Injection Domain Models
Team: A3-PS035-TC490 | Problem Statement: PS-035

Typed schemas and contracts for controlled network fault injection experiments.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.hypothesis import FaultLocation, FaultLocationKind, FaultType


class ScenarioID(str, Enum):
    """The five allowed fault scenario identifiers for Phase 03."""

    F1_LINK_FAILURE = "F1_LINK_FAILURE"
    F2_ROUTER_FAILURE = "F2_ROUTER_FAILURE"
    F3_OSPF_CONFIG_MISMATCH = "F3_OSPF_CONFIG_MISMATCH"
    F4_PACKET_LOSS = "F4_PACKET_LOSS"
    F5_HIGH_LATENCY = "F5_HIGH_LATENCY"


class ExperimentState(str, Enum):
    """Lifecycle state machine for a fault injection experiment."""

    IDLE = "IDLE"
    PRE_VALIDATING = "PRE_VALIDATING"
    ACTIVE = "ACTIVE"
    OBSERVING = "OBSERVING"
    RESTORING = "RESTORING"
    RECOVERED = "RECOVERED"
    FAILED = "FAILED"


class ExperimentOutcome(str, Enum):
    """Outcome of an experiment run."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


# Approved targets & invariants
APPROVED_ROUTERS = {"R1", "R2", "R3", "R4", "R5"}
APPROVED_ROUTER_CONTAINERS = {
    "nexora-r1": "R1",
    "nexora-r2": "R2",
    "nexora-r3": "R3",
    "nexora-r4": "R4",
    "nexora-r5": "R5",
}
ROUTER_TO_CONTAINER = {v: k for k, v in APPROVED_ROUTER_CONTAINERS.items()}

APPROVED_LINKS = {"L12", "L23", "L34", "L45", "L51"}
APPROVED_DATA_INTERFACES = {"eth1", "eth2"}
FORBIDDEN_INTERFACES = {"eth0", "mgmt", "mgmt0", "lo"}

LINK_ENDPOINTS = {
    "L12": {
        "router_a": "nexora-r1", "interface_a": "eth1", "ip_a": "10.0.12.1",
        "router_b": "nexora-r2", "interface_b": "eth1", "ip_b": "10.0.12.2",
    },
    "L23": {
        "router_a": "nexora-r2", "interface_a": "eth2", "ip_a": "10.0.23.1",
        "router_b": "nexora-r3", "interface_b": "eth1", "ip_b": "10.0.23.2",
    },
    "L34": {
        "router_a": "nexora-r3", "interface_a": "eth2", "ip_a": "10.0.34.1",
        "router_b": "nexora-r4", "interface_b": "eth1", "ip_b": "10.0.34.2",
    },
    "L45": {
        "router_a": "nexora-r4", "interface_a": "eth2", "ip_a": "10.0.45.1",
        "router_b": "nexora-r5", "interface_b": "eth1", "ip_b": "10.0.45.2",
    },
    "L51": {
        "router_a": "nexora-r5", "interface_a": "eth2", "ip_a": "10.0.15.1",
        "router_b": "nexora-r1", "interface_b": "eth2", "ip_b": "10.0.15.2",
    },
}


class ActiveFaultLock(BaseModel):
    """Persisted lock model to prevent concurrent experiments."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    scenario_id: ScenarioID
    fault_type: FaultType
    target: str
    injected_details: dict[str, Any]
    state: ExperimentState
    started_at: datetime

    @field_validator("started_at", mode="before")
    @classmethod
    def validate_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class NetworkObservation(BaseModel):
    """Snapshot of network state (neighbors, routes, reachability) at a point in time."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    container_health: dict[str, bool]
    ospf_neighbors: dict[str, dict[str, str]]  # container -> {neighbor_rid: state}
    ospf_routes_count: dict[str, int]          # container -> route count
    loopback_pings: dict[str, bool]            # "r1->r2" -> reachable
    probe_metrics: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class ExperimentRecord(BaseModel):
    """Deterministic, structured experiment report for a fault injection run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    scenario_id: ScenarioID
    fault_type: FaultType
    actual_fault_location: FaultLocation
    affected_components: list[str]
    parameters: dict[str, Any]
    injection_timestamp: datetime
    observation_timestamps: list[datetime]
    recovery_timestamp: datetime | None = None
    baseline_observations: NetworkObservation
    fault_state_observations: NetworkObservation
    restoration_observations: NetworkObservation | None = None
    experiment_outcome: ExperimentOutcome
    errors: list[str] = Field(default_factory=list)

    @field_validator("injection_timestamp", "recovery_timestamp", mode="before")
    @classmethod
    def validate_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @field_validator("observation_timestamps", mode="before")
    @classmethod
    def validate_utc_list(cls, v: Any) -> Any:
        if isinstance(v, list):
            res = []
            for item in v:
                if isinstance(item, datetime) and item.tzinfo is None:
                    res.append(item.replace(tzinfo=timezone.utc))
                else:
                    res.append(item)
            return res
        return v
