"""
Routing table evidence collector for NEXORA.

Collects RIB entries from FRRouting via structured JSON, captures next hops, outgoing interfaces,
and metrics, and detects route presence or absence.
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
    RouteObservation,
)

# Standard expected OSPF loopback prefixes across the 5 routers
EXPECTED_LOOPBACK_PREFIXES: list[str] = [
    "192.168.255.1/32",
    "192.168.255.2/32",
    "192.168.255.3/32",
    "192.168.255.4/32",
    "192.168.255.5/32",
]


class RoutingCollector(BaseCollector):
    """Collects RouteObservation records from live FRR instances."""

    COLLECTOR_NAME: ClassVar[str] = "routing"

    def __init__(
        self,
        transport,
        baseline_prefixes: list[str] | None = None,
    ) -> None:
        super().__init__(transport)
        self.baseline_prefixes = baseline_prefixes or list(EXPECTED_LOOPBACK_PREFIXES)

    def _prefix_tag(self, prefix: str) -> str:
        return prefix.replace("/", "-").replace(".", "-")

    def collect(
        self,
        router_ids: list[str] | None = None,
        incident_id: str | None = None,
    ) -> list[EvidenceRecord]:
        target_routers = self.filter_router_ids(router_ids)
        records: list[EvidenceRecord] = []
        now = self.now_utc()

        for rid in target_routers:
            if not self.transport.is_router_running(rid):
                for prefix in self.baseline_prefixes:
                    records.append(
                        RouteObservation(
                            evidence_id=self.generate_evidence_id(rid, self._prefix_tag(prefix)),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=None,
                            event_type="ROUTER_UNAVAILABLE",
                            observed_at=now,
                            collected_at=now,
                            source_type=EvidenceSourceType.ROUTING_TABLE,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.COLLECTION_FAILED,
                            destination_prefix=prefix,
                            next_hop_address=None,
                            next_hop_interface=None,
                            route_type="O",
                            metric=None,
                            is_present=False,
                            raw_reference=f"docker://nexora-{rid.lower()}/unreachable",
                        )
                    )
                continue

            code, stdout, stderr = self.transport.execute(
                rid,
                ["vtysh", "-c", "show ip route json"],
            )

            if code != 0 or not stdout.strip():
                for prefix in self.baseline_prefixes:
                    records.append(
                        RouteObservation(
                            evidence_id=self.generate_evidence_id(rid, self._prefix_tag(prefix)),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=None,
                            event_type="COMMAND_FAILED",
                            observed_at=now,
                            collected_at=now,
                            source_type=EvidenceSourceType.ROUTING_TABLE,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.COLLECTION_FAILED,
                            destination_prefix=prefix,
                            next_hop_address=None,
                            next_hop_interface=None,
                            route_type="O",
                            metric=None,
                            is_present=False,
                            raw_reference=f"vtysh-route-failed: {stderr.strip()[:100]}",
                        )
                    )
                continue

            try:
                rib_data = json.loads(stdout)
            except Exception as exc:
                for prefix in self.baseline_prefixes:
                    records.append(
                        RouteObservation(
                            evidence_id=self.generate_evidence_id(rid, self._prefix_tag(prefix)),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=None,
                            event_type="PARSE_FAILED",
                            observed_at=now,
                            collected_at=now,
                            source_type=EvidenceSourceType.ROUTING_TABLE,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.UNKNOWN,
                            destination_prefix=prefix,
                            next_hop_address=None,
                            next_hop_interface=None,
                            route_type="O",
                            metric=None,
                            is_present=False,
                            raw_reference=f"json-parse-error: {exc}",
                        )
                    )
                continue

            observed_prefixes: set[str] = set()

            for prefix, routes in rib_data.items():
                if not isinstance(routes, list):
                    continue

                for route in routes:
                    # Filter out management subnet
                    if "192.168.100." in prefix:
                        continue

                    raw_proto = route.get("protocol", "unknown").lower()
                    if raw_proto == "ospf":
                        proto_code = "O"
                    elif raw_proto == "connected":
                        proto_code = "C"
                    elif raw_proto == "static":
                        proto_code = "S"
                    else:
                        proto_code = raw_proto[:1].upper()

                    metric = route.get("metric")
                    nexthops = route.get("nexthops", [])
                    first_nh = nexthops[0] if nexthops else {}
                    nh_ip = first_nh.get("ip")
                    nh_iface = first_nh.get("interfaceName")

                    observed_prefixes.add(prefix)

                    records.append(
                        RouteObservation(
                            evidence_id=self.generate_evidence_id(rid, self._prefix_tag(prefix)),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=nh_iface or None,
                            event_type="ROUTE_OBSERVED",
                            observed_at=now,
                            collected_at=now,
                            source_type=EvidenceSourceType.ROUTING_TABLE,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.OBSERVED,
                            destination_prefix=prefix,
                            next_hop_address=nh_ip,
                            next_hop_interface=nh_iface,
                            route_type=proto_code,
                            metric=metric if isinstance(metric, int) else None,
                            is_present=True,
                            raw_reference=f"vtysh:show ip route {prefix}",
                        )
                    )

            # Check if expected baseline prefixes are missing from the routing table
            for expected_prefix in self.baseline_prefixes:
                if expected_prefix not in observed_prefixes:
                    records.append(
                        RouteObservation(
                            evidence_id=self.generate_evidence_id(
                                rid, f"missing-{self._prefix_tag(expected_prefix)}"
                            ),
                            incident_id=incident_id,
                            source_router=rid,
                            source_interface=None,
                            event_type="ROUTE_MISSING",
                            observed_at=now,
                            collected_at=now,
                            source_type=EvidenceSourceType.ROUTING_TABLE,
                            collection_method=CollectionMethod.PERIODIC_POLL,
                            collection_status=ObservationStatus.OBSERVED,
                            destination_prefix=expected_prefix,
                            next_hop_address=None,
                            next_hop_interface=None,
                            route_type="O",
                            metric=None,
                            is_present=False,
                            raw_reference=f"route {expected_prefix} absent from routing table",
                        )
                    )

        return records
