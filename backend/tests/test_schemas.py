"""
Phase 01 schema validation tests for NEXORA.

Tests validate:
- Valid five-router topology construction and constraints
- Invalid router identifiers
- Duplicate component identifiers
- Invalid link endpoints and addressing
- Invalid IPv4 address assignments
- Missing and explicit unknown evidence
- UTC timestamp validation
- Invalid packet-loss values
- Valid ranked hypotheses
- Ambiguous and insufficient-evidence diagnosis statuses
- Probe allowlist validation
- Rejection of arbitrary command fields
- Ground-truth isolation at contract boundaries
"""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.diagnosis import (
    DiagnosisResult,
    DiagnosisStatus,
    EvidenceCertificate,
    RankedHypothesis,
)
from app.schemas.evidence import (
    CollectionMethod,
    EvidenceSourceType,
    ObservationStatus,
    PingMeasurement,
    SyslogEvent,
    SyslogSeverity,
)
from app.schemas.hypothesis import FaultHypothesis, FaultLocation, FaultLocationKind, FaultType
from app.schemas.incident import Incident, IncidentStatus
from app.schemas.probe import MAX_PROBE_TIMEOUT_S, ProbeRequest, ProbeType
from app.schemas.topology import (
    InterfaceStatus,
    NetworkInterface,
    NetworkLink,
    Router,
    Topology,
)

# ---------------------------------------------------------------------------
# Helper factories for frequently-used UTC datetimes
# ---------------------------------------------------------------------------

NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 14, 13, 0, 0, tzinfo=UTC)


def _make_router(rid: str, ospf_id: str, lo: str) -> dict:
    return {
        "router_id": rid,
        "ospf_router_id": ospf_id,
        "loopback_address": lo,
        "role": f"Test router {rid}",
    }


def _make_link(
    link_id: str,
    subnet: str,
    ra: str,
    iface_a: str,
    addr_a: str,
    rb: str,
    iface_b: str,
    addr_b: str,
) -> dict:
    return {
        "link_id": link_id,
        "subnet": subnet,
        "router_a": ra,
        "interface_a": iface_a,
        "address_a": addr_a,
        "router_b": rb,
        "interface_b": iface_b,
        "address_b": addr_b,
    }


def _five_router_topology() -> dict:
    return {
        "snapshot_id": "snap-001",
        "captured_at": NOW,
        "routers": [
            _make_router("R1", "1.1.1.1", "192.168.255.1/32"),
            _make_router("R2", "2.2.2.2", "192.168.255.2/32"),
            _make_router("R3", "3.3.3.3", "192.168.255.3/32"),
            _make_router("R4", "4.4.4.4", "192.168.255.4/32"),
            _make_router("R5", "5.5.5.5", "192.168.255.5/32"),
        ],
        "links": [
            _make_link("L12", "10.0.12.0/30", "R1", "eth1", "10.0.12.1/30", "R2", "eth1", "10.0.12.2/30"),
            _make_link("L23", "10.0.23.0/30", "R2", "eth2", "10.0.23.1/30", "R3", "eth1", "10.0.23.2/30"),
            _make_link("L34", "10.0.34.0/30", "R3", "eth2", "10.0.34.1/30", "R4", "eth1", "10.0.34.2/30"),
            _make_link("L45", "10.0.45.0/30", "R4", "eth2", "10.0.45.1/30", "R5", "eth1", "10.0.45.2/30"),
            _make_link("L51", "10.0.15.0/30", "R5", "eth2", "10.0.15.1/30", "R1", "eth2", "10.0.15.2/30"),
        ],
    }


def _base_evidence_fields(router_id: str = "R1") -> dict:
    return {
        "evidence_id": "ev-001",
        "source_router": router_id,
        "event_type": "OSPF_NEIGHBOUR_DOWN",
        "observed_at": NOW,
        "collected_at": NOW,
        "source_type": EvidenceSourceType.OSPF_API,
        "collection_method": CollectionMethod.PERIODIC_POLL,
    }


