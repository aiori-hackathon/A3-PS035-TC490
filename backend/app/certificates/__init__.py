"""
NEXORA Auditable Evidence Certificate & Explainability System (Phase 09).

Consolidates:
- Original diagnosis outputs
- Supporting and contradictory evidence references
- Counterfactual verification verdicts and expectations
- Missing required observations and collector failures
- Safe proposed active next checks (strictly NOT EXECUTED)
- Snapshot provenance and cryptographic SHA-256 digest integrity
- Structured, human-readable root-cause explanations
"""

from __future__ import annotations

from app.certificates.explainer import ExplanationEngine
from app.certificates.generator import (
    CERTIFICATE_GENERATOR_VERSION,
    CertificateGenerator,
)
from app.certificates.integrity import (
    compute_snapshot_digest,
    verify_snapshot_integrity,
)
from app.schemas.certificate import (
    CERTIFICATE_SCHEMA_VERSION,
    AuditableEvidenceCertificate,
    EvidenceReference,
    EvidenceRole,
    IntegrityVerificationResult,
    ProvenanceIntegrityStatus,
    RootCauseExplanation,
)

__all__ = [
    "CERTIFICATE_GENERATOR_VERSION",
    "CERTIFICATE_SCHEMA_VERSION",
    "AuditableEvidenceCertificate",
    "CertificateGenerator",
    "EvidenceReference",
    "EvidenceRole",
    "ExplanationEngine",
    "IntegrityVerificationResult",
    "ProvenanceIntegrityStatus",
    "RootCauseExplanation",
    "compute_snapshot_digest",
    "verify_snapshot_integrity",
]
