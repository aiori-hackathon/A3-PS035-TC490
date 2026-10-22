"""Evidence interpretation and dependency boundaries for deterministic diagnosis.

Only typed observations and a small allowlist of lossless collector state tags
are interpreted. IDs and raw references are opaque provenance, never features.
Topology supplies identities/connectivity, never observations or health claims.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from ipaddress import ip_address, ip_interface, ip_network

import networkx as nx

from app.collectors.normalizer import EvidenceNormalizer
from app.schemas.evidence import (
    EvidenceRecord,
    EvidenceSourceType,
    InterfaceObservation,
    ObservationStatus,
    OSPFObservation,
    PingMeasurement,
    RouteObservation,
    TracerouteObservation,
)
from app.schemas.topology import NetworkLink, Topology


def _address_ip(value: str | None) -> str | None:
    """Normalize plain/prefixed endpoint addresses without guessing identities."""
    if not value:
        return None
    try:
        return str(ip_interface(value).ip)
    except ValueError:
        return None


def unique_records(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """Reject reused IDs with changed payloads; exact replay is harmless."""
    by_id: dict[str, EvidenceRecord] = {}
    for record in records:
        EvidenceNormalizer.assert_no_ground_truth_leakage(record.model_dump(mode="json"))
        previous = by_id.get(record.evidence_id)
        if previous is not None and previous.model_dump() != record.model_dump():
            raise ValueError(f"Conflicting payloads for evidence ID {record.evidence_id}")
        by_id[record.evidence_id] = record
    return sorted(by_id.values(), key=lambda r: (r.observed_at, r.evidence_id))


def decode_state_tags(records: list[EvidenceRecord], topology: Topology) -> list[EvidenceRecord]:
    """Decode surviving legacy tags without inventing metrics or parsing IDs.

    INTERFACE_STATE_OBSERVED means UP in InterfaceCollector. OSPF identity is
    resolvable only for a unique point-to-point source interface in this topology.
    Loopback DOWN tags are excluded: iproute operstate UNKNOWN was historically
    collected as DOWN for loopbacks; they do not identify failed data links.
    """
    endpoints = {
        (router, iface): (link, peer, address)
        for link in topology.links
        for router, iface, peer, address in (
            (link.router_a, link.interface_a, link.router_b, link.address_b),
            (link.router_b, link.interface_b, link.router_a, link.address_a),
        )
    }
    routers = {r.router_id: r for r in topology.routers}
    decoded: list[EvidenceRecord] = []
    for record in unique_records(records):
        endpoint = endpoints.get((record.source_router, record.source_interface))
        if (
            type(record) is not EvidenceRecord
            or endpoint is None
            or record.collection_status != ObservationStatus.OBSERVED
        ):
            decoded.append(record)
            continue
        data = record.model_dump()
        if record.source_type == EvidenceSourceType.INTERFACE_POLL and record.event_type in {
            "INTERFACE_DOWN_OBSERVED",
            "INTERFACE_STATE_OBSERVED",
            "INTERFACE_NOT_FOUND",
        }:
            data["observed_status"] = (
                "up" if record.event_type == "INTERFACE_STATE_OBSERVED" else "down"
            )
            decoded.append(InterfaceObservation(**data))
        elif record.source_type == EvidenceSourceType.OSPF_API and record.event_type in {
            "OSPF_NEIGHBOUR_FULL",
            "OSPF_NEIGHBOUR_DOWN",
        }:
            _, peer, address = endpoint
            data.update(
                neighbour_router_id=routers[peer].ospf_router_id,
                neighbour_address=str(ip_interface(address).ip),
                adjacency_state=record.event_type.removeprefix("OSPF_NEIGHBOUR_"),
            )
            decoded.append(OSPFObservation(**data))
        else:
            decoded.append(record)
    return decoded


@dataclass(frozen=True)
class ProbePath:
    links: frozenset[str]
    evidence_ids: tuple[str, ...] = ()
    observed: bool = False


class EvidenceContext:
    """Index evidence by actual topology components and independent polling point."""

    def __init__(self, records: list[EvidenceRecord], topology: Topology) -> None:
        self.records = decode_state_tags(records, topology)
        self.by_id = {r.evidence_id: r for r in self.records}
        self.topology = topology
        self.links = {link.link_id: link for link in topology.links}
        self.routers = {r.router_id: r for r in topology.routers}
        self.interface_link = {
            (router, interface): link.link_id
            for link in topology.links
            for router, interface in (
                (link.router_a, link.interface_a),
                (link.router_b, link.interface_b),
            )
        }
        self.address_router = {
            str(ip_interface(address).ip): r.router_id
            for r in topology.routers
            for address in [
                r.loopback_address,
                *[i.ipv4_address for i in r.interfaces if i.ipv4_address],
            ]
        }
        for link in topology.links:
            self.address_router[str(ip_interface(link.address_a).ip)] = link.router_a
            self.address_router[str(ip_interface(link.address_b).ip)] = link.router_b
        self.ospf_router = {r.ospf_router_id: r.router_id for r in topology.routers}
        self.graph = nx.Graph()
        self.graph.add_nodes_from(self.routers)
        for link in topology.links:
            self.graph.add_edge(
                link.router_a, link.router_b, link_id=link.link_id, weight=link.ospf_cost
            )
        self.interfaces: dict[str, list[InterfaceObservation]] = defaultdict(list)
        self.adjacencies: dict[str, list[OSPFObservation]] = defaultdict(list)
        self.unavailable: dict[str, list[EvidenceRecord]] = defaultdict(list)
        self.failures: dict[str, list[EvidenceRecord]] = defaultdict(list)
        self.live: dict[str, list[EvidenceRecord]] = defaultdict(list)
        self.pings: list[PingMeasurement] = []
        self.routes: list[RouteObservation] = []
        self.traces: list[TracerouteObservation] = []
        for record in self.records:
            router = record.source_router
            if router not in self.routers:
                continue
            if record.collection_status != ObservationStatus.OBSERVED:
                if record.collection_status == ObservationStatus.COLLECTION_FAILED:
                    self.failures[router].append(record)
                    if record.event_type in {"ROUTER_UNAVAILABLE", "PROBE_SOURCE_UNAVAILABLE"}:
                        self.unavailable[router].append(record)
                continue
            if isinstance(record, InterfaceObservation):
                link_id = self.interface_link.get((router, record.source_interface))
                if link_id and self.interface_state(record) in {"up", "down"}:
                    self.interfaces[link_id].append(record)
                    self.live[router].append(record)
            elif isinstance(record, OSPFObservation):
                peer = self.ospf_router.get(record.neighbour_router_id)
                link_id = self.link_between(router, peer)
                if (
                    record.source_interface is not None
                    and self.interface_link.get((router, record.source_interface)) != link_id
                ):
                    continue
                if link_id:
                    link = self.links[link_id]
                    peer_address = link.address_b if router == link.router_a else link.address_a
                    reported_address = _address_ip(record.neighbour_address)
                    # FRR may omit an address (collector placeholder 0.0.0.0).
                    # A known address must identify this exact link endpoint,
                    # even if another address belongs to the same peer router.
                    if (
                        record.neighbour_address and reported_address is None
                    ) or reported_address not in {None, "0.0.0.0", _address_ip(peer_address)}:
                        continue
                if link_id and self.adjacency_state(record) != "unknown":
                    self.adjacencies[link_id].append(record)
                    self.live[router].append(record)
            elif isinstance(record, PingMeasurement):
                if record.probe_source == router:
                    self.pings.append(record)
                    self.live[router].append(record)
            elif isinstance(record, RouteObservation):
                self.routes.append(record)
                self.live[router].append(record)
            elif isinstance(record, TracerouteObservation):
                if record.probe_source == router:
                    self.traces.append(record)
                    self.live[router].append(record)

    @staticmethod
    def interface_state(record: InterfaceObservation) -> str:
        state = record.observed_status.lower().replace("_", "-")
        return "down" if state in {"down", "admin-down"} else state

    @staticmethod
    def adjacency_state(record: OSPFObservation) -> str:
        state = record.adjacency_state.lower().split("/")[0]
        if state in {"2way", "two_way", "two-way"}:
            state = "2-way"
        return (
            state
            if state
            in {
                "full",
                "down",
                "init",
                "attempt",
                "exstart",
                "exchange",
                "loading",
                "2-way",
            }
            else "unknown"
        )

    def link_between(self, source: str, target: str | None) -> str | None:
        if source in self.graph and target in self.graph and self.graph.has_edge(source, target):
            return self.graph[source][target]["link_id"]
        return None

    def endpoints(self, link: NetworkLink) -> set[str]:
        return {link.router_a, link.router_b}

    def paths(self, ping: PingMeasurement) -> list[ProbePath]:
        """Prefer complete observed traces; otherwise retain ALL equal-cost paths.

        An inferred path is a localisation assumption, never evidence that a
        particular link was traversed. Multi-link paths produce competing causes.
        """
        source = ping.probe_source
        target = self.address_router.get(ping.target_address)
        if target is None or target == source:
            return []
        paths: list[ProbePath] = []
        for trace in self.traces:
            if (
                trace.probe_source != source
                or trace.target_address != ping.target_address
                or not trace.destination_reached
                or not trace.hops
                or abs((trace.observed_at - ping.observed_at).total_seconds()) > 30
            ):
                continue
            hops = sorted(trace.hops, key=lambda h: h.hop_number)
            if [h.hop_number for h in hops] != list(range(1, len(hops) + 1)):
                continue
            nodes = [source]
            for hop in hops:
                router = self.address_router.get(hop.hop_address or "")
                if router is None or hop.is_unreachable:
                    break
                if router != nodes[-1]:
                    nodes.append(router)
            else:
                links = [self.link_between(a, b) for a, b in zip(nodes, nodes[1:])]
                if nodes[-1] == target and links and all(links):
                    paths.append(ProbePath(frozenset(links), (trace.evidence_id,), True))
        if paths:
            return paths
        # Use a known source egress route when available, retaining the remaining
        # path uncertainty rather than declaring the whole shortest path observed.
        matching_routes = []
        for route in self.routes:
            if route.source_router != source or not route.is_present:
                continue
            try:
                network = ip_network(route.destination_prefix, strict=False)
                if ip_address(ping.target_address) not in network:
                    continue
            except ValueError:
                continue
            next_hop = _address_ip(route.next_hop_address)
            if route.next_hop_interface is not None:
                # A supplied interface is a constraint, not an optional hint.
                # Never rescue a contradictory/unknown name via its address.
                link_id = self.interface_link.get((source, route.next_hop_interface))
                if link_id is None:
                    continue
            else:
                matches = [
                    link.link_id
                    for link in self.links.values()
                    if source in self.endpoints(link)
                    and next_hop is not None
                    and next_hop == _address_ip(
                        link.address_b if source == link.router_a else link.address_a
                    )
                ]
                if len(matches) != 1:
                    continue
                link_id = matches[0]
            link = self.links[link_id]
            peer = link.router_b if source == link.router_a else link.router_a
            peer_address = link.address_b if source == link.router_a else link.address_a
            if route.next_hop_address and next_hop != _address_ip(peer_address):
                continue
            matching_routes.append((network.prefixlen, link_id, peer, route))
        longest = max((item[0] for item in matching_routes), default=-1)
        remainder = self.graph.copy()
        remainder.remove_node(source)
        for prefix_len, link_id, peer, route in matching_routes:
            if prefix_len != longest:
                continue
            try:
                for nodes in nx.all_shortest_paths(remainder, peer, target, weight="weight"):
                    links = {link_id} | {
                        remainder[a][b]["link_id"] for a, b in zip(nodes, nodes[1:])
                    }
                    paths.append(ProbePath(frozenset(links), (route.evidence_id,)))
            except nx.NetworkXNoPath:
                pass
        if paths:
            return paths
        try:
            for nodes in nx.all_shortest_paths(self.graph, source, target, weight="weight"):
                paths.append(
                    ProbePath(
                        frozenset(self.graph[a][b]["link_id"] for a, b in zip(nodes, nodes[1:]))
                    )
                )
        except nx.NetworkXNoPath:
            pass
        return paths

    def point_key(self, record: EvidenceRecord) -> tuple:
        # All availability failures for one router depend on one transport check.
        if record.collection_status == ObservationStatus.COLLECTION_FAILED:
            return ("availability", record.source_router)
        if isinstance(record, OSPFObservation):
            return ("ospf", record.source_router, record.neighbour_router_id)
        if isinstance(record, (PingMeasurement, TracerouteObservation)):
            return (record.source_type, record.source_router, record.target_address)
        if isinstance(record, RouteObservation):
            # Every prefix from one routing-table poll shares a collection point.
            return (EvidenceSourceType.ROUTING_TABLE, record.source_router)
        if record.source_type == EvidenceSourceType.ROUTING_TABLE:
            return (EvidenceSourceType.ROUTING_TABLE, record.source_router)
        return (record.source_type, record.source_router, record.source_interface)

    def primary_points(self, evidence_ids: list[str]) -> set[tuple]:
        points = set()
        for evidence_id in evidence_ids:
            record = self.by_id[evidence_id]
            if record in self.unavailable.get(record.source_router, []) or isinstance(
                record, (InterfaceObservation, OSPFObservation, PingMeasurement)
            ):
                points.add(self.point_key(record))
        return points

    def coverage(self) -> float:
        """Usable points / represented collection attempts, including explicit gaps.

        The contracts contain no collection plan; omitted attempts cannot be
        measured. Passive logs and traces are context, not primary polling points.
        """
        planned: set[tuple] = set()
        usable: set[tuple] = set()
        recognized = {r.evidence_id for rows in self.interfaces.values() for r in rows} | {
            r.evidence_id for rows in self.adjacencies.values() for r in rows
        }
        recognized |= {r.evidence_id for r in self.pings + self.routes}
        for record in self.records:
            if record.source_type not in {
                EvidenceSourceType.INTERFACE_POLL,
                EvidenceSourceType.OSPF_API,
                EvidenceSourceType.ACTIVE_PING,
                EvidenceSourceType.ROUTING_TABLE,
            }:
                continue
            # Loopbacks are excluded from data-link diagnosis coverage.
            if (
                record.source_type == EvidenceSourceType.INTERFACE_POLL
                and (record.source_router, record.source_interface) not in self.interface_link
            ):
                continue
            key = self.point_key(record)
            planned.add(key)
            if record.evidence_id in recognized:
                usable.add(key)
        return round(100 * len(usable) / len(planned), 2) if planned else 0.0
