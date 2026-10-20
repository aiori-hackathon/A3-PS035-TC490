"""
NEXORA Temporal Correlation Engine — Phase 05.

Implements configurable observation windows and temporal grouping of evidence
records. Handles:

  - Evidence collection timestamps (when collected) vs event timestamps (when observed)
  - Incomplete or delayed logs with missing timestamps
  - Out-of-order evidence from polling-based collection
  - Duplicate observations from repeated polling
  - OSPF dead-timer convergence lag (adjacency loss may lag physical event by ≥ 30s)
  - Evidence windows with configurable bounds

DESIGN PRINCIPLES:
  - All timestamps are timezone-aware UTC.
  - Windows are bounded and explicitly configurable; defaults are documented.
  - Polling-based collection does NOT fabricate event-order precision.
    If all records in a collection run share the same timestamp, they are
    treated as co-incident (simultaneous poll), not as ordered events.
  - OSPF dead-timer lag is explicitly accounted for in window calculations.
  - A missing timestamp is never treated as "earlier" — it is unknown.

Window Defaults (chosen conservatively for a 40-second OSPF dead timer lab):
  DEFAULT_WINDOW_SECONDS: 120s — covers dead-timer convergence (40s) plus lag
  MIN_WINDOW_SECONDS: 5s  — minimum meaningful window
  MAX_WINDOW_SECONDS: 600s — upper bound to prevent unbounded grouping

  OSPF_DEAD_TIMER_BUFFER_SECONDS: 45s — minimum window to capture OSPF lag events
  POLLING_JITTER_SECONDS: 5s — approximate polling interval tolerance
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.schemas.evidence import EvidenceRecord

# ---------------------------------------------------------------------------
# Window configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_SECONDS: float = 120.0
"""Default temporal correlation window in seconds.

Chosen to cover:
  - OSPF dead-timer (40s default) plus convergence lag
  - Polling interval jitter
  - Log delivery delay
"""

MIN_WINDOW_SECONDS: float = 5.0
"""Minimum allowed window. Prevents sub-second windows that would miss polling jitter."""

MAX_WINDOW_SECONDS: float = 600.0
"""Maximum allowed window. Prevents unbounded grouping across unrelated events."""

OSPF_DEAD_TIMER_BUFFER_SECONDS: float = 45.0
"""Minimum window needed to observe OSPF dead-timer expiry after a physical event.

Rationale: FRR default dead timer is 40s. Physical link failure → OSPF adjacency loss
may take up to 40s. Adding 5s buffer gives 45s minimum for this fault class.
"""

POLLING_JITTER_SECONDS: float = 5.0
"""Approximate polling jitter tolerance in seconds.

Evidence records from the same collection run may have timestamps spread over
several seconds due to serial polling. Records within this jitter window of
each other are treated as co-incident.
"""

SYSLOG_DELIVERY_DELAY_SECONDS: float = 10.0
"""Expected maximum delivery delay for syslog/daemon log events.

Docker log buffering may delay events by several seconds.
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ObservationWindow:
    """
    A bounded, explicit observation window for temporal correlation.

    Attributes
    ----------
    window_start : datetime
        UTC start of the observation window (inclusive).
    window_end : datetime
        UTC end of the observation window (inclusive).
    window_seconds : float
        Total duration of the window in seconds.
    rationale : str
        Why this window was chosen.
    anchor_time : datetime | None
        The timestamp that anchored this window (e.g. first alarm time).
    """

    window_start: datetime
    window_end: datetime
    window_seconds: float
    rationale: str
    anchor_time: datetime | None = None

    def contains(self, ts: datetime) -> bool:
        """Return True if ts falls within [window_start, window_end]."""
        return self.window_start <= ts <= self.window_end

    def overlaps_with(self, other: ObservationWindow) -> bool:
        """Return True if this window overlaps with another."""
        return self.window_start <= other.window_end and self.window_end >= other.window_start