def _make_hypothesis(
    h_id: str = "h-001",
    incident_id: str = "inc-001",
    fault_type: FaultType = FaultType.LINK_FAILURE,
    score: float = 0.8,
) -> FaultHypothesis:
    return FaultHypothesis(
        hypothesis_id=h_id,
        incident_id=incident_id,
        fault_type=fault_type,
        fault_location=FaultLocation(
            kind=FaultLocationKind.LINK,
            component_id="L12",
            affected_routers=["R1", "R2"],
        ),
        rule_score=score,
        supporting_evidence_ids=["ev-001"],
        contradictory_evidence_ids=[],
    )


def _make_certificate(cert_id: str = "cert-001", incident_id: str = "inc-001") -> EvidenceCertificate:
    return EvidenceCertificate(
        certificate_id=cert_id,
        incident_id=incident_id,
        generated_at=NOW,
        total_evidence_count=5,
        supporting_evidence_count=3,
        contradictory_evidence_count=1,
        evidence_sufficiency_met=True,
        collection_coverage_pct=80.0,
        reasoning_summary="Link L12 failure detected via dual OSPF adjacency loss.",
    )


# ===========================================================================
# TASK 2: Topology schema tests
# ===========================================================================


class TestValidTopology:
    def test_valid_five_router_topology(self) -> None:
        """A complete, valid five-router ring topology must construct without error."""
        topo = Topology(**_five_router_topology())
        assert len(topo.routers) == 5
        assert len(topo.links) == 5
        router_ids = {r.router_id for r in topo.routers}
        assert router_ids == {"R1", "R2", "R3", "R4", "R5"}

    def test_all_subnets_distinct(self) -> None:
        """All link subnets in the ring are distinct (/30)."""
        topo = Topology(**_five_router_topology())
        subnets = [lnk.subnet for lnk in topo.links]
        assert len(subnets) == len(set(subnets)), "Subnets must be unique"

    def test_all_router_ids_distinct(self) -> None:
        topo = Topology(**_five_router_topology())
        ids = [r.router_id for r in topo.routers]
        assert len(ids) == len(set(ids))

    def test_link_endpoint_addresses_in_subnet(self) -> None:
        """Each link endpoint address must fall within its /30 subnet."""
        topo = Topology(**_five_router_topology())
        for link in topo.links:
            subnet = ipaddress.IPv4Network(link.subnet)
            addr_a = ipaddress.IPv4Interface(link.address_a).ip
            addr_b = ipaddress.IPv4Interface(link.address_b).ip
            assert addr_a in subnet, f"address_a {addr_a} not in {subnet}"
            assert addr_b in subnet, f"address_b {addr_b} not in {subnet}"

    def test_loopback_is_slash32(self) -> None:
        for rid, ospf_id, lo in [
            ("R1", "1.1.1.1", "192.168.255.1/32"),
            ("R2", "2.2.2.2", "192.168.255.2/32"),
        ]:
            r = Router(
                router_id=rid,
                ospf_router_id=ospf_id,
                loopback_address=lo,
                role="test",
            )
            iface = ipaddress.IPv4Interface(r.loopback_address)
            assert iface.network.prefixlen == 32


