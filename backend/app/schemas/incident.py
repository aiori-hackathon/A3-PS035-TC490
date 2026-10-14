"""
Incident domain models for the NEXORA diagnostic system.

An Incident is a correlated collection of network alarms and observations
that may share a common root cause. An incident groups evidence records
and drives the diagnostic lifecycle.

IMPORTANT: An incident represents a diagnostic hypothesis container.
It does NOT presume that every alarm represents a separate root fault.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IncidentStatus(str, Enum):
    """Lifecycle status of a diagnostic incident."""

    OPEN = "OPEN"
    COLLECTING = "COLLECTING"
    DIAGNOSING = "DIAGNOSING"
    DIAGNOSED = "DIAGNOSED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class IncidentEvidenceReference(BaseModel):
    """A lightweight reference linking an incident to an evidence record.

    We keep this as a reference (ID only) rather than embedding the full
    EvidenceRecord to avoid duplication and circular imports.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(
        description="Unique identifier of the referenced EvidenceRecord.",
        min_length=1,
    )
    evidence_type: str = Field(
        description="Type tag of the evidence (e.g. 'SyslogEvent', 'PingMeasurement').",
        min_length=1,
    )
    added_at: datetime = Field(
        description="UTC timestamp when this evidence was linked to the incident.",
    )


class Incident(BaseModel):
    """A correlated set of network observations forming a diagnostic incident.

    Incidents collect evidence from multiple sources (syslog, OSPF, ping)
    within a defined time window. The diagnostic engine processes an incident
    to produce a DiagnosisResult.

    An incident does NOT embed ground-truth fault labels. The evaluation
    module matches diagnosis results against ground-truth post hoc.
    """

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(
        description="Globally unique incident identifier.",
        min_length=1,
    )
    detected_at: datetime = Field(
        description="UTC timestamp of the first alarm that triggered this incident.",
    )
    collection_window_start: datetime = Field(
        description="Start of the evidence collection window (UTC).",
    )
    collection_window_end: datetime | None = Field(
        default=None,
        description="End of the evidence collection window (UTC). "
        "None if collection is still in progress.",
    )
    resolved_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when the incident was resolved. None if still open.",
    )
    status: IncidentStatus = Field(
        default=IncidentStatus.OPEN,
        description="Current lifecycle status of this incident.",
    )
    topology_snapshot_id: str = Field(
        description="ID of the topology snapshot active when this incident was detected.",
        min_length=1,
    )
    potentially_affected_routers: list[str] = Field(
        default_factory=list,
        description="Router IDs that initial alarms implicate. "
        "This is a candidate list only, not a diagnosis.",
    )
    potentially_affected_links: list[str] = Field(
        default_factory=list,
        description="Link IDs that initial alarms implicate. "
        "This is a candidate list only, not a diagnosis.",
    )
    evidence_references: list[IncidentEvidenceReference] = Field(
        default_factory=list,
        description="All evidence records collected for this incident.",
    )
    notes: str | None = Field(
        default=None,
        description="Optional operator notes attached to this incident.",
        max_length=2048,
    )

    @model_validator(mode="after")
    def validate_window_order(self) -> Incident:
        if (
            self.collection_window_end is not None
            and self.collection_window_end < self.collection_window_start
        ):
            raise ValueError(
                "collection_window_end must be >= collection_window_start"
            )
        return self

    @model_validator(mode="after")
    def validate_resolved_after_detected(self) -> Incident:
        if self.resolved_at is not None and self.resolved_at < self.detected_at:
            raise ValueError("resolved_at must be >= detected_at")
        return self