@dataclass
class TemporalGroup:
    """
    A group of evidence records that fall within the same observation window.

    Evidence within a TemporalGroup may share a common temporal context
    but this does NOT imply a shared root cause.

    Attributes
    ----------
    group_id : str
        Stable identifier for this group (e.g. 'tg-0001').
    window : ObservationWindow
        The window that defines this group.
    evidence_ids : list[str]
        Evidence record IDs in this group, insertion-ordered.
    affected_routers : list[str]
        Router IDs referenced by evidence in this group.
    affected_links : list[str]
        Link IDs inferred from evidence in this group (may be empty).
    duplicate_count : int
        Number of duplicate/repeated evidence records removed.
    has_missing_timestamps : bool
        True if any record had a missing or invalid timestamp.
    notes : list[str]
        Temporal analysis notes (e.g. known lag, jitter, missing data).
    """

    group_id: str
    window: ObservationWindow
    evidence_ids: list[str] = field(default_factory=list)
    affected_routers: list[str] = field(default_factory=list)
    affected_links: list[str] = field(default_factory=list)
    duplicate_count: int = 0
    has_missing_timestamps: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.evidence_ids)

    def is_empty(self) -> bool:
        return len(self.evidence_ids) == 0


# ---------------------------------------------------------------------------
# Temporal correlator
# ---------------------------------------------------------------------------


