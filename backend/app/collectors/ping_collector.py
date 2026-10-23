"""
Active ICMP ping probe evidence collector for NEXORA.

Executes safe, bounded, read-only ping measurements between approved NEXORA topology endpoints.
Validates packet loss and RTT statistics against strict Pydantic contracts.
"""

from __future__ import annotations

import re
from typing import ClassVar

from app.collectors.base import BaseCollector
from app.collectors.transport import SecurityViolationError
from app.schemas.evidence import (
    CollectionMethod,
    EvidenceRecord,
    EvidenceSourceType,
    ObservationStatus,
    PingAttemptFailure,
    PingMeasurement,
)

# Strict whitelist of approved ping target addresses within the NEXORA laboratory
APPROVED_PING_TARGETS: set[str] = {
    # Loopback addresses
    "192.168.255.1",
    "192.168.255.2",
    "192.168.255.3",
    "192.168.255.4",
    "192.168.255.5",
    # Data-plane link addresses
    "10.0.12.1",
    "10.0.12.2",
    "10.0.23.1",
    "10.0.23.2",
    "10.0.34.1",
    "10.0.34.2",
    "10.0.45.1",
    "10.0.45.2",
    "10.0.15.1",
    "10.0.15.2",
}

# Standard ring probe pairs (source_router, target_address)
DEFAULT_PROBE_PAIRS: list[tuple[str, str]] = [
    ("R1", "192.168.255.2"),  # R1 -> R2
    ("R2", "192.168.255.3"),  # R2 -> R3
    ("R3", "192.168.255.4"),  # R3 -> R4
    ("R4", "192.168.255.5"),  # R4 -> R5
    ("R5", "192.168.255.1"),  # R5 -> R1
]


