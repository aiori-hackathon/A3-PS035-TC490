"""
NEXORA Incident Correlation Engine — Phase 05.

Deterministic engine that transforms normalized evidence snapshots into
coherent, auditable CorrelatedIncident groups.

Pipeline:
  1. Verify ground-truth isolation (no injected labels in input)
  2. Deserialize evidence records to typed subclasses (restores subclass fields)
  3. Deduplicate and temporally group evidence
  4. Classify symptoms per record / component
  5. Build evidence dependency graph (component ↔ evidence linkage)
  6. Group symptoms into incidents using:
     a. Topological proximity (shared router, shared link, adjacent OSPF pairs)
     b. Temporal proximity (within configured window)
  7. Document contradictory observations and missing evidence
  8. Produce CorrelationResult with one or more CorrelatedIncident groups

DESIGN INVARIANTS:
  - Each run on the same inputs produces equivalent results (deterministic).
  - Evidence is never fabricated. If a record is missing, it is noted explicitly.
  - Correlation groups observations; it does NOT rank fault hypotheses.
  - No ground-truth labels, scenario names, or injection parameters are used.
  - Multiple independent incident groups are supported.
  - UNKNOWN observations are never inferred as DOWN.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from app.collectors.normalizer import (
    GROUND_TRUTH_FORBIDDEN_TOKENS,
    EvidenceNormalizer,
    GroundTruthLeakageError,
)
from app.correlation.evidence_graph import EvidenceGraph
from app.correlation.temporal import DEFAULT_WINDOW_SECONDS, TemporalCorrelator
from app.schemas.correlation import (
    CORRELATION_ENGINE_VERSION,
    LATENCY_ELEVATED_THRESHOLD_MS,
    PACKET_LOSS_THRESHOLD_PCT,
    SYSLOG_WARNING_SEVERITIES,
    CorrelatedIncident,
    CorrelatedSymptom,
    CorrelationRelationship,
    CorrelationResult,
    SymptomCategory,
)
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
from app.schemas.topology import RouterStatus, Topology
from app.topology.graph import TopologyGraph, build_observed_topology_graph
from app.topology.identity import (
    resolve_link_from_router_pair,
    resolve_router_from_ospf_id,
)

logger = logging.getLogger("nexora.correlation.engine")

# Module-level constant: interface → link mapping for the NEXORA lab
_INTERFACE_TO_LINK_MAP: dict[tuple[str, str], str] = {
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
# Correlation engine
# ---------------------------------------------------------------------------


class CorrelationEngine:
    """
    Deterministic topology-aware incident correlation engine.

    Usage
    -----
    engine = CorrelationEngine()
    result = engine.correlate(snapshot_dict)

    Or with pre-deserialized records and topology:
    result = engine.correlate_records(records, topology, snapshot_id)
    """

    def __init__(
        self,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        packet_loss_threshold: float = PACKET_LOSS_THRESHOLD_PCT,
        latency_threshold_ms: float = LATENCY_ELEVATED_THRESHOLD_MS,
    ) -> None:
        self.window_seconds = window_seconds
        self.packet_loss_threshold = packet_loss_threshold
        self.latency_threshold_ms = latency_threshold_ms
        self._temporal = TemporalCorrelator(window_seconds=window_seconds)

    # ------------------------------------------------------------------
    # Main entry points
    # ------------------------------------------------------------------

    def correlate_snapshot_dict(self, snapshot_dict: dict[str, Any]) -> CorrelationResult:
        """
        Correlate evidence from a raw EvidenceSnapshot dict.

        This is the primary entry point when loading snapshots from JSON files.
        It handles the serialization polymorphism issue (typed subclass reconstruction).

        Parameters
        ----------
        snapshot_dict : dict[str, Any]
            The JSON-deserialized EvidenceSnapshot dict.

        Returns
        -------
        CorrelationResult
        """
        snapshot_id = snapshot_dict.get("snapshot_id", "unknown-snapshot")

        # Ground-truth leakage check on the entire snapshot
        self._verify_no_ground_truth_leakage(snapshot_dict, snapshot_id)

        # Reconstruct typed evidence records (restores subclass fields)
        raw_records_data: list[dict] = snapshot_dict.get("evidence_records", [])
        records: list[EvidenceRecord] = []
        for rec_dict in raw_records_data:
            try:
                typed_rec = EvidenceNormalizer.deserialize_record(rec_dict)
                records.append(typed_rec)
            except Exception as exc:
                logger.warning(
                    "Failed to deserialize evidence record: %s. Error: %s",
                    rec_dict.get("evidence_id", "?"),
                    exc,
                )

        # Reconstruct topology
        from app.schemas.topology import Topology as TopologySchema
        topology_dict = snapshot_dict.get("topology", {})
        try:
            topology = TopologySchema.model_validate(topology_dict)
        except Exception as exc:
            logger.error("Failed to parse topology from snapshot: %s", exc)
            # Create a minimal fallback topology
            from app.collectors.topology_collector import TopologyCollector
            from app.collectors.transport import MockTransport
            mock = MockTransport()
            collector = TopologyCollector(mock)
            topology = collector.get_expected_topology(snapshot_id=f"fallback-{snapshot_id}")

        return self.correlate_records(records, topology, snapshot_id)

    def correlate_records(
        self,
        records: list[EvidenceRecord],
        topology: Topology,
        snapshot_id: str = "unknown",
    ) -> CorrelationResult:
        """
        Correlate a list of typed evidence records with topology context.

        Parameters
        ----------
        records : list[EvidenceRecord]
            Typed (deserialized) evidence records.
        topology : Topology
            The observed or expected topology snapshot.
        snapshot_id : str
            Identifier of the source evidence snapshot.

        Returns
        -------
        CorrelationResult
        """
        self._verify_no_ground_truth_leakage({
            "snapshot_id": snapshot_id,
            "topology": topology.model_dump(mode="json"),
            "evidence_records": [rec.model_dump(mode="json") for rec in records],
        }, snapshot_id)
        result_id = f"cr-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
        produced_at = datetime.now(UTC)
        notes: list[str] = []

        if not records:
            return CorrelationResult(
                result_id=result_id,
                snapshot_id=snapshot_id,
                produced_at=produced_at,
                incidents=[],
                total_evidence_records=0,
                anomalous_record_count=0,
                duplicate_records_removed=0,
                ground_truth_isolation_verified=True,
                correlation_notes=["Empty evidence snapshot — no records to correlate."],
            )

        # 1. Build topology graph
        topo_graph = build_observed_topology_graph(topology)

        # 2. Deduplicate records
        deduped_records, dup_count = self._temporal.deduplicate(records)
        if dup_count > 0:
            notes.append(
                f"Removed {dup_count} logically duplicate records before correlation."
            )

        # 3. Classify symptoms per record
        symptoms_by_component: dict[str, list[CorrelatedSymptom]] = defaultdict(list)
        all_symptoms: list[CorrelatedSymptom] = []
        anomalous_count = 0
        symptom_counter = [0]

        def next_sym_id() -> str:
            symptom_counter[0] += 1
            return f"sym-{symptom_counter[0]:04d}"

        for rec in deduped_records:
            classified = self._classify_record(rec, next_sym_id)
            for sym in classified:
                all_symptoms.append(sym)
                if sym.category != SymptomCategory.HEALTHY:
                    symptoms_by_component[sym.affected_component].append(sym)
                    anomalous_count += 1

        # 4. Build evidence graph
        ev_graph = EvidenceGraph()
        ev_graph.add_records(deduped_records)

        # 5. Temporal grouping
        temporal_groups = self._temporal.group_by_window(deduped_records)
        if len(temporal_groups) > 1:
            notes.append(
                f"Records span {len(temporal_groups)} distinct temporal groups. "
                f"Treating as potentially independent incidents."
            )

        # 6. Incident grouping
        incidents: list[CorrelatedIncident] = []
        incident_counter = [0]
        produced_date = produced_at.strftime("%Y%m%d")

        def next_incident_id() -> str:
            incident_counter[0] += 1
            return f"ci-{produced_date}-{incident_counter[0]:03d}"

        if anomalous_count == 0:
            # No anomalies — report a HEALTHY result
            incidents.append(self._build_healthy_incident(
                next_incident_id(),
                temporal_groups,
                deduped_records,
                produced_at,
                {eid for sym in all_symptoms for eid in sym.supporting_evidence_ids},
            ))
        else:
            # Group symptoms into incidents using topology + temporal context
            incident_groups = self._group_symptoms_into_incidents(
                all_symptoms=[s for s in all_symptoms if s.category != SymptomCategory.HEALTHY],
                deduped_records=deduped_records,
                topo_graph=topo_graph,
                ev_graph=ev_graph,
                temporal_groups=temporal_groups,
            )
            for group_symptoms, group_records in incident_groups:
                incident = self._build_incident(
                    next_incident_id(),
                    group_symptoms,
                    group_records,
                    topo_graph,
                    ev_graph,
                )
                incidents.append(incident)

        return CorrelationResult(
            result_id=result_id,
            snapshot_id=snapshot_id,
            produced_at=produced_at,
            engine_version=CORRELATION_ENGINE_VERSION,
            incidents=incidents,
            total_evidence_records=len(records),
            anomalous_record_count=anomalous_count,
            duplicate_records_removed=dup_count,
            ground_truth_isolation_verified=True,
            correlation_notes=notes,
        )

    # ------------------------------------------------------------------
    # Symptom classification
    # ------------------------------------------------------------------

    def _classify_record(
        self,
        record: EvidenceRecord,
        next_sym_id: Any,
    ) -> list[CorrelatedSymptom]:
        """Classify an evidence record into zero or more symptoms."""
        symptoms: list[CorrelatedSymptom] = []

        if record.collection_status != ObservationStatus.OBSERVED:
            # Unavailable evidence is missing information, never observed component state.
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=SymptomCategory.COLLECTION_FAILURE,
                affected_component=record.source_router,
                description=(
                    f"Evidence unavailable for {record.source_router} "
                    f"({record.event_type}, {record.collection_status.value}). "
                    f"Component state is UNKNOWN, not necessarily DOWN."
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=False,
                observed_at=record.observed_at,
            ))
            return symptoms

        if isinstance(record, InterfaceObservation):
            symptoms.extend(self._classify_interface(record, next_sym_id))
        elif isinstance(record, OSPFObservation):
            symptoms.extend(self._classify_ospf(record, next_sym_id))
        elif isinstance(record, RouteObservation):
            symptoms.extend(self._classify_route(record, next_sym_id))
        elif isinstance(record, PingMeasurement):
            symptoms.extend(self._classify_ping(record, next_sym_id))
        elif isinstance(record, SyslogEvent):
            symptoms.extend(self._classify_syslog(record, next_sym_id))
        elif isinstance(record, TracerouteObservation):
            symptoms.extend(self._classify_traceroute(record, next_sym_id))
        else:
            # Base record: check event_type for unreachability
            if "unreachable" in record.event_type.lower() or (
                "unavailable" in record.event_type.lower()
            ):
                symptoms.append(CorrelatedSymptom(
                    symptom_id=next_sym_id(),
                    category=SymptomCategory.ROUTER_UNREACHABLE,
                    affected_component=record.source_router,
                    description=(
                        f"Router {record.source_router} reported as unavailable "
                        f"(event_type={record.event_type})."
                    ),
                    supporting_evidence_ids=[record.evidence_id],
                    is_direct_observation=True,
                    observed_at=record.observed_at,
                ))

        return symptoms

    def _classify_interface(
        self, record: InterfaceObservation, next_sym_id: Any
    ) -> list[CorrelatedSymptom]:
        symptoms: list[CorrelatedSymptom] = []
        iface_name = record.source_interface or "unknown"
        component = (
            f"iface:{record.source_router}:{iface_name}"
            if iface_name != "unknown"
            else record.source_router
        )
        status_lower = record.observed_status.lower().replace("_", "-")

        if status_lower in ("down", "admin-down"):
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=SymptomCategory.INTERFACE_DOWN,
                affected_component=component,
                description=(
                    f"Interface {record.source_router}/{iface_name} is "
                    f"'{record.observed_status}' (directly observed)."
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=True,
                observed_at=record.observed_at,
            ))
        elif status_lower == "up":
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=SymptomCategory.HEALTHY,
                affected_component=component,
                description=(
                    f"Interface {record.source_router}/{iface_name} is '{record.observed_status}'."
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=True,
                observed_at=record.observed_at,
            ))
        return symptoms

    def _classify_ospf(
        self, record: OSPFObservation, next_sym_id: Any
    ) -> list[CorrelatedSymptom]:
        symptoms: list[CorrelatedSymptom] = []
        state_lower = (record.adjacency_state or "unknown").split("/", 1)[0].strip().lower()
        nbr_ospf_id = record.neighbour_router_id
        nbr_router = resolve_router_from_ospf_id(nbr_ospf_id) or nbr_ospf_id
        adj_component = f"adj:{record.source_router}→{nbr_router}"

        if state_lower == "full":
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=SymptomCategory.HEALTHY,
                affected_component=adj_component,
                description=(
                    f"OSPF adjacency {record.source_router}→{nbr_router} is FULL."
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=True,
                observed_at=record.observed_at,
            ))
        elif state_lower == "down":
            # Check if it is a missing neighbour (explicitly absent)
            is_missing = record.collection_status == ObservationStatus.OBSERVED
            category = (
                SymptomCategory.OSPF_ADJACENCY_LOST
                if is_missing
                else SymptomCategory.COLLECTION_FAILURE
            )
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=category,
                affected_component=adj_component,
                description=(
                    f"OSPF adjacency {record.source_router}→{nbr_router} "
                    f"(OSPF-ID {nbr_ospf_id}) is {state_lower}. "
                    f"Expected state: FULL."
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=True,
                observed_at=record.observed_at,
            ))
        elif state_lower in ("init", "attempt", "2way", "exstart", "exchange", "loading"):
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=SymptomCategory.OSPF_ADJACENCY_DEGRADED,
                affected_component=adj_component,
                description=(
                    f"OSPF adjacency {record.source_router}→{nbr_router} "
                    f"is in state '{record.adjacency_state}' (not FULL, not DOWN). "
                    f"May be converging."
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=True,
                observed_at=record.observed_at,
            ))

        return symptoms

    def _classify_route(
        self, record: RouteObservation, next_sym_id: Any
    ) -> list[CorrelatedSymptom]:
        symptoms: list[CorrelatedSymptom] = []
        prefix = record.destination_prefix

        if not record.is_present:
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=SymptomCategory.ROUTE_MISSING,
                affected_component=f"prefix:{prefix}",
                description=(
                    f"Expected route {prefix} is absent from "
                    f"{record.source_router}'s routing table."
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=False,  # Absence is inferred, not directly seen
                observed_at=record.observed_at,
            ))
        else:
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=SymptomCategory.HEALTHY,
                affected_component=f"prefix:{prefix}",
                description=(
                    f"Route {prefix} is present in {record.source_router}'s RIB "
                    f"via {record.next_hop_address} ({record.next_hop_interface})."
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=True,
                observed_at=record.observed_at,
            ))
        return symptoms

    def _classify_ping(
        self, record: PingMeasurement, next_sym_id: Any
    ) -> list[CorrelatedSymptom]:
        symptoms: list[CorrelatedSymptom] = []
        target = record.target_address
        loss = record.packet_loss_pct
        avg_rtt = record.rtt_avg_ms
        component = f"ping:{record.probe_source}→{target}"

        if loss >= self.packet_loss_threshold:
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=SymptomCategory.PACKET_LOSS_ELEVATED,
                affected_component=component,
                description=(
                    f"Ping from {record.probe_source} to {target}: "
                    f"{loss:.1f}% packet loss "
                    f"(threshold: {self.packet_loss_threshold:.1f}%). "
                    f"Sent={record.packets_sent}, Received={record.packets_received}."
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=True,
                observed_at=record.observed_at,
                measurement_value=loss,
                threshold_used=self.packet_loss_threshold,
            ))
        elif avg_rtt is not None and avg_rtt >= self.latency_threshold_ms:
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=SymptomCategory.LATENCY_ELEVATED,
                affected_component=component,
                description=(
                    f"Ping from {record.probe_source} to {target}: "
                    f"avg RTT={avg_rtt:.2f}ms "
                    f"(threshold: {self.latency_threshold_ms:.1f}ms). "
                    f"Packet loss: {loss:.1f}%."
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=True,
                observed_at=record.observed_at,
                measurement_value=avg_rtt,
                threshold_used=self.latency_threshold_ms,
            ))
        else:
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=SymptomCategory.HEALTHY,
                affected_component=component,
                description=(
                    f"Ping from {record.probe_source} to {target}: "
                    f"{loss:.1f}% loss, avg RTT={avg_rtt:.2f}ms."
                    if avg_rtt is not None
                    else f"Ping from {record.probe_source} to {target}: {loss:.1f}% loss."
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=True,
                observed_at=record.observed_at,
            ))
        return symptoms

    def _classify_syslog(
        self, record: SyslogEvent, next_sym_id: Any
    ) -> list[CorrelatedSymptom]:
        symptoms: list[CorrelatedSymptom] = []
        if record.severity.value in SYSLOG_WARNING_SEVERITIES:
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=SymptomCategory.LOG_WARNING,
                affected_component=record.source_router,
                description=(
                    f"Daemon log {record.severity.value} from {record.source_router} "
                    f"({record.process_name}): {record.raw_message[:120]!r}"
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=True,
                observed_at=record.observed_at,
            ))
        return symptoms

    def _classify_traceroute(
        self, record: TracerouteObservation, next_sym_id: Any
    ) -> list[CorrelatedSymptom]:
        symptoms: list[CorrelatedSymptom] = []
        if not record.destination_reached:
            symptoms.append(CorrelatedSymptom(
                symptom_id=next_sym_id(),
                category=SymptomCategory.ROUTER_UNREACHABLE,
                affected_component=f"ping:{record.probe_source}→{record.target_address}",
                description=(
                    f"Traceroute from {record.probe_source} to {record.target_address} "
                    f"did not reach destination ({record.total_hops} hops observed). "
                    f"Target may be unreachable."
                ),
                supporting_evidence_ids=[record.evidence_id],
                is_direct_observation=True,
                observed_at=record.observed_at,
            ))
        return symptoms

    # ------------------------------------------------------------------
    # Incident grouping
    # ------------------------------------------------------------------

    def _group_symptoms_into_incidents(
        self,
        all_symptoms: list[CorrelatedSymptom],
        deduped_records: list[EvidenceRecord],
        topo_graph: TopologyGraph,
        ev_graph: EvidenceGraph,
        temporal_groups: list,
    ) -> list[tuple[list[CorrelatedSymptom], list[EvidenceRecord]]]:
        """
        Group symptoms into incident clusters using topology + temporal proximity.

        Algorithm:
        1. Extract affected routers per symptom.
        2. Find which symptoms share a router or are connected via a single link hop.
        3. Apply temporal filter: only group symptoms that fall within the
           same temporal group OR whose windows overlap.
        4. Use union-find to cluster connected symptoms.
        5. Return list of (symptom_list, record_list) tuples.

        Never groups two completely unrelated symptoms (different routers,
        different links, no shared topology) simply because they are in the
        same collection run.
        """
        if not all_symptoms:
            return []

        # Build record lookup
        record_by_id: dict[str, EvidenceRecord] = {r.evidence_id: r for r in deduped_records}

        # Build symptom → affected component set
        def get_routers_for_symptom(sym: CorrelatedSymptom) -> set[str]:
            routers: set[str] = set()
            comp = sym.affected_component
            # Extract router from component string
            if ":" in comp:
                parts = comp.split(":")
                # adj:R1→R2, iface:R1:eth1, ping:R1→10.0.12.2, prefix:192.168.255.1/32
                if parts[0] in ("adj", "iface", "ping"):
                    # Router is first segment after type
                    router_part = parts[1]
                    if "→" in router_part:
                        for r in router_part.split("→"):
                            if r.startswith("R") and r in topo_graph._router_index:
                                routers.add(r)
                    elif router_part.startswith("R") and router_part in topo_graph._router_index:
                        routers.add(router_part)
            elif comp.startswith("R") and comp in topo_graph._router_index:
                routers.add(comp)

            # Also add source routers from supporting evidence
            for eid in sym.supporting_evidence_ids:
                rec = record_by_id.get(eid)
                if rec:
                    routers.add(rec.source_router)

            return routers

        # Union-Find structure
        parent: dict[int, int] = {i: i for i in range(len(all_symptoms))}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        # Check if two sets of routers are topology-adjacent
        def are_topology_related(routers_a: set[str], routers_b: set[str]) -> bool:
            for ra in routers_a:
                for rb in routers_b:
                    if ra == rb:
                        return True
                    # Check physical adjacency (directly connected)
                    if ra in topo_graph._router_index and rb in topo_graph._router_index:
                        if topo_graph.physical_graph.has_edge(ra, rb):
                            return True
            return False

        # Build temporal membership: evidence_id → temporal group index
        tg_by_evidence: dict[str, int] = {}
        for tg_idx, tg in enumerate(temporal_groups):
            for eid in tg.evidence_ids:
                tg_by_evidence[eid] = tg_idx

        def same_temporal_group(sym_a: CorrelatedSymptom, sym_b: CorrelatedSymptom) -> bool:
            eids_a = set(sym_a.supporting_evidence_ids)
            eids_b = set(sym_b.supporting_evidence_ids)
            groups_a = {tg_by_evidence.get(e, -1) for e in eids_a}
            groups_b = {tg_by_evidence.get(e, -1) for e in eids_b}
            # Related if they share a temporal group OR are within window of each other
            return bool(groups_a & groups_b - {-1})

        # Cluster symptoms
        routers_per_sym = [get_routers_for_symptom(sym) for sym in all_symptoms]

        for i in range(len(all_symptoms)):
            for j in range(i + 1, len(all_symptoms)):
                if are_topology_related(routers_per_sym[i], routers_per_sym[j]) and (
                    same_temporal_group(all_symptoms[i], all_symptoms[j])
                    or len(temporal_groups) == 1
                ):
                    union(i, j)

        # Collect clusters
        clusters: dict[int, list[int]] = defaultdict(list)
        for i in range(len(all_symptoms)):
            clusters[find(i)].append(i)

        # Build result groups
        result: list[tuple[list[CorrelatedSymptom], list[EvidenceRecord]]] = []
        for cluster_indices in clusters.values():
            cluster_symptoms = [all_symptoms[i] for i in cluster_indices]
            # Collect all evidence IDs referenced by these symptoms
            all_eids: set[str] = set()
            for sym in cluster_symptoms:
                all_eids.update(sym.supporting_evidence_ids)
            # Also include source-router evidence in the same temporal group
            cluster_routers: set[str] = set()
            for i in cluster_indices:
                cluster_routers.update(routers_per_sym[i])
            cluster_temporal_groups = {tg_by_evidence[eid] for eid in all_eids
                                       if eid in tg_by_evidence}
            cluster_records = [
                r for r in deduped_records
                if r.evidence_id in all_eids or (
                    r.source_router in cluster_routers
                    and tg_by_evidence.get(r.evidence_id) in cluster_temporal_groups
                )
            ]
            result.append((cluster_symptoms, cluster_records))

        return result

    # ------------------------------------------------------------------
    # Incident building
    # ------------------------------------------------------------------

    def _build_incident(
        self,
        incident_id: str,
        symptoms: list[CorrelatedSymptom],
        records: list[EvidenceRecord],
        topo_graph: TopologyGraph,
        ev_graph: EvidenceGraph,
    ) -> CorrelatedIncident:
        """Build a CorrelatedIncident from a cluster of symptoms and records."""
        # Determine window from records
        window = self._temporal.compute_window(records)

        # Collect affected routers and links
        affected_routers: list[str] = []
        affected_links: list[str] = []
        all_evidence_ids: list[str] = []

        for rec in records:
            if rec.source_router not in affected_routers:
                affected_routers.append(rec.source_router)
            if rec.evidence_id not in all_evidence_ids:
                all_evidence_ids.append(rec.evidence_id)

        # Infer affected links from symptom components
        for sym in symptoms:
            comp = sym.affected_component
            # adj:R1→R2 → implies link between R1 and R2
            if comp.startswith("adj:") and "→" in comp:
                parts = comp.replace("adj:", "").split("→")
                if len(parts) == 2:
                    r1, r2 = parts
                    link_id = resolve_link_from_router_pair(r1, r2)
                    if link_id and link_id not in affected_links:
                        affected_links.append(link_id)
            # iface:R1:eth1 → implies link carried by that interface
            elif comp.startswith("iface:"):
                parts = comp.split(":")
                if len(parts) == 3:
                    _router_id, iface_name = parts[1], parts[2]
                    link_id = _INTERFACE_TO_LINK_MAP.get((_router_id, iface_name))
                    if link_id and link_id not in affected_links:
                        affected_links.append(link_id)

        # Build relationships between symptoms
        relationships = self._build_relationships(symptoms, topo_graph, ev_graph)

        # Supporting and contradictory observations
        supporting_obs: list[str] = []
        contradictory_obs: list[str] = []
        missing_info: list[str] = []

        for sym in symptoms:
            if sym.category == SymptomCategory.HEALTHY:
                continue
            supporting_obs.append(f"{sym.category.value}: {sym.description}")

        # Contradictions require conflicting observations of the same fact. Interface
        # UP and OSPF DOWN concern different protocol layers and are compatible.
        states: dict[tuple[str, str, str], dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for rec in records:
            if rec.collection_status != ObservationStatus.OBSERVED:
                continue
            if isinstance(rec, InterfaceObservation):
                fact = ("interface", rec.source_router, rec.source_interface or "")
                state = rec.observed_status.lower().replace("_", "-")
                state = "down" if state == "admin-down" else state
                if state not in {"up", "down"}:
                    continue
            elif isinstance(rec, OSPFObservation):
                fact = ("OSPF adjacency", rec.source_router, rec.neighbour_router_id)
                state = rec.adjacency_state.split("/", 1)[0].strip().lower()
                if state not in {"full", "down"}:
                    continue
            else:
                continue
            states[fact][state].append(rec.evidence_id)
        for fact, observed_states in sorted(states.items()):
            if len(observed_states) > 1:
                ids = sorted(eid for eids in observed_states.values() for eid in eids)
                contradictory_obs.append(
                    f"Conflicting {fact[0]} states for {fact[1]}/{fact[2]} within this "
                    f"observation window: {', '.join(sorted(observed_states))}. "
                    f"Evidence: {', '.join(ids)}. May represent a state transition."
                )

        for rec in records:
            if (isinstance(rec, OSPFObservation)
                    and rec.collection_status == ObservationStatus.OBSERVED):
                state = rec.adjacency_state.split("/", 1)[0].strip().lower()
                if state == "down" and not any(
                    isinstance(other, InterfaceObservation)
                    and other.collection_status == ObservationStatus.OBSERVED
                    and other.source_router == rec.source_router
                    and other.source_interface == rec.source_interface
                    and other.observed_status.lower() in {"up", "down", "admin-down", "admin_down"}
                    for other in records
                ):
                    missing_info.append(
                        f"No observed interface state for {rec.source_router}/"
                        f"{rec.source_interface or 'unknown'} accompanying OSPF loss "
                        f"evidence {rec.evidence_id}."
                    )

        # Check for collection failures (missing info)
        collection_failures = [
            r for r in records
            if r.collection_status != ObservationStatus.OBSERVED
        ]
        if collection_failures:
            failed_routers = sorted(set(r.source_router for r in collection_failures))
            missing_info.append(
                f"Evidence unavailable for: {', '.join(failed_routers)}. "
                f"Observations from these routers are incomplete."
            )

        # Check if any affected router is DOWN in the topology
        down_routers = [
            r.router_id
            for r in topo_graph.topology.routers
            if r.status == RouterStatus.DOWN and r.router_id in affected_routers
        ]
        if down_routers:
            missing_info.append(
                f"Router(s) {', '.join(down_routers)} appear DOWN. "
                f"Evidence from their perspective cannot be collected."
            )

        # Correlation explanation
        explanation = self._build_explanation(
            incident_id, symptoms, relationships, affected_routers, affected_links
        )

        # Determine status
        if len(missing_info) > 0 and len(supporting_obs) < 2:
            status = "INCOMPLETE"
        elif len(symptoms) == 1:
            status = "ISOLATED"
        else:
            status = "GROUPED"

        return CorrelatedIncident(
            incident_id=incident_id,
            status=status,
            correlation_window_start=window.window_start,
            correlation_window_end=window.window_end,
            affected_routers=sorted(affected_routers),
            affected_links=sorted(affected_links),
            symptoms=symptoms,
            relationships=relationships,
            evidence_ids=sorted(all_evidence_ids),
            supporting_observations=supporting_obs,
            contradictory_observations=contradictory_obs,
            missing_information=missing_info,
            correlation_explanation=explanation,
            engine_version=CORRELATION_ENGINE_VERSION,
        )

    def _build_healthy_incident(
        self,
        incident_id: str,
        temporal_groups: list,
        records: list[EvidenceRecord],
        produced_at: datetime,
        classified_evidence_ids: set[str],
    ) -> CorrelatedIncident:
        """Build a HEALTHY correlation result with no anomalies."""
        window = self._temporal.compute_window(records)
        routers = sorted(set(r.source_router for r in records))
        unclassified = sorted(r.evidence_id for r in records
                              if r.evidence_id not in classified_evidence_ids)
        incomplete = bool(unclassified)
        return CorrelatedIncident(
            incident_id=incident_id,
            status="INCOMPLETE" if incomplete else "HEALTHY",
            correlation_window_start=window.window_start,
            correlation_window_end=window.window_end,
            affected_routers=routers,
            affected_links=[],
            symptoms=[],
            relationships=[],
            evidence_ids=sorted(r.evidence_id for r in records),
            supporting_observations=[],
            contradictory_observations=[],
            missing_information=[
                "No usable state classification for evidence: " + ", ".join(unclassified) + "."
            ] if incomplete else [],
            correlation_explanation=(
                "No abnormalities classified, but unavailable or untyped state evidence "
                "prevents a healthy assessment."
                if incomplete else
                f"All {len(records)} evidence records from routers "
                f"{', '.join(routers)} indicate healthy baseline conditions. "
                f"No anomalies detected. No incident grouping required."
            ),
            engine_version=CORRELATION_ENGINE_VERSION,
        )

    def _build_relationships(
        self,
        symptoms: list[CorrelatedSymptom],
        topo_graph: TopologyGraph,
        ev_graph: EvidenceGraph,
    ) -> list[CorrelationRelationship]:
        """Build explicit correlation relationships between symptoms."""
        relationships: list[CorrelationRelationship] = []
        seen: set[tuple[str, str]] = set()

        for i, sym_a in enumerate(symptoms):
            for j, sym_b in enumerate(symptoms):
                if i >= j:
                    continue
                pair = (sym_a.symptom_id, sym_b.symptom_id)
                if pair in seen:
                    continue
                seen.add(pair)

                # Determine relationship kind
                comp_a = sym_a.affected_component
                comp_b = sym_b.affected_component

                # Extract routers
                routers_a = self._extract_routers_from_component(comp_a, topo_graph)
                routers_b = self._extract_routers_from_component(comp_b, topo_graph)

                shared_routers = routers_a & routers_b
                if shared_routers:
                    relationships.append(CorrelationRelationship(
                        from_component=comp_a,
                        to_component=comp_b,
                        relationship_kind="SHARED_ROUTER",
                        supporting_evidence_ids=(
                            sym_a.supporting_evidence_ids + sym_b.supporting_evidence_ids
                        ),
                        explanation=(
                            f"Symptoms share router(s) {', '.join(sorted(shared_routers))}. "
                            f"Both observations originate from or implicate the same router."
                        ),
                    ))
                else:
                    # Check physical adjacency
                    for ra in routers_a:
                        for rb in routers_b:
                            if topo_graph.physical_graph.has_edge(ra, rb):
                                link_id = topo_graph.find_link_between(ra, rb)
                                link_str = f" via link {link_id}" if link_id else ""
                                relationships.append(CorrelationRelationship(
                                    from_component=comp_a,
                                    to_component=comp_b,
                                    relationship_kind="PHYSICAL_TOPOLOGY",
                                    supporting_evidence_ids=(
                                        sym_a.supporting_evidence_ids
                                        + sym_b.supporting_evidence_ids
                                    ),
                                    explanation=(
                                        f"Symptoms implicate adjacent routers {ra} and {rb}"
                                        f"{link_str}. "
                                        f"Physical topology proximity justifies grouping."
                                    ),
                                ))
                                break

                # Dependency edges require the same actual topology link. Inspect both
                # directions so input/symptom ordering cannot create or remove an edge.
                interface_sym = next((sym for sym in (sym_a, sym_b)
                                      if sym.category == SymptomCategory.INTERFACE_DOWN), None)
                ospf_sym = next((sym for sym in (sym_a, sym_b)
                                 if sym.category in {
                                     SymptomCategory.OSPF_ADJACENCY_LOST,
                                     SymptomCategory.OSPF_ADJACENCY_DEGRADED,
                                 }), None)
                interface_link = None
                adjacency_link = None
                if interface_sym and ospf_sym:
                    iface_parts = interface_sym.affected_component.split(":")
                    if len(iface_parts) == 3:
                        endpoint = tuple(iface_parts[1:])
                        interface_link = next((link.link_id for link in topo_graph.topology.links
                                               if endpoint in {
                                                   (link.router_a, link.interface_a),
                                                   (link.router_b, link.interface_b),
                                               }), None)
                    ospf_parts = ospf_sym.affected_component.removeprefix("adj:").split("→")
                    if len(ospf_parts) == 2:
                        adjacency_link = topo_graph.find_link_between(*ospf_parts)
                if interface_link is not None and interface_link == adjacency_link:
                    iface_component = interface_sym.affected_component
                    ospf_component = ospf_sym.affected_component
                    relationships.append(CorrelationRelationship(
                        from_component=iface_component,
                        to_component=ospf_component,
                        relationship_kind="OSPF_TOPOLOGY",
                        supporting_evidence_ids=(
                            sym_a.supporting_evidence_ids + sym_b.supporting_evidence_ids
                        ),
                        explanation=(
                            f"Interface DOWN ({iface_component}) and OSPF adjacency issue "
                            f"({ospf_component}) on link {interface_link} "
                            f"may be related: a physical interface down event can cause "
                            f"OSPF adjacency loss after dead-timer expiry (~40s). "
                            f"This is a possible dependency, not a confirmed causation."
                        ),
                    ))

        return relationships

    def _extract_routers_from_component(
        self, component: str, topo_graph: TopologyGraph
    ) -> set[str]:
        """Extract router IDs mentioned in a component identifier."""
        routers: set[str] = set()
        if component in topo_graph._router_index:
            routers.add(component)
            return routers
        if "→" in component:
            for part in component.split("→"):
                clean = part.split(":")[-1]
                if clean in topo_graph._router_index:
                    routers.add(clean)
                elif ":" in component:
                    # adj:R1→R2, ping:R1→...
                    sub = component.split(":")[1]
                    if "→" in sub:
                        for r in sub.split("→"):
                            if r in topo_graph._router_index:
                                routers.add(r)
        if ":" in component:
            parts = component.split(":")
            if len(parts) >= 2 and parts[1] in topo_graph._router_index:
                routers.add(parts[1])
        return routers

    def _build_explanation(
        self,
        incident_id: str,
        symptoms: list[CorrelatedSymptom],
        relationships: list[CorrelationRelationship],
        affected_routers: list[str],
        affected_links: list[str],
    ) -> str:
        """Build a plain-English audit trail for the incident grouping."""
        lines: list[str] = [
            f"Incident {incident_id} was formed by the correlation engine "
            f"(version {CORRELATION_ENGINE_VERSION}).",
            "",
            f"Affected routers: {', '.join(sorted(affected_routers)) or 'none identified'}.",
            f"Affected links: {', '.join(sorted(affected_links)) or 'none identified'}.",
            f"Total symptoms: {len(symptoms)}.",
            "",
            "Observed symptoms:",
        ]
        for i, sym in enumerate(symptoms, 1):
            lines.append(f"  {i}. [{sym.category.value}] {sym.description}")

        if relationships:
            lines.extend(["", "Correlation relationships:"])
            for rel in relationships[:5]:  # Limit to 5 for brevity
                lines.append(f"  - {rel.relationship_kind}: {rel.explanation}")

        lines.extend([
            "",
            "Grouping rationale: Symptoms were grouped because they involve "
            "topologically adjacent or shared network components and fall "
            "within the same observation window.",
            "",
            "IMPORTANT: This is a correlation result, not a root-cause diagnosis. "
            "The actual fault type and location will be determined in Phase 06 "
            "by the hypothesis ranking and rule-based scoring engine.",
        ])

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Ground-truth isolation
    # ------------------------------------------------------------------

    def _verify_no_ground_truth_leakage(
        self, snapshot_dict: dict[str, Any], snapshot_id: str
    ) -> None:
        """
        Verify that no ground-truth labels appear in the snapshot before correlation.

        Raises
        ------
        GroundTruthLeakageError
            If any forbidden token is found in the snapshot payload.
        """
        # Validate all metadata, including topology. Scenario filenames are never input.
        metadata_keys = [key for key in snapshot_dict if key != "evidence_records"]
        for key in metadata_keys:
            value = str(snapshot_dict.get(key, "")).lower()
            for token in GROUND_TRUTH_FORBIDDEN_TOKENS:
                if token in value:
                    raise GroundTruthLeakageError(
                        f"Ground-truth token '{token}' found in snapshot metadata key "
                        f"'{key}' of snapshot '{snapshot_id}'."
                    )

        # Check each evidence record payload (already done in normalizer, but double-check)
        for rec_dict in snapshot_dict.get("evidence_records", []):
            serialized = str(rec_dict).lower()
            for token in GROUND_TRUTH_FORBIDDEN_TOKENS:
                if token in serialized:
                    raise GroundTruthLeakageError(
                        f"Ground-truth token '{token}' found in evidence record "
                        f"{rec_dict.get('evidence_id', '?')} of snapshot '{snapshot_id}'."
                    )
