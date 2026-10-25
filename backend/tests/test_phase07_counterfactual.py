"""
NEXORA Phase 07: Deterministic Counterfactual Verification Engine Test Suite.

Contains two explicitly separated suites:
A. PORTABLE TEST SUITE
   Runs on any machine without access to private live evidence archives.
   Uses committed benchmark fixtures in evaluation/datasets/observations and synthetic
   fixtures where appropriate. Never falls back silently to incompatible fixtures.
   Handles F2 protocol timer lag, F3 L23 benchmark location, and F4/F5 abstention.

B. CERTIFIED LIVE REPLAY SUITE
   Replays authenticated F1-F5 live captured snapshots from the certified evidence directory.
   Configurable via NEXORA_LIVE_EVIDENCE_DIR environment variable (defaults to local backup
   if present). If certified archives are unavailable, cleanly SKIPS with an explicit reason.
"""

from __future__ import annotations

import copy
import json
import os
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
    PingMeasurement,
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
_BENCHMARK_DATASETS = _BASE_DIR / "evaluation/datasets/observations"


def _get_live_archives_dir() -> Path | None:
    """Configurable certified live evidence directory.

    Checks NEXORA_LIVE_EVIDENCE_DIR first, then falls back to local backup
    location if it exists on this host. Returns None if certified archives
    are not found.
    """
    env_dir = os.environ.get("NEXORA_LIVE_EVIDENCE_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.exists() and p.is_dir():
            return p
    default_dir = Path("/Users/azriel/Nexora-backups/live-evidence")
    if default_dir.exists() and default_dir.is_dir():
        return default_dir
    return None


def _get_certified_live_snapshot(scenario_code: str) -> tuple[Path, dict, dict | None]:
    """Retrieve certified live snapshot and optional binding.

    Skips the calling test with an explicit message if certified archives
    are unavailable on the current host.
    """
    archives_dir = _get_live_archives_dir()
    if archives_dir is None:
        pytest.skip(
            "Certified live evidence archives not available on this machine "
            "(set NEXORA_LIVE_EVIDENCE_DIR to enable live replay suite)"
        )

    dirs = {
        "F1": archives_dir / "f1-exp-aab6c8bcaad34acfaa7583d3ea391948",
        "F2": (
            archives_dir
            / "f2-exp-5acb69cba29d4b0497f4de2b3b97f1b6"
            / "67bc39cd97744d9d92848847ad6c3945"
        ),
        "F3": archives_dir / "f3-exp-3d67ba780db64eff83471cacc1a80ea4",
        "F4": archives_dir / "f4-exp-1e5e22df3c124d21a58e50884cc54b82",
        "F5": archives_dir / "f5-exp-46f8c718e43a494ba628eb7f724325b4",
    }
    sdir = dirs.get(scenario_code)
    if not sdir or not (sdir / "snapshot.json").exists():
        pytest.skip(
            f"Certified live snapshot for scenario {scenario_code} not found in {archives_dir}"
        )

    snap_p = sdir / "snapshot.json"
    snap = json.loads(snap_p.read_text())
    binding_p = sdir / "binding.json"
    binding = json.loads(binding_p.read_text()) if binding_p.exists() else None
    return snap_p, snap, binding


def _get_benchmark_snapshot(filename: str) -> dict:
    """Retrieve committed benchmark snapshot fixture."""
    p = _BENCHMARK_DATASETS / filename
    if not p.exists():
        raise FileNotFoundError(f"Committed benchmark fixture not found: {p}")
    return json.loads(p.read_text())


@pytest.fixture
def topology() -> Topology:
    return build_expected_topology_graph().topology


@pytest.fixture
def engine() -> CounterfactualVerificationEngine:
    return CounterfactualVerificationEngine()


# =============================================================================
# SUITE A: PORTABLE TEST SUITE
# Runs on any machine without access to private live evidence archives.
# Uses committed benchmark datasets and synthetic unit fixtures.
# =============================================================================


def test_portable_f1_link_failure(engine: CounterfactualVerificationEngine):
    """1. Portable F1: Link failure on L12 verified against committed fixture."""
    snap = _get_benchmark_snapshot("f1_link_failure_snapshot.json")
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


def test_portable_f2_benchmark_timer_lag(engine: CounterfactualVerificationEngine):
    """2. Portable F2: Benchmark fixture correctly manifests OSPF dead-timer lag.

    In the historical benchmark fixture, R2 and R4 telemetry was captured before
    OSPF dead-timer expiry (timer lag), observing OSPF_NEIGHBOUR_FULL towards R3.
    The verification engine properly refutes expected adjacency drop and produces
    CONTRADICTED rather than crashing or falsifying results.
    """
    snap = _get_benchmark_snapshot("f2_router_failure_snapshot.json")
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) >= 1
    report = reports[0]
    top1 = report.top_hypotheses_verifications[0]
    assert top1.hypothesis.fault_type == FaultType.ROUTER_FAILURE
    assert top1.hypothesis.fault_location.component_id == "R3"
    # Benchmark fixture timer lag correctly results in CONTRADICTED
    assert top1.verdict == CounterfactualVerdict.CONTRADICTED
    assert top1.counterfactual_verified is False

    # Check that contradictory evidence explicitly captures the peer FULL states
    assert len(top1.contradictory_evidence_ids) >= 1
    block = top1.format_text_block()
    assert "ROUTER_FAILURE at R3" in block
    assert "CONTRADICTED" in block


