"""Strict validation for NEW capture artifacts; legacy replay remains separate."""

from collections import Counter
from datetime import UTC, datetime
from math import isfinite

from app.collectors.normalizer import EvidenceNormalizer
from app.collectors.orchestrator import EvidenceSnapshot
from app.schemas.evidence import (
    EvidenceRecord,
    ObservationStatus,
    OSPFObservation,
    PingAttemptFailure,
    PingMeasurement,
    RouteObservation,
)


def validate_capture(snapshot: dict) -> list[str]:
    """Fail on lossy/invalid records, return explicit optional-measurement gaps."""
    EvidenceNormalizer.assert_no_ground_truth_leakage(snapshot)
    parsed = EvidenceSnapshot.model_validate(snapshot)
    start, end = parsed.collection_window_start, parsed.collection_window_end
    for stamp in (start, end, parsed.captured_at):
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("Capture timestamps must be timezone-aware")
    if not start <= end <= parsed.captured_at:
        raise ValueError("Invalid capture chronology")
    if parsed.collector_errors:
        raise ValueError(f"Collector/serialization errors: {parsed.collector_errors}")
    if not parsed.evidence_records or parsed.total_records != len(parsed.evidence_records):
        raise ValueError("Missing or inconsistent evidence record count")
    if dict(Counter(r["source_type"] for r in parsed.evidence_records)) != parsed.records_by_type:
        raise ValueError("Record type counts do not match")
    missing = []
    ids = set()
    for raw in parsed.evidence_records:
        record = EvidenceNormalizer.deserialize_record(raw)
        if type(record) is EvidenceRecord:
            raise ValueError("Untyped/legacy evidence is not a lossless new capture")
        if record.evidence_id in ids:
            raise ValueError("Duplicate evidence ID in new capture")
        ids.add(record.evidence_id)
        if not start <= record.observed_at <= record.collected_at <= end:
            raise ValueError("Evidence timestamps outside capture window or inverted")
        # Detect dropped/unknown fields even when the legacy deserializer falls back.
        restored = record.model_dump(mode="json")
        if any(
            key not in restored or restored[key] != value
            for key, value in raw.items()
            if key not in {"observed_at", "collected_at", "interface_config_observed_at"}
        ):
            raise ValueError("Serialization round-trip changed evidence fields")
        if isinstance(record, PingAttemptFailure):
            missing.append(f"{record.evidence_id}: probe failed; no measured counts/loss/RTT")
        if (
            isinstance(record, PingMeasurement)
            and record.collection_status != ObservationStatus.OBSERVED
        ):
            raise ValueError("Failed probes must explicitly omit unmeasured statistics")
        if (
            isinstance(record, PingMeasurement)
            and record.collection_status == ObservationStatus.OBSERVED
        ):
            if record.packets_lost != record.packets_sent - record.packets_received:
                raise ValueError("Missing or inconsistent measured lost packet count")
            if record.source_address is None:
                raise ValueError("Measured probe source address missing")
            if record.packets_received and any(
                v is None
                for v in (
                    record.rtt_min_ms,
                    record.rtt_avg_ms,
                    record.rtt_max_ms,
                )
            ):
                raise ValueError("Replies without RTT measurements")
            if any(
                value is not None and not isfinite(value)
                for value in (
                    record.rtt_min_ms,
                    record.rtt_avg_ms,
                    record.rtt_max_ms,
                    record.rtt_mdev_ms,
                )
            ):
                raise ValueError("RTT values must be finite")
            if record.packets_received and not (
                0 <= record.rtt_min_ms <= record.rtt_avg_ms <= record.rtt_max_ms
            ):
                raise ValueError("Invalid RTT ordering")
        if isinstance(record, OSPFObservation):
            if record.observed_interface_config is None:
                missing.append(
                    f"{record.evidence_id}: observed OSPF interface configuration unavailable"
                )
            else:
                stamp = record.interface_config_observed_at
                if stamp is None or stamp.tzinfo is None or not start <= stamp <= end:
                    raise ValueError(
                        "Observed OSPF configuration timestamp missing or out of window"
                    )
        if isinstance(record, RouteObservation) and record.is_present:
            if record.next_hop_address is None and record.next_hop_interface is None:
                missing.append(f"{record.evidence_id}: route egress unavailable")
    return missing


def utc_now() -> datetime:
    return datetime.now(UTC)
