"""
Counterfactual verification schemas for the NEXORA diagnostic engine.

Defines the domain models, expectation categories, and structured reports
for testing "what network observations would we expect if this hypothesis were true?"
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.hypothesis import FaultHypothesis
from app.schemas.probe import ProbeRequest


class CounterfactualVerdict(str, Enum):
    """Deterministic verdict of counterfactual hypothesis verification.

    SUPPORTED: All required expectations matched observed evidence; no contradictions.
    CONTRADICTED: One or more key expectations directly contradicted by evidence.
    INSUFFICIENT_EVIDENCE: Key expectations could not be evaluated due to missing/failed telemetry.
    INCONCLUSIVE: Observations are ambiguous, conflicting, or non-overlapping in time.
    """

    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INCONCLUSIVE = "INCONCLUSIVE"


class ExpectationCategory(str, Enum):
    """Network observation domain tested by the expectation."""

    INTERFACE_STATE = "INTERFACE_STATE"
    OSPF_ADJACENCY = "OSPF_ADJACENCY"
    PACKET_LOSS = "PACKET_LOSS"
    RTT_LATENCY = "RTT_LATENCY"
    ROUTER_AVAILABILITY = "ROUTER_AVAILABILITY"
    CONFIGURATION_PARAM = "CONFIGURATION_PARAM"


class Criticality(str, Enum):
    """Whether an expectation is mandatory for the fault hypothesis."""

    REQUIRED = "REQUIRED"
    CONFIRMATORY = "CONFIRMATORY"


class ObservationMatch(str, Enum):
    """Outcome of comparing a single expectation against evidence."""

    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    MISSING = "MISSING"
    INCONCLUSIVE = "INCONCLUSIVE"


class ExpectedObservation(BaseModel):
    """A specific network condition expected under a given hypothesis."""

    model_config = ConfigDict(extra="forbid")

    expectation_id: str = Field(
        description="Unique identifier for this expected observation.",
        min_length=1,
    )
    category: ExpectationCategory = Field(
        description="Observation category (interface, ospf, ping loss, rtt, etc.).",
    )
    target_component: str = Field(
        description="Target router or link identifier.",
        min_length=1,
    )
    target_endpoint: str | None = Field(
        default=None,
        description="Specific interface or neighbor address if applicable.",
    )
    expected_condition: str = Field(
        description=(
            "Plain-language description of what should be observed (e.g. 'interface eth1 DOWN')."
        ),
        min_length=1,
    )
    criticality: Criticality = Field(
        default=Criticality.REQUIRED,
        description="REQUIRED for hypothesis plausibility; CONFIRMATORY adds confidence.",
    )
    rationale: str = Field(
        description="Causal explanation of why this observation is expected under the hypothesis.",
        min_length=1,
    )


class EvaluatedExpectation(BaseModel):
    """Evaluation of one expected observation against actual evidence."""

    model_config = ConfigDict(extra="forbid")

    expectation: ExpectedObservation = Field(
        description="The expectation that was evaluated.",
    )
    match_status: ObservationMatch = Field(
        description="Outcome of comparing expectation against evidence.",
    )
    supporting_evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence IDs matching and supporting this expectation.",
    )
    contradicting_evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence IDs directly refuting this expectation.",
    )
    explanation: str = Field(
        description="Plain-language summary of observed evidence vs expectation.",
        min_length=1,
    )


class CounterfactualVerificationResult(BaseModel):
    """The counterfactual verification outcome for a single fault hypothesis."""

    model_config = ConfigDict(extra="forbid")

    hypothesis: FaultHypothesis = Field(
        description="The fault hypothesis being verified.",
    )
    verdict: CounterfactualVerdict = Field(
        description="Overall verification verdict.",
    )
    counterfactual_verified: bool | None = Field(
        default=None,
        description="Boolean summary: True if SUPPORTED, False if CONTRADICTED, None otherwise.",
    )
    evaluated_expectations: list[EvaluatedExpectation] = Field(
        default_factory=list,
        description="Detailed evaluation for each generated expectation.",
    )
    supporting_evidence_ids: list[str] = Field(
        default_factory=list,
        description="All unique evidence IDs supporting this hypothesis.",
    )
    contradictory_evidence_ids: list[str] = Field(
        default_factory=list,
        description="All unique evidence IDs contradicting this hypothesis.",
    )
    missing_evidence_descriptions: list[str] = Field(
        default_factory=list,
        description="Descriptions of expected evidence that was absent or failed collection.",
    )
    explanation: str = Field(
        description="Clear, explainable reasoning trace for the verdict.",
        min_length=1,
    )
    recommended_probes: list[ProbeRequest] = Field(
        default_factory=list,
        description="Safe, bounded probes recommended to resolve missing or ambiguous evidence.",
    )

    def format_text_block(self) -> str:
        """Render a clean, human-readable verification trace block."""
        exp_lines = [f"  - {e.expectation.expected_condition}" for e in self.evaluated_expectations]
        obs_lines = [
            f"  - {e.explanation}"
            for e in self.evaluated_expectations
            if e.match_status == ObservationMatch.SUPPORTED
        ]
        if not obs_lines:
            obs_lines = ["  - None matching expected conditions"]
        contr_lines = [
            f"  - {e.explanation}"
            for e in self.evaluated_expectations
            if e.match_status == ObservationMatch.CONTRADICTED
        ]
        if not contr_lines:
            contr_lines = ["  - None."]
        missing_lines = [f"  - {m}" for m in self.missing_evidence_descriptions]
        if not missing_lines:
            missing_lines = ["  - None."]

        lines = [
            "Hypothesis:",
            (
                f"  {self.hypothesis.fault_type.value} at "
                f"{self.hypothesis.fault_location.component_id}"
            ),
            "",
            "Expected:",
            *exp_lines,
            "",
            "Observed:",
            *obs_lines,
            "",
            "Contradictions:",
            *contr_lines,
            "",
            "Missing Evidence:",
            *missing_lines,
            "",
            "Verdict:",
            f"  {self.verdict.value}",
            "",
            "Explanation:",
            f"  {self.explanation}",
        ]
        if self.recommended_probes:
            lines.extend(
                [
                    "",
                    "Recommended Safe Next Probes:",
                    *[
                        f"  - [{p.probe_type.value}] on {p.source_router}: {p.selection_reason}"
                        for p in self.recommended_probes
                    ],
                ]
            )
        return "\n".join(lines)


class VerificationReport(BaseModel):
    """Complete counterfactual verification report for an incident diagnosis."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(
        description="Identifier of the diagnosed incident.",
        min_length=1,
    )
    verified_at: datetime = Field(
        description="UTC timestamp when verification was executed.",
    )
    engine_version: str = Field(
        description="Version string of the verification engine.",
        min_length=1,
    )
    top_hypotheses_verifications: list[CounterfactualVerificationResult] = Field(
        default_factory=list,
        description="Counterfactual verification results for top ranked hypotheses.",
    )
    competing_hypotheses_verifications: list[CounterfactualVerificationResult] = Field(
        default_factory=list,
        description="Verification results for unranked/pruned competing alternatives.",
    )
    summary: str = Field(
        description="High-level human-readable verification summary.",
        min_length=1,
        max_length=4096,
    )

    @field_validator("verified_at", mode="before")
    @classmethod
    def validate_utc_aware(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("verified_at must be a timezone-aware UTC datetime")
        return v
