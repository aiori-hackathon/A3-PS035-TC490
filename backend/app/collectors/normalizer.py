"""
Evidence normalizer and schema validation service for NEXORA.

Ensures all evidence records adhere strictly to the Phase 01 domain contracts:
- Validates timezone-aware UTC datetimes
- Enforces strict ground-truth isolation (strips or flags any injected ground-truth labels)
- Supports deterministic JSON serialization and deserialization
- Reconciles missing data semantics (OBSERVED, UNKNOWN, NOT_COLLECTED, COLLECTION_FAILED)
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from app.schemas.evidence import (
    EvidenceRecord,
    EvidenceSourceType,
    InterfaceObservation,
    OSPFObservation,
    PingMeasurement,
    RouteObservation,
    SyslogEvent,
    TracerouteObservation,
)


class GroundTruthLeakageError(Exception):
    """Raised when ground-truth fault injection labels are detected in evidence records."""


# Ground-truth tokens that must never leak into diagnosis-facing evidence
GROUND_TRUTH_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "fault_type",
    "f1_link_failure",
    "f2_router_failure",
    "f3_ospf_config_mismatch",
    "f4_packet_loss",
    "f5_high_latency",
    "seeded_fault",
    "injected_loss",
    "injected_delay",
)


class EvidenceNormalizer:
    """Normalizes and validates evidence records prior to ingestion or snapshotting."""

    @classmethod
    def assert_no_ground_truth_leakage(cls, record_dict: dict[str, Any]) -> None:
        """Scan a record dict for any ground-truth identifiers or labels."""
        serialized = str(record_dict).lower()
        for token in GROUND_TRUTH_FORBIDDEN_TOKENS:
            if token in serialized:
                raise GroundTruthLeakageError(
                    f"Ground-truth token {token!r} detected in evidence record: {record_dict}"
                )

    @classmethod
    def normalize_record(cls, record: EvidenceRecord) -> EvidenceRecord:
        """Validate and normalize timestamps and fields of an EvidenceRecord."""
        # Ensure UTC timezone awareness
        if record.observed_at.tzinfo is None:
            record.observed_at = record.observed_at.replace(tzinfo=UTC)
        else:
            record.observed_at = record.observed_at.astimezone(UTC)

        if record.collected_at.tzinfo is None:
            record.collected_at = record.collected_at.replace(tzinfo=UTC)
        else:
            record.collected_at = record.collected_at.astimezone(UTC)

        # Ground-truth isolation check
        record_dump = record.model_dump(mode="json")
        cls.assert_no_ground_truth_leakage(record_dump)

        return record

    @classmethod
    def serialize_records(cls, records: list[EvidenceRecord]) -> list[dict[str, Any]]:
        """Serialize a list of evidence records to deterministic JSON dicts."""
        serialized = []
        for rec in records:
            norm_rec = cls.normalize_record(rec)
            serialized.append(norm_rec.model_dump(mode="json"))
        return serialized

    @classmethod
    def deserialize_record(cls, data: dict[str, Any]) -> EvidenceRecord:
        """Deserialize a dict into the appropriate typed EvidenceRecord subclass."""
        source_type = data.get("source_type")

        if source_type == EvidenceSourceType.INTERFACE_POLL.value:
            return InterfaceObservation.model_validate(data)
        elif source_type == EvidenceSourceType.OSPF_API.value:
            return OSPFObservation.model_validate(data)
        elif source_type == EvidenceSourceType.ROUTING_TABLE.value:
            return RouteObservation.model_validate(data)
        elif source_type == EvidenceSourceType.ACTIVE_PING.value:
            return PingMeasurement.model_validate(data)
        elif source_type == EvidenceSourceType.ACTIVE_TRACEROUTE.value:
            return TracerouteObservation.model_validate(data)
        elif source_type == EvidenceSourceType.SYSLOG.value:
            return SyslogEvent.model_validate(data)
        else:
            # Fallback to base EvidenceRecord
            return EvidenceRecord.model_validate(data)