class TestInvalidTopology:
    def test_invalid_router_id_pattern(self) -> None:
        """Router IDs must match R<N> pattern."""
        with pytest.raises(ValidationError, match="router_id"):
            Router(
                router_id="Router1",  # invalid — no 'R' prefix without digit
                ospf_router_id="1.1.1.1",
                loopback_address="192.168.255.1/32",
                role="test",
            )

    def test_invalid_router_id_lowercase(self) -> None:
        with pytest.raises(ValidationError):
            Router(
                router_id="r1",
                ospf_router_id="1.1.1.1",
                loopback_address="192.168.255.1/32",
                role="test",
            )

    def test_duplicate_router_ids(self) -> None:
        data = _five_router_topology()
        data["routers"].append(_make_router("R1", "6.6.6.6", "192.168.255.6/32"))
        with pytest.raises(ValidationError, match="Duplicate router IDs"):
            Topology(**data)

    def test_duplicate_link_ids(self) -> None:
        data = _five_router_topology()
        data["links"].append(
            _make_link("L12", "10.0.99.0/30", "R1", "eth3", "10.0.99.1/30", "R3", "eth3", "10.0.99.2/30")
        )
        with pytest.raises(ValidationError, match="Duplicate link IDs"):
            Topology(**data)

    def test_link_endpoint_not_in_topology(self) -> None:
        data = _five_router_topology()
        data["links"].append(
            _make_link("L99", "10.0.99.0/30", "R6", "eth1", "10.0.99.1/30", "R1", "eth3", "10.0.99.2/30")
        )
        with pytest.raises(ValidationError, match="not in topology routers"):
            Topology(**data)

    def test_link_self_loop_rejected(self) -> None:
        with pytest.raises(ValidationError, match="router_a and router_b must differ"):
            NetworkLink(
                **_make_link("L99", "10.0.99.0/30", "R1", "eth1", "10.0.99.1/30", "R1", "eth2", "10.0.99.2/30")
            )

    def test_invalid_ipv4_address_in_link(self) -> None:
        with pytest.raises(ValidationError):
            NetworkLink(
                **_make_link("L12", "10.0.12.0/30", "R1", "eth1", "999.999.999.999/30", "R2", "eth1", "10.0.12.2/30")
            )

    def test_address_outside_link_subnet(self) -> None:
        with pytest.raises(ValidationError, match="not in subnet"):
            NetworkLink(
                **_make_link("L12", "10.0.12.0/30", "R1", "eth1", "10.0.99.1/30", "R2", "eth1", "10.0.12.2/30")
            )

    def test_link_subnet_must_be_slash30(self) -> None:
        with pytest.raises(ValidationError, match="/30"):
            NetworkLink(
                **_make_link("L12", "10.0.12.0/24", "R1", "eth1", "10.0.12.1/24", "R2", "eth1", "10.0.12.2/24")
            )

    def test_subnet_collision_rejected(self) -> None:
        data = _five_router_topology()
        data["links"].append(
            _make_link("L99", "10.0.12.0/30", "R2", "eth3", "10.0.12.1/30", "R3", "eth3", "10.0.12.2/30")
        )
        with pytest.raises(ValidationError, match="Subnet collision"):
            Topology(**data)

    def test_duplicate_interface_names_on_router(self) -> None:
        with pytest.raises(ValidationError, match="duplicate interface names"):
            Router(
                router_id="R1",
                ospf_router_id="1.1.1.1",
                loopback_address="192.168.255.1/32",
                role="test",
                interfaces=[
                    NetworkInterface(interface_name="eth1", status=InterfaceStatus.UP),
                    NetworkInterface(interface_name="eth1", status=InterfaceStatus.DOWN),
                ],
            )

    def test_loopback_must_be_slash32(self) -> None:
        with pytest.raises(ValidationError, match="/32"):
            Router(
                router_id="R1",
                ospf_router_id="1.1.1.1",
                loopback_address="192.168.255.1/24",
                role="test",
            )


# ===========================================================================
# Evidence schema tests
# ===========================================================================


