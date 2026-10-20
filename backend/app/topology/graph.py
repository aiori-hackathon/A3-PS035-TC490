"""
NEXORA Topology Intelligence — NetworkX Graph Layer (Phase 05).

Builds and queries physical and logical topology graphs for use by the
incident correlation engine. Keeps three distinct graph views:

  EXPECTED  — the canonical baseline specification (Phase 01).
  OBSERVED  — the live-observed state from a collected EvidenceSnapshot.
  BASELINE  — an alias for EXPECTED (used when no baseline snapshot exists).

Physical topology (router ↔ link edges) and logical OSPF adjacency (router ↔
router edges) are stored as separate edge attributes / sub-graphs.

DESIGN CONSTRAINTS:
- Graph operations are read-only; they do NOT execute network commands.
- Physical topology and OSPF adjacency are kept as separate concerns.
  A missing OSPF adjacency does NOT automatically imply a physical link failure.
- UNKNOWN router/interface states are never inferred as DOWN.
- No ground-truth labels are stored or queried from this module.

Public API:
  TopologyGraph.get_router_neighbours(router_id) -> list[str]
  TopologyGraph.get_directly_connected_links(router_id) -> list[str]
  TopologyGraph.get_links_affected_by_router_outage(router_id) -> list[str]
  TopologyGraph.get_expected_adjacencies(router_id) -> list[tuple[str, str]]
  TopologyGraph.compare_adjacency_states(observed_adj) -> AdjacencyComparison
  TopologyGraph.get_connected_components() -> list[frozenset[str]]
  TopologyGraph.get_alternate_paths(src, dst) -> list[list[str]]
  TopologyGraph.map_prefix_to_router(prefix) -> str | None
  TopologyGraph.find_affected_paths(changed_component_id) -> list[tuple[str, str]]
  TopologyGraph.explain_relationship(component_a, component_b) -> str
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import networkx as nx

from app.schemas.topology import (
    NetworkLink,
    OSPFNeighbourState,
    Router,
    RouterStatus,
    RoutingAdjacency,
    Topology,
)

# ---------------------------------------------------------------------------
# Public enumerations
# ---------------------------------------------------------------------------


class TopologyKind(str, Enum):
    """Which topology view a graph represents."""

    EXPECTED = "EXPECTED"
    OBSERVED = "OBSERVED"
    BASELINE = "BASELINE"


# ---------------------------------------------------------------------------
# Dataclasses for query results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdjacencyStateEntry:
    """Single directional OSPF adjacency state in an observed comparison."""

    local_router: str
    neighbour_router: str
    expected_state: OSPFNeighbourState
    observed_state: OSPFNeighbourState | None  # None = missing / not observed
    is_full: bool
    is_missing: bool

    @property
    def is_degraded(self) -> bool:
        """True if observed but not FULL and not missing."""
        return (
            not self.is_missing
            and self.observed_state is not None
            and self.observed_state != OSPFNeighbourState.FULL
        )


@dataclass
class AdjacencyComparison:
    """Result of comparing observed OSPF adjacency states against expected."""

    total_expected: int
    full_count: int
    missing: list[AdjacencyStateEntry] = field(default_factory=list)
    degraded: list[AdjacencyStateEntry] = field(default_factory=list)
    entries: list[AdjacencyStateEntry] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        return len(self.missing) == 0 and len(self.degraded) == 0


# ---------------------------------------------------------------------------
# Topology constants
# ---------------------------------------------------------------------------

# Loopback prefix map: loopback IP (without mask) → router_id
_LOOPBACK_TO_ROUTER: dict[str, str] = {
    "192.168.255.1": "R1",
    "192.168.255.2": "R2",
    "192.168.255.3": "R3",
    "192.168.255.4": "R4",
    "192.168.255.5": "R5",
}

# Link subnet → link_id
_SUBNET_TO_LINK: dict[str, str] = {
    "10.0.12.0/30": "L12",
    "10.0.23.0/30": "L23",
    "10.0.34.0/30": "L34",
    "10.0.45.0/30": "L45",
    "10.0.15.0/30": "L51",
}

# OSPF Router-ID → stable router_id
OSPF_ID_TO_ROUTER: dict[str, str] = {
    "1.1.1.1": "R1",
    "2.2.2.2": "R2",
    "3.3.3.3": "R3",
    "4.4.4.4": "R4",
    "5.5.5.5": "R5",
}

# Stable router_id → OSPF Router-ID
ROUTER_TO_OSPF_ID: dict[str, str] = {v: k for k, v in OSPF_ID_TO_ROUTER.items()}

# Stable router_id → loopback IP (no mask)
ROUTER_TO_LOOPBACK: dict[str, str] = {
    "R1": "192.168.255.1",
    "R2": "192.168.255.2",
    "R3": "192.168.255.3",
    "R4": "192.168.255.4",
    "R5": "192.168.255.5",
}

# All loopback /32 prefixes
LOOPBACK_PREFIXES: dict[str, str] = {
    f"{ip}/32": rid for rid, ip in ROUTER_TO_LOOPBACK.items()
}


# ---------------------------------------------------------------------------
# Core TopologyGraph class
# ---------------------------------------------------------------------------


class TopologyGraph:
    """
    Graph-based topology intelligence layer for NEXORA.

    Attributes
    ----------
    topology : Topology
        The Pydantic Topology snapshot this graph was built from.
    kind : TopologyKind
        Whether this is an EXPECTED or OBSERVED graph.
    physical_graph : nx.Graph
        Undirected graph of routers connected by physical links.
        Node attrs: status, ospf_router_id, loopback
        Edge attrs: link_id, subnet, interface_a, interface_b, addr_a, addr_b
    adjacency_graph : nx.DiGraph
        Directed graph of OSPF adjacency relationships.
        Edge attrs: state, local_interface, neighbour_address, observed_at
    """

    ENGINE_VERSION: str = "nexora-correlation-v0.5.0"

    def __init__(
        self,
        topology: Topology,
        kind: TopologyKind = TopologyKind.OBSERVED,
    ) -> None:
        self.topology = topology
        self.kind = kind

        # Build router index
        self._router_index: dict[str, Router] = {r.router_id: r for r in topology.routers}
        self._link_index: dict[str, NetworkLink] = {lk.link_id: lk for lk in topology.links}

        self.physical_graph: nx.Graph = nx.Graph()
        self.adjacency_graph: nx.DiGraph = nx.DiGraph()

        self._build_physical_graph()
        self._build_adjacency_graph()

    # ------------------------------------------------------------------
    # Graph construction (private)
    # ------------------------------------------------------------------

    def _build_physical_graph(self) -> None:
        """Build undirected physical topology graph (routers + links)."""
        for router in self.topology.routers:
            self.physical_graph.add_node(
                router.router_id,
                status=router.status.value,
                ospf_router_id=ROUTER_TO_OSPF_ID.get(router.router_id, ""),
                loopback=ROUTER_TO_LOOPBACK.get(router.router_id, ""),
                role=router.role,
            )

        for link in self.topology.links:
            self.physical_graph.add_edge(
                link.router_a,
                link.router_b,
                link_id=link.link_id,
                subnet=link.subnet,
                interface_a=link.interface_a,
                interface_b=link.interface_b,
                addr_a=link.address_a,
                addr_b=link.address_b,
                ospf_cost=link.ospf_cost,
            )

    def _build_adjacency_graph(self) -> None:
        """Build directed OSPF adjacency graph from topology.adjacencies."""
        for router_id in self._router_index:
            if not self.adjacency_graph.has_node(router_id):
                self.adjacency_graph.add_node(router_id)

        for adj in self.topology.adjacencies:
            self.adjacency_graph.add_edge(
                adj.local_router,
                adj.neighbour_router,
                state=adj.state.value,
                local_interface=adj.local_interface,
                neighbour_address=adj.neighbour_address,
                observed_at=adj.observed_at.isoformat() if adj.observed_at else None,
            )

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def get_router_neighbours(self, router_id: str) -> list[str]:
        """
        Return physical neighbour router IDs (directly connected by a link).

        Parameters
        ----------
        router_id : str
            Source router identifier (e.g. 'R1').

        Returns
        -------
        list[str]
            Sorted list of directly connected router IDs.
        """
        if router_id not in self.physical_graph:
            return []
        return sorted(self.physical_graph.neighbors(router_id))

    def get_directly_connected_links(self, router_id: str) -> list[str]:
        """
        Return link IDs of all physical links connected to router_id.

        Returns
        -------
        list[str]
            Sorted link_id values.
        """
        if router_id not in self.physical_graph:
            return []
        link_ids = []
        for _, nbr, data in self.physical_graph.edges(router_id, data=True):
            link_id = data.get("link_id")
            if link_id:
                link_ids.append(link_id)
        return sorted(link_ids)

    def get_links_affected_by_router_outage(self, router_id: str) -> list[str]:
        """
        Return link IDs that would become unavailable if router_id went down.

        This is simply all links incident to router_id. It does NOT imply
        that those links themselves have failed.

        Returns
        -------
        list[str]
        """
        return self.get_directly_connected_links(router_id)

    def get_expected_adjacencies(self, router_id: str) -> list[tuple[str, str]]:
        """
        Return expected directional adjacency pairs for a router.

        Returns (local_router, neighbour_router) tuples based on the
        physical link topology (each physical link implies two expected
        directional adjacencies).

        Returns
        -------
        list[tuple[str, str]]
        """
        neighbours = self.get_router_neighbours(router_id)
        return [(router_id, nbr) for nbr in sorted(neighbours)]

    def compare_adjacency_states(
        self,
        observed_adjacencies: list[RoutingAdjacency],
    ) -> AdjacencyComparison:
        """
        Compare observed OSPF adjacency states against expected full adjacency.

        Expected adjacency: every router should have FULL adjacency with all
        physical neighbours. This checks directional (local → neighbour) pairs.

        Parameters
        ----------
        observed_adjacencies : list[RoutingAdjacency]
            Adjacency records from a collected or observed topology.

        Returns
        -------
        AdjacencyComparison
        """
        # Build expected pairs from physical graph
        expected_pairs: list[tuple[str, str]] = []
        for router_id in sorted(self._router_index.keys()):
            for nbr in sorted(self.physical_graph.neighbors(router_id)):
                expected_pairs.append((router_id, nbr))

        # Build observed map: (local, neighbour) → state
        observed_map: dict[tuple[str, str], OSPFNeighbourState] = {}
        for adj in observed_adjacencies:
            observed_map[(adj.local_router, adj.neighbour_router)] = adj.state

        entries: list[AdjacencyStateEntry] = []
        missing: list[AdjacencyStateEntry] = []
        degraded: list[AdjacencyStateEntry] = []
        full_count = 0

        for local, nbr in expected_pairs:
            obs_state = observed_map.get((local, nbr))
            is_missing = obs_state is None
            is_full = obs_state == OSPFNeighbourState.FULL

            entry = AdjacencyStateEntry(
                local_router=local,
                neighbour_router=nbr,
                expected_state=OSPFNeighbourState.FULL,
                observed_state=obs_state,
                is_full=is_full,
                is_missing=is_missing,
            )
            entries.append(entry)
            if is_full:
                full_count += 1
            elif is_missing:
                missing.append(entry)
            elif entry.is_degraded:
                degraded.append(entry)

        return AdjacencyComparison(
            total_expected=len(expected_pairs),
            full_count=full_count,
            missing=missing,
            degraded=degraded,
            entries=entries,
        )

    def get_connected_components(self) -> list[frozenset[str]]:
        """
        Return connected components of the physical topology graph.

        Only UP routers participate as effective nodes. A DOWN router is
        treated as if its edges are removed.

        Returns
        -------
        list[frozenset[str]]
            Sorted list of frozensets of router IDs.
        """
        # Create subgraph with only UP routers
        up_routers = [
            r.router_id
            for r in self.topology.routers
            if r.status != RouterStatus.DOWN
        ]
        subgraph = self.physical_graph.subgraph(up_routers)
        components = list(nx.connected_components(subgraph))
        return sorted([frozenset(c) for c in components], key=lambda s: sorted(s))

    def get_alternate_paths(self, src: str, dst: str) -> list[list[str]]:
        """
        Find all simple paths between src and dst in the physical topology.

        Uses only UP routers in the graph. The primary path is typically the
        shortest. Returns multiple paths to identify redundancy.

        Parameters
        ----------
        src : str
            Source router ID.
        dst : str
            Destination router ID.

        Returns
        -------
        list[list[str]]
            Each element is an ordered list of router IDs forming a path.
            Empty if no path exists.
        """
        if src not in self.physical_graph or dst not in self.physical_graph:
            return []
        up_routers = [
            r.router_id
            for r in self.topology.routers
            if r.status != RouterStatus.DOWN
        ]
        subgraph = self.physical_graph.subgraph(up_routers)
        try:
            paths = list(nx.all_simple_paths(subgraph, src, dst, cutoff=6))
            return sorted(paths, key=len)
        except (nx.NetworkXError, nx.NodeNotFound):
            return []

    def map_prefix_to_router(self, prefix: str) -> str | None:
        """
        Identify which router owns a destination prefix.

        Handles loopback /32 prefixes (e.g. '192.168.255.3/32' → 'R3').
        For link subnets, returns the router pair as 'R3-R4' (not a single router).

        Parameters
        ----------
        prefix : str
            IPv4 prefix string (e.g. '192.168.255.3/32').

        Returns
        -------
        str | None
            Router ID owning the prefix, or None if not recognized.
        """
        # Normalize prefix
        try:
            net = ipaddress.IPv4Network(prefix, strict=False)
            normalized = str(net)
        except ValueError:
            return None

        # Check loopback prefixes
        if normalized in LOOPBACK_PREFIXES:
            return LOOPBACK_PREFIXES[normalized]

        # Also check host address (no mask)
        host_str = str(net.network_address)
        if host_str in _LOOPBACK_TO_ROUTER:
            return _LOOPBACK_TO_ROUTER[host_str]

        return None

    def find_affected_paths(self, changed_component_id: str) -> list[tuple[str, str]]:
        """
        Find (src, dst) router pairs whose paths might be affected by a change.

        For a link change: returns pairs that traverse that link in the
        expected topology. For a router change: returns all pairs involving
        that router's neighbours.

        Parameters
        ----------
        changed_component_id : str
            Router ID (e.g. 'R3') or Link ID (e.g. 'L34').

        Returns
        -------
        list[tuple[str, str]]
            List of (src_router, dst_router) pairs.
        """
        affected: list[tuple[str, str]] = []
        all_routers = sorted(self._router_index.keys())

        if changed_component_id in self._router_index:
            # Router change: all paths through this router
            for src in all_routers:
                for dst in all_routers:
                    if src == dst or src == changed_component_id or dst == changed_component_id:
                        continue
                    paths = list(
                        nx.all_simple_paths(self.physical_graph, src, dst, cutoff=6)
                    )
                    for path in paths:
                        if changed_component_id in path:
                            affected.append((src, dst))
                            break

        elif changed_component_id in self._link_index:
            # Link change: all paths using this link
            link = self._link_index[changed_component_id]
            router_a, router_b = link.router_a, link.router_b
            for src in all_routers:
                for dst in all_routers:
                    if src == dst:
                        continue
                    paths = list(
                        nx.all_simple_paths(self.physical_graph, src, dst, cutoff=6)
                    )
                    for path in paths:
                        # Check if this link edge is traversed
                        for i in range(len(path) - 1):
                            if (
                                (path[i] == router_a and path[i + 1] == router_b)
                                or (path[i] == router_b and path[i + 1] == router_a)
                            ):
                                affected.append((src, dst))
                                break

        return sorted(set(affected))

    def explain_relationship(self, component_a: str, component_b: str) -> str:
        """
        Produce a human-readable explanation of the topology relationship
        between two components (routers or links).

        Parameters
        ----------
        component_a : str
            Router ID or Link ID.
        component_b : str
            Router ID or Link ID.

        Returns
        -------
        str
            Plain-English description of the relationship.
        """
        # Both routers
        if component_a in self._router_index and component_b in self._router_index:
            if self.physical_graph.has_edge(component_a, component_b):
                edge_data: dict[str, Any] = self.physical_graph[component_a][component_b]
                link_id = edge_data.get("link_id", "unknown")
                subnet = edge_data.get("subnet", "unknown")
                return (
                    f"{component_a} and {component_b} are directly connected via "
                    f"link {link_id} on subnet {subnet}."
                )
            else:
                paths = self.get_alternate_paths(component_a, component_b)
                if paths:
                    shortest = " → ".join(paths[0])
                    return (
                        f"{component_a} and {component_b} are not directly connected. "
                        f"Shortest physical path: {shortest}."
                    )
                return (
                    f"{component_a} and {component_b} are not connected in this topology."
                )

        # Router and link
        if component_a in self._router_index and component_b in self._link_index:
            link = self._link_index[component_b]
            if component_a in (link.router_a, link.router_b):
                return (
                    f"{component_a} is an endpoint of link {component_b} "
                    f"(subnet {link.subnet})."
                )
            return f"{component_a} is not directly connected to link {component_b}."

        if component_a in self._link_index and component_b in self._router_index:
            return self.explain_relationship(component_b, component_a)

        # Both links
        if component_a in self._link_index and component_b in self._link_index:
            lk_a = self._link_index[component_a]
            lk_b = self._link_index[component_b]
            shared = set([lk_a.router_a, lk_a.router_b]) & set([lk_b.router_a, lk_b.router_b])
            if shared:
                router = next(iter(shared))
                return (
                    f"Links {component_a} and {component_b} share router {router} "
                    f"as a common endpoint."
                )
            return f"Links {component_a} and {component_b} have no shared endpoint."

        return f"Unknown relationship between {component_a!r} and {component_b!r}."

    def get_router_info(self, router_id: str) -> dict[str, Any]:
        """
        Return metadata for a router node from the physical graph.

        Returns
        -------
        dict[str, Any]
            Node attributes dict or empty dict if router not found.
        """
        if router_id not in self.physical_graph:
            return {}
        return dict(self.physical_graph.nodes[router_id])

    def get_link_info(self, link_id: str) -> dict[str, Any] | None:
        """
        Return metadata for a link edge from the physical graph.

        Returns
        -------
        dict[str, Any] | None
        """
        if link_id not in self._link_index:
            return None
        link = self._link_index[link_id]
        if not self.physical_graph.has_edge(link.router_a, link.router_b):
            return None
        return dict(self.physical_graph[link.router_a][link.router_b])

    def find_link_between(self, router_a: str, router_b: str) -> str | None:
        """
        Return the link_id between two routers, or None if not directly connected.
        """
        if not self.physical_graph.has_edge(router_a, router_b):
            return None
        return self.physical_graph[router_a][router_b].get("link_id")


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def build_expected_topology_graph() -> TopologyGraph:
    """
    Build a TopologyGraph from the canonical expected NEXORA topology.

    This uses the Phase 01 baseline specification directly, without querying
    any live network devices.
    """
    from app.collectors.topology_collector import TopologyCollector
    from app.collectors.transport import MockTransport

    # MockTransport with empty responses; we only need the expected topology
    mock = MockTransport()
    collector = TopologyCollector(mock)
    expected_topo = collector.get_expected_topology(snapshot_id="expected-topology-static")
    return TopologyGraph(expected_topo, kind=TopologyKind.EXPECTED)


def build_observed_topology_graph(topology: Topology) -> TopologyGraph:
    """
    Build a TopologyGraph from a previously collected Topology snapshot.

    Parameters
    ----------
    topology : Topology
        The observed topology (e.g. from EvidenceSnapshot.topology).
    """
    return TopologyGraph(topology, kind=TopologyKind.OBSERVED)
