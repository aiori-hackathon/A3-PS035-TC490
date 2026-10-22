"""Phase 06 deterministic diagnosis, abstention, and provenance regressions.

Synthetic cases describe observations only. Recorded snapshot filenames are used
exclusively by these offline tests and are never passed into the diagnoser.
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.collectors.normalizer import EvidenceNormalizer, GroundTruthLeakageError
from app.core.config import Settings
from app.diagnosis.engine import (
    DiagnosisEngine,
    EvidenceCertificateBuilder,
    EvidenceSufficiencyEvaluator,
    HypothesisGenerator,
    RuleBasedDiagnoser,
)
from app.schemas.diagnosis import DiagnosisResult, DiagnosisStatus
from app.schemas.evidence import (
    CollectionMethod,
    EvidenceRecord,
    EvidenceSourceType,
    InterfaceObservation,
    ObservationStatus,
    OSPFObservation,
    PingMeasurement,
    RouteObservation,
    SyslogEvent,
    SyslogSeverity,
    TracerouteHop,
    TracerouteObservation,
)
from app.schemas.hypothesis import FaultType
from app.schemas.incident import Incident
from app.schemas.topology import Topology
from app.topology.graph import build_expected_topology_graph
from app.topology.identity import ROUTER_TO_OSPF_ID

_TS = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
_DATASETS = Path(__file__).resolve().parents[2] / "evaluation/datasets/observations"
_LINKS = {
    "L12": ("R1", "eth1", "R2", "eth1", "10.0.12.2"),
    "L23": ("R2", "eth2", "R3", "eth1", "10.0.23.2"),
    "L34": ("R3", "eth2", "R4", "eth1", "10.0.34.2"),
    "L45": ("R4", "eth2", "R5", "eth1", "10.0.45.2"),
    "L51": ("R5", "eth2", "R1", "eth2", "10.0.15.2"),
}


@pytest.fixture
def topology() -> Topology:
    return build_expected_topology_graph().topology


def _incident(topology: Topology, **changes) -> Incident:
    values = {
        "incident_id": "inc-test-06",
        "detected_at": _TS,
        "collection_window_start": _TS - timedelta(seconds=10),
        "collection_window_end": _TS + timedelta(seconds=30),
        "topology_snapshot_id": topology.snapshot_id,
    }
    values.update(changes)
    return Incident(**values)


def _common(eid: str, router: str, source: EvidenceSourceType, **changes) -> dict:
    values = {
        "evidence_id": eid,
        "source_router": router,
        "source_type": source,
        "event_type": "OBSERVATION",
        "observed_at": _TS,
        "collected_at": _TS,
        "collection_method": CollectionMethod.PERIODIC_POLL,
        "collection_status": ObservationStatus.OBSERVED,
    }
    values.update(changes)
    return values


def _iface(eid: str, router: str, interface: str, state: str, **changes) -> InterfaceObservation:
    return InterfaceObservation(
        **_common(
            eid, router, EvidenceSourceType.INTERFACE_POLL,
            event_type="INTERFACE_DOWN_OBSERVED" if state == "down" else "INTERFACE_STATE_OBSERVED",
            source_interface=interface, **changes,
        ),
        observed_status=state,
    )


def _ospf(
    eid: str, router: str, neighbour: str, interface: str,
    state: str = "Down", address: str = "10.0.12.2", **changes,
) -> OSPFObservation:
    return OSPFObservation(
        **_common(
            eid, router, EvidenceSourceType.OSPF_API,
            event_type="OSPF_NEIGHBOUR_FULL" if state.startswith("Full") else "OSPF_NEIGHBOUR_DOWN",
            source_interface=interface, **changes,
        ),
        neighbour_router_id=ROUTER_TO_OSPF_ID[neighbour],
        neighbour_address=address,
        adjacency_state=state,
    )


def _ping(
    eid: str, router: str = "R1", target: str = "10.0.12.2", loss: float = 0,
    latency: float | None = 1.0, **changes,
) -> PingMeasurement:
    return PingMeasurement(
        **_common(eid, router, EvidenceSourceType.ACTIVE_PING, event_type="PING_RESULT", **changes),
        probe_source=router,
        target_address=target,
        packets_sent=10,
        packets_received=round(10 * (1 - loss / 100)),
        packet_loss_pct=loss,
        rtt_min_ms=latency,
        rtt_avg_ms=latency,
        rtt_max_ms=latency,
    )


def _route(eid: str, prefix: str = "192.168.255.3/32", **changes) -> RouteObservation:
    return RouteObservation(
        **_common(eid, "R1", EvidenceSourceType.ROUTING_TABLE, event_type="ROUTE_MISSING", **changes),
        destination_prefix=prefix,
        route_type="OSPF",
        is_present=False,
    )


def _link_failure(link: str = "L12") -> list[EvidenceRecord]:
    ra, ia, rb, _, address = _LINKS[link]
    return [
        _iface("ev-interface-down", ra, ia, "down"),
        _ospf("ev-adjacency-down", ra, rb, ia, address=address),
    ]


def _mismatch(link: str = "L12") -> list[EvidenceRecord]:
    ra, ia, rb, ib, address = _LINKS[link]
    return [
        _iface("ev-interface-a-up", ra, ia, "up"),
        _iface("ev-interface-b-up", rb, ib, "up"),
        _ospf("ev-adjacency-down", ra, rb, ia, address=address),
    ]


def _performance(fault: FaultType, link: str = "L12") -> list[EvidenceRecord]:
    ra, ia, rb, ib, address = _LINKS[link]
    return [
        _iface("ev-interface-a-up", ra, ia, "up"),
        _iface("ev-interface-b-up", rb, ib, "up"),
        _ping(
            "ev-ping-degraded", ra, address,
            loss=40 if fault == FaultType.PACKET_LOSS else 0,
            latency=1 if fault == FaultType.PACKET_LOSS else 200,
        ),
    ]


def _router_failure() -> list[EvidenceRecord]:
    return [
        EvidenceRecord(**_common(
            "ev-router-unavailable", "R3", EvidenceSourceType.INTERFACE_POLL,
            event_type="ROUTER_UNAVAILABLE", collection_status=ObservationStatus.COLLECTION_FAILED,
        )),
        _ospf("ev-r2-lost-r3", "R2", "R3", "eth2", address="10.0.23.2"),
        _ospf("ev-r4-lost-r3", "R4", "R3", "eth1", address="10.0.34.1"),
        _iface("ev-r2-carrier-up", "R2", "eth2", "up"),
        _iface("ev-r4-carrier-up", "R4", "eth1", "up"),
        _ping("ev-r3-timeout", "R1", "192.168.255.3", loss=100, latency=None,
              collection_status=ObservationStatus.COLLECTION_FAILED),
    ]


def _diagnose(topology: Topology, records: list[EvidenceRecord], **incident_changes) -> DiagnosisResult:
    return DiagnosisEngine().diagnose(_incident(topology, **incident_changes), records, topology)


def _snapshot(topology: Topology, records: list[EvidenceRecord]) -> dict:
    return {
        "snapshot_id": "opaque-adapter-regression",
        "collection_window_start": (_TS - timedelta(seconds=10)).isoformat(),
        "collection_window_end": (_TS + timedelta(seconds=30)).isoformat(),
        "topology": topology.model_dump(mode="json"),
        "evidence_records": [record.model_dump(mode="json") for record in records],
    }


def _trace(eid: str, routers: list[str]) -> TracerouteObservation:
    return TracerouteObservation(
        **_common(eid, "R1", EvidenceSourceType.ACTIVE_TRACEROUTE, event_type="TRACEROUTE_RESULT"),
        probe_source="R1", target_address="192.168.255.3", destination_reached=True,
        total_hops=len(routers),
        hops=[TracerouteHop(hop_number=n, hop_address=f"192.168.255.{router[1:]}", rtt_ms=100)
              for n, router in enumerate(routers, 1)],
    )


def _rank_signature(result: DiagnosisResult) -> list[tuple]:
    return [
        (rh.rank, rh.hypothesis.fault_type, rh.hypothesis.fault_location.component_id,
         rh.hypothesis.rule_score)
        for rh in result.ranked_hypotheses
    ]


def _find(result: DiagnosisResult, fault: FaultType, component: str):
    return next(
        rh.hypothesis for rh in result.ranked_hypotheses
        if rh.hypothesis.fault_type == fault
        and rh.hypothesis.fault_location.component_id == component
    )


@pytest.mark.parametrize(
    ("fault", "component", "records"),
    [
        (FaultType.LINK_FAILURE, "L12", _link_failure()),
        (FaultType.ROUTER_FAILURE, "R3", _router_failure()),
        (FaultType.OSPF_CONFIGURATION_MISMATCH, "L12", _mismatch()),
        (FaultType.PACKET_LOSS, "L12", _performance(FaultType.PACKET_LOSS)),
        (FaultType.HIGH_LATENCY, "L12", _performance(FaultType.HIGH_LATENCY)),
    ],
)
def test_five_fault_categories_have_evidence_based_top1(topology, fault, component, records):
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.DIAGNOSED
    assert result.top1_hypothesis is not None
    assert result.top1_hypothesis.fault_type == fault
    assert result.top1_hypothesis.fault_location.component_id == component
    assert result.top1_hypothesis.rule_score >= 0.65
    assert result.top1_hypothesis == result.top3_hypotheses[0]
    assert result.evidence_certificate.evidence_sufficiency_met


@pytest.mark.parametrize("link", _LINKS)
def test_physical_link_localisation_uses_both_topology_endpoints(topology, link):
    result = _diagnose(topology, _link_failure(link))
    top = result.top1_hypothesis
    assert top is not None
    assert top.fault_type == FaultType.LINK_FAILURE
    assert top.fault_location.component_id == link
    ra, _, rb, _, _ = _LINKS[link]
    assert set(top.fault_location.affected_routers) == {ra, rb}


@pytest.mark.parametrize("link", ["L23", "L34", "L45", "L51"])
@pytest.mark.parametrize("fault", [FaultType.PACKET_LOSS, FaultType.HIGH_LATENCY])
def test_performance_probe_maps_to_actual_link(topology, link, fault):
    result = _diagnose(topology, _performance(fault, link))
    assert result.top1_hypothesis is not None
    assert result.top1_hypothesis.fault_type == fault
    assert result.top1_hypothesis.fault_location.component_id == link


def test_topology_interface_names_are_used_instead_of_fixed_lab_names(topology):
    data = topology.model_dump(mode="json")
    for router in data["routers"]:
        if router["router_id"] == "R1":
            for interface in router["interfaces"]:
                if interface["interface_name"] == "eth1":
                    interface["interface_name"] = "core0"
    for link in data["links"]:
        if link["link_id"] == "L12":
            link["interface_a"] = "core0"
    for adjacency in data["adjacencies"]:
        if adjacency["local_router"] == "R1" and adjacency["local_interface"] == "eth1":
            adjacency["local_interface"] = "core0"
    changed = Topology.model_validate(data)
    records = [
        _iface("ev-new-name-down", "R1", "core0", "down"),
        _ospf("ev-new-name-ospf", "R1", "R2", "core0"),
    ]
    result = _diagnose(changed, records)
    assert result.top1_hypothesis is not None
    assert result.top1_hypothesis.fault_location.component_id == "L12"


def test_support_contradiction_ids_are_real_disjoint_and_explained(topology):
    records = _link_failure() + [_iface("ev-opposing-interface-up", "R1", "eth1", "up")]
    result = _diagnose(topology, records)
    link = _find(result, FaultType.LINK_FAILURE, "L12")
    assert "ev-opposing-interface-up" in link.contradictory_evidence_ids
    assert "ev-interface-down" in link.supporting_evidence_ids
    all_ids = {record.evidence_id for record in records}
    for ranked in result.ranked_hypotheses:
        hypothesis = ranked.hypothesis
        supporting = set(hypothesis.supporting_evidence_ids)
        contradictory = set(hypothesis.contradictory_evidence_ids)
        assert supporting | contradictory <= all_ids
        assert not supporting & contradictory
        assert len(supporting) == len(hypothesis.supporting_evidence_ids)
        assert len(contradictory) == len(hypothesis.contradictory_evidence_ids)
        assert hypothesis.reasoning_trace
        trace = " ".join(hypothesis.reasoning_trace)
        assert all(eid in trace for eid in supporting | contradictory)


def test_healthy_interfaces_support_configuration_mismatch(topology):
    result = _diagnose(topology, _mismatch())
    hypothesis = _find(result, FaultType.OSPF_CONFIGURATION_MISMATCH, "L12")
    assert {"ev-interface-a-up", "ev-interface-b-up", "ev-adjacency-down"} <= set(
        hypothesis.supporting_evidence_ids
    )
    assert not hypothesis.contradictory_evidence_ids


def test_full_ospf_on_same_direction_contradicts_configuration_mismatch(topology):
    records = _mismatch()
    clean = _diagnose(topology, records)
    conflicting = _diagnose(topology, records + [
        _ospf("ev-opposing-full", "R1", "R2", "eth1", state="Full/-"),
    ])
    before = _find(clean, FaultType.OSPF_CONFIGURATION_MISMATCH, "L12")
    after = _find(conflicting, FaultType.OSPF_CONFIGURATION_MISMATCH, "L12")
    assert "ev-opposing-full" in after.contradictory_evidence_ids
    assert after.rule_score < before.rule_score
    assert conflicting.status != DiagnosisStatus.DIAGNOSED


def test_unrelated_healthy_link_does_not_contradict_failed_link(topology):
    records = _link_failure() + [
        _iface("ev-unrelated-up", "R4", "eth2", "up"),
        _ospf("ev-unrelated-full", "R4", "R5", "eth2", "Full/-", "10.0.45.2"),
    ]
    result = _diagnose(topology, records)
    candidate = _find(result, FaultType.LINK_FAILURE, "L12")
    assert "ev-unrelated-up" not in candidate.contradictory_evidence_ids
    assert "ev-unrelated-full" not in candidate.contradictory_evidence_ids


@pytest.mark.parametrize("status", [ObservationStatus.UNKNOWN, ObservationStatus.NOT_COLLECTED,
                                   ObservationStatus.COLLECTION_FAILED])
def test_failed_collection_is_not_an_observed_physical_fault(topology, status):
    records = [
        _iface("ev-unknown-interface", "R1", "eth1", "down", collection_status=status),
        _ospf("ev-unknown-ospf", "R1", "R2", "eth1", collection_status=status),
    ]
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.top1_hypothesis is None
    assert not result.evidence_certificate.evidence_sufficiency_met


@pytest.mark.parametrize("records", [
    [],
    [_iface("ev-healthy-interface", "R1", "eth1", "up"),
     _ospf("ev-healthy-ospf", "R1", "R2", "eth1", "Full/-")],
    [_ping("ev-healthy-ping")],
    [_ping("ev-timeout", loss=100, latency=None,
           collection_status=ObservationStatus.COLLECTION_FAILED)],
    [_iface("ev-single-interface", "R1", "eth1", "down")],
    [_ospf("ev-single-ospf", "R1", "R2", "eth1")],
    [EvidenceRecord(**_common("ev-generic-failure", "R3", EvidenceSourceType.INTERFACE_POLL,
                             event_type="COLLECTION_FAILURE",
                             collection_status=ObservationStatus.COLLECTION_FAILED))],
    [EvidenceRecord(**_common("ev-unavailable-only", "R3", EvidenceSourceType.INTERFACE_POLL,
                             event_type="ROUTER_UNAVAILABLE",
                             collection_status=ObservationStatus.COLLECTION_FAILED))],
])
def test_missing_healthy_or_single_source_evidence_abstains(topology, records):
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.top1_hypothesis is None
    assert result.missing_information
    assert not result.evidence_certificate.evidence_sufficiency_met


def test_low_coverage_prevents_diagnosis_despite_strong_fault_signals(topology):
    failures = [EvidenceRecord(**_common(
        f"ev-missing-{router}-{source.value}", router, source,
        event_type="COLLECTION_FAILURE", collection_status=ObservationStatus.COLLECTION_FAILED,
    )) for router in ("R2", "R3", "R4", "R5")
        for source in (EvidenceSourceType.ROUTING_TABLE, EvidenceSourceType.ACTIVE_TRACEROUTE)]
    result = _diagnose(topology, _link_failure() + failures)
    assert result.evidence_certificate.collection_coverage_pct < 60
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.top1_hypothesis is None


def test_duplicate_records_do_not_supply_independent_corroboration(topology):
    original = _iface("ev-only-physical", "R1", "eth1", "down")
    repeated = [original.model_copy(update={"evidence_id": f"ev-clone-{n}"}) for n in range(40)]
    result = _diagnose(topology, [original, original, *repeated])
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.top1_hypothesis is None


def test_duplicate_and_repeated_poll_records_do_not_inflate_scores(topology):
    records = _link_failure()
    original = _diagnose(topology, records)
    duplicate = records[0].model_copy(update={"evidence_id": "zz-duplicate-interface"})
    repeated = records[0].model_copy(update={
        "evidence_id": "zz-repeated-interface",
        "observed_at": _TS + timedelta(seconds=2),
        "collected_at": _TS + timedelta(seconds=2),
    })
    expanded = _diagnose(topology, records + [records[0], records[1], duplicate, repeated])
    assert _rank_signature(original) == _rank_signature(expanded)
    assert expanded.status == original.status


def test_dependent_route_storm_cannot_inflate_root_cause_score(topology):
    records = _link_failure() + [_route("ev-route-original")]
    original = _diagnose(topology, records)
    storm = [_route(f"ev-route-storm-{n}", prefix=f"172.16.{n}.0/24") for n in range(80)]
    expanded = _diagnose(topology, records + storm)
    assert _find(expanded, FaultType.LINK_FAILURE, "L12").rule_score == _find(
        original, FaultType.LINK_FAILURE, "L12"
    ).rule_score


def test_equal_competing_faults_are_ambiguous_with_stable_top3(topology):
    other = [record.model_copy(update={"evidence_id": f"ev-other-{index}"})
             for index, record in enumerate(_link_failure("L45"))]
    records = _link_failure() + other
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.AMBIGUOUS
    assert result.top1_hypothesis is None
    assert len(result.top3_hypotheses) >= 2
    assert {candidate.fault_location.component_id for candidate in result.top3_hypotheses} >= {
        "L12", "L45",
    }
    assert result.missing_information
    assert _rank_signature(result) == _rank_signature(_diagnose(topology, list(reversed(records))))


def test_ranking_is_stable_for_permutations_of_evidence(topology):
    records = _router_failure() + [_route("ev-missing-route")]
    expected = _diagnose(topology, records)
    for seed in range(8):
        shuffled = records.copy()
        random.Random(seed).shuffle(shuffled)
        actual = _diagnose(topology, shuffled)
        assert actual.status == expected.status
        assert _rank_signature(actual) == _rank_signature(expected)
        assert [h.model_dump() for h in actual.top3_hypotheses] == [
            h.model_dump() for h in expected.top3_hypotheses
        ]


@pytest.mark.parametrize("offset", [-11, 31])
def test_evidence_outside_incident_window_is_ignored(topology, offset):
    old = [record.model_copy(update={
        "observed_at": _TS + timedelta(seconds=offset),
        "collected_at": _TS + timedelta(seconds=offset),
    }) for record in _link_failure()]
    result = _diagnose(topology, old)
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence_certificate.total_evidence_count == 0
    assert not result.top3_hypotheses


@pytest.mark.parametrize("offset", [-10, 30])
def test_incident_window_includes_exact_boundary_timestamps(topology, offset):
    records = [record.model_copy(update={
        "observed_at": _TS + timedelta(seconds=offset),
        "collected_at": _TS + timedelta(seconds=offset),
    }) for record in _link_failure()]
    assert _diagnose(topology, records).status == DiagnosisStatus.DIAGNOSED


def test_evidence_bound_to_another_incident_is_not_used(topology):
    records = [record.model_copy(update={"incident_id": "unrelated-incident"})
               for record in _link_failure()]
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence_certificate.total_evidence_count == 0


def test_unknown_target_or_interface_does_not_invent_topology_location(topology):
    records = [
        _ping("ev-external-target", target="203.0.113.100", loss=40),
        _iface("ev-external-interface", "R1", "missing0", "down"),
    ]
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.top1_hypothesis is None
    assert all(rh.hypothesis.fault_location.component_id in {"L12", "L23", "L34", "L45", "L51",
                                                         "R1", "R2", "R3", "R4", "R5"}
               for rh in result.ranked_hypotheses)


def test_raw_log_message_does_not_generate_a_fault_from_text(topology):
    log = SyslogEvent(
        **_common("ev-opaque-log", "R1", EvidenceSourceType.SYSLOG, event_type="SYSLOG_MESSAGE"),
        severity=SyslogSeverity.INFO,
        process_name="ospfd",
        raw_message="router R3 down; link L12 down; 90% packet loss; latency 500 ms",
    )
    result = _diagnose(topology, [log])
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.top1_hypothesis is None


def test_certificate_counts_ids_and_declares_heuristic_scores(topology):
    records = _link_failure()
    result = _diagnose(topology, records)
    assert result.top1_hypothesis is not None
    certificate = result.evidence_certificate
    assert certificate.incident_id == result.incident_id
    assert certificate.total_evidence_count == len(records)
    assert certificate.supporting_evidence_count == len(result.top1_hypothesis.supporting_evidence_ids)
    assert certificate.contradictory_evidence_count == len(result.top1_hypothesis.contradictory_evidence_ids)
    assert certificate.collection_coverage_pct == 100
    assert "heuristic" in certificate.score_interpretation.lower()
    assert "not calibrated" in certificate.score_interpretation.lower()
    assert certificate.generated_at.tzinfo is not None
    assert result.diagnosed_at.tzinfo is not None
    assert result.engine_version
    assert all(h.counterfactual_verified is None for h in result.top3_hypotheses)
    assert DiagnosisResult.model_validate(result.model_dump(mode="json")) == result


def test_top3_is_exact_prefix_of_unique_ranked_candidates(topology):
    result = _diagnose(topology, _router_failure())
    ranked = result.ranked_hypotheses
    assert [rh.rank for rh in ranked] == list(range(1, len(ranked) + 1))
    assert result.top3_hypotheses == [rh.hypothesis for rh in ranked[:3]]
    assert len({h.hypothesis.hypothesis_id for h in ranked}) == len(ranked)
    assert len({(h.hypothesis.fault_type, h.hypothesis.fault_location.component_id)
                for h in ranked}) == len(ranked)
    assert [h.hypothesis.rule_score for h in ranked] == sorted(
        [h.hypothesis.rule_score for h in ranked], reverse=True,
    )


def test_component_implementations_are_concrete_and_follow_phase01_contracts():
    from app.diagnosis import interfaces

    for implementation in (HypothesisGenerator, RuleBasedDiagnoser, EvidenceSufficiencyEvaluator,
                           EvidenceCertificateBuilder):
        instance = implementation()
        assert isinstance(instance, getattr(interfaces, implementation.__name__))


@pytest.mark.parametrize("field,value", [
    ("ground_truth", {"fault_type": "ROUTER_FAILURE"}),
    ("injection_parameters", {"injected_loss": 40}),
    ("metadata", {"scenario": "f1_link_failure"}),
])
def test_snapshot_rejects_ground_truth_metadata_before_inference(topology, field, value):
    payload = {
        "snapshot_id": "snapshot-06-test",
        "collection_window_start": (_TS - timedelta(seconds=10)).isoformat(),
        "collection_window_end": (_TS + timedelta(seconds=30)).isoformat(),
        "topology": topology.model_dump(mode="json"),
        "evidence_records": [record.model_dump(mode="json") for record in _link_failure()],
        field: value,
    }
    with pytest.raises(GroundTruthLeakageError):
        DiagnosisEngine().diagnose_snapshot_dict(payload)


def test_direct_inference_rejects_ground_truth_hidden_in_evidence(topology):
    records = _link_failure()
    records[0] = records[0].model_copy(update={"raw_reference": "seeded_fault=LINK_FAILURE"})
    with pytest.raises(GroundTruthLeakageError):
        _diagnose(topology, records)


def test_inference_signatures_do_not_accept_ground_truth():
    signature = inspect.signature(DiagnosisEngine.diagnose)
    assert {"self", "incident", "evidence", "topology"} <= set(signature.parameters)
    assert set(signature.parameters) <= {
        "self", "incident", "evidence", "topology", "candidate_evidence_ids",
    }
    snapshot_signature = inspect.signature(DiagnosisEngine.diagnose_snapshot_dict)
    assert len(snapshot_signature.parameters) == 2


def test_inference_modules_do_not_import_offline_evaluation_or_lab_code():
    diagnosis_dir = Path(inspect.getfile(DiagnosisEngine)).parent
    for source in diagnosis_dir.rglob("*.py"):
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                assert not module.startswith(("app.evaluation", "evaluation", "lab", "scripts")), (
                    source, module,
                )


def test_snapshot_metadata_does_not_change_inferred_faults(topology):
    payload = {
        "snapshot_id": "opaque-capture-a",
        "collection_window_start": (_TS - timedelta(seconds=10)).isoformat(),
        "collection_window_end": (_TS + timedelta(seconds=30)).isoformat(),
        "topology": topology.model_dump(mode="json"),
        "evidence_records": [record.model_dump(mode="json") for record in _link_failure()],
        "notes": "Operator suspects a packet impairment near another router.",
    }
    alternative = copy.deepcopy(payload)
    alternative["snapshot_id"] = "opaque-capture-b"
    alternative["notes"] = "Operator suspects a routing configuration issue."
    original = DiagnosisEngine().diagnose_snapshot_dict(payload)
    changed = DiagnosisEngine().diagnose_snapshot_dict(alternative)
    assert [_rank_signature(result) for result in original] == [
        _rank_signature(result) for result in changed
    ]
    assert [result.status for result in original] == [result.status for result in changed]


@pytest.mark.parametrize("filename", [
    "f1_link_failure_snapshot.json",
    "f2_router_failure_snapshot.json",
    "f3_ospf_mismatch_snapshot.json",
    "f4_packet_loss_snapshot.json",
    "f5_high_latency_snapshot.json",
])
def test_recorded_fault_snapshots_are_processed_without_ground_truth_input(filename):
    snapshot = json.loads((_DATASETS / filename).read_text())
    original = copy.deepcopy(snapshot)
    results = DiagnosisEngine().diagnose_snapshot_dict(snapshot)
    assert results
    assert snapshot == original
    available_ids = {record["evidence_id"] for record in snapshot["evidence_records"]}
    for result in results:
        assert isinstance(result, DiagnosisResult)
        assert result.status in DiagnosisStatus
        for ranked in result.ranked_hypotheses:
            hypothesis = ranked.hypothesis
            assert set(hypothesis.supporting_evidence_ids) <= available_ids
            assert set(hypothesis.contradictory_evidence_ids) <= available_ids


def test_recorded_healthy_baseline_does_not_claim_a_root_fault():
    snapshot = json.loads((_DATASETS / "baseline_snapshot.json").read_text())
    results = DiagnosisEngine().diagnose_snapshot_dict(snapshot)
    assert all(result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE for result in results)
    assert all(result.top1_hypothesis is None for result in results)


def test_diagnosis_does_not_mutate_incident_evidence_or_topology(topology):
    records = _router_failure()
    incident = _incident(topology)
    before = (incident.model_dump(), [r.model_dump() for r in records], topology.model_dump())
    DiagnosisEngine().diagnose(incident, records, topology)
    assert before == (incident.model_dump(), [r.model_dump() for r in records], topology.model_dump())


def test_reused_evidence_id_with_changed_payload_is_rejected(topology):
    record = _iface("ev-same-id", "R1", "eth1", "down")
    conflicting = record.model_copy(update={"observed_status": "up"})
    with pytest.raises(ValueError, match="[Cc]onflict"):
        _diagnose(topology, [record, conflicting])


def test_successful_collection_from_suspected_router_is_counterevidence(topology):
    before = _diagnose(topology, _router_failure())
    after = _diagnose(topology, _router_failure() + [
        _iface("ev-r3-responded", "R3", "eth1", "up"),
    ])
    candidate = _find(after, FaultType.ROUTER_FAILURE, "R3")
    assert "ev-r3-responded" in candidate.contradictory_evidence_ids
    assert candidate.rule_score < _find(before, FaultType.ROUTER_FAILURE, "R3").rule_score
    assert after.top1_hypothesis is None or after.top1_hypothesis.fault_type != FaultType.ROUTER_FAILURE


def test_complete_packet_loss_does_not_masquerade_as_partial_loss_fault(topology):
    records = _performance(FaultType.PACKET_LOSS)
    records[-1] = _ping("ev-all-packets-lost", loss=100, latency=None)
    result = _diagnose(topology, records)
    assert not any(h.fault_type == FaultType.PACKET_LOSS for h in result.top3_hypotheses)
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE


def test_simultaneous_latency_and_partial_loss_remain_competing_explanations(topology):
    records = _performance(FaultType.PACKET_LOSS)
    records[-1] = _ping("ev-both-impairments", loss=40, latency=200)
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.AMBIGUOUS
    assert result.top1_hypothesis is None
    assert {h.fault_type for h in result.top3_hypotheses} >= {
        FaultType.PACKET_LOSS, FaultType.HIGH_LATENCY,
    }


def test_normal_probe_on_same_link_reduces_performance_score(topology):
    records = _performance(FaultType.HIGH_LATENCY)
    clean = _diagnose(topology, records)
    conflicted = _diagnose(topology, records + [_ping("ev-normal-probe", latency=1)])
    candidate = _find(conflicted, FaultType.HIGH_LATENCY, "L12")
    assert "ev-normal-probe" in candidate.contradictory_evidence_ids
    assert candidate.rule_score < _find(clean, FaultType.HIGH_LATENCY, "L12").rule_score
    assert conflicted.status != DiagnosisStatus.DIAGNOSED


def test_inferred_multi_link_path_does_not_claim_unique_fault_location(topology):
    records = [
        _iface("ev-r1-up", "R1", "eth1", "up"),
        _iface("ev-r2-left-up", "R2", "eth1", "up"),
        _iface("ev-r2-right-up", "R2", "eth2", "up"),
        _iface("ev-r3-up", "R3", "eth1", "up"),
        _ping("ev-two-link-latency", target="192.168.255.3", latency=200),
    ]
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.AMBIGUOUS
    assert result.top1_hypothesis is None
    assert {h.fault_location.component_id for h in result.top3_hypotheses} >= {"L12", "L23"}
    assert any("path" in message.lower() for message in result.missing_information)


def test_observed_trace_restricts_path_to_actual_links(topology):
    # The observed long route is valid on the ring; default shortest paths would
    # use R1 -> R2 -> R3. Traceroute constrains candidates to R1 -> R5 -> R4 -> R3.
    trace = TracerouteObservation(
        **_common("ev-observed-trace", "R1", EvidenceSourceType.ACTIVE_TRACEROUTE,
                  event_type="TRACEROUTE_RESULT"),
        probe_source="R1", target_address="192.168.255.3", destination_reached=True,
        total_hops=3,
        hops=[
            TracerouteHop(hop_number=1, hop_address="192.168.255.5", rtt_ms=100),
            TracerouteHop(hop_number=2, hop_address="192.168.255.4", rtt_ms=150),
            TracerouteHop(hop_number=3, hop_address="192.168.255.3", rtt_ms=200),
        ],
    )
    result = _diagnose(topology, [
        _ping("ev-long-path-latency", target="192.168.255.3", latency=200), trace,
    ])
    latency_candidates = [rh.hypothesis for rh in result.ranked_hypotheses
                          if rh.hypothesis.fault_type == FaultType.HIGH_LATENCY]
    assert {h.fault_location.component_id for h in latency_candidates} == {"L51", "L45", "L34"}
    assert all("ev-observed-trace" in h.supporting_evidence_ids for h in latency_candidates)
    assert result.top1_hypothesis is None


def test_invalid_trace_hop_sequence_cannot_override_topology_paths(topology):
    trace = TracerouteObservation(
        **_common("ev-incomplete-trace", "R1", EvidenceSourceType.ACTIVE_TRACEROUTE,
                  event_type="TRACEROUTE_RESULT"),
        probe_source="R1", target_address="192.168.255.3", destination_reached=True,
        total_hops=2,
        hops=[
            TracerouteHop(hop_number=1, hop_address="192.168.255.5", rtt_ms=100),
            TracerouteHop(hop_number=3, hop_address="192.168.255.3", rtt_ms=200),
        ],
    )
    result = _diagnose(topology, [_ping("ev-rtt", target="192.168.255.3", latency=200), trace])
    assert {h.fault_location.component_id for h in result.top3_hypotheses} == {"L12", "L23"}
    assert all("ev-incomplete-trace" not in h.supporting_evidence_ids for h in result.top3_hypotheses)


@pytest.mark.parametrize("minimum_score,expected_status", [
    (0.85, DiagnosisStatus.DIAGNOSED),
    (0.86, DiagnosisStatus.INSUFFICIENT_EVIDENCE),
])
def test_minimum_score_threshold_is_inclusive(topology, minimum_score, expected_status):
    settings = Settings(DIAGNOSIS_MIN_SCORE=minimum_score)
    result = DiagnosisEngine(settings).diagnose(_incident(topology), _link_failure(), topology)
    assert result.status == expected_status


@pytest.mark.parametrize("required_points,expected_status", [
    (2, DiagnosisStatus.DIAGNOSED),
    (3, DiagnosisStatus.INSUFFICIENT_EVIDENCE),
])
def test_primary_point_requirement_controls_abstention(topology, required_points, expected_status):
    settings = Settings(DIAGNOSIS_MIN_PRIMARY_POINTS=required_points)
    result = DiagnosisEngine(settings).diagnose(_incident(topology), _link_failure(), topology)
    assert result.status == expected_status


@pytest.mark.parametrize("state", ["Init", "ExStart", "Exchange", "2-Way"])
def test_protocol_degraded_states_generate_configuration_candidate(topology, state):
    records = _mismatch()
    records[-1] = _ospf("ev-degraded-protocol", "R1", "R2", "eth1", state=state)
    result = _diagnose(topology, records)
    assert result.top1_hypothesis is not None
    assert result.top1_hypothesis.fault_type == FaultType.OSPF_CONFIGURATION_MISMATCH


def test_public_sufficiency_evaluator_requires_independent_primary_evidence(topology):
    single = _iface("ev-one-point", "R1", "eth1", "down")
    hypotheses = HypothesisGenerator().generate(_incident(topology), [single], topology)
    ranked = RuleBasedDiagnoser().score_and_rank(hypotheses, [single], topology)
    enough, _, missing = EvidenceSufficiencyEvaluator().evaluate(ranked, [single])
    assert not enough
    assert missing
    enough_with_topology, coverage, missing_with_topology = EvidenceSufficiencyEvaluator().evaluate(
        ranked, [single], topology,
    )
    assert not enough_with_topology
    assert coverage == 100
    assert missing_with_topology


def test_ospf_interface_must_match_the_neighbour_link_in_topology(topology):
    records = [
        _iface("ev-r1-left-up", "R1", "eth1", "up"),
        _iface("ev-r2-left-up", "R2", "eth1", "up"),
        # R1 eth2 is connected to R5, so this cannot be an R1 -> R2 observation.
        _ospf("ev-impossible-neighbour-port", "R1", "R2", "eth2"),
    ]
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.top1_hypothesis is None
    assert all("ev-impossible-neighbour-port" not in h.supporting_evidence_ids
               for h in result.top3_hypotheses)


def test_matching_current_route_egress_constrains_probe_path(topology):
    route = RouteObservation(
        **_common("ev-current-egress", "R1", EvidenceSourceType.ROUTING_TABLE,
                  event_type="ROUTE_PRESENT"),
        destination_prefix="192.168.255.3/32", next_hop_address="10.0.15.1",
        next_hop_interface="eth2", route_type="OSPF", metric=3, is_present=True,
    )
    result = _diagnose(topology, [
        _ping("ev-routed-latency", target="192.168.255.3", latency=200), route,
    ])
    candidates = [rh.hypothesis for rh in result.ranked_hypotheses
                  if rh.hypothesis.fault_type == FaultType.HIGH_LATENCY]
    assert {h.fault_location.component_id for h in candidates} == {"L51", "L45", "L34"}
    assert all("ev-current-egress" in h.supporting_evidence_ids for h in candidates)
    # A route and one ping establish a path assumption, not two independent
    # observations of the impairment itself.
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE


def test_route_with_impossible_egress_cannot_invent_a_traversed_link(topology):
    route = RouteObservation(
        **_common("ev-impossible-egress", "R1", EvidenceSourceType.ROUTING_TABLE,
                  event_type="ROUTE_PRESENT"),
        destination_prefix="192.168.255.3/32", next_hop_address="10.0.15.1",
        next_hop_interface="missing0", route_type="OSPF", metric=3, is_present=True,
    )
    result = _diagnose(topology, [
        _ping("ev-routed-latency", target="192.168.255.3", latency=200), route,
    ])
    assert all("ev-impossible-egress" not in h.supporting_evidence_ids
               for h in result.top3_hypotheses)
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE


def test_route_withdrawal_storm_alone_cannot_establish_a_root_cause(topology):
    records = [_route(f"ev-absent-route-{n}", prefix=f"172.16.{n}.0/24") for n in range(80)]
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.top1_hypothesis is None
    assert not result.top3_hypotheses


def test_public_sufficiency_evaluator_can_validate_with_explicit_topology(topology):
    records = _link_failure()
    hypotheses = HypothesisGenerator().generate(_incident(topology), records, topology)
    ranked = RuleBasedDiagnoser().score_and_rank(hypotheses, records, topology)
    enough, coverage, _ = EvidenceSufficiencyEvaluator().evaluate(ranked, records, topology)
    assert enough
    assert coverage == 100


@pytest.mark.parametrize("required_coverage,expected_status", [
    (60.0, DiagnosisStatus.DIAGNOSED),
    (60.01, DiagnosisStatus.INSUFFICIENT_EVIDENCE),
])
def test_coverage_threshold_is_inclusive(topology, required_coverage, expected_status):
    records = _link_failure() + [_iface("ev-r2-carrier-up", "R2", "eth1", "up")]
    records.extend(EvidenceRecord(**_common(
        f"ev-gap-{router}", router, EvidenceSourceType.ROUTING_TABLE,
        event_type="COLLECTION_FAILURE", collection_status=ObservationStatus.COLLECTION_FAILED,
    )) for router in ("R3", "R4"))
    result = DiagnosisEngine(Settings(DIAGNOSIS_MIN_COVERAGE_PCT=required_coverage)).diagnose(
        _incident(topology), records, topology,
    )
    assert result.evidence_certificate.collection_coverage_pct == 60
    assert result.status == expected_status


@pytest.mark.parametrize("required_margin,expected_status", [
    (0.05, DiagnosisStatus.DIAGNOSED),
    (0.05001, DiagnosisStatus.AMBIGUOUS),
])
def test_leading_margin_threshold_is_inclusive(topology, required_margin, expected_status):
    other = [record.model_copy(update={"evidence_id": f"ev-config-{index}"})
             for index, record in enumerate(_mismatch("L45"))]
    result = DiagnosisEngine(Settings(DIAGNOSIS_MIN_MARGIN=required_margin)).diagnose(
        _incident(topology), _link_failure() + other, topology,
    )
    assert result.status == expected_status
    assert result.top1_hypothesis is None or result.top1_hypothesis.fault_type == FaultType.LINK_FAILURE


@pytest.mark.parametrize("field,value", [
    ("topology", {}),
    ("collection_window_start", "2026-10-19T12:00:00"),
    ("collection_window_end", "2026-10-18T12:00:00Z"),
    ("evidence_records", [{}]),
])
def test_malformed_snapshot_fails_closed(topology, field, value):
    payload = {
        "snapshot_id": "opaque-malformed-test",
        "collection_window_start": (_TS - timedelta(seconds=10)).isoformat(),
        "collection_window_end": (_TS + timedelta(seconds=30)).isoformat(),
        "topology": topology.model_dump(mode="json"),
        "evidence_records": [record.model_dump(mode="json") for record in _link_failure()],
    }
    payload[field] = value
    with pytest.raises((KeyError, ValueError)):
        DiagnosisEngine().diagnose_snapshot_dict(payload)


def test_snapshot_adapter_preserves_explicit_incident_binding(topology):
    records = [record.model_copy(update={"incident_id": "inc-already-bound"})
               for record in _link_failure()]
    results = DiagnosisEngine().diagnose_snapshot_dict(_snapshot(topology, records))
    assert len(results) == 1
    result = results[0]
    assert result.incident_id == "inc-already-bound"
    assert result.status == DiagnosisStatus.DIAGNOSED
    assert result.top1_hypothesis is not None
    assert result.top1_hypothesis.fault_location.component_id == "L12"
    assert result.evidence_certificate.total_evidence_count == 2
    assert set(result.top1_hypothesis.supporting_evidence_ids) == {
        record.evidence_id for record in records
    }


def test_snapshot_adapter_separates_explicit_incident_bindings(topology):
    records = [record.model_copy(update={"incident_id": "inc-bound-left"})
               for record in _link_failure()]
    records += [record.model_copy(update={
        "incident_id": "inc-bound-right", "evidence_id": f"ev-right-{index}",
    }) for index, record in enumerate(_link_failure("L45"))]
    results = DiagnosisEngine().diagnose_snapshot_dict(_snapshot(topology, records))
    by_incident = {result.incident_id: result for result in results}
    assert set(by_incident) == {"inc-bound-left", "inc-bound-right"}
    for incident_id, component in [("inc-bound-left", "L12"), ("inc-bound-right", "L45")]:
        result = by_incident[incident_id]
        assert result.status == DiagnosisStatus.DIAGNOSED
        assert result.top1_hypothesis is not None
        assert result.top1_hypothesis.fault_location.component_id == component
        assert result.evidence_certificate.total_evidence_count == 2


def test_snapshot_adapter_uses_observed_trace_to_seed_actual_path_candidates(topology):
    records = [
        _ping("ev-traced-latency", target="192.168.255.3", latency=200),
        _trace("ev-trace-long-route", ["R5", "R4", "R3"]),
    ]
    direct = _diagnose(topology, records)
    results = DiagnosisEngine().diagnose_snapshot_dict(_snapshot(topology, records))
    candidates = [rh.hypothesis for result in results for rh in result.ranked_hypotheses
                  if rh.hypothesis.fault_type == FaultType.HIGH_LATENCY]
    assert {h.fault_location.component_id for h in candidates} == {"L51", "L45", "L34"}
    assert all("ev-trace-long-route" in h.supporting_evidence_ids for h in candidates)
    assert len(results) == 1
    assert _rank_signature(results[0]) == _rank_signature(direct)


@pytest.mark.parametrize("rtt,expected_status", [
    (9.999, DiagnosisStatus.INSUFFICIENT_EVIDENCE),
    (10.0, DiagnosisStatus.DIAGNOSED),
    (10.001, DiagnosisStatus.DIAGNOSED),
])
def test_rtt_boundary_is_consistent_between_direct_and_snapshot(topology, rtt, expected_status):
    records = _performance(FaultType.HIGH_LATENCY)
    records[-1] = _ping("ev-rtt-threshold", latency=rtt)
    direct = _diagnose(topology, records)
    results = DiagnosisEngine().diagnose_snapshot_dict(_snapshot(topology, records))
    assert len(results) == 1
    assert direct.status == expected_status
    assert results[0].status == expected_status
    assert _rank_signature(results[0]) == _rank_signature(direct)


@pytest.mark.parametrize("typed_routes", [True, False])
def test_route_volume_cannot_change_represented_rib_coverage_or_status(topology, typed_routes):
    records = _link_failure() + [_route("ev-single-rib-family")]
    records += [EvidenceRecord(**_common(
        f"ev-absent-rib-{router}", router, EvidenceSourceType.ROUTING_TABLE,
        event_type="COLLECTION_FAILURE", collection_status=ObservationStatus.COLLECTION_FAILED,
    )) for router in ("R3", "R4")]
    original = _diagnose(topology, records)
    if typed_routes:
        storm = [_route(f"ev-rib-volume-{n}", prefix=f"172.16.{n}.0/24") for n in range(80)]
    else:
        storm = [EvidenceRecord(**_common(
            f"ev-rib-volume-{n}", "R1", EvidenceSourceType.ROUTING_TABLE,
            event_type="ROUTE_MISSING",
        )) for n in range(80)]
    expanded = _diagnose(topology, records + storm)
    assert original.evidence_certificate.collection_coverage_pct == 60
    assert expanded.evidence_certificate.collection_coverage_pct == 60
    assert original.status == expanded.status == DiagnosisStatus.DIAGNOSED
    assert _rank_signature(original) == _rank_signature(expanded)


def test_alternative_traces_only_support_links_present_on_their_own_path(topology):
    short_trace = _trace("ev-trace-via-r2", ["R2", "R3"])
    long_trace = _trace("ev-trace-via-r5", ["R5", "R4", "R3"])
    interfaces = [
        _iface(f"ev-up-{link}-{router}", router, interface, "up")
        for link, (ra, ia, rb, ib, _) in _LINKS.items()
        for router, interface in [(ra, ia), (rb, ib)]
    ]
    result = _diagnose(topology, [
        _ping("ev-multipath-latency", target="192.168.255.3", latency=200),
        short_trace, long_trace, *interfaces,
    ])
    assert result.status == DiagnosisStatus.AMBIGUOUS
    assert result.top1_hypothesis is None
    candidates = [rh.hypothesis for rh in result.ranked_hypotheses
                  if rh.hypothesis.fault_type == FaultType.HIGH_LATENCY]
    assert {h.fault_location.component_id for h in candidates} == set(_LINKS)
    for hypothesis in candidates:
        included = short_trace.evidence_id if hypothesis.fault_location.component_id in {
            "L12", "L23",
        } else long_trace.evidence_id
        excluded = ({short_trace.evidence_id, long_trace.evidence_id} - {included}).pop()
        assert included in hypothesis.supporting_evidence_ids
        assert excluded not in hypothesis.supporting_evidence_ids


def test_partial_operational_coverage_does_not_pick_one_link_from_multilink_probe(topology):
    records = [
        _ping("ev-multilink-impairment", target="192.168.255.3", latency=200),
        _iface("ev-known-r1-interface", "R1", "eth1", "up"),
        _iface("ev-known-r2-interface", "R2", "eth1", "up"),
    ]
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.AMBIGUOUS
    assert result.top1_hypothesis is None
    first = _find(result, FaultType.HIGH_LATENCY, "L12")
    second = _find(result, FaultType.HIGH_LATENCY, "L23")
    assert first.rule_score == second.rule_score
    assert first.supporting_evidence_ids != second.supporting_evidence_ids


@pytest.mark.parametrize("updates", [
    {"packet_loss_pct": 101.0},
    {"rtt_avg_ms": -1.0},
    {"packets_received": 11},
    {"packet_loss_pct": 40.0, "packets_received": 10},
])
def test_invalid_typed_measurements_raise_instead_of_falling_back_to_base(updates):
    payload = _ping("ev-invalid-metric").model_dump(mode="json")
    payload.update(updates)
    with pytest.raises(ValidationError):
        EvidenceNormalizer.deserialize_record(payload)


@pytest.mark.parametrize("next_hop", ["10.0.15.1", "10.0.15.1/30"])
def test_current_route_next_hop_address_without_interface_constrains_path(topology, next_hop):
    route = RouteObservation(
        **_common("ev-address-only-egress", "R1", EvidenceSourceType.ROUTING_TABLE,
                  event_type="ROUTE_PRESENT"),
        destination_prefix="192.168.255.3/32", next_hop_address=next_hop,
        next_hop_interface=None, route_type="OSPF", metric=3, is_present=True,
    )
    records = [_ping("ev-address-routed-latency", target="192.168.255.3", latency=200), route]
    direct = _diagnose(topology, records)
    snapshots = DiagnosisEngine().diagnose_snapshot_dict(_snapshot(topology, records))
    assert len(snapshots) == 1
    assert _rank_signature(snapshots[0]) == _rank_signature(direct)
    candidates = [rh.hypothesis for rh in direct.ranked_hypotheses
                  if rh.hypothesis.fault_type == FaultType.HIGH_LATENCY]
    assert {h.fault_location.component_id for h in candidates} == {"L51", "L45", "L34"}
    assert all(route.evidence_id in h.supporting_evidence_ids for h in candidates)
    assert direct.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("interface", ["missing0", "eth1", ""])
def test_route_address_cannot_override_supplied_invalid_or_conflicting_interface(topology, interface):
    route = RouteObservation(
        **_common("ev-conflicting-egress", "R1", EvidenceSourceType.ROUTING_TABLE,
                  event_type="ROUTE_PRESENT"),
        destination_prefix="192.168.255.3/32", next_hop_address="10.0.15.1",
        next_hop_interface=interface, route_type="OSPF", metric=3, is_present=True,
    )
    records = [_ping("ev-invalid-egress-latency", target="192.168.255.3", latency=200), route]
    result = _diagnose(topology, records)
    assert {rh.hypothesis.fault_location.component_id for rh in result.ranked_hypotheses} == {
        "L12", "L23",
    }
    assert all(route.evidence_id not in rh.hypothesis.supporting_evidence_ids
               for rh in result.ranked_hypotheses)


@pytest.mark.parametrize("address", [
    "10.0.15.1", "10.0.23.1", "192.168.255.2", "10.0.12.1", "203.0.113.100", "invalid-ip",
])
def test_known_wrong_ospf_address_cannot_establish_a_configuration_fault(topology, address):
    records = [
        _iface("ev-r1-port-up", "R1", "eth1", "up"),
        _iface("ev-r2-port-up", "R2", "eth1", "up"),
        _ospf("ev-wrong-neighbour-address", "R1", "R2", "eth1", address=address),
    ]
    direct = _diagnose(topology, records)
    snapshots = DiagnosisEngine().diagnose_snapshot_dict(_snapshot(topology, records))
    assert direct.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert all(result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE for result in snapshots)
    assert all("ev-wrong-neighbour-address" not in rh.hypothesis.supporting_evidence_ids
               for result in [direct, *snapshots] for rh in result.ranked_hypotheses)


@pytest.mark.parametrize("address", ["10.0.12.2/30", "0.0.0.0", ""])
def test_normalized_or_missing_ospf_address_preserves_valid_pair_identity(topology, address):
    records = _mismatch()
    records[-1] = _ospf("ev-valid-neighbour", "R1", "R2", "eth1", address=address)
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.DIAGNOSED
    assert result.top1_hypothesis is not None
    assert result.top1_hypothesis.fault_type == FaultType.OSPF_CONFIGURATION_MISMATCH
    assert result.top1_hypothesis.fault_location.component_id == "L12"


def test_known_wrong_ospf_address_is_rejected_without_a_source_interface(topology):
    record = _ospf("ev-no-port-wrong-address", "R1", "R2", "eth1", address="10.0.15.1")
    records = _mismatch()[:2] + [record.model_copy(update={"source_interface": None})]
    result = _diagnose(topology, records)
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.top1_hypothesis is None