class TestEvidenceTimestamps:
    def test_naive_observed_at_rejected(self) -> None:
        """Naive (non-UTC) timestamps must be rejected."""
        naive_dt = datetime(2026, 10, 14, 12, 0, 0)  # no tzinfo
        fields = _base_evidence_fields()
        fields["observed_at"] = naive_dt
        fields["severity"] = SyslogSeverity.ERROR
        fields["process_name"] = "ospfd"
        fields["raw_message"] = "neighbour down"
        with pytest.raises(ValidationError, match="timezone-aware"):
            SyslogEvent(**fields)

    def test_naive_collected_at_rejected(self) -> None:
        naive_dt = datetime(2026, 10, 14, 12, 0, 0)
        fields = _base_evidence_fields()
        fields["collected_at"] = naive_dt
        fields["severity"] = SyslogSeverity.ERROR
        fields["process_name"] = "ospfd"
        fields["raw_message"] = "neighbour down"
        with pytest.raises(ValidationError, match="timezone-aware"):
            SyslogEvent(**fields)

    def test_valid_utc_timestamps_accepted(self) -> None:
        fields = _base_evidence_fields()
        fields.update(
            severity=SyslogSeverity.WARNING,
            process_name="ospfd",
            raw_message="%OSPF-5-ADJCHG: Process 1, Nbr 2.2.2.2 on eth1 from Full to Down",
        )
        ev = SyslogEvent(**fields)
        assert ev.observed_at.tzinfo is not None
        assert ev.collected_at.tzinfo is not None


class TestPingMeasurementValidation:
    def _base_ping(self, **overrides: Any) -> dict:
        base = {
            **_base_evidence_fields("R1"),
            "evidence_id": "ping-001",
            "event_type": "PING_RESULT",
            "source_type": EvidenceSourceType.ACTIVE_PING,
            "collection_method": CollectionMethod.TRIGGERED_PROBE,
            "target_address": "192.168.255.3",
            "packets_sent": 10,
            "packets_received": 8,
            "packet_loss_pct": 20.0,
            "probe_source": "R1",
        }
        base.update(overrides)
        return base

    def test_valid_ping_measurement(self) -> None:
        ping = PingMeasurement(**self._base_ping())
        assert ping.packet_loss_pct == 20.0

    def test_zero_loss_valid(self) -> None:
        ping = PingMeasurement(**self._base_ping(packets_received=10, packet_loss_pct=0.0))
        assert ping.packet_loss_pct == 0.0

    def test_full_loss_valid(self) -> None:
        ping = PingMeasurement(**self._base_ping(
            packets_received=0,
            packet_loss_pct=100.0,
            collection_status=ObservationStatus.COLLECTION_FAILED,
        ))
        assert ping.packet_loss_pct == 100.0

    def test_packet_loss_above_100_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PingMeasurement(**self._base_ping(packet_loss_pct=101.0))

    def test_packet_loss_below_0_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PingMeasurement(**self._base_ping(packet_loss_pct=-1.0))

    def test_received_exceeds_sent_rejected(self) -> None:
        with pytest.raises(ValidationError, match="packets_received"):
            PingMeasurement(**self._base_ping(packets_sent=5, packets_received=10, packet_loss_pct=0.0))

    def test_inconsistent_loss_pct_rejected(self) -> None:
        # sent=10, received=8 implies 20% loss, but we claim 90% — inconsistent
        with pytest.raises(ValidationError, match="inconsistent"):
            PingMeasurement(**self._base_ping(packets_sent=10, packets_received=8, packet_loss_pct=90.0))


class TestObservationStatusSemantics:
    def test_not_collected_is_explicit_not_failure(self) -> None:
        """NOT_COLLECTED must be an explicit valid state, not an error."""
        fields = _base_evidence_fields()
        fields.update(
            severity=SyslogSeverity.INFO,
            process_name="ospfd",
            raw_message="no data collected",
            collection_status=ObservationStatus.NOT_COLLECTED,
        )
        ev = SyslogEvent(**fields)
        assert ev.collection_status == ObservationStatus.NOT_COLLECTED

    def test_collection_failed_is_explicit(self) -> None:
        fields = _base_evidence_fields()
        fields.update(
            severity=SyslogSeverity.ERROR,
            process_name="ospfd",
            raw_message="timeout",
            collection_status=ObservationStatus.COLLECTION_FAILED,
        )
        ev = SyslogEvent(**fields)
        assert ev.collection_status == ObservationStatus.COLLECTION_FAILED


