"""
NEXORA Auditable Evidence Certificate Schemas (Phase 09).

Defines typed Pydantic models for the consolidation of:
1. Original diagnosis
2. Supporting and contradictory evidence references
3. Counterfactual verification results
4. Missing required observations and collector failures
5. Safe active probe recommendations (Phase 08)
6. Provenance and cryptographic digest integrity
7. Structured, human-readable root-cause explanations
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.counterfactual import CounterfactualVerdict
from app.schemas.diagnosis import DiagnosisStatus
from app.schemas.hypothesis import FaultLocation, FaultType
from app.schemas.probe import PlannedProbe

CERTIFICATE_SCHEMA_VERSION = "phase09-evidence-certificate-v1.0"


class EvidenceRole(str, Enum):
    """Semantic role of an evidence observation in supporting or refuting a hypothesis."""

    SUPPORTING = "SUPPORTING"
    CONTRADICTORY = "CONTRADICTORY"
    COLLECTION_FAILURE = "COLLECTION_FAILURE"
    NEUTRAL_CONTEXT = "NEUTRAL_CONTEXT"


class ProvenanceIntegrityStatus(str, Enum):
    """Cryptographic and structural provenance audit outcome."""

    VERIFIED_AUTHENTIC = "VERIFIED_AUTHENTIC"
    VERIFIED_UNBOUND = "VERIFIED_UNBOUND"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    UNRESOLVED_REFERENCES = "UNRESOLVED_REFERENCES"
    INCOMPLETE_PROVENANCE = "INCOMPLETE_PROVENANCE"


class EvidenceReference(BaseModel):
    """A typed reference to an actual evidence record in the observation snapshot."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(
        description="Globally unique identifier of the referenced observation.",
        min_length=1,
    )
    source_router: str = Field(
        description="Origin router that generated or was polled for this evidence.",
        pattern=r"^R[1-9][0-9]*$",
    )
    source_interface: str | None = Field(
        default=None,
        description="Interface associated with this observation, if applicable.",
    )
    event_type: str = Field(
        description="Semantic event type label (e.g. 'INTERFACE_DOWN_OBSERVED').",
        min_length=1,
    )
    observed_at: datetime = Field(
        description="UTC timestamp when the event occurred at the device.",
    )
    role: EvidenceRole = Field(
        description="Diagnostic role of this evidence (SUPPORTING, CONTRADICTORY, etc.).",
    )
    summary: str = Field(
        description="Concise description of the observation.",
        max_length=512,
    )

    @field_validator("observed_at", mode="before")
    @classmethod
    def validate_utc_aware(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("observed_at must be a timezone-aware UTC datetime")
        return v


class IntegrityVerificationResult(BaseModel):
    """Integrity audit result verifying snapshot digest and evidence existence."""

    model_config = ConfigDict(extra="forbid")

    status: ProvenanceIntegrityStatus = Field(
        description="Categorical provenance verification status.",
    )
    is_authentic: bool = Field(
        description="True if snapshot digest matches expected provenance and references resolve.",
    )
    computed_digest: str | None = Field(
        default=None,
        description="Canonical SHA256 digest computed from the snapshot payload.",
    )
    expected_digest: str | None = Field(
        default=None,
        description="Expected SHA256 digest from binding / provenance artifact, if provided.",
    )
    source_run_id: str | None = Field(
        default=None,
        description="Run ID from capture binding, if available.",
    )
    total_evidence_records_in_snapshot: int = Field(
        ge=0,
        description="Total count of raw evidence records present in the snapshot.",
    )
    total_references_checked: int = Field(
        ge=0,
        description="Count of evidence references validated against snapshot.",
    )
    unresolved_reference_ids: list[str] = Field(
        default_factory=list,
        description="List of evidence IDs referenced by diagnosis but missing from snapshot.",
    )
    details: str = Field(
        description="Audit detail summary explaining the integrity status.",
        max_length=1024,
    )


class RootCauseExplanation(BaseModel):
    """Structured, human-readable explanation answering 8 canonical diagnostic questions."""

    model_config = ConfigDict(extra="forbid")

    what_happened: str = Field(
        description="Concise summary of the detected network defect or event.",
        max_length=1024,
    )
    where_located: str = Field(
        description="Identified component (router or link) where fault is located.",
        max_length=512,
    )
    why_selected: str = Field(
        description="Rationale explaining why the top hypothesis was selected over alternatives.",
        max_length=2048,
    )
    supporting_observations_summary: str = Field(
        description="Plain-language summary of supporting observations.",
        max_length=2048,
    )
    contradicting_observations_summary: str = Field(
        description="Plain-language summary of contradictory observations, or 'None.'",
        max_length=2048,
    )
    counterfactual_expectations_summary: str = Field(
        description="Summary of counterfactual expectations tested and their outcomes.",
        max_length=2048,
    )
    missing_evidence_summary: str = Field(
        description="Summary of expected observations that were absent or uncollected.",
        max_length=2048,
    )
    safe_next_checks_summary: str = Field(
        description="Summary of proposed read-only probe recommendations to reduce uncertainty.",
        max_length=2048,
    )
    full_text: str = Field(
        description="Bounded complete narrative combining all explanatory sections.",
        max_length=8192,
    )


class AuditableEvidenceCertificate(BaseModel):
    """Auditable, operator-facing evidence certificate consolidating diagnosis,

    verification, probe planning, provenance, and explanation.
    """

    model_config = ConfigDict(extra="forbid")

    certificate_id: str = Field(
        description="Unique deterministic certificate identifier.",
        min_length=1,
    )
    schema_version: str = Field(
        default=CERTIFICATE_SCHEMA_VERSION,
        description="Version string of the certificate schema.",
    )
    created_at: datetime = Field(
        description="UTC timestamp when this certificate was issued.",
    )
    snapshot_id: str | None = Field(
        default=None,
        description="Observation snapshot identifier.",
    )
    snapshot_digest: str | None = Field(
        default=None,
        description="Canonical SHA256 digest of the neutral observation snapshot.",
    )
    source_run_id: str | None = Field(
        default=None,
        description="Source run ID from binding / provenance, if available.",
    )
    incident_id: str = Field(
        description="Incident identifier covered by this certificate.",
        min_length=1,
    )
    selected_hypothesis_id: str | None = Field(
        default=None,
        description="Selected top-1 fault hypothesis ID, or None if abstained.",
    )
    fault_type: FaultType | str | None = Field(
        default=None,
        description="Fault classification type (e.g. LINK_FAILURE, ROUTER_FAILURE).",
    )
    fault_location: FaultLocation | str | None = Field(
        default=None,
        description="Network component location of the suspected fault.",
    )
    diagnosis_status: DiagnosisStatus | str = Field(
        description="Outcome status of the diagnostic engine (DIAGNOSED, AMBIGUOUS, etc.).",
    )
    original_heuristic_score: float | None = Field(
        default=None,
        description="Original heuristic rule_score in [0.0, 1.0] from Phase 06 diagnosis.",
    )
    score_interpretation: str = Field(
        default=(
            "Rule scores are dimensionless heuristic values in [0.0, 1.0] produced "
            "by deterministic rules. They are NOT calibrated statistical probabilities."
        ),
        description="Mandatory plain-language disclaimer regarding score interpretation.",
        max_length=1024,
    )
    counterfactual_verdict: CounterfactualVerdict | str | None = Field(
        default=None,
        description="Verdict from counterfactual verification (SUPPORTED, CONTRADICTED, etc.).",
    )
    counterfactual_verified: bool | None = Field(
        default=None,
        description="Boolean summary: True if SUPPORTED, False if CONTRADICTED, None otherwise.",
    )
    supporting_evidence_references: list[EvidenceReference] = Field(
        default_factory=list,
        description="Resolved references to observations supporting the diagnosis.",
    )
    contradictory_evidence_references: list[EvidenceReference] = Field(
        default_factory=list,
        description="Resolved references to observations contradicting the diagnosis.",
    )
    missing_required_observations: list[str] = Field(
        default_factory=list,
        description="Descriptions of expected observations that were absent or uncollected.",
    )
    collector_failures: list[str] = Field(
        default_factory=list,
        description="Descriptions of observation collection attempts that failed.",
    )
    evidence_coverage_pct: float = Field(
        ge=0.0,
        le=100.0,
        description="Percentage of planned evidence collection points successfully observed.",
    )
    sufficiency_status: str = Field(
        description="Sufficiency determination (e.g. 'SUFFICIENT', 'INSUFFICIENT', 'ABSTAINED').",
    )
    safe_probe_recommendations: list[PlannedProbe] = Field(
        default_factory=list,
        description="Ordered list of proposed safe next checks (strictly NOT EXECUTED).",
    )
    explanation: RootCauseExplanation = Field(
        description="Structured, human-readable root-cause explanation.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Explicit limitation disclosures and boundary statements.",
    )
    integrity_result: IntegrityVerificationResult = Field(
        description="Cryptographic and structural integrity verification result.",
    )

    @field_validator("created_at", mode="before")
    @classmethod
    def validate_utc_aware(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("created_at must be a timezone-aware UTC datetime")
        return v
