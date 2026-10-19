"""
Live integration tests for NEXORA evidence collection engine.

These tests execute real read-only collectors against the running 5-router FRRouting lab.
Optionally verifies fault-state symptom capture across F1-F5 using the Phase 03 FaultController.

Guarded by the NEXORA_RUN_COLLECTOR_LIVE_TESTS environment variable so destructive/live tests
never run accidentally in normal CI.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from lab.fault_injection.controller import FaultController
from lab.fault_injection.models import ScenarioID

from app.collectors.orchestrator import CollectionOrchestrator
from app.collectors.transport import DockerTransport
from app.schemas.evidence import (
    InterfaceObservation,
    OSPFObservation,
    PingMeasurement,
    RouteObservation,
    TracerouteObservation,
)
from app.schemas.topology import OSPFNeighbourState, RouterStatus

LIVE_TEST_FLAG = os.environ.get("NEXORA_RUN_COLLECTOR_LIVE_TESTS") == "1"
OBS_DIR = Path(__file__).resolve().parents[2] / "evaluation" / "datasets" / "observations"


@pytest.fixture(scope="module")
def live_orchestrator() -> CollectionOrchestrator:
    OBS_DIR.mkdir(parents=True, exist_ok=True)
    return CollectionOrchestrator(
        transport=DockerTransport(),
        storage_dir=OBS_DIR,
    )


@pytest.fixture(scope="module")
def fault_controller() -> FaultController:
    return FaultController()


def _assert_baseline_healthy(fc: FaultController) -> None:
    is_healthy, msgs = fc.check_baseline()
    assert is_healthy, f"Baseline unhealthy: {msgs}"


@pytest.mark.skipif(
    not LIVE_TEST_FLAG,
    reason="Live collector tests require running lab and NEXORA_RUN_COLLECTOR_LIVE_TESTS=1",
)
def test_live_baseline_evidence_collection(live_orchestrator: CollectionOrchestrator) -> None:
    """Collect real baseline evidence from the running lab and verify all contracts."""
    snapshot = live_orchestrator.collect_snapshot(
        include_probes=True,
        include_logs=True,
        log_tail=20,
    )

    # 1. Topology checks
    assert len(snapshot.topology.routers) == 5
    for r in snapshot.topology.routers:
        assert r.status == RouterStatus.UP

    assert len(snapshot.topology.adjacencies) == 10
    for adj in snapshot.topology.adjacencies:
        assert adj.state == OSPFNeighbourState.FULL

    # 2. Record checks
    assert snapshot.total_records > 30

    # Ensure evidence of all 6 primary types was collected
    types_present = set(snapshot.records_by_type.keys())
    assert "INTERFACE_POLL" in types_present
    assert "OSPF_API" in types_present
    assert "ROUTING_TABLE" in types_present
    assert "ACTIVE_PING" in types_present
    assert "ACTIVE_TRACEROUTE" in types_present
    assert "SYSLOG" in types_present

    # 3. Ping measurement checks
    pings = [r for r in snapshot.evidence_records if isinstance(r, PingMeasurement)]
    assert len(pings) >= 5
    for p in pings:
        assert p.packet_loss_pct == 0.0
        assert p.rtt_avg_ms is not None
        assert p.rtt_avg_ms < 50.0  # Local Docker veth ping RTT is <5ms

    # 4. Traceroute checks
    traces = [r for r in snapshot.evidence_records if isinstance(r, TracerouteObservation)]
    assert len(traces) >= 5
    for tr in traces:
        assert tr.total_hops >= 1

    # 5. Persist baseline snapshot
    saved_path = live_orchestrator.save_snapshot(snapshot, custom_filename="baseline_snapshot.json")
    assert saved_path.exists()


@pytest.mark.skipif(
    not LIVE_TEST_FLAG,
    reason="Live fault evidence tests require NEXORA_RUN_COLLECTOR_LIVE_TESTS=1",
)
def test_live_f1_link_failure_evidence(
    live_orchestrator: CollectionOrchestrator,
    fault_controller: FaultController,
) -> None:
    """Inject F1 link failure, collect real evidence, verify interface DOWN and route change."""
    # Ensure baseline is healthy
    _assert_baseline_healthy(fault_controller)

    # Inject F1: L12 link failure
    fault_controller.inject_fault(ScenarioID.F1_LINK_FAILURE, target="L12")
    try:
        # Collect snapshot while fault is active
        snapshot = live_orchestrator.collect_snapshot(include_probes=True, include_logs=False)

        # Observable symptom 1: R1 eth1 interface must be observed DOWN / admin-down
        ifaces = [
            r for r in snapshot.evidence_records
            if isinstance(r, InterfaceObservation)
            and r.source_router == "R1"
            and r.source_interface == "eth1"
        ]
        assert len(ifaces) == 1
        assert ifaces[0].observed_status in ("down", "admin-down")

        # Observable symptom 2: R1-R2 OSPF adjacency must be DOWN or missing
        ospf_r1 = [
            r for r in snapshot.evidence_records
            if isinstance(r, OSPFObservation)
            and r.source_router == "R1"
            and r.neighbour_router_id == "2.2.2.2"
        ]
        assert len(ospf_r1) == 1
        assert ospf_r1[0].adjacency_state != "Full"

        # Observable symptom 3: Alternate route for R2 (192.168.255.2/32) reroutes via eth2 (R5)
        routes_r1 = [
            r for r in snapshot.evidence_records
            if isinstance(r, RouteObservation)
            and r.source_router == "R1"
            and r.destination_prefix == "192.168.255.2/32"
        ]
        assert len(routes_r1) >= 1
        assert routes_r1[0].next_hop_interface == "eth2"

        # Save snapshot
        live_orchestrator.save_snapshot(snapshot, custom_filename="f1_link_failure_snapshot.json")

    finally:
        fault_controller.reset_fault()
        _assert_baseline_healthy(fault_controller)


@pytest.mark.skipif(
    not LIVE_TEST_FLAG,
    reason="Live fault evidence tests require NEXORA_RUN_COLLECTOR_LIVE_TESTS=1",
)
def test_live_f2_router_failure_evidence(
    live_orchestrator: CollectionOrchestrator,
    fault_controller: FaultController,
) -> None:
    """Inject F2 router failure, collect real evidence, verify router DOWN and ping loss."""
    _assert_baseline_healthy(fault_controller)

    # Inject F2: stop R3
    fault_controller.inject_fault(ScenarioID.F2_ROUTER_FAILURE, target="R3")
    try:
        snapshot = live_orchestrator.collect_snapshot(include_probes=True, include_logs=False)

        # Observable symptom 1: R3 status in topology is DOWN
        r3 = next(r for r in snapshot.topology.routers if r.router_id == "R3")
        assert r3.status == RouterStatus.DOWN

        # Observable symptom 2: Ping from R2 to R3 loopback fails with 100% loss
        r2_to_r3_pings = [
            r for r in snapshot.evidence_records
            if isinstance(r, PingMeasurement)
            and r.source_router == "R2"
            and r.target_address == "192.168.255.3"
        ]
        if r2_to_r3_pings:
            assert r2_to_r3_pings[0].packet_loss_pct == 100.0

        # Save snapshot
        live_orchestrator.save_snapshot(snapshot, custom_filename="f2_router_failure_snapshot.json")

    finally:
        fault_controller.reset_fault()
        _assert_baseline_healthy(fault_controller)


@pytest.mark.skipif(
    not LIVE_TEST_FLAG,
    reason="Live fault evidence tests require NEXORA_RUN_COLLECTOR_LIVE_TESTS=1",
)
def test_live_f3_ospf_mismatch_evidence(
    live_orchestrator: CollectionOrchestrator,
    fault_controller: FaultController,
) -> None:
    """Inject F3 OSPF mismatch, collect real evidence, verify adjacency DOWN while interface UP."""
    _assert_baseline_healthy(fault_controller)

    # Inject F3: mismatch hello/dead timers on L23 (R2 eth2)
    fault_controller.inject_fault(
        ScenarioID.F3_OSPF_CONFIG_MISMATCH,
        target="L23",
        params={"hello_interval": 5, "dead_interval": 20},
    )
    try:
        # Allow dead timer (remaining ~35s) to expire so adjacency state drops
        snapshot = live_orchestrator.collect_snapshot(include_probes=False, include_logs=False)
        for _ in range(8):
            time.sleep(5)
            snapshot = live_orchestrator.collect_snapshot(include_probes=False, include_logs=False)
            ospf_r2 = [
                r for r in snapshot.evidence_records
                if isinstance(r, OSPFObservation)
                and r.source_router == "R2"
                and r.neighbour_router_id == "3.3.3.3"
            ]
            if ospf_r2 and ospf_r2[0].adjacency_state != "Full":
                break

        # Observable symptom 1: Interface R2 eth2 remains operational UP
        ifaces = [
            r for r in snapshot.evidence_records
            if isinstance(r, InterfaceObservation)
            and r.source_router == "R2"
            and r.source_interface == "eth2"
        ]
        assert len(ifaces) == 1
        assert ifaces[0].observed_status == "up"

        # Observable symptom 2: OSPF adjacency R2 -> R3 drops to DOWN / missing
        ospf_r2 = [
            r for r in snapshot.evidence_records
            if isinstance(r, OSPFObservation)
            and r.source_router == "R2"
            and r.neighbour_router_id == "3.3.3.3"
        ]
        assert len(ospf_r2) == 1
        assert ospf_r2[0].adjacency_state != "Full"

        # Save snapshot
        live_orchestrator.save_snapshot(snapshot, custom_filename="f3_ospf_mismatch_snapshot.json")

    finally:
        fault_controller.reset_fault()
        _assert_baseline_healthy(fault_controller)


@pytest.mark.skipif(
    not LIVE_TEST_FLAG,
    reason="Live fault evidence tests require NEXORA_RUN_COLLECTOR_LIVE_TESTS=1",
)
def test_live_f4_packet_loss_evidence(
    live_orchestrator: CollectionOrchestrator,
    fault_controller: FaultController,
) -> None:
    """Inject F4 packet loss, collect real evidence, verify measured loss while interface UP."""
    _assert_baseline_healthy(fault_controller)

    # Inject F4: 25% loss on L12 (R1 eth1)
    fault_controller.inject_fault(
        ScenarioID.F4_PACKET_LOSS,
        target="L12",
        params={"loss_percentage": 25.0},
    )
    try:
        snapshot = live_orchestrator.collect_snapshot(include_probes=True, include_logs=False)

        # Observable symptom 1: Interface eth1 remains UP
        ifaces = [
            r for r in snapshot.evidence_records
            if isinstance(r, InterfaceObservation)
            and r.source_router == "R1"
            and r.source_interface == "eth1"
        ]
        assert len(ifaces) == 1
        assert ifaces[0].observed_status == "up"

        # Observable symptom 2: Measured packet loss to R2 loopback > 0%
        ping_probe = live_orchestrator.ping_collector.probe(
            source_router="R1",
            target_address="10.0.12.2",
            count=20,
            timeout_s=1,
        )
        assert ping_probe.packet_loss_pct > 0.0

        # Save snapshot
        live_orchestrator.save_snapshot(snapshot, custom_filename="f4_packet_loss_snapshot.json")

    finally:
        fault_controller.reset_fault()
        _assert_baseline_healthy(fault_controller)


@pytest.mark.skipif(
    not LIVE_TEST_FLAG,
    reason="Live fault evidence tests require NEXORA_RUN_COLLECTOR_LIVE_TESTS=1",
)
def test_live_f5_high_latency_evidence(
    live_orchestrator: CollectionOrchestrator,
    fault_controller: FaultController,
) -> None:
    """Inject F5 high latency, collect real evidence, verify elevated RTT while interface UP."""
    _assert_baseline_healthy(fault_controller)

    # Inject F5: 150ms delay on L23 (R2 eth2)
    fault_controller.inject_fault(
        ScenarioID.F5_HIGH_LATENCY,
        target="L23",
        params={"delay_ms": 150.0, "jitter_ms": 10.0},
    )
    try:
        snapshot = live_orchestrator.collect_snapshot(include_probes=True, include_logs=False)

        # Observable symptom 1: Interface eth2 remains UP
        ifaces = [
            r for r in snapshot.evidence_records
            if isinstance(r, InterfaceObservation)
            and r.source_router == "R2"
            and r.source_interface == "eth2"
        ]
        assert len(ifaces) == 1
        assert ifaces[0].observed_status == "up"

        # Observable symptom 2: Measured RTT to R3 across L23 is elevated >= 100ms
        ping_probe = live_orchestrator.ping_collector.probe(
            source_router="R2",
            target_address="10.0.23.2",
            count=4,
            timeout_s=2,
        )
        assert ping_probe.rtt_avg_ms is not None
        assert ping_probe.rtt_avg_ms >= 100.0

        # Save snapshot
        live_orchestrator.save_snapshot(snapshot, custom_filename="f5_high_latency_snapshot.json")

    finally:
        fault_controller.reset_fault()
        _assert_baseline_healthy(fault_controller)
