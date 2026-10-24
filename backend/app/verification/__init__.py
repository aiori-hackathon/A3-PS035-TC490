"""
NEXORA Phase 07: Counterfactual Verification Engine.

Exports the core engine, expectation generator, and verification schemas.
"""

from __future__ import annotations

from app.schemas.counterfactual import (
    CounterfactualVerdict,
    CounterfactualVerificationResult,
    Criticality,
    EvaluatedExpectation,
    ExpectationCategory,
    ExpectedObservation,
    ObservationMatch,
    VerificationReport,
)
from app.verification.engine import (
    VERIFIER_VERSION,
    CounterfactualVerificationEngine,
)
from app.verification.expectations import ExpectationGenerator

__all__ = [
    "VERIFIER_VERSION",
    "CounterfactualVerdict",
    "CounterfactualVerificationEngine",
    "CounterfactualVerificationResult",
    "Criticality",
    "EvaluatedExpectation",
    "ExpectationCategory",
    "ExpectationGenerator",
    "ExpectedObservation",
    "ObservationMatch",
    "VerificationReport",
]
