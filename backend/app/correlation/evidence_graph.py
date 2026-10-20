"""
NEXORA Evidence Dependency Graph — Phase 05.

Represents relationships between evidence records and the network components
they describe. Connects:

  Evidence Records ↔ Routers ↔ Interfaces ↔ Links ↔ OSPF Adjacencies ↔ Prefixes

Relationships are directional and typed. Each relationship includes:
  - Relationship type (e.g. DESCRIBES_INTERFACE, IMPLIES_LINK_CHANGE)
  - Supporting evidence IDs
  - Relevant component identifier
  - Plain-English explanation
  - Timestamp context (where available)

DESIGN CONSTRAINTS:
  - No circular conclusions: relationships represent "may be related to",
    never "was caused by".
  - No fabricated evidence: all relationships derive from actual records.
  - Evidence linking is deterministic and reproducible.
  - Ground-truth labels are never stored in relationship metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from app.schemas.evidence import (
    EvidenceRecord,
    InterfaceObservation,
    ObservationStatus,
    OSPFObservation,
    PingMeasurement,
    RouteObservation,
    SyslogEvent,
    TracerouteObservation,
)
from app.topology.identity import (
    LOOPBACK_IP_TO_ROUTER,
    resolve_link_from_router_pair,
    resolve_router_from_any_address,
    resolve_router_from_ospf_id,
)

# Module-level constant: (router_id, iface_name) → link_id
# Used in _link_interface_to_link to avoid N806 lint violation.
_EG_INTERFACE_TO_LINK: dict[tuple[str, str], str] = {
    ("R1", "eth1"): "L12",
    ("R1", "eth2"): "L51",
    ("R2", "eth1"): "L12",
    ("R2", "eth2"): "L23",
    ("R3", "eth1"): "L23",
    ("R3", "eth2"): "L34",
    ("R4", "eth1"): "L34",
    ("R4", "eth2"): "L45",
    ("R5", "eth1"): "L45",
    ("R5", "eth2"): "L51",
}

# ---------------------------------------------------------------------------
# Relationship types
# ---------------------------------------------------------------------------


class RelationshipType(str, Enum):
    """Types of relationships between evidence and network components."""

    # Evidence → Component relationships
    DESCRIBES_ROUTER = "DESCRIBES_ROUTER"
    DESCRIBES_INTERFACE = "DESCRIBES_INTERFACE"
    DESCRIBES_LINK = "DESCRIBES_LINK"
    DESCRIBES_ADJACENCY = "DESCRIBES_ADJACENCY"
    DESCRIBES_PREFIX = "DESCRIBES_PREFIX"

    # Evidence → Evidence relationships (temporal / causal chain)
    TEMPORALLY_RELATED = "TEMPORALLY_RELATED"
    TOPOLOGICALLY_RELATED = "TOPOLOGICALLY_RELATED"

    # Cross-component dependency
    INTERFACE_UNDERLIES_ADJACENCY = "INTERFACE_UNDERLIES_ADJACENCY"
    ADJACENCY_ENABLES_ROUTE = "ADJACENCY_ENABLES_ROUTE"
    LINK_UNDERLIES_ADJACENCY = "LINK_UNDERLIES_ADJACENCY"

    # Observation patterns
    CORROBORATES = "CORROBORATES"
    CONTRADICTS = "CONTRADICTS"
    MISSING_EXPECTED = "MISSING_EXPECTED"


# ---------------------------------------------------------------------------
# Relationship data class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRelationship:
    """
    A single directed relationship between an evidence record and a component
    (or another record).

    Immutable to ensure the dependency graph is not modified after construction.
    """

    from_id: str
    """Source evidence ID or component ID."""

    to_id: str
    """Target evidence ID or component ID."""

    relationship_type: RelationshipType
    """Semantic type of this relationship."""

    supporting_evidence_ids: tuple[str, ...]
    """Evidence IDs that support this relationship."""

    component_id: str
    """The network component this relationship involves (router/link/interface)."""

    explanation: str
    """Plain-English explanation of why this relationship exists."""

    observed_at: datetime | None = None
    """Timestamp from the triggering evidence record, if available."""

    def __hash__(self) -> int:
        return hash((self.from_id, self.to_id, self.relationship_type))


# ---------------------------------------------------------------------------
# Evidence graph
# ---------------------------------------------------------------------------


class EvidenceGraph:
    """
    A graph linking evidence records to network components and to each other.

    Nodes represent:
      - Evidence records (keyed by evidence_id)
      - Routers (keyed by router_id, e.g. 'R1')
      - Links (keyed by link_id, e.g. 'L12')
      - OSPF adjacency pairs (keyed by 'adj:R1→R2')
      - Destination prefixes (keyed by 'prefix:192.168.255.3/32')

    Edges represent EvidenceRelationship instances.

    This graph is built once per evidence snapshot and used by the correlation
    engine. It is not modified after construction.

    The graph does NOT establish causation — only that observations may be
    related to the same network component or fall within the same topology area.
    """

    def __init__(self) -> None:
        # node_id → node_type label and metadata
        self._nodes: dict[str, dict[str, Any]] = {}
        # (from_id, to_id, rel_type) → EvidenceRelationship
        self._edges: dict[tuple[str, str, str], EvidenceRelationship] = {}
        # evidence_id → original record (for field access)
        self._records: dict[str, EvidenceRecord] = {}

    # ------------------------------------------------------------------
    # Building the graph
    # ------------------------------------------------------------------

    def add_record(self, record: EvidenceRecord) -> None:
        """Register an evidence record and create component relationships."""
        eid = record.evidence_id
        self._records[eid] = record
        self._nodes[eid] = {
            "node_type": "evidence",
            "source_type": record.source_type.value,
            "source_router": record.source_router,
            "event_type": record.event_type,
            "collection_status": record.collection_status.value,
        }

        # Ensure source router node exists
        router_id = record.source_router
        self._ensure_router_node(router_id)

        # Router relationship
        self._add_edge(EvidenceRelationship(
            from_id=eid,
            to_id=router_id,
            relationship_type=RelationshipType.DESCRIBES_ROUTER,
            supporting_evidence_ids=(eid,),
            component_id=router_id,
            explanation=f"Evidence collected from or about router {router_id}.",
            observed_at=record.observed_at,
        ))

        # Type-specific relationships
        if isinstance(record, InterfaceObservation):
            self._link_interface_observation(record)
        elif isinstance(record, OSPFObservation):
            self._link_ospf_observation(record)
        elif isinstance(record, RouteObservation):
            self._link_route_observation(record)
        elif isinstance(record, PingMeasurement):
            self._link_ping_observation(record)
        elif isinstance(record, TracerouteObservation):
            self._link_traceroute_observation(record)
        elif isinstance(record, SyslogEvent):
            self._link_syslog_observation(record)

    def add_records(self, records: list[EvidenceRecord]) -> None:
        """Add multiple records and then compute cross-record relationships."""
        for rec in records:
            self.add_record(rec)
        self._compute_cross_record_relationships(records)

    # ------------------------------------------------------------------
    # Type-specific record linkers
    # ------------------------------------------------------------------

    def _link_interface_observation(self, rec: InterfaceObservation) -> None:
        """Create relationships for an InterfaceObservation record."""
        eid = rec.evidence_id
        router_id = rec.source_router
        iface_name = rec.source_interface

        if iface_name:
            iface_node_id = f"iface:{router_id}:{iface_name}"
            self._ensure_interface_node(router_id, iface_name)
            self._add_edge(EvidenceRelationship(
                from_id=eid,
                to_id=iface_node_id,
                relationship_type=RelationshipType.DESCRIBES_INTERFACE,
                supporting_evidence_ids=(eid,),
                component_id=iface_node_id,
                explanation=(
                    f"Interface observation reports operational status of "
                    f"{router_id}/{iface_name}: '{rec.observed_status}'."
                ),
                observed_at=rec.observed_at,
            ))

            # If interface is DOWN, it potentially affects an adjacent link
            if rec.observed_status in ("down", "admin-down", "DOWN", "ADMIN_DOWN"):
                self._link_interface_to_link(eid, router_id, iface_name, rec.observed_at)

    def _link_ospf_observation(self, rec: OSPFObservation) -> None:
        """Create relationships for an OSPFObservation record."""
        eid = rec.evidence_id
        router_id = rec.source_router
        nbr_ospf_id = rec.neighbour_router_id
        nbr_addr = rec.neighbour_address

        # Resolve neighbour router identity
        nbr_router_id = resolve_router_from_ospf_id(nbr_ospf_id)
        if nbr_router_id is None:
            nbr_router_id = resolve_router_from_any_address(nbr_addr or "")

        adj_node_id = f"adj:{router_id}→{nbr_router_id or nbr_ospf_id}"
        self._nodes[adj_node_id] = {
            "node_type": "ospf_adjacency",
            "local_router": router_id,
            "neighbour_router": nbr_router_id or nbr_ospf_id,
            "neighbour_ospf_id": nbr_ospf_id,
        }

        self._add_edge(EvidenceRelationship(
            from_id=eid,
            to_id=adj_node_id,
            relationship_type=RelationshipType.DESCRIBES_ADJACENCY,
            supporting_evidence_ids=(eid,),
            component_id=adj_node_id,
            explanation=(
                f"OSPF observation from {router_id} reports adjacency "
                f"to {nbr_ospf_id} (router {nbr_router_id or 'unknown'}) "
                f"in state '{rec.adjacency_state}'."
            ),
            observed_at=rec.observed_at,
        ))

        # If adjacency is down/missing, relate to the underlying link
        state_lower = (rec.adjacency_state or "").lower()
        if state_lower in ("down", "init", "attempt", "unknown") or (
            rec.collection_status == ObservationStatus.OBSERVED
            and state_lower not in ("full", "2way")
        ):
            if nbr_router_id:
                link_id = resolve_link_from_router_pair(router_id, nbr_router_id)
                if link_id:
                    self._ensure_link_node(link_id)
                    self._add_edge(EvidenceRelationship(
                        from_id=adj_node_id,
                        to_id=link_id,
                        relationship_type=RelationshipType.LINK_UNDERLIES_ADJACENCY,
                        supporting_evidence_ids=(eid,),
                        component_id=link_id,
                        explanation=(
                            f"OSPF adjacency {router_id}→{nbr_router_id} is "
                            f"'{rec.adjacency_state}'. Physical link {link_id} "
                            f"underlies this adjacency."
                        ),
                        observed_at=rec.observed_at,
                    ))

    def _link_route_observation(self, rec: RouteObservation) -> None:
        """Create relationships for a RouteObservation record."""
        eid = rec.evidence_id
        router_id = rec.source_router
        prefix = rec.destination_prefix

        prefix_node_id = f"prefix:{prefix}"
        if prefix_node_id not in self._nodes:
            self._nodes[prefix_node_id] = {
                "node_type": "prefix",
                "prefix": prefix,
                "owning_router": None,
            }
            # Try to identify which router owns this prefix
            owner = _resolve_prefix_owner(prefix)
            if owner:
                self._nodes[prefix_node_id]["owning_router"] = owner

        self._add_edge(EvidenceRelationship(
            from_id=eid,
            to_id=prefix_node_id,
            relationship_type=RelationshipType.DESCRIBES_PREFIX,
            supporting_evidence_ids=(eid,),
            component_id=prefix_node_id,
            explanation=(
                f"Route observation from {router_id}: prefix {prefix} is_present={rec.is_present}, "
                f"next_hop={rec.next_hop_address}, via {rec.next_hop_interface}."
            ),
            observed_at=rec.observed_at,
        ))

    def _link_ping_observation(self, rec: PingMeasurement) -> None:
        """Create relationships for a PingMeasurement record."""
        eid = rec.evidence_id
        target = rec.target_address
        src_router = rec.probe_source

        target_router = resolve_router_from_any_address(target)
        if target_router:
            self._ensure_router_node(target_router)
            self._add_edge(EvidenceRelationship(
                from_id=eid,
                to_id=target_router,
                relationship_type=RelationshipType.DESCRIBES_ROUTER,
                supporting_evidence_ids=(eid,),
                component_id=target_router,
                explanation=(
                    f"Ping probe from {src_router} to {target} (router {target_router}): "
                    f"loss={rec.packet_loss_pct}%, avg_rtt={rec.rtt_avg_ms}ms."
                ),
                observed_at=rec.observed_at,
            ))

    def _link_traceroute_observation(self, rec: TracerouteObservation) -> None:
        """Create relationships for a TracerouteObservation record."""
        eid = rec.evidence_id
        target = rec.target_address
        target_router = resolve_router_from_any_address(target)
        if target_router:
            self._ensure_router_node(target_router)
            self._add_edge(EvidenceRelationship(
                from_id=eid,
                to_id=target_router,
                relationship_type=RelationshipType.DESCRIBES_ROUTER,
                supporting_evidence_ids=(eid,),
                component_id=target_router,
                explanation=(
                    f"Traceroute from {rec.probe_source} to {target} (router {target_router}): "
                    f"reached={rec.destination_reached}, hops={rec.total_hops}."
                ),
                observed_at=rec.observed_at,
            ))

    def _link_syslog_observation(self, rec: SyslogEvent) -> None:
        """Create relationships for a SyslogEvent record."""
        eid = rec.evidence_id
        # Syslog events are already linked to source router via add_record()
        # Add daemon process context
        self._nodes[eid]["process_name"] = rec.process_name
        self._nodes[eid]["severity"] = rec.severity.value

    def _link_interface_to_link(
        self,
        eid: str,
        router_id: str,
        iface_name: str,
        observed_at: datetime | None,
    ) -> None:
        """If an interface is down, relate it to the link that it carries."""
        link_id = _EG_INTERFACE_TO_LINK.get((router_id, iface_name))
        if link_id:
            self._ensure_link_node(link_id)
            iface_node_id = f"iface:{router_id}:{iface_name}"
            self._add_edge(EvidenceRelationship(
                from_id=iface_node_id,
                to_id=link_id,
                relationship_type=RelationshipType.INTERFACE_UNDERLIES_ADJACENCY,
                supporting_evidence_ids=(eid,),
                component_id=link_id,
                explanation=(
                    f"Interface {router_id}/{iface_name} is DOWN; "
                    f"this interface carries link {link_id}."
                ),
                observed_at=observed_at,
            ))

    def _compute_cross_record_relationships(self, records: list[EvidenceRecord]) -> None:
        """
        After all records are added, compute relationships between records
        that share a common topology component.

        Only creates TOPOLOGICALLY_RELATED edges between evidence pairs that:
        - Share the same router OR
        - Are linked through a common component (link, interface, adjacency)
        Does not create edges between every pair (avoids O(n²) explosion).
        """
        # Group by router
        by_router: dict[str, list[str]] = {}
        for eid, rec in self._records.items():
            by_router.setdefault(rec.source_router, []).append(eid)

        # For each router, connect pairs of records that share an interface
        for router_id, eids in by_router.items():
            # Group by interface
            by_iface: dict[str | None, list[str]] = {}
            for eid in eids:
                rec = self._records[eid]
                by_iface.setdefault(rec.source_interface, []).append(eid)

            for iface, iface_eids in by_iface.items():
                if iface is None or len(iface_eids) < 2:
                    continue
                # Connect consecutive pairs sharing the same interface
                for i in range(len(iface_eids) - 1):
                    eid_a = iface_eids[i]
                    eid_b = iface_eids[i + 1]
                    rec_a = self._records[eid_a]
                    rec_b = self._records[eid_b]
                    if rec_a.source_type != rec_b.source_type:
                        # Different evidence types sharing same interface
                        self._add_edge(EvidenceRelationship(
                            from_id=eid_a,
                            to_id=eid_b,
                            relationship_type=RelationshipType.TOPOLOGICALLY_RELATED,
                            supporting_evidence_ids=(eid_a, eid_b),
                            component_id=f"iface:{router_id}:{iface}",
                            explanation=(
                                f"Records {eid_a} and {eid_b} both describe "
                                f"{router_id}/{iface} from different source types."
                            ),
                        ))

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def _ensure_router_node(self, router_id: str) -> None:
        if router_id not in self._nodes:
            self._nodes[router_id] = {"node_type": "router", "router_id": router_id}

    def _ensure_interface_node(self, router_id: str, iface_name: str) -> None:
        node_id = f"iface:{router_id}:{iface_name}"
        if node_id not in self._nodes:
            self._nodes[node_id] = {
                "node_type": "interface",
                "router_id": router_id,
                "interface_name": iface_name,
            }

    def _ensure_link_node(self, link_id: str) -> None:
        if link_id not in self._nodes:
            self._nodes[link_id] = {"node_type": "link", "link_id": link_id}

    def _add_edge(self, rel: EvidenceRelationship) -> None:
        key = (rel.from_id, rel.to_id, rel.relationship_type.value)
        self._edges[key] = rel

    # ------------------------------------------------------------------
    # Graph query API
    # ------------------------------------------------------------------

    def get_evidence_for_component(self, component_id: str) -> list[str]:
        """
        Return evidence IDs that have a relationship with component_id.

        Parameters
        ----------
        component_id : str
            Router ID, link ID, interface node ID, etc.

        Returns
        -------
        list[str]
            Sorted evidence IDs.
        """
        eids: set[str] = set()
        for (from_id, to_id, _), rel in self._edges.items():
            if to_id == component_id and from_id in self._records:
                eids.add(from_id)
            if from_id == component_id:
                eids.update(
                    eid for eid in rel.supporting_evidence_ids if eid in self._records
                )
        return sorted(eids)

    def get_relationships_from(self, node_id: str) -> list[EvidenceRelationship]:
        """Return all outbound relationships from node_id."""
        return [
            rel for (from_id, _, _), rel in self._edges.items()
            if from_id == node_id
        ]

    def get_relationships_to(self, node_id: str) -> list[EvidenceRelationship]:
        """Return all inbound relationships to node_id."""
        return [
            rel for (_, to_id, _), rel in self._edges.items()
            if to_id == node_id
        ]

    def get_all_relationships(self) -> list[EvidenceRelationship]:
        """Return all relationships in the graph."""
        return list(self._edges.values())

    def get_component_ids(self, node_type: str | None = None) -> list[str]:
        """
        Return node IDs, optionally filtered by node_type.

        Parameters
        ----------
        node_type : str | None
            One of 'router', 'link', 'interface', 'ospf_adjacency', 'prefix',
            'evidence', or None for all.
        """
        if node_type is None:
            return sorted(self._nodes.keys())
        return sorted(
            nid for nid, attrs in self._nodes.items()
            if attrs.get("node_type") == node_type
        )

    def get_record(self, evidence_id: str) -> EvidenceRecord | None:
        """Retrieve the original evidence record by ID."""
        return self._records.get(evidence_id)

    def all_evidence_ids(self) -> list[str]:
        """Return sorted list of all evidence record IDs in the graph."""
        return sorted(self._records.keys())

    def summary(self) -> dict[str, Any]:
        """Return a summary dict of graph statistics."""
        by_type: dict[str, int] = {}
        for attrs in self._nodes.values():
            nt = attrs.get("node_type", "unknown")
            by_type[nt] = by_type.get(nt, 0) + 1

        return {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "total_evidence_records": len(self._records),
            "nodes_by_type": by_type,
        }


# ---------------------------------------------------------------------------
# Helper: prefix owner lookup (not topology_graph import to avoid circular)
# ---------------------------------------------------------------------------

_LOOPBACK_PREFIX_TO_ROUTER: dict[str, str] = {
    "192.168.255.1/32": "R1",
    "192.168.255.2/32": "R2",
    "192.168.255.3/32": "R3",
    "192.168.255.4/32": "R4",
    "192.168.255.5/32": "R5",
}


def _resolve_prefix_owner(prefix: str) -> str | None:
    """Identify which router owns a given prefix."""
    return _LOOPBACK_PREFIX_TO_ROUTER.get(prefix) or LOOPBACK_IP_TO_ROUTER.get(
        prefix.split("/")[0]
    )
