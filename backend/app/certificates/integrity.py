"""
NEXORA Snapshot Provenance and Cryptographic Integrity Verifier (Phase 09).

Computes canonical snapshot SHA-256 digests and validates:
1. Canonical snapshot digest matching capture binding / provenance.
2. Complete resolution of evidence references against raw snapshot observations.
3. Separation between authentic verified provenance, unbound valid structure, and mismatches.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.schemas.certificate import (
    IntegrityVerificationResult,
    ProvenanceIntegrityStatus,
)


def compute_snapshot_digest(snapshot: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 digest of canonical snapshot JSON.

    Canonical format matches app.evaluation.timing.snapshot_digest:
    sorted keys, compact separators (",", ":"), UTF-8 encoding.
    """
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_snapshot_integrity(
    snapshot: dict[str, Any] | None,
    referenced_evidence_ids: list[str],
    expected_digest: str | None = None,
    source_run_id: str | None = None,
) -> IntegrityVerificationResult:
    """Verify cryptographic digest and evidence reference resolution for a snapshot.

    Fails closed if snapshot payload is missing, malformed, or references cannot be resolved.
    """
    if not isinstance(snapshot, dict):
        return IntegrityVerificationResult(
            status=ProvenanceIntegrityStatus.INCOMPLETE_PROVENANCE,
            is_authentic=False,
            computed_digest=None,
            expected_digest=expected_digest,
            source_run_id=source_run_id,
            total_evidence_records_in_snapshot=0,
            total_references_checked=len(referenced_evidence_ids),
            unresolved_reference_ids=list(referenced_evidence_ids),
            details="Snapshot payload is absent or not a dictionary.",
        )

    raw_records = snapshot.get("evidence_records")
    if not isinstance(raw_records, list):
        return IntegrityVerificationResult(
            status=ProvenanceIntegrityStatus.INCOMPLETE_PROVENANCE,
            is_authentic=False,
            computed_digest=None,
            expected_digest=expected_digest,
            source_run_id=source_run_id,
            total_evidence_records_in_snapshot=0,
            total_references_checked=len(referenced_evidence_ids),
            unresolved_reference_ids=list(referenced_evidence_ids),
            details="Snapshot missing evidence_records list.",
        )

    present_ids: set[str] = set()
    for rec in raw_records:
        if isinstance(rec, dict) and "evidence_id" in rec:
            present_ids.add(str(rec["evidence_id"]))
        elif hasattr(rec, "evidence_id"):
            present_ids.add(str(rec.evidence_id))

    unresolved = [ref for ref in referenced_evidence_ids if ref not in present_ids]
    computed = compute_snapshot_digest(snapshot)

    # Check unresolved references first
    if unresolved:
        return IntegrityVerificationResult(
            status=ProvenanceIntegrityStatus.UNRESOLVED_REFERENCES,
            is_authentic=False,
            computed_digest=computed,
            expected_digest=expected_digest,
            source_run_id=source_run_id,
            total_evidence_records_in_snapshot=len(present_ids),
            total_references_checked=len(referenced_evidence_ids),
            unresolved_reference_ids=sorted(set(unresolved)),
            details=(
                "Referenced evidence IDs do not exist in snapshot: "
                f"{', '.join(sorted(set(unresolved)))}"
            ),
        )

    # Check digest mismatch if expected digest was supplied
    if expected_digest is not None and computed != expected_digest:
        return IntegrityVerificationResult(
            status=ProvenanceIntegrityStatus.DIGEST_MISMATCH,
            is_authentic=False,
            computed_digest=computed,
            expected_digest=expected_digest,
            source_run_id=source_run_id,
            total_evidence_records_in_snapshot=len(present_ids),
            total_references_checked=len(referenced_evidence_ids),
            unresolved_reference_ids=[],
            details=(
                f"Computed snapshot digest ({computed[:16]}...) does not match "
                f"expected binding digest ({expected_digest[:16]}...)."
            ),
        )

    # If authentic binding matched
    if expected_digest is not None and computed == expected_digest:
        return IntegrityVerificationResult(
            status=ProvenanceIntegrityStatus.VERIFIED_AUTHENTIC,
            is_authentic=True,
            computed_digest=computed,
            expected_digest=expected_digest,
            source_run_id=source_run_id,
            total_evidence_records_in_snapshot=len(present_ids),
            total_references_checked=len(referenced_evidence_ids),
            unresolved_reference_ids=[],
            details=(
                "Cryptographic snapshot digest matches certified binding and "
                "all referenced observations resolve in the snapshot."
            ),
        )

    # Unbound valid snapshot (no external binding provided to compare against)
    return IntegrityVerificationResult(
        status=ProvenanceIntegrityStatus.VERIFIED_UNBOUND,
        is_authentic=True,
        computed_digest=computed,
        expected_digest=None,
        source_run_id=source_run_id,
        total_evidence_records_in_snapshot=len(present_ids),
        total_references_checked=len(referenced_evidence_ids),
        unresolved_reference_ids=[],
        details=(
            "Snapshot digest computed and all evidence references verified; "
            "no external binding artifact provided for cross-verification."
        ),
    )