# ===========================================================================
# Hypothesis schema tests
# ===========================================================================


class TestFaultHypothesis:
    def test_valid_link_failure_hypothesis(self) -> None:
        h = _make_hypothesis()
        assert h.fault_type == FaultType.LINK_FAILURE
        assert h.rule_score == 0.8

    def test_all_five_fault_types_valid(self) -> None:
        for ft in FaultType:
            kind = FaultLocationKind.LINK if "LINK" in ft.value or "PACKET" in ft.value or "LATENCY" in ft.value else FaultLocationKind.ROUTER
            comp_id = "L12" if kind == FaultLocationKind.LINK else "R1"
            h = FaultHypothesis(
                hypothesis_id=f"h-{ft.value}",
                incident_id="inc-001",
                fault_type=ft,
                fault_location=FaultLocation(kind=kind, component_id=comp_id),
                rule_score=0.5,
            )
            assert h.fault_type == ft

    def test_rule_score_above_1_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FaultHypothesis(
                hypothesis_id="h-001",
                incident_id="inc-001",
                fault_type=FaultType.LINK_FAILURE,
                fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
                rule_score=1.5,
            )

    def test_rule_score_below_0_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FaultHypothesis(
                hypothesis_id="h-001",
                incident_id="inc-001",
                fault_type=FaultType.LINK_FAILURE,
                fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
                rule_score=-0.1,
            )

    def test_overlapping_evidence_ids_rejected(self) -> None:
        with pytest.raises(ValidationError, match="both supporting and contradictory"):
            FaultHypothesis(
                hypothesis_id="h-001",
                incident_id="inc-001",
                fault_type=FaultType.LINK_FAILURE,
                fault_location=FaultLocation(kind=FaultLocationKind.LINK, component_id="L12"),
                rule_score=0.7,
                supporting_evidence_ids=["ev-001", "ev-002"],
                contradictory_evidence_ids=["ev-002"],  # overlaps!
            )

    def test_router_fault_location_requires_router_id(self) -> None:
        with pytest.raises(ValidationError, match="router pattern"):
            FaultHypothesis(
                hypothesis_id="h-001",
                incident_id="inc-001",
                fault_type=FaultType.ROUTER_FAILURE,
                fault_location=FaultLocation(
                    kind=FaultLocationKind.ROUTER,
                    component_id="L12",  # wrong — link id for router kind
                ),
                rule_score=0.6,
            )

    def test_link_fault_location_requires_link_id(self) -> None:
        with pytest.raises(ValidationError, match="link pattern"):
            FaultHypothesis(
                hypothesis_id="h-001",
                incident_id="inc-001",
                fault_type=FaultType.LINK_FAILURE,
                fault_location=FaultLocation(
                    kind=FaultLocationKind.LINK,
                    component_id="R1",  # wrong — router id for link kind
                ),
                rule_score=0.6,
            )


# ===========================================================================
# Diagnosis schema tests
# ===========================================================================


def _make_diagnosis_result(status: DiagnosisStatus, top1: FaultHypothesis | None = None) -> DiagnosisResult:
    h1 = top1 or _make_hypothesis("h-001", score=0.85)
    h2 = _make_hypothesis("h-002", fault_type=FaultType.PACKET_LOSS, score=0.45)

    ranked: list[RankedHypothesis] = []
    top3: list[FaultHypothesis] = []

    if status != DiagnosisStatus.INSUFFICIENT_EVIDENCE:
        ranked = [
            RankedHypothesis(rank=1, hypothesis=h1),
            RankedHypothesis(rank=2, hypothesis=h2),
        ]
        top3 = [h1, h2]

    return DiagnosisResult(
        result_id="diag-001",
        incident_id="inc-001",
        diagnosed_at=NOW,
        engine_version="0.1.0",
        status=status,
        ranked_hypotheses=ranked,
        top1_hypothesis=h1 if status != DiagnosisStatus.INSUFFICIENT_EVIDENCE else None,
        top3_hypotheses=top3,
        evidence_certificate=_make_certificate(),
    )


