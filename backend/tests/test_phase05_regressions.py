"""Phase 05 inference-boundary regressions found during the Phase 06 audit."""

from datetime import UTC, datetime, timedelta

import pytest

from app.collectors.normalizer import GroundTruthLeakageError
from app.correlation.engine import CorrelationEngine
from app.correlation.temporal import TemporalCorrelator
from app.schemas.correlation import SymptomCategory
from app.schemas.evidence import (
    ObservationStatus,
    SyslogEvent,
    SyslogSeverity,
)
from app.topology.graph import build_expected_topology_graph
from tests.test_phase05_correlation import (
    _make_base_record,
    _make_interface_record,
    _make_ospf_record,
    _make_ping_record,
    _make_route_record,
)

_TS = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)


def _correlate(records):
    return CorrelationEngine().correlate_records(
        records, build_expected_topology_graph().topology
    )


@pytest.mark.parametrize("records", [
    [_make_ping_record("R1", "192.168.255.2", 0, ts=_TS),
     _make_ping_record("R1", "192.168.255.3", 100, ts=_TS)],
    [_make_route_record("R1", "192.168.255.2/32", False, ts=_TS),
     _make_route_record("R1", "192.168.255.3/32", False, ts=_TS)],
    [_make_ospf_record("R1", "2.2.2.2", "down", ts=_TS),
     _make_ospf_record("R1", "5.5.5.5", "down", ts=_TS)],
    [_make_interface_record("R1", "eth1", "up", ts=_TS),
     _make_interface_record("R1", "eth1", "down", ts=_TS)],
    [_make_ping_record("R1", "192.168.255.2", 0, ts=_TS),
     _make_ping_record("R1", "192.168.255.2", 50, ts=_TS)],
])
def test_deduplication_preserves_distinct_facts_and_values(records):
    unique, removed = TemporalCorrelator().deduplicate(records)
    assert len(unique) == 2
    assert removed == 0


def test_repeated_semantic_payload_uses_stable_representative():
    first = _make_ping_record("R1", "192.168.255.2", 50, ts=_TS)
    first = first.model_copy(update={"evidence_id": "ev-a"})
    duplicate = first.model_copy(update={"evidence_id": "ev-b"})
    correlator = TemporalCorrelator()
    assert correlator.deduplicate([first, duplicate]) == correlator.deduplicate([duplicate, first])
    unique, removed = correlator.deduplicate([duplicate, first])
    assert [record.evidence_id for record in unique] == ["ev-a"]
    assert removed == 1


def test_collection_status_difference_is_not_a_duplicate():
    observed = _make_interface_record("R1", "eth1", "down", ts=_TS)
    unknown = observed.model_copy(update={
        "evidence_id": "ev-unknown", "collection_status": ObservationStatus.UNKNOWN,
    })
    assert TemporalCorrelator().deduplicate([observed, unknown])[1] == 0


def test_typed_observed_healthy_state_is_healthy_with_evidence_window():
    record = _make_interface_record("R1", "eth1", "up", ts=_TS)
    incident = _correlate([record]).incidents[0]
    assert incident.status == "HEALTHY"
    assert incident.correlation_window_start <= _TS <= incident.correlation_window_end


@pytest.mark.parametrize("state", ["unknown", "unexpected"])
def test_unknown_interface_state_does_not_establish_health(state):
    incident = _correlate([_make_interface_record("R1", "eth1", state, ts=_TS)]).incidents[0]
    assert incident.status == "INCOMPLETE"
    assert incident.missing_information


@pytest.mark.parametrize("status", [ObservationStatus.UNKNOWN, ObservationStatus.NOT_COLLECTED])
def test_unavailable_typed_state_is_neither_failure_nor_health(status):
    record = _make_interface_record("R1", "eth1", "down", ts=_TS)
    record = record.model_copy(update={"collection_status": status})
    incident = _correlate([record]).incidents[0]
    assert incident.status == "INCOMPLETE"
    assert {symptom.category for symptom in incident.symptoms} == {SymptomCategory.COLLECTION_FAILURE}
    assert all(not symptom.is_direct_observation for symptom in incident.symptoms)
    assert record.evidence_id in incident.evidence_ids


def test_full_frr_suffix_is_explicitly_classified_as_healthy():
    record = _make_ospf_record("R1", "2.2.2.2", "Full/-", ts=_TS)
    incident = _correlate([record]).incidents[0]
    assert incident.status == "HEALTHY"


def test_interface_up_and_ospf_down_are_compatible_layers():
    records = [_make_interface_record("R1", "eth1", "up", ts=_TS),
               _make_ospf_record("R1", "2.2.2.2", "down", ts=_TS)]
    incident = _correlate(records).incidents[0]
    assert incident.contradictory_observations == []
    assert not any("No observed interface state" in item for item in incident.missing_information)


def test_opposing_interface_facts_preserved_and_identified():
    records = [_make_interface_record("R1", "eth1", "up", ts=_TS),
               _make_interface_record("R1", "eth1", "down", ts=_TS)]
    incident = _correlate(records).incidents[0]
    assert len(incident.contradictory_observations) == 1
    for record in records:
        assert record.evidence_id in incident.contradictory_observations[0]


def test_interface_state_on_another_port_does_not_fill_missing_information():
    records = [_make_interface_record("R1", "eth2", "down", ts=_TS),
               _make_ospf_record("R1", "2.2.2.2", "down", iface="eth1", ts=_TS)]
    incident = _correlate(records).incidents[0]
    assert any("R1/eth1" in item for item in incident.missing_information)
    assert not any(rel.relationship_kind == "OSPF_TOPOLOGY" for rel in incident.relationships)


@pytest.mark.parametrize("reverse", [False, True])
def test_interface_adjacency_dependency_is_order_independent(reverse):
    records = [_make_interface_record("R1", "eth1", "down", ts=_TS),
               _make_ospf_record("R2", "1.1.1.1", "down", ts=_TS)]
    records[0] = records[0].model_copy(update={"evidence_id": "ev-z" if reverse else "ev-a"})
    records[1] = records[1].model_copy(update={"evidence_id": "ev-a" if reverse else "ev-z"})
    incident = _correlate(records).incidents[0]
    dependencies = [rel for rel in incident.relationships if rel.relationship_kind == "OSPF_TOPOLOGY"]
    assert len(dependencies) == 1
    assert dependencies[0].from_component == "iface:R1:eth1"
    assert dependencies[0].to_component == "adj:R2→R1"


def test_incident_context_respects_temporal_group():
    records = [_make_interface_record("R1", "eth1", "down", ts=_TS),
               _make_interface_record("R1", "eth1", "up", ts=_TS + timedelta(seconds=500))]
    incident = _correlate(records).incidents[0]
    assert incident.evidence_ids == [records[0].evidence_id]
    assert not incident.contradictory_observations
    assert incident.correlation_window_end < records[1].observed_at


def test_typed_correlation_entrypoint_checks_ground_truth_isolation():
    record = _make_base_record("R1", observed_at=_TS)
    payload = record.model_dump()
    payload.update(severity=SyslogSeverity.WARNING, process_name="ospfd",
                   raw_message="seeded_fault description")
    leaked = SyslogEvent.model_validate(payload)
    with pytest.raises(GroundTruthLeakageError):
        _correlate([leaked])


def test_topology_metadata_is_checked_for_leakage():
    topology = build_expected_topology_graph().topology
    topology.routers[0].role = "seeded_fault"
    record = _make_interface_record("R1", "eth1", "up", ts=_TS)
    with pytest.raises(GroundTruthLeakageError):
        CorrelationEngine().correlate_records([record], topology)
