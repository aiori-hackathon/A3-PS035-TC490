"""
Unit and mock-based tests for NEXORA evidence collectors.

Tests:
- Transport validation and security boundaries
- Topology collection and comparison
- Interface state and error counters
- OSPF adjacency and missing neighbor detection
- Routing table extraction and route loss detection
- Ping loss and RTT validation
- Traceroute hop parsing
- Syslog parsing and severity inference
- Evidence normalizer and ground-truth isolation
- Orchestrator multi-collector coordination and partial failure handling
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.collectors.interface_collector import InterfaceCollector
from app.collectors.normalizer import EvidenceNormalizer, GroundTruthLeakageError
from app.collectors.orchestrator import CollectionOrchestrator
from app.collectors.ospf_collector import OSPFCollector
from app.collectors.ping_collector import PingCollector
from app.collectors.routing_collector import RoutingCollector
from app.collectors.syslog_collector import SyslogCollector
from app.collectors.topology_collector import TopologyCollector
from app.collectors.traceroute_collector import TracerouteCollector
from app.collectors.transport import (
    DockerTransport,
    MockTransport,
    SecurityViolationError,
)
from app.schemas.evidence import (
    CollectionMethod,
    EvidenceSourceType,
    InterfaceObservation,
    ObservationStatus,
    OSPFObservation,
    PingMeasurement,
    RouteObservation,
    SyslogEvent,
    SyslogSeverity,
    TracerouteObservation,
)
from app.schemas.topology import RouterStatus

# ---------------------------------------------------------------------------
# Recorded real FRR & Linux command fixtures
# ---------------------------------------------------------------------------

SAMPLE_OSPF_NEIGHBOR_JSON = json.dumps({
    "neighbors": {
        "2.2.2.2": [
            {
                "priority": 1,
                "state": "Full/-",
                "converged": "Full",
                "deadTimeMsecs": 38120,
                "address": "10.0.12.2",
                "ifaceName": "eth1:10.0.12.1",
            }
        ],
        "5.5.5.5": [
            {
                "priority": 1,
                "state": "Full/-",
                "converged": "Full",
                "deadTimeMsecs": 37950,
                "address": "10.0.15.1",
                "ifaceName": "eth2:10.0.15.2",
            }
        ],
    }
})

SAMPLE_OSPF_NEIGHBOR_ONE_DOWN_JSON = json.dumps({
    "neighbors": {
        "5.5.5.5": [
            {
                "priority": 1,
                "state": "Full/-",
                "converged": "Full",
                "deadTimeMsecs": 38000,
                "address": "10.0.15.1",
                "ifaceName": "eth2:10.0.15.2",
            }
        ]
    }
})

SAMPLE_IP_LINK_JSON = json.dumps([
    {
        "ifname": "lo",
        "operstate": "UNKNOWN",
        "flags": ["LOOPBACK", "UP", "LOWER_UP"],
        "stats64": {
            "rx": {"bytes": 100, "packets": 2, "errors": 0, "dropped": 0},
            "tx": {"bytes": 100, "packets": 2, "errors": 0, "dropped": 0},
        },
    },
    {
        "ifname": "eth1",
        "operstate": "UP",
        "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
        "stats64": {
            "rx": {"bytes": 500000, "packets": 4000, "errors": 2, "dropped": 1},
            "tx": {"bytes": 300000, "packets": 2500, "errors": 0, "dropped": 0},
        },
    },
    {
        "ifname": "eth2",
        "operstate": "UP",
        "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
        "stats64": {
            "rx": {"bytes": 450000, "packets": 3500, "errors": 0, "dropped": 0},
            "tx": {"bytes": 280000, "packets": 2200, "errors": 0, "dropped": 0},
        },
    },
])

SAMPLE_IP_LINK_ETH1_DOWN_JSON = json.dumps([
    {
        "ifname": "lo",
        "operstate": "UNKNOWN",
        "flags": ["LOOPBACK", "UP", "LOWER_UP"],
    },
    {
        "ifname": "eth1",
        "operstate": "DOWN",
        "flags": ["BROADCAST", "MULTICAST"],
        "stats64": {
            "rx": {"bytes": 100, "packets": 1, "errors": 5, "dropped": 0},
            "tx": {"bytes": 0, "packets": 0, "errors": 0, "dropped": 0},
        },
    },
    {
        "ifname": "eth2",
        "operstate": "UP",
        "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
    },
])

SAMPLE_IP_ADDR_JSON = json.dumps([
    {
        "ifname": "lo",
        "operstate": "UNKNOWN",
        "addr_info": [
            {"local": "127.0.0.1", "prefixlen": 8},
            {"local": "192.168.255.1", "prefixlen": 32},
        ],
    },
    {
        "ifname": "eth1",
        "operstate": "UP",
        "addr_info": [
            {"local": "172.31.12.1", "prefixlen": 29},
            {"local": "10.0.12.1", "prefixlen": 30},
        ],
    },
    {
        "ifname": "eth2",
        "operstate": "UP",
        "addr_info": [
            {"local": "172.31.51.2", "prefixlen": 29},
            {"local": "10.0.15.2", "prefixlen": 30},
        ],
    },
])

SAMPLE_ROUTE_JSON = json.dumps({
    "192.168.255.1/32": [
        {
            "prefix": "192.168.255.1/32",
            "protocol": "connected",
            "metric": 0,
            "nexthops": [{"directlyConnected": True, "interfaceName": "lo"}],
        }
    ],
    "192.168.255.2/32": [
        {
            "prefix": "192.168.255.2/32",
            "protocol": "ospf",
            "metric": 1,
            "nexthops": [{"ip": "10.0.12.2", "interfaceName": "eth1"}],
        }
    ],
    "192.168.255.3/32": [
        {
            "prefix": "192.168.255.3/32",
            "protocol": "ospf",
            "metric": 2,
            "nexthops": [{"ip": "10.0.12.2", "interfaceName": "eth1"}],
        }
    ],
    "192.168.255.4/32": [
        {
            "prefix": "192.168.255.4/32",
            "protocol": "ospf",
            "metric": 2,
            "nexthops": [{"ip": "10.0.15.1", "interfaceName": "eth2"}],
        }
    ],
    "192.168.255.5/32": [
        {
            "prefix": "192.168.255.5/32",
            "protocol": "ospf",
            "metric": 1,
            "nexthops": [{"ip": "10.0.15.1", "interfaceName": "eth2"}],
        }
    ],
})

SAMPLE_PING_SUCCESS_OUTPUT = """PING 192.168.255.2 (192.168.255.2): 56 data bytes
64 bytes from 192.168.255.2: seq=0 ttl=64 time=0.201 ms
64 bytes from 192.168.255.2: seq=1 ttl=64 time=0.319 ms
64 bytes from 192.168.255.2: seq=2 ttl=64 time=0.394 ms