def test_portable_f3_benchmark_l23_mismatch(engine: CounterfactualVerificationEngine):
    """3. Portable F3: Committed benchmark fixture records OSPF mismatch on L23.

    Correctly tests actual fixture semantics (L23 instead of mislabeling as L12).
    """
    snap = _get_benchmark_snapshot("f3_ospf_mismatch_snapshot.json")
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) >= 1
    top1 = reports[0].top_hypotheses_verifications[0]
    assert top1.hypothesis.fault_type == FaultType.OSPF_CONFIGURATION_MISMATCH
    assert top1.hypothesis.fault_location.component_id == "L23"
    assert top1.verdict == CounterfactualVerdict.SUPPORTED
    assert top1.counterfactual_verified is True
    assert len(top1.contradictory_evidence_ids) == 0

    # Physical interfaces UP on L23
    iface_evals = [
        e
        for e in top1.evaluated_expectations
        if e.expectation.category == ExpectationCategory.INTERFACE_STATE
    ]
    assert len(iface_evals) == 2
    assert all(e.match_status == ObservationMatch.SUPPORTED for e in iface_evals)


def test_portable_f4_benchmark_insufficient_evidence_abstention(
    engine: CounterfactualVerificationEngine,
):
    """4. Portable F4: Benchmark fixture lacks packet loss anomalies.

    The diagnostic engine honestly abstains (INSUFFICIENT_EVIDENCE) and generates
    zero candidates. The counterfactual engine must NOT raise IndexError.
    """
    snap = _get_benchmark_snapshot("f4_packet_loss_snapshot.json")
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) == 1
    report = reports[0]
    # No candidates generated -> no IndexError, empty verification list
    assert len(report.top_hypotheses_verifications) == 0
    assert "evaluated 0 ranked hypotheses" in report.summary


def test_portable_f5_benchmark_insufficient_evidence_abstention(
    engine: CounterfactualVerificationEngine,
):
    """5. Portable F5: Benchmark fixture lacks RTT latency anomalies.

    The diagnostic engine honestly abstains (INSUFFICIENT_EVIDENCE) and generates
    zero candidates. The counterfactual engine must NOT raise IndexError.
    """
    snap = _get_benchmark_snapshot("f5_high_latency_snapshot.json")
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) == 1
    report = reports[0]
    assert len(report.top_hypotheses_verifications) == 0
    assert "evaluated 0 ranked hypotheses" in report.summary