class TemporalCorrelator:
    """
    Groups evidence records into temporal windows for incident correlation.

    Usage
    -----
    correlator = TemporalCorrelator(window_seconds=120.0)
    groups = correlator.group_by_window(records)
    """

    def __init__(
        self,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        polling_jitter_seconds: float = POLLING_JITTER_SECONDS,
        ospf_dead_timer_buffer_seconds: float = OSPF_DEAD_TIMER_BUFFER_SECONDS,
    ) -> None:
        if window_seconds < MIN_WINDOW_SECONDS:
            raise ValueError(
                f"window_seconds ({window_seconds}) < MIN_WINDOW_SECONDS ({MIN_WINDOW_SECONDS})"
            )
        if window_seconds > MAX_WINDOW_SECONDS:
            raise ValueError(
                f"window_seconds ({window_seconds}) > MAX_WINDOW_SECONDS ({MAX_WINDOW_SECONDS})"
            )

        self.window_seconds = window_seconds
        self.polling_jitter_seconds = polling_jitter_seconds
        self.ospf_dead_timer_buffer_seconds = ospf_dead_timer_buffer_seconds

    def extract_timestamp(self, record: EvidenceRecord) -> datetime | None:
        """
        Extract the best available timestamp from a record.

        Prefers observed_at (event time) over collected_at (ingestion time).
        Both must be timezone-aware UTC.

        Returns None only if both timestamps are unavailable (should not happen
        with validated EvidenceRecord instances but handled defensively).
        """
        ts = record.observed_at
        if ts is not None and ts.tzinfo is not None:
            return ts.astimezone(UTC)
        ts = record.collected_at
        if ts is not None and ts.tzinfo is not None:
            return ts.astimezone(UTC)
        return None

    def deduplicate(self, records: list[EvidenceRecord]) -> tuple[list[EvidenceRecord], int]:
        """
        Remove exact duplicate evidence records.

        Two records are considered duplicates if they share the same:
        - source_router
        - source_type
        - event_type
        - source_interface
        - observed_at (within POLLING_JITTER_SECONDS)

        Note: evidence_id is globally unique, so records are never identical
        by ID. This deduplication handles logical duplicates from repeated polls.

        Returns
        -------
        tuple[list[EvidenceRecord], int]
            (deduplicated list, number of duplicates removed)
        """
        seen: set[tuple] = set()
        unique: list[EvidenceRecord] = []
        duplicates_removed = 0

        for rec in records:
            ts = self.extract_timestamp(rec)
            # Round timestamp to nearest jitter bucket
            if ts is not None:
                bucket = int(ts.timestamp() / self.polling_jitter_seconds)
            else:
                bucket = -1  # Unknown timestamp bucket

            key = (
                rec.source_router,
                rec.source_type.value,
                rec.event_type,
                rec.source_interface or "",
                bucket,
            )
            if key in seen:
                duplicates_removed += 1
            else:
                seen.add(key)
                unique.append(rec)

        return unique, duplicates_removed

    def compute_window(
        self,
        records: list[EvidenceRecord],
        anchor_time: datetime | None = None,
    ) -> ObservationWindow:
        """
        Compute an appropriate observation window for a set of records.

        If an anchor_time is provided, the window is centered around it.
        Otherwise, the window spans from the earliest to latest timestamp
        in the records, extended by the configured window_seconds.

        Policy:
        - Single-timestamp collections (all records at same time): window extends
          ±window_seconds/2 from that timestamp.
        - Multi-timestamp collections: window spans earliest to latest,
          extended by OSPF dead timer buffer on each end.

        Returns
        -------
        ObservationWindow
        """
        timestamps = [
            self.extract_timestamp(rec)
            for rec in records
            if self.extract_timestamp(rec) is not None
        ]

        # Note whether any records are missing timestamps (used later in group assembly)

        if not timestamps:
            # All timestamps unknown — use current time as anchor
            now = datetime.now(UTC)
            return ObservationWindow(
                window_start=now - timedelta(seconds=self.window_seconds / 2),
                window_end=now + timedelta(seconds=self.window_seconds / 2),
                window_seconds=self.window_seconds,
                rationale=(
                    "No timestamps available in records. Window centered on current time. "
                    "Event ordering cannot be determined from polling data."
                ),
                anchor_time=anchor_time,
            )

        earliest = min(timestamps)
        latest = max(timestamps)
        span = (latest - earliest).total_seconds()

        if anchor_time is not None:
            # Anchor-based window
            half_window = timedelta(seconds=self.window_seconds / 2)
            return ObservationWindow(
                window_start=anchor_time - half_window,
                window_end=anchor_time + timedelta(seconds=self.window_seconds),
                window_seconds=self.window_seconds + self.window_seconds / 2,
                rationale=(
                    f"Window anchored to {anchor_time.isoformat()}. "
                    f"Extends {self.window_seconds/2:.0f}s before and "
                    f"{self.window_seconds:.0f}s after anchor to capture "
                    f"OSPF dead-timer convergence ({self.ospf_dead_timer_buffer_seconds:.0f}s)."
                ),
                anchor_time=anchor_time,
            )

        if span < self.polling_jitter_seconds:
            # All records effectively co-incident (single collection run)
            midpoint = earliest + timedelta(seconds=span / 2)
            half_window = timedelta(seconds=self.window_seconds / 2)
            rationale = (
                f"All {len(timestamps)} timestamps within {span:.1f}s of each other — "
                f"treated as a single collection run. Window extends ±{self.window_seconds/2:.0f}s "
                f"from collection midpoint to capture any pre-existing or delayed events."
            )
        else:
            # Spread records: extend by OSPF buffer on each side
            buffer = timedelta(seconds=self.ospf_dead_timer_buffer_seconds)
            return ObservationWindow(
                window_start=earliest - buffer,
                window_end=latest + buffer,
                window_seconds=(latest - earliest + 2 * buffer).total_seconds(),
                rationale=(
                    f"Records span {span:.1f}s. Window extended by "
                    f"{self.ospf_dead_timer_buffer_seconds:.0f}s on each side to account for "
                    f"OSPF dead-timer convergence lag and syslog delivery delay."
                ),
                anchor_time=earliest,
            )
            # Note: rationale is set in the else branch above; this satisfies mypy

        midpoint = earliest + timedelta(seconds=span / 2)
        half_window = timedelta(seconds=self.window_seconds / 2)
        return ObservationWindow(
            window_start=midpoint - half_window,
            window_end=midpoint + half_window,
            window_seconds=self.window_seconds,
            rationale=rationale,  # type: ignore[possibly-undefined]
            anchor_time=earliest,
        )

    def is_within_window(
        self, record: EvidenceRecord, window: ObservationWindow
    ) -> bool:
        """
        Return True if a record falls within a given window.

        Records with no usable timestamp are included in the window
        (conservative: we cannot exclude what we cannot place).
        """
        ts = self.extract_timestamp(record)
        if ts is None:
            return True  # Cannot exclude unknown-timestamp records
        return window.contains(ts)

    def group_by_window(
        self,
        records: list[EvidenceRecord],
        router_link_map: dict[str, list[str]] | None = None,
    ) -> list[TemporalGroup]:
        """
        Group evidence records by temporal proximity.

        Algorithm:
        1. Deduplicate records.
        2. Extract timestamps; flag missing.
        3. Sort by timestamp (NaT records placed last).
        4. Greedily assign records to windows: a new window starts when
           the current record is more than window_seconds after the window anchor.
        5. Each window becomes a TemporalGroup.

        Parameters
        ----------
        records : list[EvidenceRecord]
            Unsorted, possibly duplicate evidence records.
        router_link_map : dict[str, list[str]] | None
            Optional map of router_id → [link_ids] for link attribution.

        Returns
        -------
        list[TemporalGroup]
            Ordered list of non-overlapping temporal groups.
        """
        if not records:
            return []

        # 1. Deduplicate
        deduped, dup_count = self.deduplicate(records)

        # 2. Extract timestamps and separate records with/without timestamps
        timestamped: list[tuple[datetime, EvidenceRecord]] = []
        no_timestamp: list[EvidenceRecord] = []

        for rec in deduped:
            ts = self.extract_timestamp(rec)
            if ts is None:
                no_timestamp.append(rec)
            else:
                timestamped.append((ts, rec))

        # 3. Sort by timestamp
        timestamped.sort(key=lambda x: x[0])

        # 4. Greedy windowing
        groups: list[TemporalGroup] = []
        group_counter = [0]

        def new_group(anchor_ts: datetime, rationale: str) -> TemporalGroup:
            group_counter[0] += 1
            gid = f"tg-{group_counter[0]:04d}"
            window = ObservationWindow(
                window_start=anchor_ts,
                window_end=anchor_ts + timedelta(seconds=self.window_seconds),
                window_seconds=self.window_seconds,
                rationale=rationale,
                anchor_time=anchor_ts,
            )
            return TemporalGroup(group_id=gid, window=window)

        current_group: TemporalGroup | None = None

        for ts, rec in timestamped:
            if current_group is None:
                current_group = new_group(
                    ts,
                    f"Window anchored at {ts.isoformat()} (first timestamped record). "
                    f"Duration: {self.window_seconds:.0f}s to capture OSPF convergence.",
                )

            if self.is_within_window(rec, current_group.window):
                current_group.evidence_ids.append(rec.evidence_id)
                router = rec.source_router
                if router not in current_group.affected_routers:
                    current_group.affected_routers.append(router)
            else:
                # Close current group and start a new one
                if current_group.size > 0:
                    groups.append(current_group)
                current_group = new_group(
                    ts,
                    f"New window starting at {ts.isoformat()} — prior window ended at "
                    f"{current_group.window.window_end.isoformat()}.",
                )
                current_group.evidence_ids.append(rec.evidence_id)
                current_group.affected_routers.append(rec.source_router)

        if current_group is not None and current_group.size > 0:
            groups.append(current_group)

        # 5. Handle no-timestamp records: assign to largest group or create one
        if no_timestamp:
            if groups:
                # Add to first group with a note
                target_group = groups[0]
                for rec in no_timestamp:
                    if rec.evidence_id not in target_group.evidence_ids:
                        target_group.evidence_ids.append(rec.evidence_id)
                        if rec.source_router not in target_group.affected_routers:
                            target_group.affected_routers.append(rec.source_router)
                target_group.has_missing_timestamps = True
                target_group.notes.append(
                    f"{len(no_timestamp)} records had missing timestamps; "
                    f"placed in group {target_group.group_id} (cannot determine order)."
                )
            else:
                # All records lack timestamps
                group_counter[0] += 1
                gid = f"tg-{group_counter[0]:04d}"
                now = datetime.now(UTC)
                window = ObservationWindow(
                    window_start=now - timedelta(seconds=self.window_seconds),
                    window_end=now,
                    window_seconds=self.window_seconds,
                    rationale="All records lack timestamps; window uses current time.",
                    anchor_time=now,
                )
                nt_group = TemporalGroup(
                    group_id=gid,
                    window=window,
                    evidence_ids=[r.evidence_id for r in no_timestamp],
                    affected_routers=sorted(
                        set(r.source_router for r in no_timestamp)
                    ),
                    has_missing_timestamps=True,
                    notes=["All records in this group have missing timestamps."],
                )
                groups.append(nt_group)

        # Propagate duplicate count to first group
        if groups:
            groups[0].duplicate_count = dup_count

        return groups

    def merge_overlapping_groups(
        self, groups: list[TemporalGroup]
    ) -> list[TemporalGroup]:
        """
        Merge temporal groups whose windows overlap.

        Two groups are merged if their windows overlap AND their affected
        routers share common topology proximity. This is a simple overlap
        check; topology adjacency is applied by the correlation engine.

        Returns
        -------
        list[TemporalGroup]
            Merged groups with combined evidence and notes.
        """
        if len(groups) <= 1:
            return groups

        merged: list[TemporalGroup] = []
        groups_sorted = sorted(groups, key=lambda g: g.window.window_start)
        current = groups_sorted[0]

        for next_group in groups_sorted[1:]:
            if current.window.overlaps_with(next_group.window):
                # Merge next_group into current
                for eid in next_group.evidence_ids:
                    if eid not in current.evidence_ids:
                        current.evidence_ids.append(eid)
                for router in next_group.affected_routers:
                    if router not in current.affected_routers:
                        current.affected_routers.append(router)
                for link in next_group.affected_links:
                    if link not in current.affected_links:
                        current.affected_links.append(link)
                # Extend window
                new_end = max(
                    current.window.window_end, next_group.window.window_end
                )
                current.window = ObservationWindow(
                    window_start=current.window.window_start,
                    window_end=new_end,
                    window_seconds=(
                        new_end - current.window.window_start
                    ).total_seconds(),
                    rationale=(
                        f"{current.window.rationale} | Merged with {next_group.group_id}: "
                        f"windows overlap."
                    ),
                    anchor_time=current.window.anchor_time,
                )
                current.duplicate_count += next_group.duplicate_count
                if next_group.has_missing_timestamps:
                    current.has_missing_timestamps = True
                current.notes.extend(next_group.notes)
            else:
                merged.append(current)
                current = next_group

        merged.append(current)
        return merged

    @staticmethod
    def describe_time_relationship(
        rec_a: EvidenceRecord,
        rec_b: EvidenceRecord,
        jitter_seconds: float = POLLING_JITTER_SECONDS,
    ) -> str:
        """
        Describe the time relationship between two evidence records.

        Returns a human-readable explanation. Does NOT infer causation.
        """
        ts_a = rec_a.observed_at
        ts_b = rec_b.observed_at

        if ts_a is None or ts_b is None:
            return (
                f"Time relationship between {rec_a.evidence_id} and {rec_b.evidence_id} "
                f"is unknown (missing timestamp)."
            )

        delta = abs((ts_b - ts_a).total_seconds())

        if delta <= jitter_seconds:
            return (
                f"Records {rec_a.evidence_id} and {rec_b.evidence_id} are co-incident "
                f"(Δt={delta:.1f}s, within polling jitter of {jitter_seconds:.0f}s). "
                f"Event ordering cannot be determined from polling timestamps."
            )
        elif delta <= OSPF_DEAD_TIMER_BUFFER_SECONDS:
            return (
                f"Records {rec_a.evidence_id} and {rec_b.evidence_id} are temporally close "
                f"(Δt={delta:.1f}s). Δt is within OSPF dead-timer convergence window "
                f"({OSPF_DEAD_TIMER_BUFFER_SECONDS:.0f}s). Earlier event may have triggered later."
            )
        else:
            first = rec_a.evidence_id if ts_a <= ts_b else rec_b.evidence_id
            second = rec_b.evidence_id if ts_a <= ts_b else rec_a.evidence_id
            return (
                f"Records are temporally separated by {delta:.1f}s. "
                f"{first} observed before {second}. "
                f"Relationship requires additional topology context."
            )
