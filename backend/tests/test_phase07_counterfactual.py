"""
NEXORA Phase 07: Deterministic Counterfactual Verification Engine Test Suite.

Tests all 15 requirements from Phase 07 specification:
1. F1 link-failure expectations.
2. F2 multi-peer router-failure expectations.
3. F3 OSPF configuration mismatch.
4. F4 partial packet loss.
5. F5 high latency.
6. Missing observations -> INSUFFICIENT_EVIDENCE & probe requests.
7. Contradictory evidence detection -> CONTRADICTED.
8. Collector failures distinguished from negative findings.
9. Neighbor timer lag tolerance.
10. Ambiguous competing hypotheses evaluation.
11. Stale observations filtered by incident window.
12. Topology-aware dynamic expectations and location validation.
13. Determinism across 5x repeated runs.
14. Ground-truth isolation (no leakage into inference).
15. Preservation of original Phase 06 diagnostic outputs and scores.
16. CounterfactualVerifier Protocol conformance.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.collectors.normalizer import GroundTruthLeakageError
from app.diagnosis.engine import DiagnosisEngine
from app.diagnosis.interfaces import CounterfactualVerifier
from app.schemas.counterfactual import (
    CounterfactualVerdict,
    CounterfactualVerificationResult,
    ExpectationCategory,
    ObservationMatch,
)
from app.schemas.evidence import (
    CollectionMethod,
    EvidenceSourceType,
    InterfaceObservation,
    ObservationStatus,
    OSPFObservation,
)
from app.schemas.hypothesis import (
    FaultHypothesis,
    FaultLocation,
    FaultLocationKind,
    FaultType,
)
from app.schemas.topology import Topology
from app.topology.graph import build_expected_topology_graph
from app.verification.engine import CounterfactualVerificationEngine
from app.verification.expectations import ExpectationGenerator

_BASE_DIR = Path(__file__).resolve().parents[2]
_LIVE_ARCHIVES = Path("/Users/azriel/Nexora-backups/live-evidence")
_FALLBACK_DATASETS = _BASE_DIR / "evaluation/datasets/observations"


def _get_snapshot_path(scenario_code: str) -> Path:
    """Find the certified neutral snapshot for a scenario."""
    # Check live evidence backups first
    if _LIVE_ARCHIVES.exists():
        for d in _LIVE_ARCHIVES.iterdir():
            if d.is_dir() and d.name.startswith(f"{scenario_code.lower()}-"):
                if (d / "snapshot.json").exists():
                    return d / "snapshot.json"
                for sub in d.iterdir():
                    if sub.is_dir() and (sub / "snapshot.json").exists():
                        return sub / "snapshot.json"

    # Fallback to recorded dataset
    mapping = {
        "F1": "f1_link_failure_snapshot.json",
        "F2": "f2_router_failure_snapshot.json",
        "F3": "f3_ospf_mismatch_snapshot.json",
        "F4": "f4_packet_loss_snapshot.json",
        "F5": "f5_high_latency_snapshot.json",
    }
    fb = _FALLBACK_DATASETS / mapping[scenario_code]
    if fb.exists():
        return fb
    raise FileNotFoundError(f"No snapshot found for {scenario_code}")


@pytest.fixture
def topology() -> Topology:
    return build_expected_topology_graph().topology


@pytest.fixture
def engine() -> CounterfactualVerificationEngine:
    return CounterfactualVerificationEngine()


# -----------------------------------------------------------------------------
# 1. F1 Link Failure Expectations
# -----------------------------------------------------------------------------
def test_f1_link_failure_expectations(engine: CounterfactualVerificationEngine):
    snap_p = _get_snapshot_path("F1")
    snap = json.loads(snap_p.read_text())
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) >= 1
    report = reports[0]
    assert len(report.top_hypotheses_verifications) >= 1

    top1 = report.top_hypotheses_verifications[0]
    assert top1.hypothesis.fault_type == FaultType.LINK_FAILURE
    assert top1.hypothesis.fault_location.component_id == "L12"
    assert top1.verdict == CounterfactualVerdict.SUPPORTED
    assert top1.counterfactual_verified is True
    assert len(top1.supporting_evidence_ids) > 0
    assert len(top1.contradictory_evidence_ids) == 0

    # Competing alternatives on L12 should be contradicted
    competing = {c.hypothesis.fault_type: c for c in report.competing_hypotheses_verifications}
    assert FaultType.OSPF_CONFIGURATION_MISMATCH in competing
    assert (
        competing[FaultType.OSPF_CONFIGURATION_MISMATCH].verdict
        == CounterfactualVerdict.CONTRADICTED
    )
    assert competing[FaultType.PACKET_LOSS].verdict == CounterfactualVerdict.CONTRADICTED
    assert competing[FaultType.HIGH_LATENCY].verdict == CounterfactualVerdict.CONTRADICTED


# -----------------------------------------------------------------------------
# 2. F2 Multi-Peer Router Failure Expectations
# -----------------------------------------------------------------------------
def test_f2_multi_peer_router_failure_expectations(engine: CounterfactualVerificationEngine):
    snap_p = _get_snapshot_path("F2")
    snap = json.loads(snap_p.read_text())
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) >= 1
    report = reports[0]
    top1 = report.top_hypotheses_verifications[0]
    assert top1.hypothesis.fault_type == FaultType.ROUTER_FAILURE
    assert top1.hypothesis.fault_location.component_id == "R3"
    assert top1.verdict == CounterfactualVerdict.SUPPORTED
    assert top1.counterfactual_verified is True
    assert len(top1.supporting_evidence_ids) >= 2
    assert len(top1.contradictory_evidence_ids) == 0

    # Verify both incident links (L23, L34) experienced peer OSPF loss
    ospf_evals = [
        e
        for e in top1.evaluated_expectations
        if e.expectation.category == ExpectationCategory.OSPF_ADJACENCY
    ]
    assert len(ospf_evals) == 2
    assert all(e.match_status == ObservationMatch.SUPPORTED for e in ospf_evals)

    # Explanation block check
    block = top1.format_text_block()
    assert "ROUTER_FAILURE at R3" in block
    assert "Verdict:\n  SUPPORTED" in block


# -----------------------------------------------------------------------------
# 3. F3 OSPF Configuration Mismatch
# -----------------------------------------------------------------------------
def test_f3_ospf_mismatch_expectations(engine: CounterfactualVerificationEngine):
    snap_p = _get_snapshot_path("F3")
    snap = json.loads(snap_p.read_text())
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) >= 1
    top1 = reports[0].top_hypotheses_verifications[0]
    assert top1.hypothesis.fault_type == FaultType.OSPF_CONFIGURATION_MISMATCH
    assert top1.hypothesis.fault_location.component_id == "L12"
    assert top1.verdict == CounterfactualVerdict.SUPPORTED
    assert top1.counterfactual_verified is True
    assert len(top1.contradictory_evidence_ids) == 0

    # Physical interfaces UP
    iface_evals = [
        e
        for e in top1.evaluated_expectations
        if e.expectation.category == ExpectationCategory.INTERFACE_STATE
    ]
    assert len(iface_evals) == 2
    assert all(e.match_status == ObservationMatch.SUPPORTED for e in iface_evals)


# -----------------------------------------------------------------------------
# 4. F4 Partial Packet Loss
# -----------------------------------------------------------------------------
def test_f4_partial_packet_loss_expectations(engine: CounterfactualVerificationEngine):
    snap_p = _get_snapshot_path("F4")
    snap = json.loads(snap_p.read_text())
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) >= 1
    top1 = reports[0].top_hypotheses_verifications[0]
    assert top1.hypothesis.fault_type == FaultType.PACKET_LOSS
    assert top1.hypothesis.fault_location.component_id == "L12"
    assert top1.verdict == CounterfactualVerdict.SUPPORTED
    assert top1.counterfactual_verified is True
    assert len(top1.contradictory_evidence_ids) == 0

    loss_eval = next(
        e
        for e in top1.evaluated_expectations
        if e.expectation.category == ExpectationCategory.PACKET_LOSS
    )
    assert loss_eval.match_status == ObservationMatch.SUPPORTED


# -----------------------------------------------------------------------------
# 5. F5 High Latency
# -----------------------------------------------------------------------------
def test_f5_high_latency_expectations(engine: CounterfactualVerificationEngine):
    snap_p = _get_snapshot_path("F5")
    snap = json.loads(snap_p.read_text())
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) >= 1
    top1 = reports[0].top_hypotheses_verifications[0]
    assert top1.hypothesis.fault_type == FaultType.HIGH_LATENCY
    assert top1.hypothesis.fault_location.component_id == "L12"
    assert top1.verdict == CounterfactualVerdict.SUPPORTED
    assert top1.counterfactual_verified is True
    assert len(top1.contradictory_evidence_ids) == 0

    rtt_eval = next(
        e
        for e in top1.evaluated_expectations
        if e.expectation.category == ExpectationCategory.RTT_LATENCY
    )
    assert rtt_eval.match_status == ObservationMatch.SUPPORTED


# -----------------------------------------------------------------------------
# 6. Missing Observations -> INSUFFICIENT_EVIDENCE & Probes
# -----------------------------------------------------------------------------
def test_missing_observations_insufficient_evidence(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    hyp = FaultHypothesis(
        hypothesis_id="h-test-missing",
        incident_id="inc-test",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(
            component_id="L45",
            kind=FaultLocationKind.LINK,
        ),
        rule_score=0.7,
    )
    # Zero evidence provided
    res = engine.verify_hypothesis_detailed(hyp, [], topology)
    assert res.verdict == CounterfactualVerdict.INSUFFICIENT_EVIDENCE
    assert res.counterfactual_verified is None
    assert len(res.missing_evidence_descriptions) > 0
    assert len(res.recommended_probes) > 0
    assert any(
        p.target_interface == "eth2" or p.target_interface == "eth1" for p in res.recommended_probes
    )


# -----------------------------------------------------------------------------
# 7. Contradictory Evidence Detection -> CONTRADICTED
# -----------------------------------------------------------------------------
def test_contradictory_evidence_detection(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    now = datetime.now(UTC)
    hyp = FaultHypothesis(
        hypothesis_id="h-test-contr",
        incident_id="inc-test",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(
            component_id="L12",
            kind=FaultLocationKind.LINK,
        ),
        rule_score=0.7,
    )
    # Evidence shows both endpoints UP and OSPF FULL -> directly contradicts LINK_FAILURE
    recs = [
        InterfaceObservation(
            evidence_id="ev-iface-r1",
            source_router="R1",
            source_interface="eth1",
            observed_status="up",
            source_type=EvidenceSourceType.INTERFACE_POLL,
            event_type="INTERFACE_STATE_OBSERVED",
            observed_at=now,
            collected_at=now,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
        ),
        InterfaceObservation(
            evidence_id="ev-iface-r2",
            source_router="R2",
            source_interface="eth1",
            observed_status="up",
            source_type=EvidenceSourceType.INTERFACE_POLL,
            event_type="INTERFACE_STATE_OBSERVED",
            observed_at=now,
            collected_at=now,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
        ),
        OSPFObservation(
            evidence_id="ev-ospf-r1",
            source_router="R1",
            source_interface="eth1",
            neighbour_router_id="2.2.2.2",
            neighbour_address="10.0.12.2",
            adjacency_state="Full",
            source_type=EvidenceSourceType.OSPF_API,
            event_type="OSPF_NEIGHBOUR_FULL",
            observed_at=now,
            collected_at=now,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
        ),
    ]
    res = engine.verify_hypothesis_detailed(hyp, recs, topology)
    assert res.verdict == CounterfactualVerdict.CONTRADICTED
    assert res.counterfactual_verified is False
    assert len(res.contradictory_evidence_ids) > 0


# -----------------------------------------------------------------------------
# 8. Collector Failures Distinguished from Negative Findings
# -----------------------------------------------------------------------------
def test_collector_failures_distinguished(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    now = datetime.now(UTC)
    hyp = FaultHypothesis(
        hypothesis_id="h-test-failed-col",
        incident_id="inc-test",
        fault_type=FaultType.OSPF_CONFIGURATION_MISMATCH,
        fault_location=FaultLocation(
            component_id="L12",
            kind=FaultLocationKind.LINK,
        ),
        rule_score=0.8,
    )
    # Collector failed to collect interface telemetry
    recs = [
        InterfaceObservation(
            evidence_id="ev-fail-1",
            source_router="R1",
            source_interface="eth1",
            observed_status="unknown",
            source_type=EvidenceSourceType.INTERFACE_POLL,
            event_type="COLLECTION_TIMEOUT",
            observed_at=now,
            collected_at=now,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.COLLECTION_FAILED,
        ),
    ]
    res = engine.verify_hypothesis_detailed(hyp, recs, topology)
    # Missing/failed telemetry must NOT be interpreted as contradiction
    assert res.verdict in (
        CounterfactualVerdict.INSUFFICIENT_EVIDENCE,
        CounterfactualVerdict.INCONCLUSIVE,
    )
    assert res.counterfactual_verified is None
    assert len(res.contradictory_evidence_ids) == 0


# -----------------------------------------------------------------------------
# 9. Neighbor Timer Lag Tolerance
# -----------------------------------------------------------------------------
def test_neighbor_timer_lag_tolerance(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    now = datetime.now(UTC)
    hyp = FaultHypothesis(
        hypothesis_id="h-test-lag",
        incident_id="inc-test",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(
            component_id="L12",
            kind=FaultLocationKind.LINK,
        ),
        rule_score=0.75,
    )
    # R1 detected DOWN and lost OSPF, but R2 still has Full due to dead-timer lag
    recs = [
        InterfaceObservation(
            evidence_id="ev-iface-r1-down",
            source_router="R1",
            source_interface="eth1",
            observed_status="down",
            source_type=EvidenceSourceType.INTERFACE_POLL,
            event_type="INTERFACE_DOWN_OBSERVED",
            observed_at=now,
            collected_at=now,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
        ),
        OSPFObservation(
            evidence_id="ev-ospf-r1-down",
            source_router="R1",
            source_interface="eth1",
            neighbour_router_id="2.2.2.2",
            neighbour_address="10.0.12.2",
            adjacency_state="Down",
            source_type=EvidenceSourceType.OSPF_API,
            event_type="OSPF_NEIGHBOUR_DOWN",
            observed_at=now,
            collected_at=now,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
        ),
        OSPFObservation(
            evidence_id="ev-ospf-r2-lag",
            source_router="R2",
            source_interface="eth1",
            neighbour_router_id="1.1.1.1",
            neighbour_address="10.0.12.1",
            adjacency_state="Full",
            source_type=EvidenceSourceType.OSPF_API,
            event_type="OSPF_NEIGHBOUR_FULL",
            observed_at=now,
            collected_at=now,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
        ),
    ]
    res = engine.verify_hypothesis_detailed(hyp, recs, topology)
    # Link failure is SUPPORTED despite R2 dead-timer lag
    assert res.verdict == CounterfactualVerdict.SUPPORTED
    assert res.counterfactual_verified is True
    assert (
        "dead-timer lag"
        in [e.explanation for e in res.evaluated_expectations if "dead-timer lag" in e.explanation][
            0
        ]
    )


# -----------------------------------------------------------------------------
# 10. Ambiguous Competing Hypotheses Evaluation
# -----------------------------------------------------------------------------
def test_ambiguous_competing_hypotheses_evaluation(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    snap_p = _get_snapshot_path("F1")
    snap = json.loads(snap_p.read_text())
    reports = engine.verify_snapshot_dict(snap)
    assert len(reports) >= 1
    rep = reports[0]

    # Both top hypotheses and competing alternatives are evaluated
    assert len(rep.top_hypotheses_verifications) >= 1
    assert len(rep.competing_hypotheses_verifications) >= 3

    # Competing alternatives must have separate verification results
    for comp in rep.competing_hypotheses_verifications:
        assert isinstance(comp, CounterfactualVerificationResult)
        assert comp.hypothesis.fault_location.component_id == "L12"


# -----------------------------------------------------------------------------
# 11. Stale Observations Filtered by Incident Window
# -----------------------------------------------------------------------------
def test_stale_observations_filtered(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)
    hyp = FaultHypothesis(
        hypothesis_id="h-test-stale",
        incident_id="inc-test",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(
            component_id="L12",
            kind=FaultLocationKind.LINK,
        ),
        rule_score=0.75,
    )
    # Stale observation: observed 1 hour before incident window
    stale_rec = InterfaceObservation(
        evidence_id="ev-stale",
        source_router="R1",
        source_interface="eth1",
        observed_status="down",
        source_type=EvidenceSourceType.INTERFACE_POLL,
        event_type="INTERFACE_DOWN_OBSERVED",
        observed_at=t0 - timedelta(hours=1),
        collected_at=t0 - timedelta(hours=1),
        collection_method=CollectionMethod.PERIODIC_POLL,
        collection_status=ObservationStatus.OBSERVED,
    )
    window = (t0, t0 + timedelta(minutes=5))
    res = engine.verify_hypothesis_detailed(hyp, [stale_rec], topology, incident_window=window)
    # Stale record excluded -> missing evidence
    assert res.verdict == CounterfactualVerdict.INSUFFICIENT_EVIDENCE
    assert "ev-stale" not in res.supporting_evidence_ids


# -----------------------------------------------------------------------------
# 12. Topology-Aware Dynamic Expectations and Location Validation
# -----------------------------------------------------------------------------
def test_topology_aware_dynamic_expectations(topology: Topology):
    gen = ExpectationGenerator()
    # R3 incident links are L23, L34
    h_r3 = FaultHypothesis(
        hypothesis_id="h-r3",
        incident_id="inc-1",
        fault_type=FaultType.ROUTER_FAILURE,
        fault_location=FaultLocation(component_id="R3", kind=FaultLocationKind.ROUTER),
        rule_score=1.0,
    )
    exp_r3 = gen.generate_expectations(h_r3, topology)
    ospf_r3_links = {
        e.target_component for e in exp_r3 if e.category == ExpectationCategory.OSPF_ADJACENCY
    }
    assert ospf_r3_links == {"L23", "L34"}

    # R1 incident links are L12, L51
    h_r1 = FaultHypothesis(
        hypothesis_id="h-r1",
        incident_id="inc-1",
        fault_type=FaultType.ROUTER_FAILURE,
        fault_location=FaultLocation(component_id="R1", kind=FaultLocationKind.ROUTER),
        rule_score=1.0,
    )
    exp_r1 = gen.generate_expectations(h_r1, topology)
    ospf_r1_links = {
        e.target_component for e in exp_r1 if e.category == ExpectationCategory.OSPF_ADJACENCY
    }
    assert ospf_r1_links == {"L12", "L51"}

    # Unknown router raises ValueError
    h_unknown = FaultHypothesis(
        hypothesis_id="h-unknown",
        incident_id="inc-1",
        fault_type=FaultType.ROUTER_FAILURE,
        fault_location=FaultLocation(component_id="R99", kind=FaultLocationKind.ROUTER),
        rule_score=1.0,
    )
    with pytest.raises(ValueError, match="not found in topology"):
        gen.generate_expectations(h_unknown, topology)


# -----------------------------------------------------------------------------
# 13. Determinism Across Repeated Runs
# -----------------------------------------------------------------------------
def test_determinism_across_repeated_runs(engine: CounterfactualVerificationEngine):
    snap_p = _get_snapshot_path("F1")
    snap = json.loads(snap_p.read_text())

    runs = [engine.verify_snapshot_dict(copy.deepcopy(snap)) for _ in range(5)]
    baseline = runs[0][0].model_dump(mode="json")
    for idx, r in enumerate(runs[1:], 2):
        d = r[0].model_dump(mode="json")
        # verified_at timestamp differs per invocation; ignore it for determinism check
        baseline_copy = {k: v for k, v in baseline.items() if k != "verified_at"}
        d_copy = {k: v for k, v in d.items() if k != "verified_at"}
        assert baseline_copy == d_copy, f"Verification non-deterministic on run {idx}"


# -----------------------------------------------------------------------------
# 14. Ground-Truth Isolation
# -----------------------------------------------------------------------------
def test_no_ground_truth_leakage(engine: CounterfactualVerificationEngine):
    snap_p = _get_snapshot_path("F1")
    snap = json.loads(snap_p.read_text())

    # Contaminate snapshot with forbidden token
    contaminated = copy.deepcopy(snap)
    contaminated["ground_truth"] = {"injected_fault": "LINK_FAILURE"}

    with pytest.raises(GroundTruthLeakageError):
        engine.verify_snapshot_dict(contaminated)


# -----------------------------------------------------------------------------
# 15. Preservation of Original Phase 06 Outputs
# -----------------------------------------------------------------------------
def test_preservation_of_original_phase06_outputs(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    snap_p = _get_snapshot_path("F1")
    snap = json.loads(snap_p.read_text())

    d_engine = DiagnosisEngine()
    original_results = d_engine.diagnose_snapshot_dict(copy.deepcopy(snap))
    orig_top1 = original_results[0].top1_hypothesis

    reports = engine.verify_snapshot_dict(copy.deepcopy(snap))
    verified_top1 = reports[0].top_hypotheses_verifications[0].hypothesis

    # Verify rule score and location are unchanged
    assert orig_top1 is not None
    assert orig_top1.fault_type == verified_top1.fault_type
    assert orig_top1.fault_location.component_id == verified_top1.fault_location.component_id
    assert orig_top1.rule_score == verified_top1.rule_score


# -----------------------------------------------------------------------------
# 16. CounterfactualVerifier Protocol Conformance
# -----------------------------------------------------------------------------
def test_counterfactual_verifier_protocol_conformance(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    assert isinstance(engine, CounterfactualVerifier)

    hyp = FaultHypothesis(
        hypothesis_id="h-proto",
        incident_id="inc-proto",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(component_id="L12", kind=FaultLocationKind.LINK),
        rule_score=0.75,
        counterfactual_verified=None,
    )
    # verify() must return a FaultHypothesis with counterfactual_verified set
    updated = engine.verify(hyp, [], topology)
    assert isinstance(updated, FaultHypothesis)
    assert updated.counterfactual_verified is None  # no evidence -> None
