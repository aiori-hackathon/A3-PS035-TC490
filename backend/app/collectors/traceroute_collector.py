"""
Active traceroute probe evidence collector for NEXORA.

Executes safe, bounded traceroute probes between approved NEXORA topology endpoints
to discover actual forwarding paths, per-hop latency, and unreachable hops.
"""

from __future__ import annotations

import re
from typing import ClassVar

from app.collectors.base import BaseCollector
from app.collectors.ping_collector import APPROVED_PING_TARGETS
from app.collectors.transport import SecurityViolationError
from app.schemas.evidence import (
    CollectionMethod,
    EvidenceRecord,
    EvidenceSourceType,
    ObservationStatus,
    TracerouteHop,
    TracerouteObservation,
)


class TracerouteCollector(BaseCollector):
    """Executes bounded traceroute probes and produces TracerouteObservation records."""

    COLLECTOR_NAME: ClassVar[str] = "traceroute"

    # Regex for hop line: " 1  10.0.12.2  0.077 ms" or " 2  * *"
    HOP_PATTERN: ClassVar[re.Pattern] = re.compile(
        r"^\s*(\d+)\s+([0-9.]+)\s+([\d.]+)\s*ms",
        re.MULTILINE,
    )
    TIMEOUT_HOP_PATTERN: ClassVar[re.Pattern] = re.compile(
        r"^\s*(\d+)\s+\*",
        re.MULTILINE,
    )

    def probe(
        self,
        source_router: str,
        target_address: str,
        max_hops: int = 5,
        timeout_s: int = 1,
        incident_id: str | None = None,
    ) -> TracerouteObservation:
        src = source_router.upper()
        if src not in self.filter_router_ids(None):
            raise SecurityViolationError(f"Invalid source router: {source_router!r}")

        if target_address not in APPROVED_PING_TARGETS:
            raise SecurityViolationError(
                f"Target address {target_address!r} is not on the approved NEXORA target whitelist."
            )

        bounded_hops = max(1, min(max_hops, 10))
        bounded_timeout = max(1, min(timeout_s, 5))

        now = self.now_utc()
        evidence_id = self.generate_evidence_id(src, f"trace-to-{target_address.replace('.', '-')}")

        if not self.transport.is_router_running(src):
            return TracerouteObservation(
                evidence_id=evidence_id,
                incident_id=incident_id,
                source_router=src,
                probe_source=src,
                source_interface=None,
                event_type="PROBE_SOURCE_UNAVAILABLE",
                observed_at=now,
                collected_at=now,
                source_type=EvidenceSourceType.ACTIVE_TRACEROUTE,
                collection_method=CollectionMethod.TRIGGERED_PROBE,
                collection_status=ObservationStatus.COLLECTION_FAILED,
                target_address=target_address,
                hops=[],
                total_hops=0,
                destination_reached=False,
                raw_reference=f"source router {src} unavailable",
            )

        cmd = [
            "traceroute",
            "-n",
            "-w",
            str(bounded_timeout),
            "-q",
            "1",
            "-m",
            str(bounded_hops),
            target_address,
        ]

        total_timeout = float(bounded_hops * bounded_timeout + 3.0)
        code, stdout, stderr = self.transport.execute(src, cmd, timeout=total_timeout)

        hops: list[TracerouteHop] = []
        destination_reached = False

        for line in stdout.splitlines():
            line_strip = line.strip()
            if not line_strip or line_strip.startswith("traceroute"):
                continue

            hop_match = self.HOP_PATTERN.match(line)
            if hop_match:
                hop_num = int(hop_match.group(1))
                hop_addr = hop_match.group(2)
                rtt = float(hop_match.group(3))
                hops.append(
                    TracerouteHop(
                        hop_number=hop_num,
                        hop_address=hop_addr,
                        rtt_ms=rtt,
                        is_unreachable=False,
                    )
                )
                if hop_addr == target_address:
                    destination_reached = True
                continue

            timeout_match = self.TIMEOUT_HOP_PATTERN.match(line)
            if timeout_match:
                hop_num = int(timeout_match.group(1))
                hops.append(
                    TracerouteHop(
                        hop_number=hop_num,
                        hop_address=None,
                        rtt_ms=None,
                        is_unreachable=True,
                    )
                )

        status = ObservationStatus.OBSERVED if hops else ObservationStatus.COLLECTION_FAILED
        event_type = "TRACEROUTE_COMPLETED" if destination_reached else "TRACEROUTE_INCOMPLETE"

        return TracerouteObservation(
            evidence_id=evidence_id,
            incident_id=incident_id,
            source_router=src,
            probe_source=src,
            source_interface=None,
            event_type=event_type,
            observed_at=now,
            collected_at=now,
            source_type=EvidenceSourceType.ACTIVE_TRACEROUTE,
            collection_method=CollectionMethod.TRIGGERED_PROBE,
            collection_status=status,
            target_address=target_address,
            hops=hops,
            total_hops=len(hops),
            destination_reached=destination_reached,
            raw_reference=f"traceroute -n -w {bounded_timeout} -m {bounded_hops} {target_address}",
        )

    def collect(
        self,
        router_ids: list[str] | None = None,
        incident_id: str | None = None,
        target_address: str = "192.168.255.3",
    ) -> list[EvidenceRecord]:
        target_routers = self.filter_router_ids(router_ids)
        records: list[EvidenceRecord] = []
        for rid in target_routers:
            record = self.probe(
                source_router=rid,
                target_address=target_address,
                max_hops=5,
                timeout_s=1,
                incident_id=incident_id,
            )
            records.append(record)
        return records
