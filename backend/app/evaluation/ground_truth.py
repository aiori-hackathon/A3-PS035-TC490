"""
Ground-truth isolation module for the NEXORA evaluation system.

CRITICAL SECURITY BOUNDARY
===========================

This module is part of the OFFLINE EVALUATION SYSTEM ONLY.

FaultInjectionRecord instances MUST NEVER be:
  - Included in live EvidenceRecord objects
  - Passed as input to FaultHypothesis generation
  - Passed as input to DiagnosisResult inference
  - Passed as input to ProbeRequest selection logic
  - Exposed via any live API endpoint
  - Loaded into memory alongside active diagnostic inference code paths

ALLOWED USES (offline evaluation only):
  - Comparing a completed DiagnosisResult against its known ground truth
  - Computing evaluation metrics (Top-1 accuracy, Top-3 accuracy, abstention rate)
  - Training optional supervised ML models (Random Forest comparison only)
  - Generating benchmark reports in evaluation/reports/

INFORMATION FLOW DIAGRAM
========================

  [Lab Controller] ──fault_inject──> [Network Lab] ──observes──> [Collectors]
        │                                                               │
        └──────────> [FaultInjectionRecord]                     [EvidenceRecord]
                          │  (ISOLATED)                               │
                          │                                    [DiagnosisResult]
                          │                                           │
                          └──> [EvaluationEngine] <──────────────────┘
                                    │
                               [BenchmarkReport]

The two pipelines (ground-truth and diagnostic) MUST NOT share runtime state.
They only converge in the offline EvaluationEngine, which runs POST inference.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.hypothesis import FaultType


class FaultInjectionRecord(BaseModel):
    """Ground-truth label for a single fault injection scenario.

    ISOLATED: This model is exclusively for offline evaluation.
    It must never appear in any live inference data path.

    See module docstring for the full isolation contract.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(
        description="Unique run identifier for this experiment execution.",
        min_length=1,
    )
    scenario_id: str = Field(
        description="Scenario identifier (e.g. 'SCEN-01-L12-LINK-FAILURE'). "
        "Maps to the fault scenario taxonomy in topology.md.",
        min_length=1,
        max_length=64,
    )
    seeded_fault_type: FaultType = Field(
        description="The type of fault that was injected. "
        "GROUND-TRUTH LABEL — DO NOT expose to diagnostic inference.",
    )
    actual_fault_location_id: str = Field(
        description="Router ID (e.g. 'R3') or Link ID (e.g. 'L34') where the fault "
        "was injected. GROUND-TRUTH LABEL — DO NOT expose to diagnostic inference.",
        min_length=1,
        max_length=16,
    )
    injection_timestamp: datetime = Field(
        description="UTC timestamp when the fault was injected into the lab.",
    )
    recovery_timestamp: datetime | None = Field(
        default=None,
        description="UTC timestamp when the fault was recovered / cleared. "
        "None if the fault is still active.",
    )
    experiment_seed: int = Field(
        description="Random seed used to initialise any stochastic aspects of the "
        "fault injection (e.g. netem loss seed). Enables reproducibility.",
        ge=0,
    )
    lab_operator_notes: str | None = Field(
        default=None,
        description="Optional free-text notes from the lab operator.",
        max_length=2048,
    )

    @field_validator("injection_timestamp", "recovery_timestamp", mode="before")
    @classmethod
    def validate_utc_aware(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("FaultInjectionRecord timestamps must be timezone-aware UTC datetimes")
        return v

    def is_ground_truth_label_safe_for_inference(self) -> bool:
        """Always returns False.

        This method exists solely as a documentation guard. Ground-truth labels
        are NEVER safe to pass to the inference pipeline.
        Calling code should not use this method to conditionally expose labels.
        """
        return False
