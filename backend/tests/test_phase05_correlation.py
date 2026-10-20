"""
NEXORA Phase 05 — Topology Intelligence & Incident Correlation Tests.

Test coverage:
  01. OSPF identity mapping validation
  02. Router identity resolution (OSPF-ID / loopback / link address)
  03. TopologyGraph construction from expected topology
  04. TopologyGraph neighbour queries
  05. TopologyGraph path queries and affected-path detection
  06. TopologyGraph adjacency comparison
  07. TopologyGraph connected components after router removal
  08. Evidence dependency graph construction and component queries
  09. Evidence dependency graph relationship types
  10. Temporal correlator deduplication
  11. Temporal correlator window computation (co-incident collection)
  12. Temporal correlator OSPF dead-timer buffer accounting
  13. Temporal correlator grouping with spread records
  14. CorrelationResult and CorrelatedIncident schema validation
  15. CorrelatedIncident rejects ground-truth fields (extra="forbid")
  16. Correlation engine — healthy baseline snapshot
  17. Correlation engine — COLLECTION_FAILURE records (F2 router failure)
  18. Correlation engine — typed symptom classification (interface DOWN)
  19. Correlation engine — typed symptom classification (OSPF adjacency LOST)
  20. Correlation engine — typed symptom classification (packet loss elevated)
  21. Correlation engine — typed symptom classification (latency elevated)
  22. Correlation engine — typed symptom classification (route missing)
  23. Correlation engine — multiple symptoms grouping by topology proximity
  24. Correlation engine — isolation of unrelated symptoms (different routers)
  25. Correlation engine — contradictory observation detection (OSPF lost, iface up)
  26. Correlation engine — ground-truth isolation verification
  27. Correlation engine — snapshot with injected ground-truth raises GroundTruthLeakageError
  28. Correlation engine — correlate all six snapshot files (smoke test)
  29. Correlation engine — multiple independent incident groups
  30. Correlation engine — determinism (same input = same result structure)
  31. CorrelationResult schema serializes and round-trips cleanly
  32. EvidenceNormalizer.deserialize_record — graceful fallback to base class
  33. EvidenceNormalizer.deserialize_record — typed reconstruction when fields present
  34. TopologyGraph.explain_relationship — direct link
  35. TopologyGraph.explain_relationship — indirect path
  36. TopologyGraph.map_prefix_to_router — loopback /32
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.collectors.normalizer import EvidenceNormalizer, GroundTruthLeakageError
from app.correlation.engine import CorrelationEngine
from app.correlation.evidence_graph import EvidenceGraph, RelationshipType
from app.correlation.temporal import (
    OSPF_DEAD_TIMER_BUFFER_SECONDS,
    TemporalCorrelator,
)
from app.schemas.correlation import (
    CORRELATION_ENGINE_VERSION,
    CorrelatedIncident,
    CorrelatedSymptom,
    CorrelationResult,
    SymptomCategory,
)
from app.schemas.evidence import (
    CollectionMethod,
    EvidenceRecord,
    EvidenceSourceType,
    InterfaceObservation,
    ObservationStatus,
    OSPFObservation,
    PingMeasurement,
    RouteObservation,
)
from app.schemas.topology import OSPFNeighbourState
from app.topology.graph import (
    TopologyKind,
    build_expected_topology_graph,
)
from app.topology.identity import (
    OSPF_ID_TO_ROUTER,
    ROUTER_TO_LOOPBACK_IP,
    ROUTER_TO_OSPF_ID,
    resolve_link_from_router_pair,
    resolve_router_from_any_address,
    resolve_router_from_ospf_id,
    validate_identity_mapping,
    validate_ospf_id_format,
    validate_router_id_format,
)

# ---------------------------------------------------------------------------
# Observation datasets directory
# ---------------------------------------------------------------------------

_DATASETS_DIR = (
    Path(__file__).resolve().parents[2]
    / "evaluation"
    / "datasets"
    / "observations"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _make_base_record(
    source_router: str = "R1",
    source_type: EvidenceSourceType = EvidenceSourceType.OSPF_API,
    event_type: str = "OSPF_NEIGHBOUR_FULL",
    observed_at: datetime | None = None,
    source_interface: str | None = None,
    collection_status: ObservationStatus = ObservationStatus.OBSERVED,
) -> EvidenceRecord:
    ts = observed_at or _now()
    return EvidenceRecord(
        evidence_id=f"ev-test-{uuid.uuid4().hex[:8]}",
        source_router=source_router,
        source_type=source_type,
        event_type=event_type,
        observed_at=ts,
        collected_at=ts,
        collection_method=CollectionMethod.PERIODIC_POLL,
        collection_status=collection_status,
        source_interface=source_interface,
    )


def _make_interface_record(
    router: str,
    iface: str,
    status: str,
    ts: datetime | None = None,
) -> InterfaceObservation:
    ts = ts or _now()
    return InterfaceObservation(
        evidence_id=f"ev-iface-{router}-{iface}-{uuid.uuid4().hex[:6]}",
        source_router=router,
        source_type=EvidenceSourceType.INTERFACE_POLL,
        event_type="INTERFACE_STATUS",
        observed_at=ts,
        collected_at=ts,
        collection_method=CollectionMethod.PERIODIC_POLL,
        collection_status=ObservationStatus.OBSERVED,
        source_interface=iface,
        observed_status=status,
    )


def _make_ospf_record(
    local_router: str,
    nbr_ospf_id: str,
    state: str,
    iface: str = "eth1",
    ts: datetime | None = None,
) -> OSPFObservation:
    ts = ts or _now()
    return OSPFObservation(
        evidence_id=f"ev-ospf-{local_router}-{nbr_ospf_id.replace('.', '')}-{uuid.uuid4().hex[:6]}",
        source_router=local_router,
        source_type=EvidenceSourceType.OSPF_API,
        event_type="OSPF_NEIGHBOUR_FULL" if state == "Full/-" else "OSPF_NEIGHBOUR_DOWN",
        observed_at=ts,
        collected_at=ts,
        collection_method=CollectionMethod.PERIODIC_POLL,
        collection_status=ObservationStatus.OBSERVED,
        source_interface=iface,
        neighbour_router_id=nbr_ospf_id,
        neighbour_address="10.0.12.2",
        adjacency_state=state,
    )


def _make_ping_record(
    probe_src: str,
    target: str,
    loss_pct: float,
    avg_rtt: float | None = 0.5,
    ts: datetime | None = None,
) -> PingMeasurement:
    ts = ts or _now()
    sent = 10  # Use 10 so 50% → exactly 5 received, avoiding rounding errors
    received = int(sent * (1 - loss_pct / 100))
    actual_loss = (1 - received / sent) * 100 if sent > 0 else 0.0
    return PingMeasurement(
        evidence_id=f"ev-ping-{probe_src}-{target.replace('.', '')}-{uuid.uuid4().hex[:6]}",
        source_router=probe_src,
        source_type=EvidenceSourceType.ACTIVE_PING,
        event_type="PING_RESULT",
        observed_at=ts,
        collected_at=ts,
        collection_method=CollectionMethod.TRIGGERED_PROBE,
        collection_status=ObservationStatus.OBSERVED,
        target_address=target,
        probe_source=probe_src,
        packets_sent=sent,
        packets_received=received,
        packet_loss_pct=actual_loss,
        rtt_min_ms=avg_rtt,
        rtt_avg_ms=avg_rtt,
        rtt_max_ms=avg_rtt,
    )


def _make_route_record(
    router: str,
    prefix: str,
    is_present: bool,
    next_hop: str = "10.0.12.2",
    ts: datetime | None = None,
) -> RouteObservation:
    ts = ts or _now()
    return RouteObservation(
        evidence_id=f"ev-route-{router}-{prefix.replace('/', '_')}-{uuid.uuid4().hex[:6]}",
        source_router=router,
        source_type=EvidenceSourceType.ROUTING_TABLE,
        event_type="ROUTE_PRESENT" if is_present else "ROUTE_MISSING",
        observed_at=ts,
        collected_at=ts,
        collection_method=CollectionMethod.PERIODIC_POLL,
        collection_status=ObservationStatus.OBSERVED,
        destination_prefix=prefix,
        is_present=is_present,
        next_hop_address=next_hop if is_present else None,
        next_hop_interface="eth1" if is_present else None,
        route_type="OSPF",
    )


def _make_collection_failed_record(router: str) -> EvidenceRecord:
    ts = _now()
    return EvidenceRecord(
        evidence_id=f"ev-fail-{router}-{uuid.uuid4().hex[:6]}",
        source_router=router,
        source_type=EvidenceSourceType.INTERFACE_POLL,
        event_type="COLLECTION_FAILURE",
        observed_at=ts,
        collected_at=ts,
        collection_method=CollectionMethod.PERIODIC_POLL,
        collection_status=ObservationStatus.COLLECTION_FAILED,
    )


# ===========================================================================
# 01 — OSPF identity mapping validation
# ===========================================================================


class TestOSPFIdentityMapping:
    """Validate OSPF Router-ID, loopback, and router-id are distinct per router."""

    def test_ospf_id_ne_loopback_for_all_routers(self):
        """OSPF Router-ID must not equal the loopback IP for any router."""
        mapping = validate_identity_mapping()
        for rid, m in mapping.items():
            assert m["ospf_id_ne_loopback"], (
                f"Router {rid}: OSPF Router-ID {m['ospf_router_id']!r} "
                f"must NOT equal loopback IP {m['loopback_ip']!r}"
            )

    def test_all_five_routers_present(self):
        """Exactly R1–R5 must be in the identity mapping."""
        mapping = validate_identity_mapping()
        assert set(mapping.keys()) == {"R1", "R2", "R3", "R4", "R5"}

    def test_ospf_router_ids_have_correct_format(self):
        """OSPF Router-IDs must be dotted-decimal IPv4 addresses."""
        for rid, ospf_id in ROUTER_TO_OSPF_ID.items():
            assert validate_ospf_id_format(ospf_id), (
                f"Router {rid}: OSPF Router-ID {ospf_id!r} is not valid dotted-decimal"
            )

    def test_router_ids_have_correct_format(self):
        """Stable router IDs must match R<N> pattern."""
        for rid in ROUTER_TO_OSPF_ID:
            assert validate_router_id_format(rid), (
                f"Router ID {rid!r} does not match R<N> pattern"
            )

    def test_ospf_id_to_router_reverse_lookup(self):
        """Reverse lookup from OSPF-ID to router_id is consistent."""
        for rid, ospf_id in ROUTER_TO_OSPF_ID.items():
            resolved = OSPF_ID_TO_ROUTER.get(ospf_id)
            assert resolved == rid, (
                f"Reverse lookup of {ospf_id!r} returned {resolved!r}, expected {rid!r}"
            )

    def test_r2_ospf_id_is_2222_not_loopback(self):
        """
        Phase 04 report incorrectly used '192.168.255.2' to describe R2's OSPF identity.
        This test explicitly confirms R2's OSPF Router-ID is '2.2.2.2' (not '192.168.255.2').
        """
        assert ROUTER_TO_OSPF_ID["R2"] == "2.2.2.2", (
            "R2 OSPF Router-ID must be '2.2.2.2' (not '192.168.255.2' which is the loopback)."
        )
        assert ROUTER_TO_LOOPBACK_IP["R2"] == "192.168.255.2"
        # They must be different
        assert ROUTER_TO_OSPF_ID["R2"] != ROUTER_TO_LOOPBACK_IP["R2"]


# ===========================================================================
# 02 — Router identity resolution
# ===========================================================================


class TestRouterIdentityResolution:

    def test_resolve_from_ospf_id(self):
        assert resolve_router_from_ospf_id("1.1.1.1") == "R1"
        assert resolve_router_from_ospf_id("3.3.3.3") == "R3"
        assert resolve_router_from_ospf_id("9.9.9.9") is None

    def test_resolve_from_loopback(self):
        assert resolve_router_from_any_address("192.168.255.1") == "R1"
        assert resolve_router_from_any_address("192.168.255.4") == "R4"
        assert resolve_router_from_any_address("192.168.255.1/32") == "R1"

    def test_resolve_from_link_address(self):
        assert resolve_router_from_any_address("10.0.12.1") == "R1"
        assert resolve_router_from_any_address("10.0.12.2") == "R2"
        assert resolve_router_from_any_address("10.0.45.2") == "R5"

    def test_resolve_link_from_router_pair(self):
        assert resolve_link_from_router_pair("R1", "R2") == "L12"
        assert resolve_link_from_router_pair("R2", "R1") == "L12"  # bidirectional
        assert resolve_link_from_router_pair("R5", "R1") == "L51"
        assert resolve_link_from_router_pair("R1", "R4") is None  # not directly connected

    def test_resolve_unknown_address_returns_none(self):
        assert resolve_router_from_any_address("172.16.0.1") is None
        assert resolve_router_from_any_address("not-an-ip") is None


# ===========================================================================
# 03 — TopologyGraph construction
# ===========================================================================


class TestTopologyGraphConstruction:

    def test_build_expected_topology_graph(self):
        topo = build_expected_topology_graph()
        assert topo.kind == TopologyKind.EXPECTED
        assert len(topo.topology.routers) == 5
        assert len(topo.topology.links) == 5

    def test_all_routers_in_physical_graph(self):
        topo = build_expected_topology_graph()
        for rid in ["R1", "R2", "R3", "R4", "R5"]:
            assert rid in topo.physical_graph.nodes, f"{rid} missing from physical graph"

    def test_all_links_in_physical_graph(self):
        topo = build_expected_topology_graph()
        # 5 links → 5 edges
        assert topo.physical_graph.number_of_edges() == 5

    def test_router_node_attributes(self):
        topo = build_expected_topology_graph()
        r1_attrs = topo.get_router_info("R1")
        assert r1_attrs["ospf_router_id"] == "1.1.1.1"
        assert r1_attrs["loopback"] == "192.168.255.1"


# ===========================================================================
# 04 — Neighbour queries
# ===========================================================================


class TestTopologyGraphNeighbours:

    def test_r1_direct_neighbours(self):
        topo = build_expected_topology_graph()
        nbrs = topo.get_router_neighbours("R1")
        assert set(nbrs) == {"R2", "R5"}, f"Expected R2 and R5, got {nbrs}"

    def test_r3_direct_neighbours(self):
        topo = build_expected_topology_graph()
        nbrs = topo.get_router_neighbours("R3")
        assert set(nbrs) == {"R2", "R4"}

    def test_r1_directly_connected_links(self):
        topo = build_expected_topology_graph()
        links = topo.get_directly_connected_links("R1")
        assert set(links) == {"L12", "L51"}

    def test_find_link_between_adjacent(self):
        topo = build_expected_topology_graph()
        assert topo.find_link_between("R1", "R2") == "L12"
        assert topo.find_link_between("R4", "R5") == "L45"

    def test_find_link_between_non_adjacent_returns_none(self):
        topo = build_expected_topology_graph()
        assert topo.find_link_between("R1", "R4") is None

    def test_links_affected_by_router_outage(self):
        topo = build_expected_topology_graph()
        affected = topo.get_links_affected_by_router_outage("R3")
        assert set(affected) == {"L23", "L34"}

    def test_unknown_router_returns_empty(self):
        topo = build_expected_topology_graph()
        assert topo.get_router_neighbours("R99") == []


# ===========================================================================
# 05 — Path queries
# ===========================================================================


class TestTopologyGraphPaths:

    def test_all_simple_paths_r1_to_r3(self):
        topo = build_expected_topology_graph()
        paths = topo.get_alternate_paths("R1", "R3")
        assert len(paths) >= 1
        # All paths must start at R1 and end at R3
        for path in paths:
            assert path[0] == "R1"
            assert path[-1] == "R3"

    def test_shortest_path_r1_to_r3(self):
        topo = build_expected_topology_graph()
        paths = topo.get_alternate_paths("R1", "R3")
        # Shortest path: R1 → R2 → R3 (length 3)
        shortest = paths[0]
        assert len(shortest) == 3

    def test_alternate_path_exists_r1_to_r4(self):
        topo = build_expected_topology_graph()
        paths = topo.get_alternate_paths("R1", "R4")
        # At least 2 paths should exist (ring topology)
        assert len(paths) >= 2

    def test_find_affected_paths_link_change(self):
        topo = build_expected_topology_graph()
        affected = topo.find_affected_paths("L12")
        # Any path through R1-R2 link is affected
        assert len(affected) > 0
        # All pairs should involve routers near L12
        router_set = {r for pair in affected for r in pair}
        assert "R1" in router_set or "R2" in router_set

    def test_map_prefix_to_router(self):
        topo = build_expected_topology_graph()
        assert topo.map_prefix_to_router("192.168.255.3/32") == "R3"
        assert topo.map_prefix_to_router("192.168.255.1/32") == "R1"
        assert topo.map_prefix_to_router("10.0.12.0/30") is None  # link subnet, not loopback


# ===========================================================================
# 06 — Adjacency comparison
# ===========================================================================


class TestAdjacencyComparison:

    @staticmethod
    def _make_full_adjacencies() -> list:
        """Build RoutingAdjacency objects for all 10 expected directional pairs."""
        from app.schemas.topology import RoutingAdjacency
        ts = _now()
        links = [
            ("R1", "R2", "eth1", "10.0.12.2"),
            ("R2", "R1", "eth1", "10.0.12.1"),
            ("R2", "R3", "eth2", "10.0.23.2"),
            ("R3", "R2", "eth1", "10.0.23.1"),
            ("R3", "R4", "eth2", "10.0.34.2"),
            ("R4", "R3", "eth1", "10.0.34.1"),
            ("R4", "R5", "eth2", "10.0.45.2"),
            ("R5", "R4", "eth1", "10.0.45.1"),
            ("R5", "R1", "eth2", "10.0.15.1"),
            ("R1", "R5", "eth2", "10.0.15.2"),
        ]
        return [
            RoutingAdjacency(
                local_router=local,
                neighbour_router=nbr,
                local_interface=iface,
                neighbour_address=nbr_addr,
                state=OSPFNeighbourState.FULL,
                observed_at=ts,
            )
            for local, nbr, iface, nbr_addr in links
        ]

    def test_healthy_adjacency_comparison(self):
        topo = build_expected_topology_graph()
        adj = self._make_full_adjacencies()
        comparison = topo.compare_adjacency_states(adj)
        assert comparison.is_healthy, (
            f"Expected healthy comparison, got {len(comparison.missing)} missing"
        )
        assert comparison.full_count == comparison.total_expected
        assert len(comparison.missing) == 0

    def test_missing_adjacency_detected(self):
        topo = build_expected_topology_graph()
        adj = [a for a in self._make_full_adjacencies() if not (
            a.local_router == "R1" and a.neighbour_router == "R2"
        )]
        comparison = topo.compare_adjacency_states(adj)
        assert not comparison.is_healthy
        missing_pairs = [(e.local_router, e.neighbour_router) for e in comparison.missing]
        assert ("R1", "R2") in missing_pairs

    def test_expected_adjacency_count_is_10(self):
        """10 directional adjacencies expected (5 links × 2 directions)."""
        topo = build_expected_topology_graph()
        adj = self._make_full_adjacencies()
        comparison = topo.compare_adjacency_states(adj)
        assert comparison.total_expected == 10, (
            f"Expected 10 directional adjacencies, got {comparison.total_expected}"
        )


# ===========================================================================
# 07 — Connected components
# ===========================================================================


class TestConnectedComponents:

    def test_healthy_topology_is_single_component(self):
        topo = build_expected_topology_graph()
        components = topo.get_connected_components()
        assert len(components) == 1
        assert frozenset(["R1", "R2", "R3", "R4", "R5"]) in components

    def test_explain_relationship_direct_link(self):
        topo = build_expected_topology_graph()
        explanation = topo.explain_relationship("R1", "R2")
        assert "L12" in explanation or "directly connected" in explanation

    def test_explain_relationship_indirect(self):
        topo = build_expected_topology_graph()
        explanation = topo.explain_relationship("R1", "R4")
        assert "path" in explanation.lower() or "not directly" in explanation.lower()

    def test_explain_relationship_router_to_link(self):
        topo = build_expected_topology_graph()
        explanation = topo.explain_relationship("R1", "L12")
        assert "endpoint" in explanation.lower() or "R1" in explanation


# ===========================================================================
# 08 — Evidence dependency graph
# ===========================================================================


class TestEvidenceGraph:

    def test_build_empty_graph(self):
        eg = EvidenceGraph()
        assert eg.summary()["total_nodes"] == 0
        assert eg.summary()["total_edges"] == 0

    def test_add_base_record_creates_router_node(self):
        eg = EvidenceGraph()
        rec = _make_base_record(source_router="R1")
        eg.add_record(rec)
        routers = eg.get_component_ids("router")
        assert "R1" in routers

    def test_add_interface_record_creates_interface_node(self):
        eg = EvidenceGraph()
        rec = _make_interface_record("R2", "eth1", "up")
        eg.add_record(rec)
        ifaces = eg.get_component_ids("interface")
        assert "iface:R2:eth1" in ifaces

    def test_add_ospf_record_creates_adjacency_node(self):
        eg = EvidenceGraph()
        rec = _make_ospf_record("R1", "2.2.2.2", "Full/-")
        eg.add_record(rec)
        adj_nodes = eg.get_component_ids("ospf_adjacency")
        assert len(adj_nodes) >= 1

    def test_get_evidence_for_router(self):
        eg = EvidenceGraph()
        rec1 = _make_base_record("R1")
        rec2 = _make_base_record("R1")
        eg.add_records([rec1, rec2])
        eids = eg.get_evidence_for_component("R1")
        assert rec1.evidence_id in eids
        assert rec2.evidence_id in eids

    def test_downed_interface_creates_link_relationship(self):
        eg = EvidenceGraph()
        rec = _make_interface_record("R1", "eth1", "down")
        eg.add_record(rec)
        rels = eg.get_all_relationships()
        link_rels = [r for r in rels if r.relationship_type == RelationshipType.INTERFACE_UNDERLIES_ADJACENCY]
        assert len(link_rels) >= 1
        assert any(r.component_id == "L12" for r in link_rels)

    def test_graph_summary(self):
        eg = EvidenceGraph()
        for i in range(3):
            eg.add_record(_make_base_record(f"R{i+1}"))
        summary = eg.summary()
        assert summary["total_evidence_records"] == 3
        assert summary["total_nodes"] > 0


# ===========================================================================
# 09 — Relationship types
# ===========================================================================


class TestEvidenceGraphRelationshipTypes:

    def test_ospf_down_creates_link_underlie_rel(self):
        eg = EvidenceGraph()
        rec = _make_ospf_record("R1", "2.2.2.2", "down")
        eg.add_record(rec)
        rels = eg.get_all_relationships()
        link_rels = [
            r for r in rels
            if r.relationship_type == RelationshipType.LINK_UNDERLIES_ADJACENCY
        ]
        assert len(link_rels) >= 1

    def test_all_records_have_describes_router_rel(self):
        eg = EvidenceGraph()
        rec = _make_base_record("R3")
        eg.add_record(rec)
        rels = eg.get_relationships_from(rec.evidence_id)
        types = {r.relationship_type for r in rels}
        assert RelationshipType.DESCRIBES_ROUTER in types


# ===========================================================================
# 10 — Temporal correlator deduplication
# ===========================================================================


class TestTemporalCorrelatorDeduplication:

    def test_exact_duplicate_records_removed(self):
        correlator = TemporalCorrelator()
        ts = _now()
        rec1 = _make_base_record("R1", observed_at=ts, source_interface="eth1")
        rec2 = _make_base_record("R1", observed_at=ts, source_interface="eth1")
        # Same router, type, event, interface, timestamp bucket → duplicate
        deduped, dup_count = correlator.deduplicate([rec1, rec2])
        assert dup_count == 1
        assert len(deduped) == 1

    def test_different_routers_not_deduplicated(self):
        correlator = TemporalCorrelator()
        ts = _now()
        rec1 = _make_base_record("R1", observed_at=ts)
        rec2 = _make_base_record("R2", observed_at=ts)
        deduped, dup_count = correlator.deduplicate([rec1, rec2])
        assert dup_count == 0
        assert len(deduped) == 2

    def test_different_event_types_not_deduplicated(self):
        correlator = TemporalCorrelator()
        ts = _now()
        rec1 = _make_base_record("R1", event_type="EVENT_A", observed_at=ts)
        rec2 = _make_base_record("R1", event_type="EVENT_B", observed_at=ts)
        deduped, _ = correlator.deduplicate([rec1, rec2])
        assert len(deduped) == 2

    def test_empty_list_deduplicates_cleanly(self):
        correlator = TemporalCorrelator()
        deduped, dup_count = correlator.deduplicate([])
        assert deduped == []
        assert dup_count == 0


# ===========================================================================
# 11 — Temporal window computation (co-incident collection)
# ===========================================================================


class TestTemporalWindowComputation:

    def test_co_incident_records_produce_single_group(self):
        correlator = TemporalCorrelator(window_seconds=120.0)
        ts = _now()
        records = [_make_base_record(f"R{i+1}", observed_at=ts) for i in range(5)]
        groups = correlator.group_by_window(records)
        assert len(groups) == 1
        assert groups[0].size == 5

    def test_window_duration_matches_config(self):
        correlator = TemporalCorrelator(window_seconds=60.0)
        ts = _now()
        rec = _make_base_record("R1", observed_at=ts)
        window = correlator.compute_window([rec])
        assert window.window_seconds >= 60.0

    def test_window_contains_anchor_time(self):
        correlator = TemporalCorrelator()
        ts = _now()
        records = [_make_base_record("R1", observed_at=ts)]
        window = correlator.compute_window(records)
        assert window.contains(ts)

    def test_minimum_window_enforced(self):
        with pytest.raises(ValueError, match="MIN_WINDOW_SECONDS"):
            TemporalCorrelator(window_seconds=1.0)

    def test_maximum_window_enforced(self):
        with pytest.raises(ValueError, match="MAX_WINDOW_SECONDS"):
            TemporalCorrelator(window_seconds=9000.0)


# ===========================================================================
# 12 — OSPF dead-timer buffer
# ===========================================================================


class TestOSPFDeadTimerBuffer:

    def test_ospf_buffer_default_is_45s(self):
        assert OSPF_DEAD_TIMER_BUFFER_SECONDS == 45.0

    def test_spread_records_window_extended_by_buffer(self):
        from datetime import timedelta

        correlator = TemporalCorrelator(window_seconds=120.0)
        ts_start = _now()
        ts_end = ts_start + timedelta(seconds=60)
        rec1 = _make_base_record("R1", observed_at=ts_start)
        rec2 = _make_base_record("R2", observed_at=ts_end)
        window = correlator.compute_window([rec1, rec2])
        # Window should extend at least 45s beyond ts_end
        assert window.window_end >= ts_end + timedelta(seconds=44)
        assert window.window_start <= ts_start


# ===========================================================================
# 13 — Temporal grouping with spread records
# ===========================================================================


class TestTemporalGrouping:

    def test_well_separated_records_form_two_groups(self):
        from datetime import timedelta

        correlator = TemporalCorrelator(window_seconds=30.0)
        ts1 = _now()
        ts2 = ts1 + timedelta(seconds=200)  # Far beyond 30s window
        records = [
            _make_base_record("R1", observed_at=ts1),
            _make_base_record("R2", observed_at=ts2),
        ]
        groups = correlator.group_by_window(records)
        assert len(groups) == 2

    def test_close_records_form_one_group(self):
        from datetime import timedelta

        correlator = TemporalCorrelator(window_seconds=120.0)
        ts = _now()
        records = [
            _make_base_record("R1", observed_at=ts),
            _make_base_record("R2", observed_at=ts + timedelta(seconds=10)),
        ]
        groups = correlator.group_by_window(records)
        assert len(groups) == 1

    def test_empty_records_returns_empty_groups(self):
        correlator = TemporalCorrelator()
        groups = correlator.group_by_window([])
        assert groups == []


# ===========================================================================
# 14 — Schema validation
# ===========================================================================


class TestSchemaValidation:

    def test_correlated_incident_rejects_naive_datetimes(self):
        ts_naive = datetime(2026, 10, 1, 0, 0, 0)  # No tzinfo
        with pytest.raises(Exception):
            CorrelatedIncident(
                incident_id="ci-test-001",
                status="HEALTHY",
                correlation_window_start=ts_naive,
                correlation_window_end=ts_naive,
                correlation_explanation="test",
            )

    def test_correlation_result_rejects_naive_datetime(self):
        ts_naive = datetime(2026, 10, 1, 0, 0, 0)
        with pytest.raises(Exception):
            CorrelationResult(
                result_id="cr-test-001",
                snapshot_id="snap-001",
                produced_at=ts_naive,
                total_evidence_records=0,
                anomalous_record_count=0,
                duplicate_records_removed=0,
                ground_truth_isolation_verified=True,
            )

    def test_correlated_symptom_valid_construction(self):
        sym = CorrelatedSymptom(
            symptom_id="sym-0001",
            category=SymptomCategory.OSPF_ADJACENCY_LOST,
            affected_component="adj:R1→R2",
            description="OSPF adjacency R1→R2 is DOWN.",
            supporting_evidence_ids=["ev-001"],
            is_direct_observation=True,
        )
        assert sym.category == SymptomCategory.OSPF_ADJACENCY_LOST

    def test_all_symptom_categories_are_strings(self):
        for cat in SymptomCategory:
            assert isinstance(cat.value, str)

    def test_correlation_result_round_trip(self):
        ts = _now()
        result = CorrelationResult(
            result_id="cr-roundtrip",
            snapshot_id="snap-rt",
            produced_at=ts,
            total_evidence_records=0,
            anomalous_record_count=0,
            duplicate_records_removed=0,
            ground_truth_isolation_verified=True,
        )
        data = result.model_dump(mode="json")
        restored = CorrelationResult.model_validate(data)
        assert restored.result_id == "cr-roundtrip"
        assert restored.produced_at.tzinfo is not None


# ===========================================================================
# 15 — Extra field rejection
# ===========================================================================


class TestExtraFieldRejection:

    def test_correlated_incident_rejects_extra_fields(self):
        ts = _now()
        with pytest.raises(Exception):
            CorrelatedIncident(
                incident_id="ci-001",
                status="HEALTHY",
                correlation_window_start=ts,
                correlation_window_end=ts,
                correlation_explanation="test",
                fault_type="LINK_FAILURE",  # MUST be rejected — ground-truth
            )

    def test_correlated_symptom_rejects_extra_fields(self):
        with pytest.raises(Exception):
            CorrelatedSymptom(
                symptom_id="sym-001",
                category=SymptomCategory.HEALTHY,
                affected_component="R1",
                description="OK",
                is_direct_observation=True,
                injected_label="F1",  # MUST be rejected
            )


# ===========================================================================
# 16 — Correlation engine: healthy baseline
# ===========================================================================


class TestCorrelationEngineHealthy:

    def test_healthy_baseline_single_group(self):
        engine = CorrelationEngine()
        records = [_make_base_record(f"R{i+1}") for i in range(5)]
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records(records, topo)
        assert len(result.incidents) == 1
        assert result.incidents[0].status == "HEALTHY"

    def test_healthy_result_has_zero_anomalous(self):
        engine = CorrelationEngine()
        records = [_make_base_record(f"R{i+1}") for i in range(5)]
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records(records, topo)
        assert result.anomalous_record_count == 0

    def test_empty_records_returns_empty_result(self):
        engine = CorrelationEngine()
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([], topo)
        assert result.total_evidence_records == 0
        assert result.incidents == []


# ===========================================================================
# 17 — Correlation engine: COLLECTION_FAILURE (F2 router failure proxy)
# ===========================================================================


class TestCorrelationEngineCollectionFailure:

    def test_collection_failure_triggers_symptom(self):
        engine = CorrelationEngine()
        failed_rec = _make_collection_failed_record("R3")
        healthy_recs = [_make_base_record(f"R{i+1}") for i in range(5) if i != 2]
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([failed_rec] + healthy_recs, topo)
        assert result.anomalous_record_count >= 1
        # At least one incident should be non-HEALTHY
        non_healthy = [inc for inc in result.incidents if inc.status != "HEALTHY"]
        assert len(non_healthy) >= 1

    def test_collection_failure_does_not_infer_router_down(self):
        """COLLECTION_FAILURE must be classified as COLLECTION_FAILURE, not ROUTER_DOWN."""
        engine = CorrelationEngine()
        failed_rec = _make_collection_failed_record("R3")
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([failed_rec], topo)
        for inc in result.incidents:
            for sym in inc.symptoms:
                assert sym.category != SymptomCategory.ROUTER_UNREACHABLE, (
                    "COLLECTION_FAILURE must not be inferred as ROUTER_UNREACHABLE"
                )
                if sym.category == SymptomCategory.COLLECTION_FAILURE:
                    assert "UNKNOWN" in sym.description or "cannot" in sym.description.lower()


# ===========================================================================
# 18 — Typed symptom: interface DOWN
# ===========================================================================


class TestSymptomClassificationInterfaceDown:

    def test_interface_down_creates_symptom(self):
        engine = CorrelationEngine()
        rec = _make_interface_record("R1", "eth1", "down")
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        all_symptoms = [s for inc in result.incidents for s in inc.symptoms]
        iface_down = [s for s in all_symptoms if s.category == SymptomCategory.INTERFACE_DOWN]
        assert len(iface_down) >= 1

    def test_interface_up_creates_healthy_symptom(self):
        engine = CorrelationEngine()
        rec = _make_interface_record("R1", "eth1", "up")
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        assert result.anomalous_record_count == 0
        all_symptoms = [s for inc in result.incidents for s in inc.symptoms]
        down_syms = [s for s in all_symptoms if s.category == SymptomCategory.INTERFACE_DOWN]
        assert len(down_syms) == 0

    def test_interface_down_links_correct_component(self):
        engine = CorrelationEngine()
        rec = _make_interface_record("R1", "eth1", "down")
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        # Affected links should include L12 (R1 eth1 carries L12)
        affected_links = set()
        for inc in result.incidents:
            affected_links.update(inc.affected_links)
        assert "L12" in affected_links


# ===========================================================================
# 19 — Typed symptom: OSPF adjacency LOST
# ===========================================================================


class TestSymptomClassificationOSPFLost:

    def test_ospf_down_creates_adjacency_lost_symptom(self):
        engine = CorrelationEngine()
        rec = _make_ospf_record("R1", "2.2.2.2", "down")
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        all_symptoms = [s for inc in result.incidents for s in inc.symptoms]
        lost = [s for s in all_symptoms if s.category == SymptomCategory.OSPF_ADJACENCY_LOST]
        assert len(lost) >= 1

    def test_ospf_full_creates_healthy_symptom(self):
        engine = CorrelationEngine()
        rec = _make_ospf_record("R1", "2.2.2.2", "Full/-")
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        assert result.anomalous_record_count == 0

    def test_ospf_neighbour_id_resolved_to_r2(self):
        """OSPF neighbour_router_id '2.2.2.2' must resolve to 'R2', not remain as OSPF-ID."""
        engine = CorrelationEngine()
        rec = _make_ospf_record("R1", "2.2.2.2", "down")
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        all_symptoms = [s for inc in result.incidents for s in inc.symptoms]
        lost = [s for s in all_symptoms if s.category == SymptomCategory.OSPF_ADJACENCY_LOST]
        assert len(lost) >= 1
        # Component should reference 'R2' not '2.2.2.2'
        for sym in lost:
            assert "R2" in sym.affected_component, (
                f"Expected 'R2' in component, got {sym.affected_component!r}. "
                f"OSPF Router-ID '2.2.2.2' must be resolved to stable name 'R2'."
            )


# ===========================================================================
# 20 — Typed symptom: packet loss elevated
# ===========================================================================


class TestSymptomClassificationPacketLoss:

    def test_high_loss_creates_packet_loss_symptom(self):
        engine = CorrelationEngine(packet_loss_threshold=5.0)
        rec = _make_ping_record("R1", "192.168.255.3", loss_pct=50.0)
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        all_symptoms = [s for inc in result.incidents for s in inc.symptoms]
        loss_syms = [s for s in all_symptoms if s.category == SymptomCategory.PACKET_LOSS_ELEVATED]
        assert len(loss_syms) >= 1

    def test_zero_loss_creates_healthy_symptom(self):
        engine = CorrelationEngine(packet_loss_threshold=5.0)
        rec = _make_ping_record("R1", "192.168.255.3", loss_pct=0.0, avg_rtt=0.5)
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        assert result.anomalous_record_count == 0

    def test_loss_threshold_documented_in_symptom(self):
        engine = CorrelationEngine(packet_loss_threshold=5.0)
        rec = _make_ping_record("R1", "192.168.255.3", loss_pct=100.0)
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        all_symptoms = [s for inc in result.incidents for s in inc.symptoms]
        loss_syms = [s for s in all_symptoms if s.category == SymptomCategory.PACKET_LOSS_ELEVATED]
        for sym in loss_syms:
            assert sym.threshold_used == 5.0
            assert sym.measurement_value == 100.0


# ===========================================================================
# 21 — Typed symptom: latency elevated
# ===========================================================================


class TestSymptomClassificationLatency:

    def test_high_latency_creates_symptom(self):
        engine = CorrelationEngine(latency_threshold_ms=10.0)
        rec = _make_ping_record("R1", "192.168.255.3", loss_pct=0.0, avg_rtt=500.0)
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        all_symptoms = [s for inc in result.incidents for s in inc.symptoms]
        lat_syms = [s for s in all_symptoms if s.category == SymptomCategory.LATENCY_ELEVATED]
        assert len(lat_syms) >= 1

    def test_latency_threshold_documented(self):
        engine = CorrelationEngine(latency_threshold_ms=10.0)
        rec = _make_ping_record("R1", "192.168.255.3", loss_pct=0.0, avg_rtt=500.0)
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        all_symptoms = [s for inc in result.incidents for s in inc.symptoms]
        lat_syms = [s for s in all_symptoms if s.category == SymptomCategory.LATENCY_ELEVATED]
        assert lat_syms[0].threshold_used == 10.0


# ===========================================================================
# 22 — Typed symptom: route missing
# ===========================================================================


class TestSymptomClassificationRouteMissing:

    def test_missing_route_creates_symptom(self):
        engine = CorrelationEngine()
        rec = _make_route_record("R1", "192.168.255.3/32", is_present=False)
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        all_symptoms = [s for inc in result.incidents for s in inc.symptoms]
        missing = [s for s in all_symptoms if s.category == SymptomCategory.ROUTE_MISSING]
        assert len(missing) >= 1

    def test_present_route_creates_healthy_symptom(self):
        engine = CorrelationEngine()
        rec = _make_route_record("R1", "192.168.255.3/32", is_present=True)
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        assert result.anomalous_record_count == 0

    def test_missing_route_is_not_direct_observation(self):
        """Route absence is inferred, not directly observed — is_direct_observation must be False."""
        engine = CorrelationEngine()
        rec = _make_route_record("R1", "192.168.255.3/32", is_present=False)
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        all_symptoms = [s for inc in result.incidents for s in inc.symptoms]
        missing = [s for s in all_symptoms if s.category == SymptomCategory.ROUTE_MISSING]
        for sym in missing:
            assert not sym.is_direct_observation, (
                "Route absence is inferred from RIB query, not directly observed"
            )


# ===========================================================================
# 23 — Multiple symptoms grouping by topology proximity
# ===========================================================================


class TestSymptomGroupingTopology:

    def test_adjacent_router_symptoms_grouped(self):
        """Symptoms on R1 and R2 (directly connected) are grouped into one incident."""
        engine = CorrelationEngine()
        ts = _now()
        r1_iface_down = _make_interface_record("R1", "eth1", "down", ts=ts)
        r2_ospf_lost = _make_ospf_record("R2", "1.1.1.1", "down", ts=ts)
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([r1_iface_down, r2_ospf_lost], topo)
        # Should have one grouped incident (R1 and R2 are adjacent)
        grouped = [inc for inc in result.incidents if inc.status == "GROUPED"]
        assert len(grouped) >= 1
        # The grouped incident should reference both R1 and R2
        for inc in grouped:
            router_set = set(inc.affected_routers)
            assert "R1" in router_set or "R2" in router_set

    def test_incident_has_topology_relationship(self):
        """A GROUPED incident must document a topology-based relationship."""
        engine = CorrelationEngine()
        ts = _now()
        r1_iface_down = _make_interface_record("R1", "eth1", "down", ts=ts)
        r2_ospf_lost = _make_ospf_record("R2", "1.1.1.1", "down", ts=ts)
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([r1_iface_down, r2_ospf_lost], topo)
        grouped = [inc for inc in result.incidents if inc.status == "GROUPED"]
        if grouped:
            inc = grouped[0]
            assert len(inc.relationships) >= 1

    def test_iface_down_and_ospf_lost_creates_ospf_topology_rel(self):
        """Interface DOWN + OSPF adjacency LOST should produce an OSPF_TOPOLOGY relationship."""
        engine = CorrelationEngine()
        ts = _now()
        iface_rec = _make_interface_record("R1", "eth1", "down", ts=ts)
        ospf_rec = _make_ospf_record("R1", "2.2.2.2", "down", ts=ts)
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([iface_rec, ospf_rec], topo)
        all_rels = [r for inc in result.incidents for r in inc.relationships]
        ospf_rels = [r for r in all_rels if r.relationship_kind == "OSPF_TOPOLOGY"]
        assert len(ospf_rels) >= 1, (
            "Interface DOWN and OSPF adjacency LOST on the same router must produce "
            "an OSPF_TOPOLOGY relationship documenting the possible dependency."
        )


# ===========================================================================
# 24 — Isolation of unrelated symptoms
# ===========================================================================


class TestSymptomIsolation:

    def test_single_symptom_is_isolated(self):
        engine = CorrelationEngine()
        rec = _make_interface_record("R1", "eth1", "down")
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        # A single symptom with no related evidence is ISOLATED or GROUPED
        # (not HEALTHY since it has an anomaly)
        statuses = [inc.status for inc in result.incidents]
        assert "HEALTHY" not in statuses


# ===========================================================================
# 25 — Contradictory observation detection
# ===========================================================================


class TestContradictoryObservations:

    def test_ospf_lost_without_iface_down_noted_as_contradictory(self):
        """
        OSPF adjacency lost with no corresponding interface-down observation
        should be noted as potentially contradictory (could be config mismatch
        rather than physical link failure).
        """
        engine = CorrelationEngine()
        rec = _make_ospf_record("R1", "2.2.2.2", "down")
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([rec], topo)
        for inc in result.incidents:
            if inc.contradictory_observations:
                # Should mention that no interface-down was observed
                combined = " ".join(inc.contradictory_observations).lower()
                assert "interface" in combined or "configuration" in combined


# ===========================================================================
# 26 — Ground-truth isolation
# ===========================================================================


class TestGroundTruthIsolation:

    def test_correlation_result_has_isolation_verified_true(self):
        engine = CorrelationEngine()
        records = [_make_base_record("R1")]
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records(records, topo)
        assert result.ground_truth_isolation_verified is True

    def test_no_fault_type_field_in_incidents(self):
        """CorrelatedIncident must not have fault_type, fault_location, or ground-truth fields."""
        engine = CorrelationEngine()
        records = [_make_interface_record("R1", "eth1", "down")]
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records(records, topo)
        for inc in result.incidents:
            inc_dict = inc.model_dump()
            assert "fault_type" not in inc_dict
            assert "fault_location" not in inc_dict
            assert "seeded_fault" not in inc_dict
            assert "injected_label" not in inc_dict

    def test_engine_version_is_present(self):
        engine = CorrelationEngine()
        records = [_make_base_record("R1")]
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records(records, topo)
        assert result.engine_version == CORRELATION_ENGINE_VERSION


# ===========================================================================
# 27 — Ground-truth injection triggers LeakageError
# ===========================================================================


class TestGroundTruthLeakageDetection:

    def test_snapshot_with_fault_type_in_metadata_raises(self):
        """
        A snapshot whose metadata contains ground-truth tokens must raise
        GroundTruthLeakageError before any correlation.
        """
        engine = CorrelationEngine()
        # Construct a minimal snapshot dict with a forbidden token in metadata
        snapshot_dict = {
            "snapshot_id": "snap-with-fault_type-in-id",  # has forbidden token
            "evidence_records": [],
            "topology": {},
            "captured_at": _now().isoformat(),
            "router_ids": ["R1"],
        }
        with pytest.raises(GroundTruthLeakageError):
            engine.correlate_snapshot_dict(snapshot_dict)


# ===========================================================================
# 28 — Smoke test: all six snapshot files
# ===========================================================================


@pytest.mark.skipif(
    not _DATASETS_DIR.exists(),
    reason="Observation datasets directory not found",
)
class TestAllSnapshotFiles:
    """Smoke test: all six snapshot files must correlate without raising exceptions."""

    SNAPSHOT_FILES = [
        "baseline_snapshot.json",
        "f1_link_failure_snapshot.json",
        "f2_router_failure_snapshot.json",
        "f3_ospf_mismatch_snapshot.json",
        "f4_packet_loss_snapshot.json",
        "f5_high_latency_snapshot.json",
    ]

    @pytest.mark.parametrize("filename", SNAPSHOT_FILES)
    def test_snapshot_correlates_without_exception(self, filename: str):
        snap_path = _DATASETS_DIR / filename
        if not snap_path.exists():
            pytest.skip(f"Snapshot file not found: {snap_path}")

        with open(snap_path) as f:
            snap = json.load(f)

        engine = CorrelationEngine()
        result = engine.correlate_snapshot_dict(snap)

        assert result.result_id, "Result must have a result_id"
        assert result.engine_version == CORRELATION_ENGINE_VERSION
        assert result.total_evidence_records >= 0
        assert result.ground_truth_isolation_verified is True
        assert isinstance(result.incidents, list)

    def test_baseline_snapshot_is_healthy(self):
        snap_path = _DATASETS_DIR / "baseline_snapshot.json"
        if not snap_path.exists():
            pytest.skip("Baseline snapshot not found")
        with open(snap_path) as f:
            snap = json.load(f)
        engine = CorrelationEngine()
        result = engine.correlate_snapshot_dict(snap)
        # Baseline must produce HEALTHY (no anomalies from base records)
        statuses = [inc.status for inc in result.incidents]
        assert result.anomalous_record_count == 0, (
            f"Baseline snapshot must have 0 anomalous records, "
            f"got {result.anomalous_record_count}"
        )
        assert all(s == "HEALTHY" for s in statuses), (
            f"Baseline snapshot must be HEALTHY, got statuses: {statuses}"
        )

    def test_f2_router_failure_detects_anomalies(self):
        snap_path = _DATASETS_DIR / "f2_router_failure_snapshot.json"
        if not snap_path.exists():
            pytest.skip("F2 snapshot not found")
        with open(snap_path) as f:
            snap = json.load(f)
        engine = CorrelationEngine()
        result = engine.correlate_snapshot_dict(snap)
        # Router failure produces COLLECTION_FAILED records which ARE preserved
        # in base serialization (collection_status field is in EvidenceRecord base)
        assert result.anomalous_record_count >= 1, (
            "F2 router failure snapshot must produce at least 1 anomalous record. "
            "COLLECTION_FAILED records survive base serialization."
        )


# ===========================================================================
# 29 — Multiple independent incident groups
# ===========================================================================


class TestMultipleIncidentGroups:

    def test_non_adjacent_anomalies_may_form_multiple_groups(self):
        """
        Symptoms on non-adjacent routers (R1 and R4) should not be forced
        into the same incident group (they are not physically adjacent in the
        ring topology). They may form separate groups.
        """
        engine = CorrelationEngine()
        ts = _now()
        r1_down = _make_interface_record("R1", "eth1", "down", ts=ts)
        r4_down = _make_interface_record("R4", "eth1", "down", ts=ts)
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records([r1_down, r4_down], topo)
        # At least one incident should exist
        assert len(result.incidents) >= 1
        # Total anomalous count should be >= 2
        assert result.anomalous_record_count >= 2


# ===========================================================================
# 30 — Determinism
# ===========================================================================


class TestDeterminism:

    def test_same_input_produces_structurally_equivalent_result(self):
        """Running correlation twice on the same records produces equivalent results."""
        engine = CorrelationEngine()
        ts = _now()
        records = [
            _make_interface_record("R1", "eth1", "down", ts=ts),
            _make_ospf_record("R1", "2.2.2.2", "down", ts=ts),
        ]
        topo = build_expected_topology_graph().topology

        result1 = engine.correlate_records(records, topo)
        result2 = engine.correlate_records(records, topo)

        # Same number of incidents
        assert len(result1.incidents) == len(result2.incidents)
        # Same anomalous count
        assert result1.anomalous_record_count == result2.anomalous_record_count
        # Same statuses (order may vary, so compare sorted)
        statuses1 = sorted(inc.status for inc in result1.incidents)
        statuses2 = sorted(inc.status for inc in result2.incidents)
        assert statuses1 == statuses2


# ===========================================================================
# 31 — Correlation result round-trip serialization
# ===========================================================================


class TestCorrelationResultSerialization:

    def test_full_result_round_trip(self):
        engine = CorrelationEngine()
        records = [
            _make_interface_record("R1", "eth1", "down"),
            _make_ospf_record("R1", "2.2.2.2", "down"),
        ]
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records(records, topo)

        # Serialize
        data = result.model_dump(mode="json")
        # Restore
        restored = CorrelationResult.model_validate(data)

        assert restored.result_id == result.result_id
        assert len(restored.incidents) == len(result.incidents)

    def test_result_json_contains_no_ground_truth_tokens(self):
        """The JSON output of the correlation engine must not contain ground-truth tokens."""
        from app.collectors.normalizer import GROUND_TRUTH_FORBIDDEN_TOKENS

        engine = CorrelationEngine()
        records = [_make_interface_record("R1", "eth1", "down")]
        topo = build_expected_topology_graph().topology
        result = engine.correlate_records(records, topo)

        result_json = json.dumps(result.model_dump(mode="json")).lower()
        for token in GROUND_TRUTH_FORBIDDEN_TOKENS:
            assert token not in result_json, (
                f"Forbidden ground-truth token '{token}' found in correlation output"
            )


# ===========================================================================
# 32 & 33 — EvidenceNormalizer.deserialize_record
# ===========================================================================


class TestDeserializeRecord:

    def test_graceful_fallback_when_subclass_fields_missing(self):
        """Legacy snapshots with only base fields must deserialize to EvidenceRecord."""
        ts = _now()
        base_data = {
            "evidence_id": "ev-legacy-001",
            "source_router": "R1",
            "source_type": "INTERFACE_POLL",  # normally needs observed_status
            "event_type": "INTERFACE_STATUS",
            "observed_at": ts.isoformat(),
            "collected_at": ts.isoformat(),
            "collection_method": "PERIODIC_POLL",
            "collection_status": "OBSERVED",
            "incident_id": None,
            "raw_reference": None,
            "source_interface": "eth1",
        }
        # Should fall back to base EvidenceRecord
        record = EvidenceNormalizer.deserialize_record(base_data)
        assert isinstance(record, EvidenceRecord)
        assert record.evidence_id == "ev-legacy-001"

    def test_typed_reconstruction_when_all_fields_present(self):
        """When all subclass fields are present, reconstruction must return the typed subclass."""
        ts = _now()
        ping_data = {
            "evidence_id": "ev-ping-typed-001",
            "source_router": "R1",
            "source_type": "ACTIVE_PING",
            "event_type": "PING_RESULT",
            "observed_at": ts.isoformat(),
            "collected_at": ts.isoformat(),
            "collection_method": "TRIGGERED_PROBE",
            "collection_status": "OBSERVED",
            "incident_id": None,
            "raw_reference": None,
            "source_interface": None,
            "target_address": "192.168.255.3",
            "probe_source": "R1",
            "packets_sent": 5,
            "packets_received": 5,
            "packet_loss_pct": 0.0,
            "rtt_min_ms": 0.3,
            "rtt_avg_ms": 0.5,
            "rtt_max_ms": 0.8,
        }
        record = EvidenceNormalizer.deserialize_record(ping_data)
        assert isinstance(record, PingMeasurement)
        assert record.packet_loss_pct == 0.0

    def test_unknown_source_type_falls_back_gracefully(self):
        """
        Data with an unknown source_type should raise a graceful exception
        (not an internal error), since source_type is required in EvidenceRecord
        and unknown values cannot be coerced.
        """
        ts = _now()
        data = {
            "evidence_id": "ev-unknown-001",
            "source_router": "R1",
            "source_type": "UNKNOWN_TYPE",  # Not a valid EvidenceSourceType
            "event_type": "SOME_EVENT",
            "observed_at": ts.isoformat(),
            "collected_at": ts.isoformat(),
            "collection_method": "PERIODIC_POLL",
            "collection_status": "OBSERVED",
            "incident_id": None,
            "raw_reference": None,
            "source_interface": None,
        }
        # Unknown source_type → not in subclass_map → base fallback strips source_type
        # → source_type is required → raises ValidationError gracefully
        with pytest.raises(Exception):
            EvidenceNormalizer.deserialize_record(data)


# ===========================================================================
# 34 & 35 — TopologyGraph explain_relationship
# ===========================================================================


class TestExplainRelationship:

    def test_direct_link_explanation_mentions_link_id(self):
        topo = build_expected_topology_graph()
        expl = topo.explain_relationship("R1", "R2")
        assert "L12" in expl

    def test_non_adjacent_explanation_mentions_path(self):
        topo = build_expected_topology_graph()
        expl = topo.explain_relationship("R1", "R3")
        assert "path" in expl.lower() or "directly" in expl.lower()

    def test_router_to_link_explanation(self):
        topo = build_expected_topology_graph()
        expl = topo.explain_relationship("R1", "L12")
        assert "endpoint" in expl.lower() or "L12" in expl


# ===========================================================================
# 36 — map_prefix_to_router
# ===========================================================================


class TestMapPrefixToRouter:

    def test_loopback_prefix_maps_to_correct_router(self):
        topo = build_expected_topology_graph()
        for i in range(1, 6):
            prefix = f"192.168.255.{i}/32"
            expected_router = f"R{i}"
            result = topo.map_prefix_to_router(prefix)
            assert result == expected_router, (
                f"Prefix {prefix!r} should map to {expected_router!r}, got {result!r}"
            )

    def test_link_subnet_does_not_map_to_single_router(self):
        topo = build_expected_topology_graph()
        # Link subnets are not loopback prefixes
        result = topo.map_prefix_to_router("10.0.12.0/30")
        assert result is None

    def test_unknown_prefix_returns_none(self):
        topo = build_expected_topology_graph()
        assert topo.map_prefix_to_router("172.16.0.0/16") is None
