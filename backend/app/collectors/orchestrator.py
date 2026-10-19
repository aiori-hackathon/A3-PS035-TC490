"""
Evidence collection orchestrator and snapshot persistence service for NEXORA.

Coordinates all specialized collectors (topology, interfaces, OSPF, routing, ping,
traceroute, syslog), applies normalization, tracks collector errors, and persists
structured observation snapshots under evaluation/datasets/observations/.

Strictly enforces ground-truth isolation: snapshots contain ONLY observable evidence.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.collectors.base import DEFAULT_ROUTER_IDS
from app.collectors.interface_collector import InterfaceCollector
from app.collectors.normalizer import EvidenceNormalizer
from app.collectors.ospf_collector import OSPFCollector
from app.collectors.ping_collector import PingCollector
from app.collectors.routing_collector import RoutingCollector
from app.collectors.syslog_collector import SyslogCollector
from app.collectors.topology_collector import TopologyCollector
from app.collectors.traceroute_collector import TracerouteCollector
from app.collectors.transport import CollectorTransport, DockerTransport
from app.schemas.evidence import EvidenceRecord
from app.schemas.topology import Topology

logger = logging.getLogger("nexora.collectors.orchestrator")

# Default observation storage directory (relative to workspace root)
DEFAULT_STORAGE_DIR = (
    Path(__file__).resolve().parents[3] / "evaluation" / "datasets" / "observations"
)


class EvidenceSnapshot(BaseModel):
    """An immutable, auditable snapshot of network observations and topology."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(description="Globally unique snapshot identifier.")
    schema_version: str = Field(default="1.0.0", description="Snapshot format schema version.")
    captured_at: datetime = Field(description="UTC timestamp when collection completed.")
    collection_window_start: datetime = Field(description="UTC timestamp when collection began.")
    collection_window_end: datetime = Field(description="UTC timestamp when collection ended.")
    router_ids: list[str] = Field(description="Routers targeted in this collection session.")
    topology: Topology = Field(description="Observed live network topology model.")
    evidence_records: list[EvidenceRecord] = Field(
        description="All normalized evidence observations."
    )
    collector_errors: list[str] = Field(
        default_factory=list,
        description="Any collector errors recorded.",
    )
    total_records: int = Field(ge=0, description="Total number of evidence records in snapshot.")
    records_by_type: dict[str, int] = Field(
        default_factory=dict,
        description="Count of records grouped by source evidence type.",
    )


class CollectionOrchestrator:
    """Orchestrates comprehensive multi-collector observation snapshots."""

    def __init__(
        self,
        transport: CollectorTransport | None = None,
        storage_dir: Path | None = None,
    ) -> None:
        self.transport = transport or DockerTransport()
        self.storage_dir = storage_dir or DEFAULT_STORAGE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Initialize sub-collectors
        self.topology_collector = TopologyCollector(self.transport)
        self.interface_collector = InterfaceCollector(self.transport)
        self.ospf_collector = OSPFCollector(self.transport)
        self.routing_collector = RoutingCollector(self.transport)
        self.ping_collector = PingCollector(self.transport)
        self.traceroute_collector = TracerouteCollector(self.transport)
        self.syslog_collector = SyslogCollector(self.transport)

    def collect_snapshot(
        self,
        router_ids: list[str] | None = None,
        incident_id: str | None = None,
        include_probes: bool = True,
        include_logs: bool = True,
        log_tail: int = 50,
    ) -> EvidenceSnapshot:
        """Run all collectors to produce a complete EvidenceSnapshot."""
        start_time = datetime.now(UTC)
        requested = router_ids or DEFAULT_ROUTER_IDS
        target_routers = [r.upper() for r in requested if r.upper() in DEFAULT_ROUTER_IDS]

        ts_str = start_time.strftime("%Y%m%dT%H%M%SZ")
        short_id = uuid.uuid4().hex[:6]
        snapshot_id = f"obs-snap-{ts_str}-{short_id}"

        collected_records: list[EvidenceRecord] = []
        errors: list[str] = []

        # 1. Topology collection
        try:
            observed_topo = self.topology_collector.collect_observed_topology(
                snapshot_id=f"topo-{snapshot_id}"
            )
        except Exception as exc:
            errors.append(f"TopologyCollector error: {exc}")
            observed_topo = self.topology_collector.get_expected_topology(
                snapshot_id=f"topo-{snapshot_id}"
            )

        # 2. Interface state collection
        try:
            iface_records = self.interface_collector.collect(
                target_routers,
                incident_id=incident_id,
            )
            collected_records.extend(iface_records)
        except Exception as exc:
            errors.append(f"InterfaceCollector error: {exc}")

        # 3. OSPF adjacency collection
        try:
            ospf_records = self.ospf_collector.collect(target_routers, incident_id=incident_id)
            collected_records.extend(ospf_records)
        except Exception as exc:
            errors.append(f"OSPFCollector error: {exc}")

        # 4. Routing table collection
        try:
            route_records = self.routing_collector.collect(target_routers, incident_id=incident_id)
            collected_records.extend(route_records)
        except Exception as exc:
            errors.append(f"RoutingCollector error: {exc}")

        # 5. Active ping measurements
        if include_probes:
            try:
                ping_records = self.ping_collector.collect(target_routers, incident_id=incident_id)
                collected_records.extend(ping_records)
            except Exception as exc:
                errors.append(f"PingCollector error: {exc}")

            # 6. Active traceroute probes
            try:
                trace_records = self.traceroute_collector.collect(
                    target_routers,
                    incident_id=incident_id,
                )
                collected_records.extend(trace_records)
            except Exception as exc:
                errors.append(f"TracerouteCollector error: {exc}")

        # 7. Syslog and daemon logs
        if include_logs:
            try:
                syslog_records = self.syslog_collector.collect(
                    target_routers, incident_id=incident_id, tail=log_tail
                )
                collected_records.extend(syslog_records)
            except Exception as exc:
                errors.append(f"SyslogCollector error: {exc}")

        end_time = datetime.now(UTC)

        # 8. Normalization and ground-truth isolation audit
        normalized_records: list[EvidenceRecord] = []
        for rec in collected_records:
            try:
                norm_rec = EvidenceNormalizer.normalize_record(rec)
                normalized_records.append(norm_rec)
            except Exception as exc:
                errors.append(f"Normalization error for {rec.evidence_id}: {exc}")

        # Compute summary counts
        type_counts = Counter(r.source_type.value for r in normalized_records)

        snapshot = EvidenceSnapshot(
            snapshot_id=snapshot_id,
            schema_version="1.0.0",
            captured_at=end_time,
            collection_window_start=start_time,
            collection_window_end=end_time,
            router_ids=target_routers,
            topology=observed_topo,
            evidence_records=normalized_records,
            collector_errors=errors,
            total_records=len(normalized_records),
            records_by_type=dict(type_counts),
        )

        return snapshot

    def save_snapshot(
        self,
        snapshot: EvidenceSnapshot,
        custom_filename: str | None = None,
    ) -> Path:
        """Persist snapshot as deterministic JSON to storage directory."""
        fname = custom_filename or f"{snapshot.snapshot_id}.json"
        dest_path = self.storage_dir / fname

        data = snapshot.model_dump(mode="json")
        with open(dest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)

        return dest_path