--- 192.168.255.2 ping statistics ---
3 packets transmitted, 3 packets received, 0% packet loss
round-trip min/avg/max = 0.201/0.304/0.394 ms
"""

SAMPLE_PING_LOSS_OUTPUT = """PING 192.168.255.2 (192.168.255.2): 56 data bytes
64 bytes from 192.168.255.2: seq=0 ttl=64 time=0.250 ms
Request timeout for icmp_seq 1
64 bytes from 192.168.255.2: seq=2 ttl=64 time=0.350 ms
64 bytes from 192.168.255.2: seq=3 ttl=64 time=0.300 ms

--- 192.168.255.2 ping statistics ---
4 packets transmitted, 3 packets received, 25.0% packet loss
round-trip min/avg/max = 0.250/0.300/0.350 ms
"""

SAMPLE_TRACEROUTE_OUTPUT = """traceroute to 192.168.255.3 (192.168.255.3), 5 hops max, 46 byte packets
 1  10.0.12.2  0.077 ms
 2  192.168.255.3  0.002 ms
"""

SAMPLE_DOCKER_LOGS = [
    "2026-10-19T06:43:33.275388668Z 2026/10/19 06:43:33 WATCHFRR: [QDG3Y-BY5TN] ospfd state -> up : connect succeeded",
    "2026-10-19T06:43:33.275389959Z 2026/10/19 06:43:33 WATCHFRR: [QDG3Y-BY5TN] zebra state -> up : connect succeeded",
    "2026-10-19T17:09:04.686509722Z 2026/10/19 17:09:04 WATCHFRR: [YZRX4-ZXG0C] Thread Starvation detected",
]


# ---------------------------------------------------------------------------
# Test Transport Security & Boundaries
# ---------------------------------------------------------------------------


def test_transport_rejects_unauthorized_router() -> None:
    transport = DockerTransport()
    with pytest.raises(SecurityViolationError, match="Unauthorized router target"):
        transport.execute("R99", ["ip", "-j", "addr", "show"])


def test_transport_rejects_management_interface_target() -> None:
    transport = DockerTransport()
    with pytest.raises(SecurityViolationError, match="forbidden pattern"):
        transport.execute("R1", ["ping", "-c", "3", "192.168.100.2"])


def test_transport_rejects_arbitrary_shell_characters() -> None:
    transport = DockerTransport()
    with pytest.raises(SecurityViolationError, match="forbidden pattern"):
        transport.execute("R1", ["ip", "-j", "addr", "show", ";", "rm", "-rf", "/"])


def test_mock_transport_executes_configured_responses() -> None:
    mock = MockTransport()
    mock.set_response("R1", ["ip", "-j", "addr", "show"], 0, SAMPLE_IP_ADDR_JSON)
    code, stdout, _ = mock.execute("R1", ["ip", "-j", "addr", "show"])
    assert code == 0
    assert "192.168.255.1" in stdout


# ---------------------------------------------------------------------------
# Test Topology Collector
# ---------------------------------------------------------------------------


def test_topology_collector_expected_topology() -> None:
    mock = MockTransport()
    collector = TopologyCollector(mock)
    topo = collector.get_expected_topology()

    assert len(topo.routers) == 5
    assert len(topo.links) == 5
    router_ids = {r.router_id for r in topo.routers}
    assert router_ids == {"R1", "R2", "R3", "R4", "R5"}


def test_topology_collector_observed_healthy() -> None:
    mock = MockTransport()
    for rid in ["R1", "R2", "R3", "R4", "R5"]:
        mock.set_response(rid, ["ip", "-j", "addr", "show"], 0, SAMPLE_IP_ADDR_JSON)
        mock.set_response(rid, ["vtysh", "-c", "show ip ospf neighbor json"], 0, SAMPLE_OSPF_NEIGHBOR_JSON)

    collector = TopologyCollector(mock)
    topo = collector.collect_observed_topology()
    assert len(topo.routers) == 5
    for r in topo.routers:
        assert r.status == RouterStatus.UP


def test_topology_collector_handles_stopped_router() -> None:
    mock = MockTransport()
    mock.set_router_running("R3", False)
    collector = TopologyCollector(mock)
    topo = collector.collect_observed_topology()

    r3 = next(r for r in topo.routers if r.router_id == "R3")
    assert r3.status == RouterStatus.DOWN

    comp = collector.compare(topo)
    assert not comp.is_healthy
    assert "R3" in comp.down_routers


# ---------------------------------------------------------------------------
# Test Interface Collector
# ---------------------------------------------------------------------------


def test_interface_collector_healthy() -> None:
    mock = MockTransport()
    mock.set_response("R1", ["ip", "-j", "-s", "link", "show"], 0, SAMPLE_IP_LINK_JSON)

    collector = InterfaceCollector(mock)
    records = collector.collect(["R1"])

    assert len(records) == 3
    iface_map = {r.source_interface: r for r in records if isinstance(r, InterfaceObservation)}
    assert iface_map["eth1"].observed_status == "up"
    assert iface_map["eth1"].error_count == 3  # 2 errors + 1 dropped
    assert iface_map["eth1"].collection_status == ObservationStatus.OBSERVED


def test_interface_collector_down_link() -> None:
    mock = MockTransport()
    mock.set_response("R1", ["ip", "-j", "-s", "link", "show"], 0, SAMPLE_IP_LINK_ETH1_DOWN_JSON)

    collector = InterfaceCollector(mock)
    records = collector.collect(["R1"])
    iface_map = {r.source_interface: r for r in records if isinstance(r, InterfaceObservation)}

    assert iface_map["eth1"].observed_status in ("down", "admin-down")
    assert iface_map["eth1"].event_type == "INTERFACE_DOWN_OBSERVED"


def test_interface_collector_router_down() -> None:
    mock = MockTransport()
    mock.set_router_running("R1", False)

    collector = InterfaceCollector(mock)
    records = collector.collect(["R1"])

    assert len(records) == 3
    for r in records:
        assert isinstance(r, InterfaceObservation)
        assert r.collection_status == ObservationStatus.COLLECTION_FAILED
        assert r.observed_status == "down"


# ---------------------------------------------------------------------------
# Test OSPF Collector
# ---------------------------------------------------------------------------


def test_ospf_collector_healthy_full_adjacencies() -> None:
    mock = MockTransport()
    mock.set_response(
        "R1",
        ["vtysh", "-c", "show ip ospf neighbor json"],
        0,
        SAMPLE_OSPF_NEIGHBOR_JSON,
    )

    collector = OSPFCollector(mock)
    records = collector.collect(["R1"])

    assert len(records) == 2
    for r in records:
        assert isinstance(r, OSPFObservation)
        assert r.adjacency_state == "Full"
        assert r.collection_status == ObservationStatus.OBSERVED
        assert r.dead_timer_remaining_s is not None
        assert r.dead_timer_remaining_s > 0.0


def test_ospf_collector_detects_missing_neighbour() -> None:
    mock = MockTransport()
    mock.set_response(
        "R1",
        ["vtysh", "-c", "show ip ospf neighbor json"],
        0,
        SAMPLE_OSPF_NEIGHBOR_ONE_DOWN_JSON,
    )

    collector = OSPFCollector(mock)
    records = collector.collect(["R1"])

    assert len(records) == 2
    nbr_map = {r.neighbour_router_id: r for r in records if isinstance(r, OSPFObservation)}
    assert nbr_map["5.5.5.5"].adjacency_state == "Full"
    assert nbr_map["2.2.2.2"].adjacency_state == "Down"
    assert nbr_map["2.2.2.2"].event_type == "OSPF_NEIGHBOUR_DOWN"
    assert nbr_map["2.2.2.2"].dead_timer_remaining_s == 0.0


# ---------------------------------------------------------------------------
# Test Routing Collector
# ---------------------------------------------------------------------------


def test_routing_collector_healthy_rib() -> None:
    mock = MockTransport()
    mock.set_response("R1", ["vtysh", "-c", "show ip route json"], 0, SAMPLE_ROUTE_JSON)

    collector = RoutingCollector(mock)
    records = collector.collect(["R1"])

    prefix_map = {r.destination_prefix: r for r in records if isinstance(r, RouteObservation)}
    assert "192.168.255.3/32" in prefix_map
    assert prefix_map["192.168.255.3/32"].route_type == "O"
    assert prefix_map["192.168.255.3/32"].next_hop_address == "10.0.12.2"
    assert prefix_map["192.168.255.3/32"].is_present is True


def test_routing_collector_missing_route() -> None:
    mock = MockTransport()
    # Route to R3 missing
    sparse_rib = json.dumps({
        "192.168.255.1/32": [{"prefix": "192.168.255.1/32", "protocol": "connected", "metric": 0}],
        "192.168.255.2/32": [{"prefix": "192.168.255.2/32", "protocol": "ospf", "metric": 1}],
    })
    mock.set_response("R1", ["vtysh", "-c", "show ip route json"], 0, sparse_rib)

    collector = RoutingCollector(mock)
    records = collector.collect(["R1"])

    missing = [
        r for r in records
        if isinstance(r, RouteObservation) and r.destination_prefix == "192.168.255.3/32"
    ]
    assert len(missing) == 1
    assert missing[0].is_present is False
    assert missing[0].event_type == "ROUTE_MISSING"


# ---------------------------------------------------------------------------
# Test Ping & Traceroute Collectors
# ---------------------------------------------------------------------------


def test_ping_collector_success() -> None:
    mock = MockTransport()
    mock.set_response(
        "R1",
        ["ping", "-c", "3", "-W", "1", "192.168.255.2"],
        0,
        SAMPLE_PING_SUCCESS_OUTPUT,
    )

    collector = PingCollector(mock)
    record = collector.probe("R1", "192.168.255.2", count=3, timeout_s=1)

    assert isinstance(record, PingMeasurement)
    assert record.packets_sent == 3
    assert record.packets_received == 3
    assert record.packet_loss_pct == 0.0
    assert record.rtt_min_ms == 0.201
    assert record.rtt_avg_ms == 0.304
    assert record.rtt_max_ms == 0.394


def test_ping_collector_packet_loss() -> None:
    mock = MockTransport()
    mock.set_response(
        "R1",
        ["ping", "-c", "4", "-W", "1", "192.168.255.2"],
        0,
        SAMPLE_PING_LOSS_OUTPUT,
    )

    collector = PingCollector(mock)
    record = collector.probe("R1", "192.168.255.2", count=4, timeout_s=1)

    assert record.packets_sent == 4
    assert record.packets_received == 3
    assert record.packet_loss_pct == 25.0


def test_ping_collector_rejects_unapproved_target() -> None:
    mock = MockTransport()
    collector = PingCollector(mock)
    with pytest.raises(SecurityViolationError, match="not on the approved"):
        collector.probe("R1", "8.8.8.8")


def test_traceroute_collector_hops() -> None:
    mock = MockTransport()
    mock.set_response(
        "R1",
        ["traceroute", "-n", "-w", "1", "-q", "1", "-m", "5", "192.168.255.3"],
        0,
        SAMPLE_TRACEROUTE_OUTPUT,
    )

    collector = TracerouteCollector(mock)
    record = collector.probe("R1", "192.168.255.3", max_hops=5, timeout_s=1)

    assert isinstance(record, TracerouteObservation)
    assert record.total_hops == 2
    assert record.destination_reached is True
    assert record.hops[0].hop_address == "10.0.12.2"
    assert record.hops[1].hop_address == "192.168.255.3"


# ---------------------------------------------------------------------------
# Test Syslog Collector
# ---------------------------------------------------------------------------


def test_syslog_collector_parsing() -> None:
    mock = MockTransport()
    mock.set_logs("R1", SAMPLE_DOCKER_LOGS)

    collector = SyslogCollector(mock)
    records = collector.collect(["R1"])

    assert len(records) == 3
    for r in records:
        assert isinstance(r, SyslogEvent)
        assert r.source_router == "R1"
        assert r.source_type == EvidenceSourceType.SYSLOG
        assert r.observed_at.tzinfo == UTC

    # Severity inference test
    starvation_event = records[2]
    assert isinstance(starvation_event, SyslogEvent)
    assert starvation_event.severity in (SyslogSeverity.ERROR, SyslogSeverity.WARNING)


# ---------------------------------------------------------------------------
# Test Normalizer & Ground-Truth Isolation
# ---------------------------------------------------------------------------


def test_normalizer_detects_ground_truth_leakage() -> None:
    now = datetime.now(UTC)
    leaked_record = {
        "evidence_id": "ev-test-1",
        "source_router": "R1",
        "event_type": "f1_link_failure",  # FORBIDDEN TOKEN
        "observed_at": now.isoformat(),
        "collected_at": now.isoformat(),
        "source_type": "INTERFACE_POLL",
        "collection_method": "PERIODIC_POLL",
    }
    with pytest.raises(GroundTruthLeakageError, match="Ground-truth token"):
        EvidenceNormalizer.assert_no_ground_truth_leakage(leaked_record)


def test_normalizer_validates_and_serializes() -> None:
    now = datetime.now(UTC)
    record = InterfaceObservation(
        evidence_id="ev-test-valid-1",
        source_router="R1",
        source_interface="eth1",
        event_type="INTERFACE_STATE_OBSERVED",
        observed_at=now,
        collected_at=now,
        source_type=EvidenceSourceType.INTERFACE_POLL,
        collection_method=CollectionMethod.PERIODIC_POLL,
        observed_status="up",
        speed_mbps=10000,
        error_count=0,
    )

    serialized = EvidenceNormalizer.serialize_records([record])
    assert len(serialized) == 1
    assert serialized[0]["evidence_id"] == "ev-test-valid-1"

    deserialized = EvidenceNormalizer.deserialize_record(serialized[0])
    assert isinstance(deserialized, InterfaceObservation)
    assert deserialized.source_router == "R1"


# ---------------------------------------------------------------------------
# Test Orchestrator
# ---------------------------------------------------------------------------


def test_orchestrator_multi_collector_run(tmp_path: Path) -> None:
    mock = MockTransport()
    for rid in ["R1", "R2", "R3", "R4", "R5"]:
        mock.set_response(rid, ["ip", "-j", "addr", "show"], 0, SAMPLE_IP_ADDR_JSON)
        mock.set_response(rid, ["ip", "-j", "-s", "link", "show"], 0, SAMPLE_IP_LINK_JSON)
        mock.set_response(rid, ["vtysh", "-c", "show ip ospf neighbor json"], 0, SAMPLE_OSPF_NEIGHBOR_JSON)
        mock.set_response(rid, ["vtysh", "-c", "show ip route json"], 0, SAMPLE_ROUTE_JSON)
        mock.set_response(rid, ["ping", "-c", "5", "-W", "1", "192.168.255.2"], 0, SAMPLE_PING_SUCCESS_OUTPUT)
        mock.set_response(
            rid,
            ["traceroute", "-n", "-w", "1", "-q", "1", "-m", "5", "192.168.255.3"],
            0,
            SAMPLE_TRACEROUTE_OUTPUT,
        )
        mock.set_logs(rid, SAMPLE_DOCKER_LOGS)

    orchestrator = CollectionOrchestrator(mock, storage_dir=tmp_path)
    snapshot = orchestrator.collect_snapshot(include_probes=True, include_logs=True)

    assert snapshot.total_records > 0
    assert len(snapshot.router_ids) == 5
    assert len(snapshot.collector_errors) == 0

    saved_file = orchestrator.save_snapshot(snapshot)
    assert saved_file.exists()

    with open(saved_file) as f:
        data = json.load(f)
    assert data["snapshot_id"] == snapshot.snapshot_id
    assert "evidence_records" in data
