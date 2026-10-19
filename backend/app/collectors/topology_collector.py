"""
Live topology discovery and expectation comparison collector for NEXORA.

Discovers router states, interface configurations, IP addresses, and OSPF adjacencies.
Distinguishes between EXPECTED TOPOLOGY (Phase 01 baseline specification)
and OBSERVED TOPOLOGY (live lab state).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.collectors.base import DEFAULT_ROUTER_IDS, BaseCollector
from app.schemas.topology import (
    InterfaceStatus,
    NetworkInterface,
    NetworkLink,
    OSPFNeighbourState,
    Router,
    RouterStatus,
    RoutingAdjacency,
    Topology,
)

EXPECTED_ROUTERS_METADATA: dict[str, dict] = {
    "R1": {
        "ospf_router_id": "1.1.1.1",
        "loopback_address": "192.168.255.1/32",
        "role": "Core Gateway / Entry Point",
        "interfaces": {
            "lo": {"ipv4": "192.168.255.1/32", "area": "0.0.0.0", "passive": False},
            "eth1": {"ipv4": "10.0.12.1/30", "area": "0.0.0.0", "passive": False},
            "eth2": {"ipv4": "10.0.15.2/30", "area": "0.0.0.0", "passive": False},
        },
    },
    "R2": {
        "ospf_router_id": "2.2.2.2",
        "loopback_address": "192.168.255.2/32",
        "role": "Aggregation Node A",
        "interfaces": {
            "lo": {"ipv4": "192.168.255.2/32", "area": "0.0.0.0", "passive": False},
            "eth1": {"ipv4": "10.0.12.2/30", "area": "0.0.0.0", "passive": False},
            "eth2": {"ipv4": "10.0.23.1/30", "area": "0.0.0.0", "passive": False},
        },
    },
    "R3": {
        "ospf_router_id": "3.3.3.3",
        "loopback_address": "192.168.255.3/32",
        "role": "Aggregation Node B",
        "interfaces": {
            "lo": {"ipv4": "192.168.255.3/32", "area": "0.0.0.0", "passive": False},
            "eth1": {"ipv4": "10.0.23.2/30", "area": "0.0.0.0", "passive": False},
            "eth2": {"ipv4": "10.0.34.1/30", "area": "0.0.0.0", "passive": False},
        },
    },
    "R4": {
        "ospf_router_id": "4.4.4.4",
        "loopback_address": "192.168.255.4/32",
        "role": "Edge Router",
        "interfaces": {
            "lo": {"ipv4": "192.168.255.4/32", "area": "0.0.0.0", "passive": False},
            "eth1": {"ipv4": "10.0.34.2/30", "area": "0.0.0.0", "passive": False},
            "eth2": {"ipv4": "10.0.45.1/30", "area": "0.0.0.0", "passive": False},
        },
    },
    "R5": {
        "ospf_router_id": "5.5.5.5",
        "loopback_address": "192.168.255.5/32",
        "role": "Peer / Transit Node",
        "interfaces": {
            "lo": {"ipv4": "192.168.255.5/32", "area": "0.0.0.0", "passive": False},
            "eth1": {"ipv4": "10.0.45.2/30", "area": "0.0.0.0", "passive": False},
            "eth2": {"ipv4": "10.0.15.1/30", "area": "0.0.0.0", "passive": False},
        },
    },
}

EXPECTED_LINKS_SPEC: list[dict] = [
    {
        "link_id": "L12",
        "subnet": "10.0.12.0/30",
        "router_a": "R1",
        "interface_a": "eth1",
        "address_a": "10.0.12.1/30",
        "router_b": "R2",
        "interface_b": "eth1",
        "address_b": "10.0.12.2/30",
        "ospf_cost": 1,
    },
    {
        "link_id": "L23",
        "subnet": "10.0.23.0/30",
        "router_a": "R2",
        "interface_a": "eth2",
        "address_a": "10.0.23.1/30",
        "router_b": "R3",
        "interface_b": "eth1",
        "address_b": "10.0.23.2/30",
        "ospf_cost": 1,
    },
    {
        "link_id": "L34",
        "subnet": "10.0.34.0/30",
        "router_a": "R3",
        "interface_a": "eth2",
        "address_a": "10.0.34.1/30",
        "router_b": "R4",
        "interface_b": "eth1",
        "address_b": "10.0.34.2/30",
        "ospf_cost": 1,
    },
    {
        "link_id": "L45",
        "subnet": "10.0.45.0/30",
        "router_a": "R4",
        "interface_a": "eth2",
        "address_a": "10.0.45.1/30",
        "router_b": "R5",
        "interface_b": "eth1",
        "address_b": "10.0.45.2/30",
        "ospf_cost": 1,
    },
    {
        "link_id": "L51",
        "subnet": "10.0.15.0/30",
        "router_a": "R5",
        "interface_a": "eth2",
        "address_a": "10.0.15.1/30",
        "router_b": "R1",
        "interface_b": "eth2",
        "address_b": "10.0.15.2/30",
        "ospf_cost": 1,
    },
]

ROUTER_ID_BY_OSPF_ID: dict[str, str] = {
    meta["ospf_router_id"]: rid for rid, meta in EXPECTED_ROUTERS_METADATA.items()
}


@dataclass
class TopologyComparison:
    """Comparison result between expected topology and observed topology."""

    expected_routers: int
    observed_up_routers: int
    down_routers: list[str] = field(default_factory=list)
    expected_links: int = 5
    expected_adjacencies: int = 10
    observed_adjacencies: int = 0
    missing_adjacencies: list[tuple[str, str]] = field(default_factory=list)
    degraded_adjacencies: list[tuple[str, str, str]] = field(default_factory=list)
    is_healthy: bool = False


class TopologyCollector(BaseCollector):
    """Discovers live topology and compares against the Phase 01 specification."""

    COLLECTOR_NAME: ClassVar[str] = "topology"

    def get_expected_topology(self, snapshot_id: str | None = None) -> Topology:
        """Return the canonical baseline expected topology."""
        snap_id = snapshot_id or f"expected-topo-{int(self.now_utc().timestamp())}"
        routers = []
        for rid, meta in EXPECTED_ROUTERS_METADATA.items():
            ifaces = [
                NetworkInterface(
                    interface_name=iname,
                    ipv4_address=idata["ipv4"],
                    status=InterfaceStatus.UP,
                    is_ospf_passive=idata["passive"],
                    ospf_area=idata["area"],
                )
                for iname, idata in meta["interfaces"].items()
            ]
            routers.append(
                Router(
                    router_id=rid,
                    ospf_router_id=meta["ospf_router_id"],
                    loopback_address=meta["loopback_address"],
                    role=meta["role"],
                    status=RouterStatus.UP,
                    interfaces=ifaces,
                )
            )

        links = [NetworkLink(**link_data) for link_data in EXPECTED_LINKS_SPEC]
        return Topology(
            snapshot_id=snap_id,
            captured_at=self.now_utc(),
            routers=routers,
            links=links,
            adjacencies=[],
        )

    def collect_observed_topology(self, snapshot_id: str | None = None) -> Topology:
        """Query live routers to assemble the observed topology."""
        now = self.now_utc()
        snap_id = snapshot_id or f"observed-topo-{int(now.timestamp())}"

        observed_routers: list[Router] = []
        observed_adjacencies: list[RoutingAdjacency] = []

        for rid in DEFAULT_ROUTER_IDS:
            meta = EXPECTED_ROUTERS_METADATA[rid]
            is_running = self.transport.is_router_running(rid)

            if not is_running:
                # Stopped router is explicitly represented as DOWN, not omitted!
                down_ifaces = [
                    NetworkInterface(
                        interface_name=iname,
                        ipv4_address=idata["ipv4"],
                        status=InterfaceStatus.DOWN,
                        is_ospf_passive=idata["passive"],
                        ospf_area=idata["area"],
                    )
                    for iname, idata in meta["interfaces"].items()
                ]
                observed_routers.append(
                    Router(
                        router_id=rid,
                        ospf_router_id=meta["ospf_router_id"],
                        loopback_address=meta["loopback_address"],
                        role=meta["role"],
                        status=RouterStatus.DOWN,
                        interfaces=down_ifaces,
                    )
                )
                continue

            # Router is running: query live interfaces
            ifaces = self._discover_interfaces(rid, meta)
            observed_routers.append(
                Router(
                    router_id=rid,
                    ospf_router_id=meta["ospf_router_id"],
                    loopback_address=meta["loopback_address"],
                    role=meta["role"],
                    status=RouterStatus.UP,
                    interfaces=ifaces,
                )
            )

            # Query live OSPF adjacencies
            adjs = self._discover_adjacencies(rid, now)
            observed_adjacencies.extend(adjs)

        # Links are based on the known physical topology
        links = [NetworkLink(**link_data) for link_data in EXPECTED_LINKS_SPEC]

        return Topology(
            snapshot_id=snap_id,
            captured_at=now,
            routers=observed_routers,
            links=links,
            adjacencies=observed_adjacencies,
        )

    def _discover_interfaces(self, router_id: str, meta: dict) -> list[NetworkInterface]:
        """Discover live interface statuses and addresses via ip -j addr show."""
        interfaces: list[NetworkInterface] = []
        code, stdout, _ = self.transport.execute(router_id, ["ip", "-j", "addr", "show"])

        if code != 0 or not stdout.strip():
            # Fallback to metadata with UNKNOWN status
            return [
                NetworkInterface(
                    interface_name=iname,
                    ipv4_address=idata["ipv4"],
                    status=InterfaceStatus.UNKNOWN,
                    is_ospf_passive=idata["passive"],
                    ospf_area=idata["area"],
                )
                for iname, idata in meta["interfaces"].items()
            ]

        try:
            addr_data = json.loads(stdout)
        except Exception:
            addr_data = []

        iface_map: dict[str, dict] = {item.get("ifname", ""): item for item in addr_data}

        for iname, idata in meta["interfaces"].items():
            live_item = iface_map.get(iname)
            if live_item is None:
                interfaces.append(
                    NetworkInterface(
                        interface_name=iname,
                        ipv4_address=idata["ipv4"],
                        status=InterfaceStatus.DOWN,
                        is_ospf_passive=idata["passive"],
                        ospf_area=idata["area"],
                    )
                )
                continue

            operstate = (live_item.get("operstate") or "UNKNOWN").upper()
            status = InterfaceStatus.UP if operstate in ("UP", "UNKNOWN") else InterfaceStatus.DOWN

            # Find matching data plane IPv4 address
            discovered_ip = None
            for addr_info in live_item.get("addr_info", []):
                local_ip = addr_info.get("local")
                prefixlen = addr_info.get("prefixlen")
                if (
                    local_ip
                    and prefixlen
                    and not local_ip.startswith("127.")
                    and not local_ip.startswith("172.31.")
                ):
                    discovered_ip = f"{local_ip}/{prefixlen}"
                    break

            interfaces.append(
                NetworkInterface(
                    interface_name=iname,
                    ipv4_address=discovered_ip or idata["ipv4"],
                    status=status,
                    is_ospf_passive=idata["passive"],
                    ospf_area=idata["area"],
                )
            )

        return interfaces

    def _discover_adjacencies(
        self,
        router_id: str,
        observed_at: datetime,
    ) -> list[RoutingAdjacency]:
        """Discover live OSPF adjacencies from vtysh show ip ospf neighbor json."""
        adjacencies: list[RoutingAdjacency] = []
        code, stdout, _ = self.transport.execute(
            router_id,
            ["vtysh", "-c", "show ip ospf neighbor json"],
        )
        if code != 0 or not stdout.strip():
            return []

        try:
            data = json.loads(stdout)
        except Exception:
            return []

        neighbors_dict = data.get("neighbors", {})
        for nbr_ospf_id, nbr_list in neighbors_dict.items():
            nbr_router_id = ROUTER_ID_BY_OSPF_ID.get(nbr_ospf_id, nbr_ospf_id)
            for item in nbr_list:
                raw_state = item.get("converged") or item.get("state", "UNKNOWN")
                state_str = raw_state.split("/")[0].strip().upper()
                ospf_state = getattr(OSPFNeighbourState, state_str, OSPFNeighbourState.UNKNOWN)

                iface_field = item.get("ifaceName", "")
                local_iface = iface_field.split(":")[0] if ":" in iface_field else iface_field
                nbr_addr = item.get("address", "")

                if nbr_addr:
                    adjacencies.append(
                        RoutingAdjacency(
                            local_router=router_id,
                            neighbour_router=nbr_router_id,
                            local_interface=local_iface,
                            neighbour_address=nbr_addr,
                            state=ospf_state,
                            observed_at=observed_at,
                        )
                    )

        return adjacencies

    def compare(self, observed: Topology) -> TopologyComparison:
        """Compare observed topology against expected baseline."""
        down_routers = [r.router_id for r in observed.routers if r.status == RouterStatus.DOWN]
        up_routers_count = len(
            [r.router_id for r in observed.routers if r.status == RouterStatus.UP]
        )

        # Directional expected adjacencies: 10 pairs
        expected_pairs = [
            ("R1", "R2"),
            ("R1", "R5"),
            ("R2", "R1"),
            ("R2", "R3"),
            ("R3", "R2"),
            ("R3", "R4"),
            ("R4", "R3"),
            ("R4", "R5"),
            ("R5", "R4"),
            ("R5", "R1"),
        ]

        observed_map: dict[tuple[str, str], OSPFNeighbourState] = {
            (adj.local_router, adj.neighbour_router): adj.state
            for adj in observed.adjacencies
        }

        missing: list[tuple[str, str]] = []
        degraded: list[tuple[str, str, str]] = []

        for local, nbr in expected_pairs:
            if (local, nbr) not in observed_map:
                missing.append((local, nbr))
            else:
                state = observed_map[(local, nbr)]
                if state != OSPFNeighbourState.FULL:
                    degraded.append((local, nbr, state.value))

        is_healthy = (
            len(down_routers) == 0
            and len(missing) == 0
            and len(degraded) == 0
            and len(observed.adjacencies) == 10
        )

        return TopologyComparison(
            expected_routers=5,
            observed_up_routers=up_routers_count,
            down_routers=down_routers,
            expected_adjacencies=10,
            observed_adjacencies=len(observed.adjacencies),
            missing_adjacencies=missing,
            degraded_adjacencies=degraded,
            is_healthy=is_healthy,
        )

    def collect(
        self,
        router_ids: list[str] | None = None,
        incident_id: str | None = None,
    ) -> list:
        """TopologyCollector primary method returns Topology, but satisfies BaseCollector."""
        return [self.collect_observed_topology()]
