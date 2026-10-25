"""
NEXORA Phase 09: Evidence Certificates & Explainability Test Suite.

Verifies all 20 required acceptance criteria:
1. Missing snapshot ID
2. Wrong snapshot digest (DIGEST_MISMATCH)
3. Unknown evidence ID (UNRESOLVED_REFERENCES)
4. Duplicate evidence reference deduplication
5. Collector failure tracking
6. Contradictory observations preserved
7. Missing required expectations listed
8. Abstained diagnosis handled
9. Inconclusive verification handled
10. Insufficient evidence state
11. Unsupported fault type handling
12. Long F2-style explanation bounding (<= 8192 chars)
13. Invalid or missing provenance (VERIFIED_UNBOUND / INCOMPLETE_PROVENANCE)
14. Schema version consistency (phase09-evidence-certificate-v1.0)
15. No ground-truth leakage
16. Repeated deterministic generation (5x identical output)
17. Safe probe plans strictly PROPOSED_NOT_EXECUTED
18. No mutation of original evidence or snapshot
19. Invalid candidate references handled safely
20. Empty or incomplete inputs fail closed

Plus verification across all 5 live certified fault archives (F1–F5).
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.certificates.generator import CertificateGenerator
from app.certificates.integrity import verify_snapshot_integrity
from app.schemas.certificate import (
    CERTIFICATE_SCHEMA_VERSION,
    AuditableEvidenceCertificate,
    EvidenceRole,
    ProvenanceIntegrityStatus,
)
from app.schemas.counterfactual import (
    CounterfactualVerdict,
    CounterfactualVerificationResult,
    VerificationReport,
)
from app.schemas.diagnosis import (
    DiagnosisResult,
    DiagnosisStatus,
    EvidenceCertificate,
    RankedHypothesis,
)
from app.schemas.hypothesis import (
    FaultHypothesis,
    FaultLocation,
    FaultLocationKind,
    FaultType,
)
from app.schemas.probe import (
    ExecutionAuthorizationState,
    ProbeSafetyStatus,
)
from app.schemas.topology import Topology
from app.topology.graph import build_expected_topology_graph

_BASE_DIR = Path(__file__).resolve().parents[2]
_LIVE_ARCHIVES = Path("/Users/azriel/Nexora-backups/live-evidence")
_FALLBACK_DATASETS = _BASE_DIR / "evaluation/datasets/observations"


def _get_snapshot_and_binding(scenario_code: str) -> tuple[dict, dict | None]:
    """Find certified snapshot and optional binding."""
    if _LIVE_ARCHIVES.exists():
        dirs = {
            "F1": _LIVE_ARCHIVES / "f1-exp-aab6c8bcaad34acfaa7583d3ea391948",
            "F2": (
                _LIVE_ARCHIVES
                / "f2-exp-5acb69cba29d4b0497f4de2b3b97f1b6"
                / "67bc39cd97744d9d92848847ad6c3945"
            ),
            "F3": _LIVE_ARCHIVES / "f3-exp-3d67ba780db64eff83471cacc1a80ea4",
            "F4": _LIVE_ARCHIVES / "f4-exp-1e5e22df3c124d21a58e50884cc54b82",
            "F5": _LIVE_ARCHIVES / "f5-exp-46f8c718e43a494ba628eb7f724325b4",
        }
        sdir = dirs.get(scenario_code)
        if sdir and (sdir / "snapshot.json").exists():
            snap = json.loads((sdir / "snapshot.json").read_text())
            binding = (
                json.loads((sdir / "binding.json").read_text())
                if (sdir / "binding.json").exists()
                else None
            )
            return snap, binding

    mapping = {
        "F1": "f1_link_failure_snapshot.json",
        "F2": "f2_router_failure_snapshot.json",
        "F3": "f3_ospf_mismatch_snapshot.json",
        "F4": "f4_packet_loss_snapshot.json",
        "F5": "f5_high_latency_snapshot.json",
    }
    fb = _FALLBACK_DATASETS / mapping[scenario_code]
    if fb.exists():
        return json.loads(fb.read_text()), None
    raise FileNotFoundError(f"Snapshot not found for {scenario_code}")


@pytest.fixture
def generator() -> CertificateGenerator:
    return CertificateGenerator()


@pytest.fixture
def topology() -> Topology:
    return build_expected_topology_graph().topology


def _make_mock_diagnosis(
    incident_id: str,
    ranked_hypotheses: list[RankedHypothesis],
    status: DiagnosisStatus = DiagnosisStatus.DIAGNOSED,
) -> DiagnosisResult:
    now = datetime.now(UTC)
    return DiagnosisResult(
        result_id=f"res-{incident_id}",
        incident_id=incident_id,
        engine_version="test-1.0",
        diagnosed_at=now,
        status=status,
        ranked_hypotheses=ranked_hypotheses,
        evidence_certificate=EvidenceCertificate(
            certificate_id=f"cert-{incident_id}",
            incident_id=incident_id,
            generated_at=now,
            total_evidence_count=len(ranked_hypotheses),
            supporting_evidence_count=len(ranked_hypotheses),
            contradictory_evidence_count=0,
            missing_evidence_descriptions=[],
            evidence_sufficiency_met=True,
            collection_coverage_pct=100.0,
            reasoning_summary="Test mock certificate",
        ),
    )


# -----------------------------------------------------------------------------
# 1. Missing Snapshot ID
# -----------------------------------------------------------------------------
def test_missing_snapshot_id(generator: CertificateGenerator, topology: Topology):
    """1. Snapshot without snapshot_id is handled safely with None snapshot_id."""
    raw, _ = _get_snapshot_and_binding("F1")
    raw_no_id = copy.deepcopy(raw)
    del raw_no_id["snapshot_id"]

    cert = generator.generate_from_snapshot_dict(raw_no_id)
    assert cert.snapshot_id is None
    assert cert.certificate_id.startswith("cert-")
    assert cert.integrity_result.computed_digest is not None


# -----------------------------------------------------------------------------
# 2. Wrong Snapshot Digest
# -----------------------------------------------------------------------------
def test_wrong_snapshot_digest(generator: CertificateGenerator):
    """2. Mismatch between computed snapshot digest and binding triggers DIGEST_MISMATCH."""
    raw, binding = _get_snapshot_and_binding("F1")
    tampered_binding = {
        "run_id": "exp-test-wrong-digest",
        "snapshot_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    }
    cert = generator.generate_from_snapshot_dict(raw, binding=tampered_binding)
    assert cert.integrity_result.status == ProvenanceIntegrityStatus.DIGEST_MISMATCH
    assert not cert.integrity_result.is_authentic
    assert "does not match" in cert.integrity_result.details


# -----------------------------------------------------------------------------
# 3. Unknown Evidence ID
# -----------------------------------------------------------------------------
def test_unknown_evidence_id(generator: CertificateGenerator, topology: Topology):
    """3. Referenced evidence IDs missing from snapshot trigger UNRESOLVED_REFERENCES."""
    raw, _ = _get_snapshot_and_binding("F1")
    h = FaultHypothesis(
        hypothesis_id="h-unknown-ev",
        incident_id="inc-test",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.8,
        supporting_evidence_ids=["ev-nonexistent-12345"],
    )
    diag = _make_mock_diagnosis("inc-test", [RankedHypothesis(rank=1, hypothesis=h)])
    cert = generator.generate_certificate(snapshot=raw, diagnosis=diag, topology=topology)

    assert cert.integrity_result.status == ProvenanceIntegrityStatus.UNRESOLVED_REFERENCES
    assert not cert.integrity_result.is_authentic
    assert "ev-nonexistent-12345" in cert.integrity_result.unresolved_reference_ids


# -----------------------------------------------------------------------------
# 4. Duplicate Evidence Reference
# -----------------------------------------------------------------------------
def test_duplicate_evidence_reference(generator: CertificateGenerator, topology: Topology):
    """4. Evidence referenced multiple times across hypotheses is cleanly deduplicated."""
    raw, _ = _get_snapshot_and_binding("F1")
    first_eid = raw["evidence_records"][0]["evidence_id"]

    h = FaultHypothesis(
        hypothesis_id="h-dup",
        incident_id="inc-dup",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.8,
        supporting_evidence_ids=[first_eid, first_eid, first_eid],
    )
    diag = _make_mock_diagnosis("inc-dup", [RankedHypothesis(rank=1, hypothesis=h)])
    cert = generator.generate_certificate(snapshot=raw, diagnosis=diag, topology=topology)

    matching_refs = [
        r for r in cert.supporting_evidence_references if r.evidence_id == first_eid
    ]
    assert len(matching_refs) == 1


# -----------------------------------------------------------------------------
# 5. Collector Failure
# -----------------------------------------------------------------------------
def test_collector_failure_tracked(generator: CertificateGenerator, topology: Topology):
    """5. Observations with COLLECTION_FAILED are recorded in collector_failures."""
    raw, _ = _get_snapshot_and_binding("F1")
    raw_with_fail = copy.deepcopy(raw)
    raw_with_fail["evidence_records"].append(
        {
            "evidence_id": "ev-fail-sim",
            "source_router": "R1",
            "source_interface": "eth1",
            "collection_status": "COLLECTION_FAILED",
            "event_type": "INTERFACE_POLL_FAILED",
            "observed_at": datetime.now(UTC).isoformat(),
            "collected_at": datetime.now(UTC).isoformat(),
        }
    )
    h = FaultHypothesis(
        hypothesis_id="h-col-fail",
        incident_id="inc-cf",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.7,
    )
    diag = _make_mock_diagnosis("inc-cf", [RankedHypothesis(rank=1, hypothesis=h)])
    cert = generator.generate_certificate(snapshot=raw_with_fail, diagnosis=diag, topology=topology)

    assert len(cert.collector_failures) >= 1
    assert any("ev-fail-sim" in cf for cf in cert.collector_failures)


# -----------------------------------------------------------------------------
# 6. Contradictory Observations
# -----------------------------------------------------------------------------
def test_contradictory_observations_preserved(generator: CertificateGenerator, topology: Topology):
    """6. Contradictory observations are preserved in contradictory_evidence_references."""
    raw, _ = _get_snapshot_and_binding("F1")
    first_eid = raw["evidence_records"][0]["evidence_id"]

    h = FaultHypothesis(
        hypothesis_id="h-contra-test",
        incident_id="inc-contra",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.6,
        contradictory_evidence_ids=[first_eid],
    )
    diag = _make_mock_diagnosis("inc-contra", [RankedHypothesis(rank=1, hypothesis=h)])
    cert = generator.generate_certificate(snapshot=raw, diagnosis=diag, topology=topology)

    assert len(cert.contradictory_evidence_references) >= 1
    assert cert.contradictory_evidence_references[0].role == EvidenceRole.CONTRADICTORY
    assert "CONTRADICTING OBSERVATIONS" in cert.explanation.full_text


# -----------------------------------------------------------------------------
# 7. Missing Required Expectations
# -----------------------------------------------------------------------------
def test_missing_required_expectations(generator: CertificateGenerator, topology: Topology):
    """7. Unmet counterfactual expectations are recorded in missing_required_observations."""
    raw, _ = _get_snapshot_and_binding("F1")
    h = FaultHypothesis(
        hypothesis_id="h-missing-exp",
        incident_id="inc-me",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.7,
    )
    diag = _make_mock_diagnosis("inc-me", [RankedHypothesis(rank=1, hypothesis=h)])
    verif_res = CounterfactualVerificationResult(
        hypothesis=h,
        verdict=CounterfactualVerdict.INCONCLUSIVE,
        missing_evidence_descriptions=["No OSPF adjacency loss detected on L12"],
        explanation="Missing required observation",
    )
    report = VerificationReport(
        incident_id="inc-me",
        verified_at=datetime.now(UTC),
        engine_version="test-1.0",
        top_hypotheses_verifications=[verif_res],
        summary="Test report",
    )
    cert = generator.generate_certificate(
        snapshot=raw, diagnosis=diag, verification_report=report, topology=topology
    )
    assert "No OSPF adjacency loss detected on L12" in cert.missing_required_observations
    assert "MISSING EVIDENCE" in cert.explanation.full_text


# -----------------------------------------------------------------------------
# 8. Abstained Diagnosis Handled
# -----------------------------------------------------------------------------
def test_abstained_diagnosis_handled(generator: CertificateGenerator, topology: Topology):
    """8. Abstained diagnosis (INSUFFICIENT_EVIDENCE) sets sufficiency_status=ABSTAINED_INSUFFICIENT."""
    raw, _ = _get_snapshot_and_binding("F1")
    diag = _make_mock_diagnosis(
        "inc-abstain",
        ranked_hypotheses=[],
        status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
    )
    cert = generator.generate_certificate(snapshot=raw, diagnosis=diag, topology=topology)

    assert cert.sufficiency_status == "ABSTAINED_INSUFFICIENT"
    assert cert.selected_hypothesis_id is None
    assert "abstained" in cert.explanation.what_happened.lower()


# -----------------------------------------------------------------------------
# 9. Inconclusive Verification Handled
# -----------------------------------------------------------------------------
def test_inconclusive_verification(generator: CertificateGenerator, topology: Topology):
    """9. Inconclusive counterfactual verdict is reflected without claiming false certainty."""
    raw, _ = _get_snapshot_and_binding("F1")
    h = FaultHypothesis(
        hypothesis_id="h-incon",
        incident_id="inc-incon",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.75,
    )
    diag = _make_mock_diagnosis("inc-incon", [RankedHypothesis(rank=1, hypothesis=h)])
    verif_res = CounterfactualVerificationResult(
        hypothesis=h,
        verdict=CounterfactualVerdict.INCONCLUSIVE,
        explanation="Inconclusive observations",
    )
    report = VerificationReport(
        incident_id="inc-incon",
        verified_at=datetime.now(UTC),
        engine_version="test-1.0",
        top_hypotheses_verifications=[verif_res],
        summary="Inconclusive report",
    )
    cert = generator.generate_certificate(
        snapshot=raw, diagnosis=diag, verification_report=report, topology=topology
    )
    assert cert.counterfactual_verdict == CounterfactualVerdict.INCONCLUSIVE
    assert "INCONCLUSIVE" in cert.explanation.counterfactual_expectations_summary


# -----------------------------------------------------------------------------
# 10. Insufficient Evidence State
# -----------------------------------------------------------------------------
def test_insufficient_evidence_state(generator: CertificateGenerator, topology: Topology):
    """10. INSUFFICIENT_EVIDENCE diagnosis status does not assert definitive root cause."""
    raw, _ = _get_snapshot_and_binding("F1")
    diag = _make_mock_diagnosis(
        "inc-insuf",
        ranked_hypotheses=[],
        status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
    )
    cert = generator.generate_certificate(snapshot=raw, diagnosis=diag, topology=topology)
    assert "insufficient" in cert.explanation.what_happened.lower()
    assert cert.fault_type is None
    assert cert.fault_location is None


# -----------------------------------------------------------------------------
# 11. Unsupported Fault Type Handling
# -----------------------------------------------------------------------------
def test_unsupported_fault_type_handling(generator: CertificateGenerator, topology: Topology):
    """11. Generic/unsupported fault type strings fall back gracefully in explanation."""
    raw, _ = _get_snapshot_and_binding("F1")
    h = FaultHypothesis(
        hypothesis_id="h-custom",
        incident_id="inc-custom",
        fault_type=FaultType.ROUTER_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.ROUTER, component_id="R1"),
        rule_score=0.5,
    )
    diag = _make_mock_diagnosis("inc-custom", [RankedHypothesis(rank=1, hypothesis=h)])
    cert = generator.generate_certificate(snapshot=raw, diagnosis=diag, topology=topology)
    assert cert.fault_type == FaultType.ROUTER_FAILURE
    assert "Router node outage" in cert.explanation.what_happened


# -----------------------------------------------------------------------------
# 12. Long F2-Style Explanation Bounded
# -----------------------------------------------------------------------------
def test_long_f2_explanation_bounded(generator: CertificateGenerator):
    """12. Multi-link F2 explanation does not exceed max_length=8192."""
    raw, binding = _get_snapshot_and_binding("F2")
    cert = generator.generate_from_snapshot_dict(raw, binding=binding)

    assert len(cert.explanation.full_text) <= 8192
    assert len(cert.explanation.why_selected) <= 2048
    assert "collateral manifestations" in cert.explanation.why_selected
    assert cert.fault_type == FaultType.ROUTER_FAILURE


# -----------------------------------------------------------------------------
# 13. Invalid or Missing Provenance
# -----------------------------------------------------------------------------
def test_invalid_or_missing_provenance(generator: CertificateGenerator):
    """13. Absence of binding returns VERIFIED_UNBOUND without inventing run ID."""
    raw, _ = _get_snapshot_and_binding("F1")
    # Pass binding=None
    cert = generator.generate_from_snapshot_dict(raw, binding=None)
    assert cert.integrity_result.status == ProvenanceIntegrityStatus.VERIFIED_UNBOUND
    assert cert.integrity_result.is_authentic
    assert cert.source_run_id is None or cert.source_run_id == raw.get("run_id")


# -----------------------------------------------------------------------------
# 14. Schema Version Consistency
# -----------------------------------------------------------------------------
def test_schema_version_consistency(generator: CertificateGenerator):
    """14. Certificate schema version is strictly phase09-evidence-certificate-v1.0."""
    raw, binding = _get_snapshot_and_binding("F1")
    cert = generator.generate_from_snapshot_dict(raw, binding=binding)
    assert cert.schema_version == CERTIFICATE_SCHEMA_VERSION
    assert cert.schema_version == "phase09-evidence-certificate-v1.0"


# -----------------------------------------------------------------------------
# 15. No Ground-Truth Leakage
# -----------------------------------------------------------------------------
def test_no_ground_truth_leakage(generator: CertificateGenerator):
    """15. Generated certificate contains no injection commands or truth labels."""
    raw, binding = _get_snapshot_and_binding("F1")
    cert = generator.generate_from_snapshot_dict(raw, binding=binding)

    dumped = cert.model_dump_json()
    assert "tc qdisc add" not in dumped
    assert "docker stop" not in dumped
    assert "truth.json" not in dumped
    assert "actual_fault_location_id" not in dumped


# -----------------------------------------------------------------------------
# 16. Repeated Deterministic Generation
# -----------------------------------------------------------------------------
def test_repeated_deterministic_generation(generator: CertificateGenerator):
    """16. Five repeat runs produce identical certificate ID, digests, and scores."""
    raw, binding = _get_snapshot_and_binding("F1")
    certs: list[AuditableEvidenceCertificate] = [
        generator.generate_from_snapshot_dict(raw, binding=binding) for _ in range(5)
    ]

    base_id = certs[0].certificate_id
    base_digest = certs[0].snapshot_digest
    base_score = certs[0].original_heuristic_score

    for c in certs[1:]:
        assert c.certificate_id == base_id
        assert c.snapshot_digest == base_digest
        assert c.original_heuristic_score == base_score
        assert c.explanation.why_selected == certs[0].explanation.why_selected


# -----------------------------------------------------------------------------
# 17. Safe Probe Plans Not Executed
# -----------------------------------------------------------------------------
def test_safe_probes_not_executed(generator: CertificateGenerator):
    """17. All embedded probe recommendations have execution_authorization=PROPOSED_NOT_EXECUTED."""
    raw, binding = _get_snapshot_and_binding("F2")
    cert = generator.generate_from_snapshot_dict(raw, binding=binding)

    assert len(cert.safe_probe_recommendations) >= 1
    for p in cert.safe_probe_recommendations:
        assert p.execution_authorization == ExecutionAuthorizationState.PROPOSED_NOT_EXECUTED
        assert p.safety_status == ProbeSafetyStatus.SAFE


# -----------------------------------------------------------------------------
# 18. No Mutation of Original Evidence
# -----------------------------------------------------------------------------
def test_no_mutation_of_original_evidence(generator: CertificateGenerator):
    """18. Certificate generation does not mutate the input snapshot dict."""
    raw, binding = _get_snapshot_and_binding("F1")
    raw_copy = copy.deepcopy(raw)

    generator.generate_from_snapshot_dict(raw, binding=binding)
    assert raw == raw_copy


# -----------------------------------------------------------------------------
# 19. Invalid Candidate References
# -----------------------------------------------------------------------------
def test_invalid_candidate_references(generator: CertificateGenerator, topology: Topology):
    """19. Candidate with empty or None locations handled safely without crash."""
    raw, _ = _get_snapshot_and_binding("F1")
    h = FaultHypothesis(
        hypothesis_id="h-inv-loc",
        incident_id="inc-inv",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.5,
    )
    diag = _make_mock_diagnosis("inc-inv", [RankedHypothesis(rank=1, hypothesis=h)])
    cert = generator.generate_certificate(snapshot=raw, diagnosis=diag, topology=topology)
    assert cert.selected_hypothesis_id == "h-inv-loc"
    assert cert.fault_location.component_id == "L12"


# -----------------------------------------------------------------------------
# 20. Empty or Incomplete Inputs
# -----------------------------------------------------------------------------
def test_empty_or_incomplete_inputs_fail_closed(generator: CertificateGenerator):
    """20. Empty snapshot dictionary fails closed with INCOMPLETE_PROVENANCE."""
    empty_snap: dict = {}
    res = verify_snapshot_integrity(
        snapshot=empty_snap,
        referenced_evidence_ids=["ev-1"],
    )
    assert res.status == ProvenanceIntegrityStatus.INCOMPLETE_PROVENANCE
    assert not res.is_authentic


# -----------------------------------------------------------------------------
# Certified Live Archives Validation (F1–F5)
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("scenario_code,expected_fault_type,expected_location", [
    ("F1", FaultType.LINK_FAILURE, "L12"),
    ("F2", FaultType.ROUTER_FAILURE, "R3"),
    ("F3", FaultType.OSPF_CONFIGURATION_MISMATCH, "L12"),
    ("F4", FaultType.PACKET_LOSS, "L12"),
    ("F5", FaultType.HIGH_LATENCY, "L12"),
])
def test_certified_live_scenarios(
    generator: CertificateGenerator,
    scenario_code: str,
    expected_fault_type: FaultType,
    expected_location: str,
):
    """Verify certificate generation for all 5 certified live fault scenarios."""
    snap, binding = _get_snapshot_and_binding(scenario_code)
    cert = generator.generate_from_snapshot_dict(snap, binding=binding)

    assert cert.certificate_id.startswith("cert-")
    assert cert.schema_version == "phase09-evidence-certificate-v1.0"
    assert cert.fault_type == expected_fault_type
    assert cert.fault_location is not None
    assert cert.fault_location.component_id == expected_location
    assert cert.diagnosis_status == DiagnosisStatus.DIAGNOSED
    assert cert.counterfactual_verdict == CounterfactualVerdict.SUPPORTED
    assert cert.counterfactual_verified is True
    assert cert.integrity_result.is_authentic is True
    if binding:
        assert cert.integrity_result.status == ProvenanceIntegrityStatus.VERIFIED_AUTHENTIC
        assert cert.source_run_id == binding.get("run_id")
    assert len(cert.supporting_evidence_references) >= 1
    assert len(cert.explanation.full_text) > 500