class PingCollector(BaseCollector):
    """Executes bounded ICMP ping probes and produces PingMeasurement records."""

    COLLECTOR_NAME: ClassVar[str] = "ping"

    # Regex patterns for busybox / iputils ping output
    STAT_PATTERN: ClassVar[re.Pattern] = re.compile(
        r"(\d+)\s+packets transmitted,\s+(\d+)\s+(?:packets\s+)?received,\s+([\d.]+)%\s+packet loss"
    )
    RTT_PATTERN: ClassVar[re.Pattern] = re.compile(
        r"(?:round-trip|rtt)\s+min/avg/max(?:/mdev)?\s*=\s*"
        r"([\d.]+)/([\d.]+)/([\d.]+)(?:/([\d.]+))?\s*ms\b"
    )

    def probe(
        self,
        source_router: str,
        target_address: str,
        count: int = 5,
        timeout_s: int = 1,
        incident_id: str | None = None,
        source_address: str | None = None,
        interval_s: float | None = None,
    ) -> PingMeasurement | PingAttemptFailure:
        """Execute a single bounded ping probe and return a PingMeasurement record."""
        src = source_router.upper()
        if src not in self.filter_router_ids(None):
            raise SecurityViolationError(f"Invalid source router: {source_router!r}")

        if target_address not in APPROVED_PING_TARGETS:
            raise SecurityViolationError(
                f"Target address {target_address!r} is not on the approved NEXORA target whitelist."
            )

        # Enforce parameter bounds
        if not 1 <= count <= 20:
            raise ValueError("Probe count must be between 1 and 20")
        if source_address is not None:
            from app.collectors.topology_collector import EXPECTED_ROUTERS_METADATA

            addresses = {
                i["ipv4"].split("/")[0]
                for i in EXPECTED_ROUTERS_METADATA[src]["interfaces"].values()
            }
            if source_address not in addresses:
                raise SecurityViolationError("Source address is not assigned to this NEXORA router")
        bounded_count = count
        bounded_timeout = max(1, min(timeout_s, 10))

        now = self.now_utc()
        evidence_id = self.generate_evidence_id(src, f"to-{target_address.replace('.', '-')}")

        if not self.transport.is_router_running(src):
            return PingAttemptFailure(
                evidence_id=evidence_id,
                incident_id=incident_id,
                source_router=src,
                probe_source=src,
                source_interface=None,
                event_type="PROBE_SOURCE_UNAVAILABLE",
                observed_at=now,
                collected_at=self.now_utc(),
                source_type=EvidenceSourceType.ACTIVE_PING,
                collection_method=CollectionMethod.TRIGGERED_PROBE,
                collection_status=ObservationStatus.COLLECTION_FAILED,
                target_address=target_address,
                requested_packets=bounded_count,
                source_address=source_address,
                raw_reference=f"source router {src} unavailable",
            )

        cmd = [
            "ping",
            "-c",
            str(bounded_count),
            "-W",
            str(bounded_timeout),
            target_address,
        ]

        if interval_s is not None:
            bounded_interval = max(0.1, min(float(interval_s), 10.0))
            cmd[-1:-1] = ["-i", str(bounded_interval)]
            total_timeout = float(bounded_count * bounded_interval + bounded_timeout + 3.0)
        else:
            total_timeout = float(bounded_count * bounded_timeout + 3.0)

        if source_address is not None:
            cmd[-1:-1] = ["-I", source_address]

        code, stdout, stderr = self.transport.execute(src, cmd, timeout=total_timeout)
        combined_output = f"{stdout}\n{stderr}"

        # Parse transmission statistics
        stat_match = self.STAT_PATTERN.search(combined_output)
        if not stat_match:
            # Command failed completely without statistics
            return PingAttemptFailure(
                evidence_id=evidence_id,
                incident_id=incident_id,
                source_router=src,
                probe_source=src,
                source_interface=None,
                event_type="PROBE_EXECUTION_FAILED",
                observed_at=now,
                collected_at=self.now_utc(),
                source_type=EvidenceSourceType.ACTIVE_PING,
                collection_method=CollectionMethod.TRIGGERED_PROBE,
                collection_status=ObservationStatus.COLLECTION_FAILED,
                target_address=target_address,
                requested_packets=bounded_count,
                source_address=source_address,
                raw_reference=f"ping failed: {stderr.strip()[:100]}",
            )

        sent = int(stat_match.group(1))
        received = int(stat_match.group(2))
        _reported_loss = float(stat_match.group(3))

        # Enforce consistency with Pydantic validator expectation: 100.0 * (sent - received) / sent
        exact_loss = round(100.0 * (sent - received) / sent, 1) if sent > 0 else 100.0

        rtt_min: float | None = None
        rtt_avg: float | None = None
        rtt_max: float | None = None
        rtt_mdev: float | None = None

        if received > 0:
            rtt_match = self.RTT_PATTERN.search(combined_output)
            if rtt_match:
                rtt_min = float(rtt_match.group(1))
                rtt_avg = float(rtt_match.group(2))
                rtt_max = float(rtt_match.group(3))
                if rtt_match.group(4) is not None:
                    rtt_mdev = float(rtt_match.group(4))

        status = ObservationStatus.OBSERVED
        event_type = "PING_PROBE_SUCCESS" if received > 0 else "PING_PROBE_LOST"

        return PingMeasurement(
            evidence_id=evidence_id,
            incident_id=incident_id,
            source_router=src,
            probe_source=src,
            source_interface=None,
            event_type=event_type,
            observed_at=now,
            collected_at=self.now_utc(),
            source_type=EvidenceSourceType.ACTIVE_PING,
            collection_method=CollectionMethod.TRIGGERED_PROBE,
            collection_status=status,
            target_address=target_address,
            source_address=source_address,
            packets_lost=sent - received,
            packets_sent=sent,
            packets_received=received,
            packet_loss_pct=exact_loss,
            rtt_min_ms=rtt_min,
            rtt_avg_ms=rtt_avg,
            rtt_max_ms=rtt_max,
            rtt_mdev_ms=rtt_mdev,
            raw_reference=" ".join(cmd),
        )

    def collect(
        self,
        router_ids: list[str] | None = None,
        incident_id: str | None = None,
        probe_pairs: list[tuple[str, str]] | None = None,
    ) -> list[EvidenceRecord]:
        """Collect ping measurements for specified or default probe pairs."""
        pairs_to_probe = probe_pairs or DEFAULT_PROBE_PAIRS
        target_routers = set(self.filter_router_ids(router_ids))

        results: list[EvidenceRecord] = []
        for src, target in pairs_to_probe:
            if src in target_routers:
                record = self.probe(
                    source_router=src,
                    target_address=target,
                    count=5,
                    timeout_s=1,
                    incident_id=incident_id,
                )
                results.append(record)

        return results