class TestDiagnosisResult:
    def test_valid_diagnosed_result(self) -> None:
        result = _make_diagnosis_result(DiagnosisStatus.DIAGNOSED)
        assert result.status == DiagnosisStatus.DIAGNOSED
        assert result.top1_hypothesis is not None

    def test_valid_ambiguous_result(self) -> None:
        result = _make_diagnosis_result(DiagnosisStatus.AMBIGUOUS)
        assert result.status == DiagnosisStatus.AMBIGUOUS

    def test_insufficient_evidence_result(self) -> None:
        result = _make_diagnosis_result(DiagnosisStatus.INSUFFICIENT_EVIDENCE)
        assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
        assert result.top1_hypothesis is None

    def test_insufficient_evidence_with_top1_rejected(self) -> None:
        """Abstaining diagnosis must have top1 = None."""
        with pytest.raises(ValidationError, match="top1_hypothesis must be None"):
            DiagnosisResult(
                result_id="diag-001",
                incident_id="inc-001",
                diagnosed_at=NOW,
                engine_version="0.1.0",
                status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
                ranked_hypotheses=[],
                top1_hypothesis=_make_hypothesis(),  # invalid when abstaining
                top3_hypotheses=[],
                evidence_certificate=_make_certificate(),
            )

    def test_ranked_hypotheses_must_be_sequential(self) -> None:
        h1 = _make_hypothesis("h-001", score=0.9)
        h2 = _make_hypothesis("h-002", score=0.5)
        with pytest.raises(ValidationError, match="sequential"):
            DiagnosisResult(
                result_id="diag-001",
                incident_id="inc-001",
                diagnosed_at=NOW,
                engine_version="0.1.0",
                status=DiagnosisStatus.DIAGNOSED,
                ranked_hypotheses=[
                    RankedHypothesis(rank=1, hypothesis=h1),
                    RankedHypothesis(rank=3, hypothesis=h2),  # gap — invalid
                ],
                top1_hypothesis=h1,
                top3_hypotheses=[h1],
                evidence_certificate=_make_certificate(),
            )

    def test_top3_must_be_subset_of_ranked(self) -> None:
        h1 = _make_hypothesis("h-001", score=0.9)
        h_orphan = _make_hypothesis("h-orphan", score=0.7)
        with pytest.raises(ValidationError, match="not found in ranked_hypotheses"):
            DiagnosisResult(
                result_id="diag-001",
                incident_id="inc-001",
                diagnosed_at=NOW,
                engine_version="0.1.0",
                status=DiagnosisStatus.DIAGNOSED,
                ranked_hypotheses=[RankedHypothesis(rank=1, hypothesis=h1)],
                top1_hypothesis=h1,
                top3_hypotheses=[h1, h_orphan],  # h_orphan not in ranked_hypotheses
                evidence_certificate=_make_certificate(),
            )

    def test_naive_diagnosed_at_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            DiagnosisResult(
                result_id="diag-001",
                incident_id="inc-001",
                diagnosed_at=datetime(2026, 10, 14, 12, 0, 0),  # naive
                engine_version="0.1.0",
                status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
                ranked_hypotheses=[],
                top1_hypothesis=None,
                top3_hypotheses=[],
                evidence_certificate=_make_certificate(),
            )


# ===========================================================================
# Probe schema tests
# ===========================================================================


