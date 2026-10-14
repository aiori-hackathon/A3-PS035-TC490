"""
Diagnosis result domain models for the NEXORA diagnostic system.

A DiagnosisResult is the output of the diagnostic pipeline for a given Incident.
It packages ranked FaultHypotheses with an EvidenceCertificate that documents
evidence provenance, sufficiency assessment, and audit trail.

DESIGN INVARIANTS:
- DiagnosisResult.top1_hypothesis and top3_hypotheses are derived from
  ranked_hypotheses. They are NEVER populated from ground-truth labels.
- INSUFFICIENT_EVIDENCE status means the engine has explicitly abstained.
  This is valid and expected behaviour, not an error.
- rule_score values are heuristic, not calibrated probabilities.
  EvidenceCertificate.score_interpretation makes this explicit.
- No remediation action may be triggered from a DiagnosisResult.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.hypothesis import FaultHypothesis

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DiagnosisStatus(str, Enum):
    """Overall outcome of a diagnostic run for an incident.

    DIAGNOSED: A confident top-1 hypothesis was produced.
    AMBIGUOUS: Multiple competing hypotheses remain with insufficient separation.
    INSUFFICIENT_EVIDENCE: Evidence collection was too incomplete to diagnose.
      This is a valid abstention, not a system failure.
    """

    DIAGNOSED = "DIAGNOSED"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------------------
# Ranked hypothesis wrapper
# ---------------------------------------------------------------------------


class RankedHypothesis(BaseModel):
    """A FaultHypothesis annotated with its rank within a diagnosis run."""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(
        ge=1,
        description="Rank of this hypothesis within the diagnosis (1 = highest scoring).",
    )
    hypothesis: FaultHypothesis = Field(
        description="The ranked fault hypothesis.",
    )


# ---------------------------------------------------------------------------
# Evidence certificate
# ---------------------------------------------------------------------------


class EvidenceCertificate(BaseModel):
    """An auditable summary of the evidence used to produce a DiagnosisResult.

    The certificate documents what was collected, what was missing, whether
    collection was sufficient, and explicitly states the score interpretation.

    EvidenceCertificates support post-hoc audit and verification. They do NOT
    contain ground-truth labels and are safe to expose in operator-facing views.
    """

    model_config = ConfigDict(extra="forbid")

    certificate_id: str = Field(
        description="Unique identifier for this certificate.",
        min_length=1,
    )
    incident_id: str = Field(
        description="Incident this certificate covers.",
        min_length=1,
    )
    generated_at: datetime = Field(
        description="UTC timestamp when this certificate was generated.",
    )
    total_evidence_count: int = Field(
        ge=0,
        description="Total number of EvidenceRecords considered during diagnosis.",
    )
    supporting_evidence_count: int = Field(
        ge=0,
        description="Number of evidence records supporting the top-1 hypothesis.",
    )
    contradictory_evidence_count: int = Field(
        ge=0,
        description="Number of evidence records contradicting the top-1 hypothesis.",
    )
    missing_evidence_descriptions: list[str] = Field(
        default_factory=list,
        description="Descriptions of observations that were absent but relevant.",
    )
    evidence_sufficiency_met: bool = Field(
        description="True if the engine determined that collected evidence "
        "meets the sufficiency threshold for a confident diagnosis.",
    )
    score_interpretation: str = Field(
        default=(
            "Rule scores are dimensionless heuristic values in [0.0, 1.0] produced "
            "by deterministic rules. They are NOT calibrated statistical probabilities."
        ),
        description="Mandatory plain-language note clarifying what rule_score means.",
        max_length=1024,
    )
    collection_coverage_pct: float = Field(
        ge=0.0,
        le=100.0,
        description="Percentage of planned evidence collection points that were "
        "successfully observed.",
    )
    reasoning_summary: str = Field(
        description="Human-readable summary of the key reasoning steps.",
        max_length=4096,
    )

    @field_validator("generated_at", mode="before")
    @classmethod
    def validate_utc_aware(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("generated_at must be a timezone-aware UTC datetime")
        return v


# ---------------------------------------------------------------------------
# Diagnosis result
# ---------------------------------------------------------------------------


class DiagnosisResult(BaseModel):
    """The complete output of the NEXORA diagnostic engine for one Incident.

    A DiagnosisResult:
    - MUST be produced only from evidence collected during the incident window.
    - MUST NOT reference or use ground-truth FaultInjectionRecord labels.
    - MAY abstain (status=INSUFFICIENT_EVIDENCE) when evidence is incomplete.
    - MUST document its engine version for reproducibility.
    - MUST attach an EvidenceCertificate for auditability.
    """

    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(
        description="Globally unique identifier for this diagnosis result.",
        min_length=1,
    )
    incident_id: str = Field(
        description="The incident this result diagnoses.",
        min_length=1,
    )
    diagnosed_at: datetime = Field(
        description="UTC timestamp when diagnosis was completed.",
    )
    engine_version: str = Field(
        description="Version string of the diagnostic engine that produced this result. "
        "Used for reproducibility and comparison.",
        min_length=1,
        max_length=32,
    )
    status: DiagnosisStatus = Field(
        description="Overall diagnosis outcome.",
    )
    ranked_hypotheses: list[RankedHypothesis] = Field(
        default_factory=list,
        description="All candidate hypotheses, ordered by rank (rank=1 first).",
    )
    top1_hypothesis: FaultHypothesis | None = Field(
        default=None,
        description="The highest-ranked hypothesis. None if status is INSUFFICIENT_EVIDENCE.",
    )
    top3_hypotheses: list[FaultHypothesis] = Field(
        default_factory=list,
        description="Up to three highest-ranked hypotheses. May be fewer if "
        "fewer candidates were generated.",
        max_length=3,
    )
    evidence_certificate: EvidenceCertificate = Field(
        description="Auditable certificate documenting evidence provenance and sufficiency.",
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Plain-language descriptions of information that would improve "
        "diagnostic confidence.",
    )

    @field_validator("diagnosed_at", mode="before")
    @classmethod
    def validate_utc_aware(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("diagnosed_at must be a timezone-aware UTC datetime")
        return v

    @model_validator(mode="after")
    def validate_top1_consistency(self) -> DiagnosisResult:
        """top1_hypothesis must be None iff status is INSUFFICIENT_EVIDENCE."""
        if self.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE:
            if self.top1_hypothesis is not None:
                raise ValueError(
                    "top1_hypothesis must be None when status is INSUFFICIENT_EVIDENCE"
                )
        return self

    @model_validator(mode="after")
    def validate_top3_subset_of_ranked(self) -> DiagnosisResult:
        """top3 hypothesis IDs must appear in ranked_hypotheses."""
        ranked_ids = {rh.hypothesis.hypothesis_id for rh in self.ranked_hypotheses}
        for h in self.top3_hypotheses:
            if h.hypothesis_id not in ranked_ids:
                raise ValueError(
                    f"top3_hypothesis {h.hypothesis_id!r} not found in ranked_hypotheses"
                )
        return self

    @model_validator(mode="after")
    def validate_ranked_hypotheses_ordering(self) -> DiagnosisResult:
        """Ranked hypotheses must have sequential, non-duplicate ranks starting at 1."""
        if not self.ranked_hypotheses:
            return self
        ranks = [rh.rank for rh in self.ranked_hypotheses]
        expected = list(range(1, len(ranks) + 1))
        if sorted(ranks) != expected:
            raise ValueError(
                f"ranked_hypotheses ranks must be sequential starting at 1, got {sorted(ranks)}"
            )
        return self
