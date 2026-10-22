"""Offline-only provenance and timestamp audit; never imported by inference.

A filename is not an experiment identity. A capture binding must be written by
the capture workflow and retained separately from the inference payload. It binds
the exact canonical snapshot digest and snapshot ID to the truth's run ID.
It also records reset_started_at: recovery_timestamp may include convergence time
and is not a safe upper bound on fault activity.
Historical records without that binding cannot be retroactively certified.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.schemas.diagnosis import DiagnosisResult


def snapshot_digest(snapshot: dict) -> str:
    """SHA256 of canonical JSON, independent of file name or whitespace."""
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _range(values: list[datetime | None]) -> dict:
    known = [value for value in values if value is not None]
    return {
        "start": _iso(min(known)) if known else None,
        "end": _iso(max(known)) if known else None,
    }


def _timing(value: datetime | None, start: datetime | None, end: datetime | None) -> str:
    # A missing restoration time does not establish that the fault stayed active.
    if value is None or start is None or end is None or start >= end:
        return "UNKNOWN_TIMING"
    if value < start:
        return "BEFORE_FAULT"
    if value >= end:
        return "POST_FAULT_RECOVERY"
    return "FAULT_ACTIVE"


def _combined(classes: list[str]) -> str:
    if not classes or "UNKNOWN_TIMING" in classes:
        return "UNKNOWN_TIMING"
    return classes[0] if len(set(classes)) == 1 else "MIXED"


def audit_timing(
    snapshot: dict,
    results: list[DiagnosisResult],
    truth: Any,
    capture_binding: dict | None = None,
) -> dict:
    """Certify fault-time eligibility after inference, without altering predictions.

    Conservatively require the entire collection window AND every record's two
    timestamps to be fault-active. Invalid/unmatched data gets no accuracy credit
    or penalty. The per-record audit includes rejected/unused context so mixed
    captures cannot silently become an apparently valid fault-time benchmark.
    """
    reasons: list[str] = []
    expected_binding = {
        "run_id": getattr(truth, "run_id", None),
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_sha256": snapshot_digest(snapshot),
    }
    association_valid = bool(capture_binding) and all(
        bool(value) and capture_binding.get(key) == value
        for key, value in expected_binding.items()
    )
    if not association_valid:
        reasons.append(
            "Missing or mismatched capture binding (run ID, snapshot ID, canonical SHA256); "
            "scenario names and filenames do not establish a shared experiment."
        )
    injection = _timestamp(getattr(truth, "injection_timestamp", None))
    recovery = _timestamp(getattr(truth, "recovery_timestamp", None))
    interval_valid = injection is not None and recovery is not None and injection < recovery
    if not interval_valid:
        reasons.append("Injection/recovery interval is missing, naive, invalid, or unordered.")
    reset_started = _timestamp((capture_binding or {}).get("reset_started_at"))
    reset_valid = bool(
        interval_valid and reset_started is not None and injection < reset_started <= recovery
    )
    if not reset_valid:
        reasons.append(
            "A valid reset_started_at boundary is required to exclude restoration polling."
        )
    start = _timestamp(snapshot.get("collection_window_start"))
    end = _timestamp(snapshot.get("collection_window_end"))
    captured = _timestamp(snapshot.get("captured_at"))
    window_valid = start is not None and end is not None and start <= end
    if captured is None or (end is not None and captured < end):
        reasons.append("Capture completion time is missing, invalid, naive, or before window end.")
    window_class = (
        _combined([_timing(start, injection, recovery), _timing(end, injection, recovery)])
        if window_valid else "UNKNOWN_TIMING"
    )
    if not window_valid:
        reasons.append("Collection window is missing, naive, invalid, or unordered.")
    if window_class != "FAULT_ACTIVE":
        reasons.append(f"Collection window is {window_class} relative to declared truth.")
    if window_valid and reset_valid and end >= reset_started:
        reasons.append(
            "Collection overlaps or follows reset; fault-active capture is not established."
        )

    def actual_timing(value: datetime | None) -> str:
        if not association_valid or not reset_valid:
            return "UNKNOWN_TIMING"
        declared = _timing(value, injection, recovery)
        # Reset execution/convergence is an uncertain transition, not confirmed active or healthy.
        if declared == "FAULT_ACTIVE" and value >= reset_started:
            return "UNKNOWN_TIMING"
        return declared

    support: set[str] = set()
    contradiction: set[str] = set()
    for result in results:
        for ranked in result.ranked_hypotheses:
            support.update(ranked.hypothesis.supporting_evidence_ids)
            contradiction.update(ranked.hypothesis.contradictory_evidence_ids)
    referenced = support | contradiction
    seen: set[str] = set()
    payloads: dict[str, dict] = {}
    records = []
    observed_values = []
    collected_values = []
    invalid_record_count = 0
    for record in snapshot.get("evidence_records", []):
        evidence_id = record.get("evidence_id")
        if not evidence_id:
            reasons.append("An observation has no evidence ID.")
        elif evidence_id in payloads and payloads[evidence_id] != record:
            reasons.append(f"Conflicting payloads share evidence ID {evidence_id}.")
        payloads[evidence_id] = record
        seen.add(evidence_id)
        observed = _timestamp(record.get("observed_at"))
        collected = _timestamp(record.get("collected_at"))
        observed_values.append(observed)
        collected_values.append(collected)
        observed_class = _timing(observed, injection, recovery)
        collected_class = _timing(collected, injection, recovery)
        chronology_valid = (
            window_valid and observed is not None and collected is not None
            and start <= observed <= collected <= end
        )
        if not chronology_valid:
            invalid_record_count += 1
        records.append({
            "evidence_id": evidence_id,
            "observed_at": _iso(observed),
            "collected_at": _iso(collected),
            "observed_timing": observed_class,
            "collected_timing": collected_class,
            "actual_observed_timing": actual_timing(observed),
            "actual_collected_timing": actual_timing(collected),
            "chronology_valid": chronology_valid,
            "roles": (
                (["SUPPORT"] if evidence_id in support else [])
                + (["CONTRADICTION"] if evidence_id in contradiction else [])
            ),
        })
    missing_ids = sorted(referenced - seen)
    if missing_ids:
        reasons.append("Diagnosis references evidence IDs absent from the snapshot.")
    if not records:
        reasons.append("No timestamped observations are available.")
    if invalid_record_count:
        reasons.append(
            f"{invalid_record_count} records have missing/invalid timestamps, inverted "
            "observation/collection times, or times outside the collection window."
        )
    observation_counts = Counter(record["observed_timing"] for record in records)
    collection_counts = Counter(record["collected_timing"] for record in records)
    if records and (
        observation_counts["FAULT_ACTIVE"] != len(records)
        or collection_counts["FAULT_ACTIVE"] != len(records)
    ):
        reasons.append("Not all observation and collection timestamps are fault-active.")
    declared_timing = _combined(
        [window_class] + [record[field] for record in records
                          for field in ("observed_timing", "collected_timing")]
    ) if records else "UNKNOWN_TIMING"
    actual_class = _combined(
        [actual_timing(start), actual_timing(end)]
        + [record[field] for record in records
           for field in ("actual_observed_timing", "actual_collected_timing")]
    ) if records and window_valid else "UNKNOWN_TIMING"
    if actual_class != "FAULT_ACTIVE":
        reasons.append(
            f"Actual capture timing is {actual_class}; fault-active evidence is unverified."
        )
    return {
        "evaluable": not reasons,
        "association_valid": association_valid,
        "actual_capture_timing": actual_class,
        "declared_window_timing": window_class,
        "declared_capture_timing": declared_timing,
        "window_valid": window_valid,
        "interval_valid": interval_valid,
        "injection_timestamp": _iso(injection),
        "recovery_timestamp": _iso(recovery),
        "reset_started_at": _iso(reset_started),
        "collection_window_start": _iso(start),
        "collection_window_end": _iso(end),
        "captured_at": _iso(captured),
        "observation_range": _range(observed_values),
        "collection_range": _range(collected_values),
        "observation_counts": dict(sorted(observation_counts.items())),
        "collection_counts": dict(sorted(collection_counts.items())),
        "used_evidence_ids": sorted(referenced),
        "missing_referenced_evidence_ids": missing_ids,
        "records": records,
        "reasons": reasons,
    }