class TestProbeRequest:
    def _base_probe(self, probe_type: ProbeType = ProbeType.PING) -> dict:
        return {
            "probe_id": "probe-001",
            "incident_id": "inc-001",
            "probe_type": probe_type,
            "source_router": "R1",
            "selection_reason": "High packet loss detected on R1→R3 path",
            "requested_at": NOW,
        }

    def test_valid_ping_probe(self) -> None:
        probe = ProbeRequest(**{**self._base_probe(ProbeType.PING), "target_address": "192.168.255.3"})
        assert probe.probe_type == ProbeType.PING

    def test_valid_ospf_neighbour_probe(self) -> None:
        probe = ProbeRequest(**{**self._base_probe(ProbeType.OSPF_NEIGHBOUR), "target_router": "R2"})
        assert probe.probe_type == ProbeType.OSPF_NEIGHBOUR

    def test_valid_interface_state_probe(self) -> None:
        probe = ProbeRequest(**{**self._base_probe(ProbeType.INTERFACE_STATE), "target_interface": "eth1"})
        assert probe.probe_type == ProbeType.INTERFACE_STATE

    def test_valid_routing_table_probe(self) -> None:
        probe = ProbeRequest(**{**self._base_probe(ProbeType.ROUTING_TABLE), "target_prefix": "192.168.255.3/32"})
        assert probe.probe_type == ProbeType.ROUTING_TABLE

    def test_valid_traceroute_probe(self) -> None:
        probe = ProbeRequest(**{**self._base_probe(ProbeType.TRACEROUTE), "target_address": "192.168.255.5"})
        assert probe.probe_type == ProbeType.TRACEROUTE

    def test_ping_without_target_address_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires target_address"):
            ProbeRequest(**self._base_probe(ProbeType.PING))

    def test_ospf_neighbour_without_target_router_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires target_router"):
            ProbeRequest(**self._base_probe(ProbeType.OSPF_NEIGHBOUR))

    def test_interface_state_without_target_interface_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires target_interface"):
            ProbeRequest(**self._base_probe(ProbeType.INTERFACE_STATE))

    def test_routing_table_without_target_prefix_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires target_prefix"):
            ProbeRequest(**self._base_probe(ProbeType.ROUTING_TABLE))

    def test_timeout_hard_limit_enforced(self) -> None:
        """Timeout must not exceed MAX_PROBE_TIMEOUT_S."""
        with pytest.raises(ValidationError):
            ProbeRequest(**{
                **self._base_probe(ProbeType.PING),
                "target_address": "192.168.255.3",
                "timeout_s": MAX_PROBE_TIMEOUT_S + 1,
            })

    def test_no_arbitrary_command_field_allowed(self) -> None:
        """ProbeRequest must reject unknown fields (extra='forbid')."""
        with pytest.raises(ValidationError):
            ProbeRequest(**{
                **self._base_probe(ProbeType.PING),
                "target_address": "192.168.255.3",
                "command": "show ip route",  # arbitrary — must be rejected
            })

    def test_no_script_field_allowed(self) -> None:
        with pytest.raises(ValidationError):
            ProbeRequest(**{
                **self._base_probe(ProbeType.PING),
                "target_address": "192.168.255.3",
                "script": "rm -rf /",  # must be rejected
            })

    def test_all_probe_types_exist(self) -> None:
        """All five specified ProbeType values must exist."""
        expected = {"PING", "INTERFACE_STATE", "OSPF_NEIGHBOUR", "ROUTING_TABLE", "TRACEROUTE"}
        actual = {pt.value for pt in ProbeType}
        assert expected == actual


# ===========================================================================
# Ground-truth isolation tests
# ===========================================================================