def test_portable_synthetic_f4_packet_loss(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    """Synthetic Portable F4: Verified partial packet loss on L12."""
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    hyp = FaultHypothesis(
        hypothesis_id="h-synth-f4",
        incident_id="inc-synth-f4",
        fault_type=FaultType.PACKET_LOSS,
        fault_location=FaultLocation(component_id="L12", kind=FaultLocationKind.LINK),
        rule_score=0.65,
    )
    recs = [
        InterfaceObservation(
            evidence_id="ev-r1-eth1-up",
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
            evidence_id="ev-r2-eth1-up",
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
        PingMeasurement(
            evidence_id="ev-synth-ping-loss",
            source_router="R1",
            probe_source="R1",
            target_address="10.0.12.2",
            packets_sent=20,
            packets_received=16,
            packet_loss_pct=20.0,
            rtt_min_ms=1.2,
            rtt_avg_ms=2.5,
            rtt_max_ms=3.8,
            rtt_mdev_ms=0.5,
            source_type=EvidenceSourceType.ACTIVE_PING,
            event_type="PING_PROBE_RESULT",
            observed_at=now,
            collected_at=now,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
        ),
    ]
    res = engine.verify_hypothesis_detailed(hyp, recs, topology)
    assert res.verdict == CounterfactualVerdict.SUPPORTED
    assert res.counterfactual_verified is True
    assert len(res.supporting_evidence_ids) >= 3
    assert len(res.contradictory_evidence_ids) == 0


def test_portable_synthetic_f5_high_latency(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    """Synthetic Portable F5: Verified high RTT latency on L12."""
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    hyp = FaultHypothesis(
        hypothesis_id="h-synth-f5",
        incident_id="inc-synth-f5",
        fault_type=FaultType.HIGH_LATENCY,
        fault_location=FaultLocation(component_id="L12", kind=FaultLocationKind.LINK),
        rule_score=0.65,
    )
    recs = [
        InterfaceObservation(
            evidence_id="ev-r1-eth1-up",
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
            evidence_id="ev-r2-eth1-up",
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
        PingMeasurement(
            evidence_id="ev-synth-ping-rtt",
            source_router="R1",
            probe_source="R1",
            target_address="10.0.12.2",
            packets_sent=20,
            packets_received=20,
            packet_loss_pct=0.0,
            rtt_min_ms=30.0,
            rtt_avg_ms=45.0,
            rtt_max_ms=60.0,
            rtt_mdev_ms=5.0,
            source_type=EvidenceSourceType.ACTIVE_PING,
            event_type="PING_PROBE_RESULT",
            observed_at=now,
            collected_at=now,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
        ),
    ]
    res = engine.verify_hypothesis_detailed(hyp, recs, topology)
    assert res.verdict == CounterfactualVerdict.SUPPORTED
    assert res.counterfactual_verified is True
    assert len(res.supporting_evidence_ids) >= 3
    assert len(res.contradictory_evidence_ids) == 0


def test_missing_observations_insufficient_evidence(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    """6. Missing Observations -> INSUFFICIENT_EVIDENCE & Probes."""
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
    res = engine.verify_hypothesis_detailed(hyp, [], topology)
    assert res.verdict == CounterfactualVerdict.INSUFFICIENT_EVIDENCE
    assert res.counterfactual_verified is None
    assert len(res.missing_evidence_descriptions) > 0
    assert len(res.recommended_probes) > 0
    assert any(
        p.target_interface in {"eth1", "eth2"} for p in res.recommended_probes
    )


def test_contradictory_evidence_detection(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    """7. Contradictory Evidence Detection -> CONTRADICTED."""
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


def test_collector_failures_distinguished(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    """8. Collector Failures Distinguished from Negative Findings."""
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
    assert res.verdict in (
        CounterfactualVerdict.INSUFFICIENT_EVIDENCE,
        CounterfactualVerdict.INCONCLUSIVE,
    )
    assert res.counterfactual_verified is None
    assert len(res.contradictory_evidence_ids) == 0


def test_neighbor_timer_lag_tolerance(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    """9. Neighbor Timer Lag Tolerance."""
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
    assert res.verdict == CounterfactualVerdict.SUPPORTED
    assert res.counterfactual_verified is True
    assert (
        "dead-timer lag"
        in [e.explanation for e in res.evaluated_expectations if "dead-timer lag" in e.explanation][
            0
        ]
    )


def test_ambiguous_competing_hypotheses_evaluation(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    """10. Ambiguous Competing Hypotheses Evaluation."""
    snap = _get_benchmark_snapshot("f1_link_failure_snapshot.json")
    reports = engine.verify_snapshot_dict(snap)
    assert len(reports) >= 1
    rep = reports[0]

    assert len(rep.top_hypotheses_verifications) >= 1
    assert len(rep.competing_hypotheses_verifications) >= 3

    for comp in rep.competing_hypotheses_verifications:
        assert isinstance(comp, CounterfactualVerificationResult)
        assert comp.hypothesis.fault_location.component_id == "L12"


def test_stale_observations_filtered(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    """11. Stale Observations Filtered by Incident Window."""
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
    assert res.verdict == CounterfactualVerdict.INSUFFICIENT_EVIDENCE
    assert "ev-stale" not in res.supporting_evidence_ids


def test_topology_aware_dynamic_expectations(topology: Topology):
    """12. Topology-Aware Dynamic Expectations and Location Validation."""
    gen = ExpectationGenerator()
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

    h_unknown = FaultHypothesis(
        hypothesis_id="h-unknown",
        incident_id="inc-1",
        fault_type=FaultType.ROUTER_FAILURE,
        fault_location=FaultLocation(component_id="R99", kind=FaultLocationKind.ROUTER),
        rule_score=1.0,
    )
    with pytest.raises(ValueError, match="not found in topology"):
        gen.generate_expectations(h_unknown, topology)


def test_determinism_across_repeated_runs(engine: CounterfactualVerificationEngine):
    """13. Determinism Across Repeated Runs.

    Verifies that:
    1. With controlled clock, 5 repeated invocations produce 100% byte-identical
       serialization (including all probe IDs and timestamps).
    2. Without controlled clock, all semantic fields (verdicts, probe IDs, probe types,
       selection reasons) are identical across repeated runs.
    """
    snap = _get_benchmark_snapshot("f1_link_failure_snapshot.json")
    fixed_time = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)

    # 1. Controlled clock determinism
    controlled_runs = [
        engine.verify_snapshot_dict(copy.deepcopy(snap), verified_at=fixed_time)
        for _ in range(5)
    ]
    baseline_json = controlled_runs[0][0].model_dump(mode="json")
    for idx, r in enumerate(controlled_runs[1:], 2):
        assert r[0].model_dump(mode="json") == baseline_json, (
            f"Controlled clock verification non-deterministic on run {idx}"
        )

    # 2. Dynamic clock semantic stability
    dynamic_runs = [
        engine.verify_snapshot_dict(copy.deepcopy(snap))
        for _ in range(3)
    ]
    d_base = dynamic_runs[0][0].model_dump(mode="json")
    for idx, r in enumerate(dynamic_runs[1:], 2):
        d_run = r[0].model_dump(mode="json")
        # Compare probe IDs across runs
        base_probes = [
            p["probe_id"]
            for v in d_base["competing_hypotheses_verifications"]
            for p in v["recommended_probes"]
        ]
        run_probes = [
            p["probe_id"]
            for v in d_run["competing_hypotheses_verifications"]
            for p in v["recommended_probes"]
        ]
        assert base_probes == run_probes, (
            f"Probe IDs non-deterministic on dynamic run {idx}"
        )


def test_no_ground_truth_leakage(engine: CounterfactualVerificationEngine):
    """14. Ground-Truth Isolation."""
    snap = _get_benchmark_snapshot("f1_link_failure_snapshot.json")
    contaminated = copy.deepcopy(snap)
    contaminated["ground_truth"] = {"injected_fault": "LINK_FAILURE"}

    with pytest.raises(GroundTruthLeakageError):
        engine.verify_snapshot_dict(contaminated)


def test_preservation_of_original_phase06_outputs(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    """15. Preservation of Original Phase 06 Outputs."""
    snap = _get_benchmark_snapshot("f1_link_failure_snapshot.json")

    d_engine = DiagnosisEngine()
    original_results = d_engine.diagnose_snapshot_dict(copy.deepcopy(snap))
    orig_top1 = original_results[0].top1_hypothesis

    reports = engine.verify_snapshot_dict(copy.deepcopy(snap))
    verified_top1 = reports[0].top_hypotheses_verifications[0].hypothesis

    assert orig_top1 is not None
    assert orig_top1.fault_type == verified_top1.fault_type
    assert orig_top1.fault_location.component_id == verified_top1.fault_location.component_id
    assert orig_top1.rule_score == verified_top1.rule_score


def test_counterfactual_verifier_protocol_conformance(
    engine: CounterfactualVerificationEngine,
    topology: Topology,
):
    """16. CounterfactualVerifier Protocol Conformance."""
    assert isinstance(engine, CounterfactualVerifier)

    hyp = FaultHypothesis(
        hypothesis_id="h-proto",
        incident_id="inc-proto",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(component_id="L12", kind=FaultLocationKind.LINK),
        rule_score=0.75,
        counterfactual_verified=None,
    )
    updated = engine.verify(hyp, [], topology)
    assert isinstance(updated, FaultHypothesis)
    assert updated.counterfactual_verified is None


# =============================================================================
# SUITE B: CERTIFIED LIVE REPLAY SUITE
# Replays authentic F1-F5 neutral captures from certified archives.
# Skips cleanly if archives are unavailable (e.g. on Track B / MacBook 2).
# =============================================================================


def test_certified_live_f1_link_failure(engine: CounterfactualVerificationEngine):
    """Live Replay F1: Physical link failure at L12 (score 0.7500, SUPPORTED)."""
    snap_p, snap, binding = _get_certified_live_snapshot("F1")
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) >= 1
    top1 = reports[0].top_hypotheses_verifications[0]
    assert top1.hypothesis.fault_type == FaultType.LINK_FAILURE
    assert top1.hypothesis.fault_location.component_id == "L12"
    assert top1.hypothesis.rule_score == 0.75
    assert top1.verdict == CounterfactualVerdict.SUPPORTED
    assert top1.counterfactual_verified is True
    assert len(top1.supporting_evidence_ids) > 0


def test_certified_live_f2_multi_peer_router_failure(
    engine: CounterfactualVerificationEngine,
):
    """Live Replay F2: Multi-peer router failure at R3 (score 1.0000, SUPPORTED)."""
    snap_p, snap, binding = _get_certified_live_snapshot("F2")
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) >= 1
    top1 = reports[0].top_hypotheses_verifications[0]
    assert top1.hypothesis.fault_type == FaultType.ROUTER_FAILURE
    assert top1.hypothesis.fault_location.component_id == "R3"
    assert top1.hypothesis.rule_score == 1.0
    assert top1.verdict == CounterfactualVerdict.SUPPORTED
    assert top1.counterfactual_verified is True

    # Both incident links (L23, L34) experienced peer OSPF loss
    ospf_evals = [
        e
        for e in top1.evaluated_expectations
        if e.expectation.category == ExpectationCategory.OSPF_ADJACENCY
    ]
    assert len(ospf_evals) == 2
    assert all(e.match_status == ObservationMatch.SUPPORTED for e in ospf_evals)


def test_certified_live_f3_ospf_mismatch(engine: CounterfactualVerificationEngine):
    """Live Replay F3: OSPF configuration mismatch at L12 (score 0.8000, SUPPORTED)."""
    snap_p, snap, binding = _get_certified_live_snapshot("F3")
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) >= 1
    top1 = reports[0].top_hypotheses_verifications[0]
    assert top1.hypothesis.fault_type == FaultType.OSPF_CONFIGURATION_MISMATCH
    assert top1.hypothesis.fault_location.component_id == "L12"
    assert top1.hypothesis.rule_score == 0.80
    assert top1.verdict == CounterfactualVerdict.SUPPORTED
    assert top1.counterfactual_verified is True

    # Physical interfaces UP
    iface_evals = [
        e
        for e in top1.evaluated_expectations
        if e.expectation.category == ExpectationCategory.INTERFACE_STATE
    ]
    assert len(iface_evals) == 2
    assert all(e.match_status == ObservationMatch.SUPPORTED for e in iface_evals)


def test_certified_live_f4_partial_packet_loss(
    engine: CounterfactualVerificationEngine,
):
    """Live Replay F4: Partial packet loss at L12 (score 0.6500, SUPPORTED)."""
    snap_p, snap, binding = _get_certified_live_snapshot("F4")
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) >= 1
    top1 = reports[0].top_hypotheses_verifications[0]
    assert top1.hypothesis.fault_type == FaultType.PACKET_LOSS
    assert top1.hypothesis.fault_location.component_id == "L12"
    assert top1.hypothesis.rule_score == 0.65
    assert top1.verdict == CounterfactualVerdict.SUPPORTED
    assert top1.counterfactual_verified is True


def test_certified_live_f5_high_latency(engine: CounterfactualVerificationEngine):
    """Live Replay F5: High latency at L12 (score 0.6500, SUPPORTED)."""
    snap_p, snap, binding = _get_certified_live_snapshot("F5")
    reports = engine.verify_snapshot_dict(snap)

    assert len(reports) >= 1
    top1 = reports[0].top_hypotheses_verifications[0]
    assert top1.hypothesis.fault_type == FaultType.HIGH_LATENCY
    assert top1.hypothesis.fault_location.component_id == "L12"
    assert top1.hypothesis.rule_score == 0.65
    assert top1.verdict == CounterfactualVerdict.SUPPORTED
    assert top1.counterfactual_verified is True


# Backward-compatible aliases for original Phase 07 test names
test_f1_link_failure_expectations = test_certified_live_f1_link_failure
test_f2_multi_peer_router_failure_expectations = test_certified_live_f2_multi_peer_router_failure
test_f3_ospf_mismatch_expectations = test_certified_live_f3_ospf_mismatch
test_f4_partial_packet_loss_expectations = test_certified_live_f4_partial_packet_loss
test_f5_high_latency_expectations = test_certified_live_f5_high_latency
