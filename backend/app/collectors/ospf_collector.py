"""
OSPF adjacency state and timer evidence collector for NEXORA.

Collects OSPF neighbour states, remaining dead timers, and detects missing neighbours
using structured JSON output from FRRouting.
"""

from __future__ import annotations

import json
from typing import ClassVar

from app.collectors.base import BaseCollector
from app.schemas.evidence import (
    CollectionMethod,
    EvidenceRecord,
    EvidenceSourceType,
    ObservationStatus,
    OSPFObservation,
)

EXPECTED_OSPF_NEIGHBOURS: dict[str, list[dict]] = {
    "R1": [
        {"nbr_router_id": "2.2.2.2", "nbr_address": "10.0.12.2", "interface": "eth1"},
        {"nbr_router_id": "5.5.5.5", "nbr_address": "10.0.15.1", "interface": "eth2"},
    ],
    "R2": [
        {"nbr_router_id": "1.1.1.1", "nbr_address": "10.0.12.1", "interface": "eth1"},
        {"nbr_router_id": "3.3.3.3", "nbr_address": "10.0.23.2", "interface": "eth2"},
    ],
    "R3": [
        {"nbr_router_id": "2.2.2.2", "nbr_address": "10.0.23.1", "interface": "eth1"},
        {"nbr_router_id": "4.4.4.4", "nbr_address": "10.0.34.2", "interface": "eth2"},
    ],
    "R4": [
        {"nbr_router_id": "3.3.3.3", "nbr_address": "10.0.34.1", "interface": "eth1"},
        {"nbr_router_id": "5.5.5.5", "nbr_address": "10.0.45.2", "interface": "eth2"},
    ],
    "R5": [
        {"nbr_router_id": "4.4.4.4", "nbr_address": "10.0.45.1", "interface": "eth1"},
        {"nbr_router_id": "1.1.1.1", "nbr_address": "10.0.15.2", "interface": "eth2"},
    ],
}


class OSPFCollector(BaseCollector):
    """Collects OSPFObservation evidence records from FRRouting."""

    COLLECTOR_NAME: ClassVar[str] = "ospf"

    def collect(
        self,
        router_ids: list[str] | None = None,
        incident_id: str | None = None,
    ) -> list[EvidenceRecord]:
        target_routers = self.filter_router_ids(router_ids)
        records: list[EvidenceRecord] = []
        now = self.now_utc()

        for rid in target_routers:
            expected_nbrs = EXPECTED_OSPF_NEIGHBOURS.get(rid, [])

            if not self.transport.is_router_running(rid):
                for exp in expected_nbrs:
                    nbr_tag = exp["nbr_router_id"].replace(".", "-")
                    records.append(
                        OSPFObservation(
                            evidence_id=self.generate_evidence_id(rid, nbr_tag),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=exp["interface"],
                            event_type="ROUTER_UNAVAILABLE",
                            observed_at=now,
                            collected_at=now,
                            source_type=EvidenceSourceType.OSPF_API,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.COLLECTION_FAILED,
                            neighbour_router_id=exp["nbr_router_id"],
                            neighbour_address=exp["nbr_address"],
                            adjacency_state="Down",
                            dead_timer_remaining_s=None,
                            raw_reference=f"docker://nexora-{rid.lower()}/unreachable",
                        )
                    )
                continue

            code, stdout, stderr = self.transport.execute(
                rid,
                ["vtysh", "-c", "show ip ospf neighbor json"],
            )

            if code != 0 or not stdout.strip():
                for exp in expected_nbrs:
                    nbr_tag = exp["nbr_router_id"].replace(".", "-")
                    records.append(
                        OSPFObservation(
                            evidence_id=self.generate_evidence_id(rid, nbr_tag),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=exp["interface"],
                            event_type="COMMAND_FAILED",
                            observed_at=now,
                            collected_at=now,
                            source_type=EvidenceSourceType.OSPF_API,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.COLLECTION_FAILED,
                            neighbour_router_id=exp["nbr_router_id"],
                            neighbour_address=exp["nbr_address"],
                            adjacency_state="Unknown",
                            dead_timer_remaining_s=None,
                            raw_reference=f"vtysh-failed: {stderr.strip()[:100]}",
                        )
                    )
                continue

            try:
                data = json.loads(stdout)
            except Exception as exc:
                for exp in expected_nbrs:
                    nbr_tag = exp["nbr_router_id"].replace(".", "-")
                    records.append(
                        OSPFObservation(
                            evidence_id=self.generate_evidence_id(rid, nbr_tag),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=exp["interface"],
                            event_type="PARSE_FAILED",
                            observed_at=now,
                            collected_at=now,
                            source_type=EvidenceSourceType.OSPF_API,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.UNKNOWN,
                            neighbour_router_id=exp["nbr_router_id"],
                            neighbour_address=exp["nbr_address"],
                            adjacency_state="Unknown",
                            dead_timer_remaining_s=None,
                            raw_reference=f"json-parse-error: {exc}",
                        )
                    )
                continue

            neighbors_dict = data.get("neighbors", {})
            observed_nbr_ids: set[str] = set()

            for nbr_id, nbr_list in neighbors_dict.items():
                for item in nbr_list:
                    observed_nbr_ids.add(nbr_id)
                    raw_state = item.get("converged") or item.get("state", "Unknown")
                    state_clean = raw_state.split("/")[0].strip()

                    dead_ms = item.get("deadTimeMsecs")
                    dead_s = round(float(dead_ms) / 1000.0, 3) if dead_ms is not None else None

                    iface_field = item.get("ifaceName", "")
                    local_iface = iface_field.split(":")[0] if ":" in iface_field else iface_field
                    address = item.get("address", "")

                    event_type = (
                        "OSPF_NEIGHBOUR_FULL"
                        if state_clean.lower() == "full"
                        else f"OSPF_NEIGHBOUR_{state_clean.upper()}"
                    )

                    records.append(
                        OSPFObservation(
                            evidence_id=self.generate_evidence_id(rid, nbr_id.replace(".", "-")),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=local_iface or None,
                            event_type=event_type,
                            observed_at=now,
                            collected_at=now,
                            source_type=EvidenceSourceType.OSPF_API,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.OBSERVED,
                            neighbour_router_id=nbr_id,
                            neighbour_address=address or "0.0.0.0",
                            adjacency_state=state_clean,
                            dead_timer_remaining_s=dead_s,
                            raw_reference="vtysh:show ip ospf neighbor json",
                        )
                    )

            # Check for expected neighbours that are completely missing
            for exp in expected_nbrs:
                if exp["nbr_router_id"] not in observed_nbr_ids:
                    nbr_tag = exp["nbr_router_id"].replace(".", "-")
                    records.append(
                        OSPFObservation(
                            evidence_id=self.generate_evidence_id(rid, nbr_tag),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=exp["interface"],
                            event_type="OSPF_NEIGHBOUR_DOWN",
                            observed_at=now,
                            collected_at=now,
                            source_type=EvidenceSourceType.OSPF_API,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.OBSERVED,
                            neighbour_router_id=exp["nbr_router_id"],
                            neighbour_address=exp["nbr_address"],
                            adjacency_state="Down",
                            dead_timer_remaining_s=0.0,
                            raw_reference=f"neighbor {exp['nbr_router_id']} absent from table",
                        )
                    )

        return records