class TestGroundTruthIsolation:
    def test_fault_injection_record_constructs(self) -> None:
        from app.evaluation.ground_truth import FaultInjectionRecord

        record = FaultInjectionRecord(
            run_id="run-001",
            scenario_id="SCEN-01-L12-LINK-FAILURE",
            seeded_fault_type=FaultType.LINK_FAILURE,
            actual_fault_location_id="L12",
            injection_timestamp=NOW,
            recovery_timestamp=LATER,
            experiment_seed=42,
        )
        assert record.seeded_fault_type == FaultType.LINK_FAILURE

    def test_ground_truth_label_not_safe_for_inference(self) -> None:
        """is_ground_truth_label_safe_for_inference must always return False."""
        from app.evaluation.ground_truth import FaultInjectionRecord

        record = FaultInjectionRecord(
            run_id="run-001",
            scenario_id="SCEN-01",
            seeded_fault_type=FaultType.ROUTER_FAILURE,
            actual_fault_location_id="R3",
            injection_timestamp=NOW,
            experiment_seed=0,
        )
        assert record.is_ground_truth_label_safe_for_inference() is False

    def test_fault_injection_record_fields_not_in_evidence_record(self) -> None:
        """EvidenceRecord has no fields that could hold ground-truth labels."""
        from app.schemas.evidence import EvidenceRecord

        evidence_fields = set(EvidenceRecord.model_fields.keys())
        forbidden_fields = {
            "seeded_fault_type",
            "actual_fault_location_id",
            "ground_truth",
            "true_label",
            "injected_fault",
        }
        overlap = evidence_fields & forbidden_fields
        assert not overlap, f"EvidenceRecord must not contain ground-truth fields: {overlap}"

    def test_fault_injection_record_fields_not_in_hypothesis(self) -> None:
        """FaultHypothesis has no fields that could hold ground-truth labels."""
        hypothesis_fields = set(FaultHypothesis.model_fields.keys())
        forbidden_fields = {
            "seeded_fault_type",
            "actual_fault_location_id",
            "ground_truth",
            "true_label",
            "injected_fault",
        }
        overlap = hypothesis_fields & forbidden_fields
        assert not overlap, f"FaultHypothesis must not contain ground-truth fields: {overlap}"

    def test_naive_injection_timestamp_rejected(self) -> None:
        from app.evaluation.ground_truth import FaultInjectionRecord

        with pytest.raises(ValidationError, match="timezone-aware"):
            FaultInjectionRecord(
                run_id="run-001",
                scenario_id="SCEN-01",
                seeded_fault_type=FaultType.LINK_FAILURE,
                actual_fault_location_id="L12",
                injection_timestamp=datetime(2026, 10, 14, 12, 0, 0),  # naive
                experiment_seed=0,
            )

    def test_fault_injection_not_importable_from_diagnosis_module(self) -> None:
        """ground_truth should not be auto-imported by the diagnosis module."""
        import importlib

        diag_module = importlib.import_module("app.diagnosis.interfaces")
        # FaultInjectionRecord should not be a top-level name in the interfaces module
        assert not hasattr(diag_module, "FaultInjectionRecord"), (
            "FaultInjectionRecord must not be importable from diagnosis.interfaces"
        )


# ===========================================================================
# Incident schema tests
# ===========================================================================


class TestIncidentModel:
    def test_valid_incident(self) -> None:
        inc = Incident(
            incident_id="inc-001",
            detected_at=NOW,
            collection_window_start=NOW,
            topology_snapshot_id="snap-001",
        )
        assert inc.status == IncidentStatus.OPEN

    def test_window_end_before_start_rejected(self) -> None:
        with pytest.raises(ValidationError, match="collection_window_end must be"):
            Incident(
                incident_id="inc-001",
                detected_at=NOW,
                collection_window_start=LATER,
                collection_window_end=NOW,  # before start
                topology_snapshot_id="snap-001",
            )

    def test_resolved_before_detected_rejected(self) -> None:
        with pytest.raises(ValidationError, match="resolved_at must be"):
            Incident(
                incident_id="inc-001",
                detected_at=LATER,
                collection_window_start=LATER,
                resolved_at=NOW,  # before detected_at
                topology_snapshot_id="snap-001",
            )
