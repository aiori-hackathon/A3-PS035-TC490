"""
NEXORA Phase 08: Safe Active Probe Planning Engine Test Suite.

Verifies all 20 required acceptance criteria:
1. F1 link failure recommendations.
2. F2 router failure vs competing links ambiguity.
3. F3 OSPF configuration mismatch recommendations.
4. F4 packet loss recommendations.
5. F5 high latency recommendations.
6. Missing observations trigger targeted probes.
7. Contradictory observations handled.
8. Collector failure distinguished from negative finding.
9. Stale evidence filtering.
10. Unknown topology components rejected.
11. Unsafe target rejection.
12. Management interface protection (eth0, 172.17.x.x).
13. Probe deduplication.
14. Ranking determinism (5x repeat runs).
15. Probe cost limits and recommendation budgets.
16. Missing collector support / unsupported capabilities.
17. No ground truth leakage.
18. No network execution (strictly PROPOSED / NOT EXECUTED).
19. No change to Phase 06/07 diagnosis results.
20. Empty and abstention outcomes.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.collectors.normalizer import EvidenceNormalizer, GroundTruthLeakageError
from app.diagnosis.engine import DiagnosisEngine
from app.probes.planner import ProbePlanner
from app.probes.policy import ProbeSafetyPolicy
from app.schemas.counterfactual import (
    VerificationReport,
)
from app.schemas.diagnosis import DiagnosisResult, EvidenceCertificate, RankedHypothesis
from app.schemas.evidence import (
    CollectionMethod,
    EvidenceSourceType,
    InterfaceObservation,
    ObservationStatus,
)
from app.schemas.hypothesis import (
    FaultHypothesis,
    FaultLocation,
    FaultLocationKind,
    FaultType,
)
from app.schemas.probe import (
    ExecutionAuthorizationState,
    PlannedProbe,
    ProbeRequest,
    ProbeSafetyStatus,
    ProbeType,
)
from app.schemas.topology import Topology
from app.topology.graph import build_expected_topology_graph
from app.verification.engine import CounterfactualVerificationEngine

_BASE_DIR = Path(__file__).resolve().parents[2]
_LIVE_ARCHIVES = Path("/Users/azriel/Nexora-backups/live-evidence")
_FALLBACK_DATASETS = _BASE_DIR / "evaluation/datasets/observations"


def _get_snapshot_path(scenario_code: str) -> Path:
    """Find the certified neutral snapshot for a scenario."""
    if _LIVE_ARCHIVES.exists():
        for d in _LIVE_ARCHIVES.iterdir():
            if d.is_dir() and d.name.startswith(f"{scenario_code.lower()}-"):
                if (d / "snapshot.json").exists():
                    return d / "snapshot.json"
                for sub in d.iterdir():
                    if sub.is_dir() and (sub / "snapshot.json").exists():
                        return sub / "snapshot.json"

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


def _make_mock_diagnosis(
    incident_id: str,
    ranked_hypotheses: list[RankedHypothesis],
    status: str = "DIAGNOSED",
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


@pytest.fixture
def topology() -> Topology:
    return build_expected_topology_graph().topology


@pytest.fixture
def planner() -> ProbePlanner:
    return ProbePlanner()


@pytest.fixture
def verifier() -> CounterfactualVerificationEngine:
    return CounterfactualVerificationEngine()


@pytest.fixture
def diagnosis_engine() -> DiagnosisEngine:
    return DiagnosisEngine()


# -----------------------------------------------------------------------------
# 1. F1 Link Failure
# -----------------------------------------------------------------------------
def test_f1_link_failure_plan(planner: ProbePlanner):
    """1. F1 link failure recommends interface state and ping probes on L12."""
    raw = json.loads(_get_snapshot_path("F1").read_text())
    plans = planner.plan_snapshot_dict(raw)
    assert len(plans) == 1
    plan = plans[0]
    assert plan.incident_id.startswith("incident-")
    assert not plan.is_abstention
    assert len(plan.recommended_probes) >= 1

    # Check that recommended probes target L12 or endpoints R1/R2
    target_components = {p.target_component for p in plan.recommended_probes}
    assert "L12" in target_components

    for p in plan.recommended_probes:
        assert p.safety_status == ProbeSafetyStatus.SAFE
        assert p.execution_authorization == ExecutionAuthorizationState.PROPOSED_NOT_EXECUTED
        assert p.probe_request.timeout_s <= 30


# -----------------------------------------------------------------------------
# 2. F2 Router Failure vs Competing Links Ambiguity
# -----------------------------------------------------------------------------
def test_f2_router_failure_competing_links_ambiguity(
    planner: ProbePlanner, topology: Topology, verifier: CounterfactualVerificationEngine
):
    """2. F2 router failure vs adjacent links ambiguity generates discriminating probes."""
    raw = json.loads(_get_snapshot_path("F2").read_text())
    topo = Topology.model_validate(raw["topology"])
    records = [EvidenceNormalizer.deserialize_record(r) for r in raw["evidence_records"]]

    h_r3 = FaultHypothesis(
        hypothesis_id="h-r3",
        incident_id="inc-f2-test",
        fault_type=FaultType.ROUTER_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.ROUTER, component_id="R3"),
        rule_score=1.0,
    )
    h_l23 = FaultHypothesis(
        hypothesis_id="h-l23",
        incident_id="inc-f2-test",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L23"),
        rule_score=0.8,
    )
    h_l34 = FaultHypothesis(
        hypothesis_id="h-l34",
        incident_id="inc-f2-test",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L34"),
        rule_score=0.8,
    )

    diag = _make_mock_diagnosis(
        incident_id="inc-f2-test",
        ranked_hypotheses=[
            RankedHypothesis(rank=1, hypothesis=h_r3),
            RankedHypothesis(rank=2, hypothesis=h_l23),
            RankedHypothesis(rank=3, hypothesis=h_l34),
        ],
    )

    verif_report = verifier.verify_diagnosis(diag, records, topo)
    plan = planner.plan_probes(diag, verif_report, records, topo)

    assert len(plan.ambiguities_addressed) >= 1
    assert any("R3" in a for a in plan.ambiguities_addressed)
    assert len(plan.recommended_probes) >= 3

    # Probes should check peer interfaces (R2 eth2, R4 eth1) and peer OSPF
    sources = {p.source_router for p in plan.recommended_probes}
    assert "R2" in sources
    assert "R4" in sources

    # Check discrimination logic
    iface_probes = [p for p in plan.recommended_probes if p.probe_type == ProbeType.INTERFACE_STATE]
    assert len(iface_probes) >= 2
    for p in iface_probes:
        assert "ROUTER_FAILURE at R3" in p.discriminating_outcomes.hypotheses_supported_if_true
        assert any(
            "LINK_FAILURE" in h for h in p.discriminating_outcomes.hypotheses_supported_if_false
        )


# -----------------------------------------------------------------------------
# 3. F3 OSPF Configuration Mismatch
# -----------------------------------------------------------------------------
def test_f3_ospf_mismatch_plan(planner: ProbePlanner):
    """3. F3 OSPF configuration mismatch recommends neighbor and interface checks."""
    raw = json.loads(_get_snapshot_path("F3").read_text())
    plans = planner.plan_snapshot_dict(raw)
    assert len(plans) == 1
    plan = plans[0]
    assert not plan.is_abstention
    assert len(plan.recommended_probes) >= 1

    probe_types = {p.probe_type for p in plan.recommended_probes}
    assert ProbeType.OSPF_NEIGHBOUR in probe_types or ProbeType.INTERFACE_STATE in probe_types


# -----------------------------------------------------------------------------
# 4. F4 Packet Loss
# -----------------------------------------------------------------------------
def test_f4_packet_loss_plan(
    planner: ProbePlanner, topology: Topology, verifier: CounterfactualVerificationEngine
):
    """4. F4 packet loss recommends bounded ping to verify packet loss rate."""
    h_f4 = FaultHypothesis(
        hypothesis_id="h-f4",
        incident_id="inc-f4",
        fault_type=FaultType.PACKET_LOSS,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.9,
    )
    diag = _make_mock_diagnosis(
        incident_id="inc-f4",
        ranked_hypotheses=[RankedHypothesis(rank=1, hypothesis=h_f4)],
    )

    verif_report = verifier.verify_diagnosis(diag, [], topology)
    plan = planner.plan_probes(diag, verif_report, [], topology)

    assert len(plan.recommended_probes) >= 1
    ping_probes = [p for p in plan.recommended_probes if p.probe_type == ProbeType.PING]
    assert len(ping_probes) >= 1
    assert ping_probes[0].target_component == "L12"
    assert "packet loss" in ping_probes[0].selection_reason.lower()


# -----------------------------------------------------------------------------
# 5. F5 High Latency
# -----------------------------------------------------------------------------
def test_f5_high_latency_plan(
    planner: ProbePlanner, topology: Topology, verifier: CounterfactualVerificationEngine
):
    """5. F5 high latency recommends bounded ping to verify round-trip time."""
    h_f5 = FaultHypothesis(
        hypothesis_id="h-f5",
        incident_id="inc-f5",
        fault_type=FaultType.HIGH_LATENCY,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.9,
    )
    diag = _make_mock_diagnosis(
        incident_id="inc-f5",
        ranked_hypotheses=[RankedHypothesis(rank=1, hypothesis=h_f5)],
    )

    verif_report = verifier.verify_diagnosis(diag, [], topology)
    plan = planner.plan_probes(diag, verif_report, [], topology)

    assert len(plan.recommended_probes) >= 1
    ping_probes = [p for p in plan.recommended_probes if p.probe_type == ProbeType.PING]
    assert len(ping_probes) >= 1
    assert ping_probes[0].target_component == "L12"
    assert "latency" in ping_probes[0].selection_reason.lower()


# -----------------------------------------------------------------------------
# 6. Missing Observations Trigger Targeted Probes
# -----------------------------------------------------------------------------
def test_missing_observations_trigger_probes(
    planner: ProbePlanner, topology: Topology, verifier: CounterfactualVerificationEngine
):
    """6. Empty evidence results in INSUFFICIENT_EVIDENCE and generates missing probes."""
    h = FaultHypothesis(
        hypothesis_id="h-missing-test",
        incident_id="inc-missing",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.7,
    )
    diag = _make_mock_diagnosis(
        incident_id="inc-missing",
        ranked_hypotheses=[RankedHypothesis(rank=1, hypothesis=h)],
        status="INSUFFICIENT_EVIDENCE",
    )
    verif_report = verifier.verify_diagnosis(diag, [], topology)
    plan = planner.plan_probes(diag, verif_report, [], topology)

    assert len(plan.recommended_probes) >= 1
    assert any(p.target_component == "L12" for p in plan.recommended_probes)


# -----------------------------------------------------------------------------
# 7. Contradictory Observations Handled
# -----------------------------------------------------------------------------
def test_contradictory_observations_handled(
    planner: ProbePlanner, topology: Topology, verifier: CounterfactualVerificationEngine
):
    """7. Contradictory observations on one candidate route attention to alternatives."""
    # Observe interface UP when link failure is hypothesized
    obs = InterfaceObservation(
        evidence_id="ev-contra-iface",
        source_router="R1",
        source_interface="eth1",
        observed_status="up",
        source_type=EvidenceSourceType.INTERFACE_POLL,
        event_type="INTERFACE_STATE_OBSERVED",
        observed_at=datetime.now(UTC),
        collected_at=datetime.now(UTC),
        collection_method=CollectionMethod.PERIODIC_POLL,
        collection_status=ObservationStatus.OBSERVED,
    )
    h_link = FaultHypothesis(
        hypothesis_id="h-contra-link",
        incident_id="inc-contra",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.5,
    )
    h_ospf = FaultHypothesis(
        hypothesis_id="h-alt-ospf",
        incident_id="inc-contra",
        fault_type=FaultType.OSPF_CONFIGURATION_MISMATCH,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.8,
    )
    diag = _make_mock_diagnosis(
        incident_id="inc-contra",
        ranked_hypotheses=[
            RankedHypothesis(rank=1, hypothesis=h_ospf),
            RankedHypothesis(rank=2, hypothesis=h_link),
        ],
    )
    verif_report = verifier.verify_diagnosis(diag, [obs], topology)
    plan = planner.plan_probes(diag, verif_report, [obs], topology)

    assert len(plan.recommended_probes) >= 1
    # Top probe targets OSPF_CONFIGURATION_MISMATCH on L12
    top_probe = plan.recommended_probes[0]
    assert top_probe.target_component in {"L12", "R1", "R2"}
    assert "OSPF" in (top_probe.related_fault_type or "") or top_probe.probe_type in {
        ProbeType.OSPF_NEIGHBOUR,
        ProbeType.INTERFACE_STATE,
    }


# -----------------------------------------------------------------------------
# 8. Collector Failure Distinguished From Negative Finding
# -----------------------------------------------------------------------------
def test_collector_failure_distinguished_from_negative_finding(
    planner: ProbePlanner, topology: Topology, verifier: CounterfactualVerificationEngine
):
    """8. Collector failure (COLLECTION_FAILED) is treated as missing evidence to recheck."""
    obs_fail = InterfaceObservation(
        evidence_id="ev-fail-1",
        source_router="R1",
        source_interface="eth1",
        observed_status="unknown",
        source_type=EvidenceSourceType.INTERFACE_POLL,
        event_type="INTERFACE_STATE_OBSERVED",
        observed_at=datetime.now(UTC),
        collected_at=datetime.now(UTC),
        collection_method=CollectionMethod.PERIODIC_POLL,
        collection_status=ObservationStatus.COLLECTION_FAILED,
    )
    h = FaultHypothesis(
        hypothesis_id="h-fail-test",
        incident_id="inc-fail",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.7,
    )
    diag = _make_mock_diagnosis(
        incident_id="inc-fail",
        ranked_hypotheses=[RankedHypothesis(rank=1, hypothesis=h)],
        status="INSUFFICIENT_EVIDENCE",
    )
    verif_report = verifier.verify_diagnosis(diag, [obs_fail], topology)
    plan = planner.plan_probes(diag, verif_report, [obs_fail], topology)

    # Should plan an interface state probe to re-examine R1 eth1
    assert any(
        p.probe_type == ProbeType.INTERFACE_STATE
        and p.source_router == "R1"
        and p.probe_request.target_interface == "eth1"
        for p in plan.recommended_probes
    )


# -----------------------------------------------------------------------------
# 9. Stale Evidence Filtering
# -----------------------------------------------------------------------------
def test_stale_evidence_filtering(
    planner: ProbePlanner, topology: Topology, verifier: CounterfactualVerificationEngine
):
    """9. Telemetry outside the incident collection window is ignored, prompting probe."""
    now = datetime.now(UTC)
    old_time = now - timedelta(hours=2)
    obs_old = InterfaceObservation(
        evidence_id="ev-stale",
        source_router="R1",
        source_interface="eth1",
        observed_status="down",
        source_type=EvidenceSourceType.INTERFACE_POLL,
        event_type="INTERFACE_STATE_OBSERVED",
        observed_at=old_time,
        collected_at=old_time,
        collection_method=CollectionMethod.PERIODIC_POLL,
        collection_status=ObservationStatus.OBSERVED,
    )
    h = FaultHypothesis(
        hypothesis_id="h-stale",
        incident_id="inc-stale",
        fault_type=FaultType.LINK_FAILURE,
        fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
        rule_score=0.7,
    )
    diag = _make_mock_diagnosis(
        incident_id="inc-stale",
        ranked_hypotheses=[RankedHypothesis(rank=1, hypothesis=h)],
        status="INSUFFICIENT_EVIDENCE",
    )
    # Window is current time, old evidence excluded
    w_start = now - timedelta(minutes=5)
    w_end = now
    verif_report = verifier.verify_diagnosis(
        diag, [obs_old], topology, incident_window=(w_start, w_end)
    )
    plan = planner.plan_probes(diag, verif_report, [obs_old], topology)

    assert len(plan.recommended_probes) >= 1
    assert any(p.target_component == "L12" for p in plan.recommended_probes)


# -----------------------------------------------------------------------------
# 10. Unknown Topology Components Rejected
# -----------------------------------------------------------------------------
def test_unknown_topology_components_rejected(planner: ProbePlanner, topology: Topology):
    """10. Probes targeting non-existent routers (R99) or links are rejected with UNSAFE."""
    policy = ProbeSafetyPolicy(topology)
    bad_req = ProbeRequest(
        probe_id="req-bad-router",
        incident_id="inc-bad",
        probe_type=ProbeType.PING,
        source_router="R99",
        target_router="R1",
        target_address="192.168.255.1",
        selection_reason="Testing bad router",
        timeout_s=5,
        requested_at=datetime.now(UTC),
    )
    is_safe, status, rationale = policy.validate_request(bad_req)
    assert not is_safe
    assert status == ProbeSafetyStatus.UNSAFE
    assert "R99" in rationale


# -----------------------------------------------------------------------------
# 11. Unsafe Target Rejection
# -----------------------------------------------------------------------------
def test_unsafe_target_rejection(planner: ProbePlanner, topology: Topology):
    """11. External IP targets outside topology (e.g. 8.8.8.8) are rejected with UNSAFE."""
    policy = ProbeSafetyPolicy(topology)
    bad_req = ProbeRequest(
        probe_id="req-bad-ip",
        incident_id="inc-bad-ip",
        probe_type=ProbeType.PING,
        source_router="R1",
        target_address="8.8.8.8",
        selection_reason="Testing external internet IP",
        timeout_s=5,
        requested_at=datetime.now(UTC),
    )
    is_safe, status, rationale = policy.validate_request(bad_req)
    assert not is_safe
    assert status == ProbeSafetyStatus.UNSAFE
    assert "outside approved network topology" in rationale


# -----------------------------------------------------------------------------
# 12. Management Interface Protection
# -----------------------------------------------------------------------------
def test_management_interface_protection(planner: ProbePlanner, topology: Topology):
    """12. Probes targeting eth0 or management subnets are rejected with POLICY_VIOLATION."""
    policy = ProbeSafetyPolicy(topology)
    bad_req_iface = ProbeRequest(
        probe_id="req-mgmt-iface",
        incident_id="inc-mgmt",
        probe_type=ProbeType.INTERFACE_STATE,
        source_router="R1",
        target_interface="eth0",
        selection_reason="Testing management interface access",
        timeout_s=5,
        requested_at=datetime.now(UTC),
    )
    is_safe, status, rationale = policy.validate_request(bad_req_iface)
    assert not is_safe
    assert status == ProbeSafetyStatus.POLICY_VIOLATION
    assert "protected management interface" in rationale

    # Management IP check
    bad_req_ip = ProbeRequest(
        probe_id="req-mgmt-ip",
        incident_id="inc-mgmt",
        probe_type=ProbeType.PING,
        source_router="R1",
        target_address="172.17.0.2",
        selection_reason="Testing Docker management IP",
        timeout_s=5,
        requested_at=datetime.now(UTC),
    )
    is_safe2, status2, rationale2 = policy.validate_request(bad_req_ip)
    assert not is_safe2
    assert status2 == ProbeSafetyStatus.POLICY_VIOLATION
    assert "protected subnet" in rationale2


# -----------------------------------------------------------------------------
# 13. Probe Deduplication
# -----------------------------------------------------------------------------
def test_probe_deduplication(planner: ProbePlanner, topology: Topology):
    """13. Duplicate candidate probes targeting the same check are deduplicated."""
    req1 = ProbeRequest(
        probe_id="req-dup-1",
        incident_id="inc-dup",
        probe_type=ProbeType.INTERFACE_STATE,
        source_router="R1",
        target_interface="eth1",
        selection_reason="Check 1",
        requested_at=datetime.now(UTC),
    )
    req2 = ProbeRequest(
        probe_id="req-dup-2",
        incident_id="inc-dup",
        probe_type=ProbeType.INTERFACE_STATE,
        source_router="R1",
        target_interface="eth1",
        selection_reason="Check 2",
        requested_at=datetime.now(UTC),
    )
    p1 = PlannedProbe(
        plan_id="plan-1",
        incident_id="inc-dup",
        probe_request=req1,
        probe_type=ProbeType.INTERFACE_STATE,
        source_router="R1",
        target_interface="eth1",
        target_component="L12",
        selection_reason="Reason 1",
        discriminating_outcomes={
            "observation_if_true": "T",
            "observation_if_false": "F",
        },
        priority_score=0.85,
        ranking_rationale="R1",
    )
    p2 = PlannedProbe(
        plan_id="plan-2",
        incident_id="inc-dup",
        probe_request=req2,
        probe_type=ProbeType.INTERFACE_STATE,
        source_router="R1",
        target_interface="eth1",
        target_component="L12",
        selection_reason="Reason 2",
        discriminating_outcomes={
            "observation_if_true": "T",
            "observation_if_false": "F",
        },
        priority_score=0.95,
        ranking_rationale="R2",
    )
    deduped = planner._deduplicate_probes([p1, p2])
    assert len(deduped) == 1
    assert deduped[0].priority_score == 0.95


# -----------------------------------------------------------------------------
# 14. Ranking Determinism Across 5x Repeat Runs
# -----------------------------------------------------------------------------
def test_ranking_determinism_5x(planner: ProbePlanner):
    """14. 5x repeated runs produce byte-identical sorted recommendations and plan IDs."""
    raw = json.loads(_get_snapshot_path("F1").read_text())
    first_run = planner.plan_snapshot_dict(raw)[0]
    first_ids = [p.plan_id for p in first_run.recommended_probes]
    first_scores = [p.priority_score for p in first_run.recommended_probes]

    for _ in range(4):
        run_i = planner.plan_snapshot_dict(raw)[0]
        ids_i = [p.plan_id for p in run_i.recommended_probes]
        scores_i = [p.priority_score for p in run_i.recommended_probes]
        assert ids_i == first_ids
        assert scores_i == first_scores


# -----------------------------------------------------------------------------
# 15. Probe Cost Limits and Budgets
# -----------------------------------------------------------------------------
def test_probe_cost_limits(planner: ProbePlanner, topology: Topology):
    """15. Recommendations respect max_recommended_probes and cost budgets."""
    policy = ProbeSafetyPolicy(topology, max_recommended_probes=2, max_cost_budget=3.0)
    custom_planner = ProbePlanner(safety_policy=policy)
    raw = json.loads(_get_snapshot_path("F2").read_text())
    plans = custom_planner.plan_snapshot_dict(raw)
    assert len(plans) == 1
    plan = plans[0]
    assert len(plan.recommended_probes) <= 2
    total_cost = sum(p.cost.relative_cost_score for p in plan.recommended_probes)
    assert total_cost <= 3.0


# -----------------------------------------------------------------------------
# 16. Missing Collector Support
# -----------------------------------------------------------------------------
def test_missing_collector_unsupported(planner: ProbePlanner, topology: Topology):
    """16. Injected invalid/unsupported probe type is captured in unsupported_probes."""
    policy = ProbeSafetyPolicy(topology)
    # Validate method handles unsupported probe types
    req = ProbeRequest(
        probe_id="req-custom-type",
        incident_id="inc-test",
        probe_type=ProbeType.PING,
        source_router="R1",
        target_address="10.0.12.2",
        selection_reason="Test unsupported",
        requested_at=datetime.now(UTC),
    )
    # Simulate an invalid probe type attribute on the request object
    object.__setattr__(req, "probe_type", "BGP_SESSION_RESET")
    is_safe, status, rationale = policy.validate_request(req)
    assert not is_safe
    assert status == ProbeSafetyStatus.UNSUPPORTED_CAPABILITY


# -----------------------------------------------------------------------------
# 17. No Ground Truth Leakage
# -----------------------------------------------------------------------------
def test_no_ground_truth_leakage(planner: ProbePlanner):
    """17. Snapshots containing ground-truth keys are rejected immediately."""
    raw = json.loads(_get_snapshot_path("F1").read_text())
    leaky = copy.deepcopy(raw)
    leaky["ground_truth"] = {"scenario": "F1_LINK_FAILURE", "target": "L12"}

    with pytest.raises(GroundTruthLeakageError):
        planner.plan_snapshot_dict(leaky)


# -----------------------------------------------------------------------------
# 18. No Network Execution (Planning Invariant)
# -----------------------------------------------------------------------------
def test_no_network_execution(planner: ProbePlanner):
    """18. All generated probes are PROPOSED_NOT_EXECUTED with zero execution side effects."""
    raw = json.loads(_get_snapshot_path("F1").read_text())
    plans = planner.plan_snapshot_dict(raw)
    for plan in plans:
        for p in plan.recommended_probes:
            assert p.execution_authorization == ExecutionAuthorizationState.PROPOSED_NOT_EXECUTED
            assert not hasattr(p, "execution_result")
            assert not hasattr(p, "output_data")


# -----------------------------------------------------------------------------
# 19. No Change to Phase 06/07 Diagnosis Results
# -----------------------------------------------------------------------------
def test_no_change_to_diagnosis_results(
    planner: ProbePlanner,
    diagnosis_engine: DiagnosisEngine,
    verifier: CounterfactualVerificationEngine,
):
    """19. Generating a probe plan does not alter candidate rankings, scores, or reports."""
    raw = json.loads(_get_snapshot_path("F1").read_text())
    diag_before = diagnosis_engine.diagnose_snapshot_dict(raw)[0]
    top_score_before = diag_before.ranked_hypotheses[0].hypothesis.rule_score

    plans = planner.plan_snapshot_dict(raw)
    assert len(plans) == 1

    diag_after = diagnosis_engine.diagnose_snapshot_dict(raw)[0]
    top_score_after = diag_after.ranked_hypotheses[0].hypothesis.rule_score
    assert top_score_before == top_score_after
    assert len(diag_before.ranked_hypotheses) == len(diag_after.ranked_hypotheses)


# -----------------------------------------------------------------------------
# 20. Empty and Abstention Outcomes
# -----------------------------------------------------------------------------
def test_empty_and_abstention_outcomes(planner: ProbePlanner, topology: Topology):
    """20. Explicit abstention result produced when no probe is needed or possible."""
    empty_diag = _make_mock_diagnosis(
        incident_id="inc-empty",
        ranked_hypotheses=[],
    )
    empty_report = VerificationReport(
        incident_id="inc-empty",
        verified_at=datetime.now(UTC),
        engine_version="test-1.0",
        top_hypotheses_verifications=[],
        competing_hypotheses_verifications=[],
        summary="Empty report",
    )

    plan = planner.plan_probes(empty_diag, empty_report, [], topology)
    assert plan.is_abstention
    assert plan.abstention_reason is not None
    assert len(plan.recommended_probes) == 0
    assert "abstained" in plan.summary.lower()
