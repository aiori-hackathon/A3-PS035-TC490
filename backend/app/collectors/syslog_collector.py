"""
Syslog and daemon event log evidence collector for NEXORA.

Collects and normalizes timestamped events from FRRouting daemons and container logs
into immutable SyslogEvent evidence records.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import ClassVar

from app.collectors.base import BaseCollector
from app.schemas.evidence import (
    CollectionMethod,
    EvidenceRecord,
    EvidenceSourceType,
    ObservationStatus,
    SyslogEvent,
    SyslogSeverity,
)


class SyslogCollector(BaseCollector):
    """Collects SyslogEvent records from router container logs."""

    COLLECTOR_NAME: ClassVar[str] = "syslog"

    # RFC3339 docker timestamp pattern: 2026-10-19T06:43:33.275388668Z
    DOCKER_TS_PATTERN: ClassVar[re.Pattern] = re.compile(
        r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s+(.*)$"
    )

    # FRR embedded timestamp pattern: 2026/10/19 06:43:33
    FRR_TS_PATTERN: ClassVar[re.Pattern] = re.compile(
        r"(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})"
    )

    def _parse_timestamp(self, ts_str: str) -> datetime | None:
        """Parse Docker RFC3339 or ISO timestamp into timezone-aware UTC datetime."""
        try:
            # Handle nanoseconds by trimming to microseconds
            if "." in ts_str:
                base, fraction = ts_str.rstrip("Z").split(".", 1)
                clean_fraction = (fraction + "000000")[:6]
                clean_str = f"{base}.{clean_fraction}+00:00"
            else:
                clean_str = ts_str.rstrip("Z") + "+00:00"
            return datetime.fromisoformat(clean_str).astimezone(UTC)
        except Exception:
            return None

    def _infer_process_and_severity(self, message: str) -> tuple[str, SyslogSeverity]:
        """Infer emitting process and standard severity level from message content."""
        msg_upper = message.upper()

        # Emitting daemon / process
        process = "frr"
        if "WATCHFRR" in msg_upper:
            process = "watchfrr"
        elif "OSPF" in msg_upper or "OSPFD" in msg_upper:
            process = "ospfd"
        elif "ZEBRA" in msg_upper:
            process = "zebra"
        elif "STATIC" in msg_upper or "STATICD" in msg_upper:
            process = "staticd"
        elif "STARTUP" in msg_upper:
            process = "startup"

        # Severity mapping
        if any(w in msg_upper for w in ("CRITICAL", "PANIC", "FATAL", "CRASH")):
            severity = SyslogSeverity.CRITICAL
        elif any(w in msg_upper for w in ("ERROR", "FAILED", "DOWN", "STARVATION")):
            severity = SyslogSeverity.ERROR
        elif any(w in msg_upper for w in ("WARN", "WARNING", "DEPRECATED")):
            severity = SyslogSeverity.WARNING
        elif any(w in msg_upper for w in ("NOTICE", "STATE -> UP", "CONNECT SUCCEEDED")):
            severity = SyslogSeverity.NOTICE
        elif any(w in msg_upper for w in ("DEBUG", "TRACE")):
            severity = SyslogSeverity.DEBUG
        else:
            severity = SyslogSeverity.INFO

        return process, severity

    def collect(
        self,
        router_ids: list[str] | None = None,
        incident_id: str | None = None,
        tail: int = 50,
        since: str | None = None,
    ) -> list[EvidenceRecord]:
        target_routers = self.filter_router_ids(router_ids)
        records: list[EvidenceRecord] = []
        now = self.now_utc()

        for rid in target_routers:
            if not self.transport.is_router_running(rid):
                records.append(
                    SyslogEvent(
                        evidence_id=self.generate_evidence_id(rid, "unreachable"),
                        incident_id=incident_id,
                        source_router=rid,
                        source_interface=None,
                        event_type="ROUTER_UNAVAILABLE",
                        observed_at=now,
                        collected_at=now,
                        source_type=EvidenceSourceType.SYSLOG,
                        collection_method=CollectionMethod.PASSIVE_SYSLOG,
                        collection_status=ObservationStatus.COLLECTION_FAILED,
                        severity=SyslogSeverity.ERROR,
                        process_name="docker",
                        message_id=None,
                        raw_message=f"Router container for {rid} is not running",
                        raw_reference=f"docker://nexora-{rid.lower()}/unreachable",
                    )
                )
                continue

            lines = self.transport.get_logs(rid, tail=tail, since=since)
            if not lines:
                records.append(
                    SyslogEvent(
                        evidence_id=self.generate_evidence_id(rid, "no-logs"),
                        incident_id=incident_id,
                        source_router=rid,
                        source_interface=None,
                        event_type="NO_LOGS_AVAILABLE",
                        observed_at=now,
                        collected_at=now,
                        source_type=EvidenceSourceType.SYSLOG,
                        collection_method=CollectionMethod.PASSIVE_SYSLOG,
                        collection_status=ObservationStatus.NOT_COLLECTED,
                        severity=SyslogSeverity.INFO,
                        process_name="docker",
                        message_id=None,
                        raw_message="No recent log entries returned by container daemon",
                        raw_reference=f"docker://nexora-{rid.lower()}/empty",
                    )
                )
                continue

            for idx, raw_line in enumerate(lines):
                line = raw_line.strip()
                if not line:
                    continue

                observed_at = now
                payload = line

                # Try parsing Docker RFC3339 timestamp prefix
                ts_match = self.DOCKER_TS_PATTERN.match(line)
                if ts_match:
                    parsed_ts = self._parse_timestamp(ts_match.group(1))
                    if parsed_ts:
                        observed_at = parsed_ts
                    payload = ts_match.group(2)

                process, severity = self._infer_process_and_severity(payload)

                # Sanitise payload string to prevent oversized entries
                sanitized_message = payload[:4000]

                records.append(
                    SyslogEvent(
                        evidence_id=self.generate_evidence_id(rid, f"line-{idx}"),
                        incident_id=incident_id,
                        source_router=rid,
                        source_interface=None,
                        event_type="SYSLOG_MESSAGE",
                        observed_at=observed_at,
                        collected_at=now,
                        source_type=EvidenceSourceType.SYSLOG,
                        collection_method=CollectionMethod.PASSIVE_SYSLOG,
                        collection_status=ObservationStatus.OBSERVED,
                        severity=severity,
                        process_name=process,
                        message_id=None,
                        raw_message=sanitized_message,
                        raw_reference=f"docker://nexora-{rid.lower()}/logs/line-{idx}",
                    )
                )

        return records
