"""
Network interface state and statistics evidence collector for NEXORA.

Collects operational state, error counters, and packet statistics for data-plane interfaces
on approved NEXORA router nodes.
"""

from __future__ import annotations

import json
from typing import ClassVar

from app.collectors.base import BaseCollector
from app.collectors.topology_collector import EXPECTED_ROUTERS_METADATA
from app.schemas.evidence import (
    CollectionMethod,
    EvidenceRecord,
    EvidenceSourceType,
    InterfaceObservation,
    ObservationStatus,
)


class InterfaceCollector(BaseCollector):
    """Collects InterfaceObservation records from live router containers."""

    COLLECTOR_NAME: ClassVar[str] = "interface"

    def collect(
        self,
        router_ids: list[str] | None = None,
        incident_id: str | None = None,
    ) -> list[EvidenceRecord]:
        target_routers = self.filter_router_ids(router_ids)
        records: list[EvidenceRecord] = []
        for rid in target_routers:
            now = self.now_utc()
            meta = EXPECTED_ROUTERS_METADATA.get(rid, {})
            expected_ifaces = list(meta.get("interfaces", {}).keys()) or ["eth1", "eth2", "lo"]

            if not self.transport.is_router_running(rid):
                for iface in expected_ifaces:
                    records.append(
                        InterfaceObservation(
                            evidence_id=self.generate_evidence_id(rid, iface),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=iface,
                            event_type="ROUTER_UNAVAILABLE",
                            observed_at=now,
                            collected_at=self.now_utc(),
                            source_type=EvidenceSourceType.INTERFACE_POLL,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.COLLECTION_FAILED,
                            observed_status="down",
                            speed_mbps=None,
                            error_count=None,
                            raw_reference=f"docker://nexora-{rid.lower()}/unreachable",
                        )
                    )
                continue

            # Query live interface stats
            code, stdout, stderr = self.transport.execute(
                rid,
                ["ip", "-j", "-s", "link", "show"],
            )

            if code != 0 or not stdout.strip():
                for iface in expected_ifaces:
                    records.append(
                        InterfaceObservation(
                            evidence_id=self.generate_evidence_id(rid, iface),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=iface,
                            event_type="COMMAND_FAILED",
                            observed_at=now,
                            collected_at=self.now_utc(),
                            source_type=EvidenceSourceType.INTERFACE_POLL,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.COLLECTION_FAILED,
                            observed_status="unknown",
                            speed_mbps=None,
                            error_count=None,
                            raw_reference=f"ip-link-failed: {stderr.strip()[:100]}",
                        )
                    )
                continue

            try:
                link_data = json.loads(stdout)
            except Exception as exc:
                for iface in expected_ifaces:
                    records.append(
                        InterfaceObservation(
                            evidence_id=self.generate_evidence_id(rid, iface),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=iface,
                            event_type="PARSE_FAILED",
                            observed_at=now,
                            collected_at=self.now_utc(),
                            source_type=EvidenceSourceType.INTERFACE_POLL,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.UNKNOWN,
                            observed_status="unknown",
                            speed_mbps=None,
                            error_count=None,
                            raw_reference=f"json-parse-error: {exc}",
                        )
                    )
                continue

            discovered_by_name = {
                item.get("ifname"): item for item in link_data if item.get("ifname")
            }

            for iface in expected_ifaces:
                item = discovered_by_name.get(iface)
                if not item:
                    # Missing interface is explicitly recorded
                    records.append(
                        InterfaceObservation(
                            evidence_id=self.generate_evidence_id(rid, iface),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=iface,
                            event_type="INTERFACE_NOT_FOUND",
                            observed_at=now,
                            collected_at=self.now_utc(),
                            source_type=EvidenceSourceType.INTERFACE_POLL,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.OBSERVED,
                            observed_status="down",
                            speed_mbps=None,
                            error_count=None,
                            raw_reference=f"interface {iface} not present in kernel link list",
                        )
                    )
                    continue

                raw_operstate = (item.get("operstate") or "UNKNOWN").lower()
                flags = item.get("flags") or []
                is_admin_up = "UP" in flags

                if raw_operstate == "up":
                    observed_status = "up"
                elif not is_admin_up:
                    observed_status = "admin-down"
                else:
                    observed_status = "down"

                event_type = (
                    "INTERFACE_DOWN_OBSERVED"
                    if observed_status in ("down", "admin-down")
                    else "INTERFACE_STATE_OBSERVED"
                )

                # Parse error counters from stats64
                stats64 = item.get("stats64", {})
                rx = stats64.get("rx", {})
                tx = stats64.get("tx", {})
                errors = rx.get("errors", 0) + tx.get("errors", 0)
                dropped = rx.get("dropped", 0) + tx.get("dropped", 0)
                total_errors = errors + dropped

                records.append(
                    InterfaceObservation(
                        evidence_id=self.generate_evidence_id(rid, iface),
                        incident_id=incident_id,
                        source_router=rid,
                        source_interface=iface,
                        event_type=event_type,
                        observed_at=now,
                        collected_at=self.now_utc(),
                        source_type=EvidenceSourceType.INTERFACE_POLL,
                        collection_method=CollectionMethod.PERIODIC_POLL,
                        collection_status=ObservationStatus.OBSERVED,
                        observed_status=observed_status,
                        speed_mbps=10000 if iface != "lo" else 0,
                        error_count=total_errors,
                        raw_reference=f"ip -j -s link show dev {iface}",
                    )
                )

        return records
