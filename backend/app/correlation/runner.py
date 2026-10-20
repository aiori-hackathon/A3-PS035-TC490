#!/usr/bin/env python3
"""
NEXORA Phase 05 — Correlation Runner CLI.

Loads a sanitized evidence snapshot, builds a topology graph, runs the
correlation engine, and produces an auditable incident correlation report.

Usage
-----
  cd backend
  uv run python -m app.correlation.runner <snapshot_path> [--output <output_path>]

  # Example:
  uv run python -m app.correlation.runner \\
      ../evaluation/datasets/observations/baseline_snapshot.json

Notes
-----
- Input snapshot filenames are stripped and not passed into correlation features.
  The engine only sees the snapshot contents.
- Output filenames use neutral generated identifiers.
- No ground-truth labels are included in the report.
- Do NOT display experimental ground truth in inference results.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "backend"))

from app.correlation.engine import CorrelationEngine  # noqa: E402
from app.schemas.correlation import CorrelatedIncident, CorrelationResult  # noqa: E402


def load_snapshot(snapshot_path: Path) -> dict:
    """
    Load a snapshot from disk.

    The filename is NOT passed to the correlation engine — only the contents.
    This prevents scenario-specific filenames from leaking into correlation.
    """
    with open(snapshot_path, encoding="utf-8") as f:
        return json.load(f)


def format_incident_report(incident: CorrelatedIncident) -> str:
    """Format a single CorrelatedIncident for human-readable output."""
    lines: list[str] = [
        f"  ┌─ Incident: {incident.incident_id}",
        f"  │  Status:   {incident.status}",
        f"  │  Window:   {incident.correlation_window_start.isoformat()} → "
        f"{incident.correlation_window_end.isoformat()}",
        f"  │  Routers:  {', '.join(incident.affected_routers) or 'none'}",
        f"  │  Links:    {', '.join(incident.affected_links) or 'none'}",
        f"  │  Symptoms: {len(incident.symptoms)}",
        f"  │  Evidence: {len(incident.evidence_ids)} records",
    ]
    if incident.symptoms:
        lines.append("  │")
        lines.append("  │  Symptoms:")
        for sym in incident.symptoms[:10]:  # Limit display
            lines.append(
                f"  │    [{sym.category.value}] {sym.affected_component}: "
                f"{sym.description[:80]}{'...' if len(sym.description) > 80 else ''}"
            )
        if len(incident.symptoms) > 10:
            lines.append(f"  │    ... and {len(incident.symptoms) - 10} more")

    if incident.relationships:
        lines.append("  │")
        lines.append("  │  Correlation Relationships:")
        for rel in incident.relationships[:5]:
            lines.append(
                f"  │    [{rel.relationship_kind}] {rel.from_component} → {rel.to_component}"
            )
            expl = rel.explanation
            expl_short = (expl[:97] + "...") if len(expl) > 97 else expl
            lines.append(f"  │      {expl_short}")

    if incident.contradictory_observations:
        lines.append("  │")
        lines.append("  │  ⚠ Contradictory Observations:")
        for obs in incident.contradictory_observations:
            lines.append(f"  │    {obs[:120]}")

    if incident.missing_information:
        lines.append("  │")
        lines.append("  │  Missing Information:")
        for mi in incident.missing_information:
            lines.append(f"  │    {mi[:120]}")

    lines.append("  │")
    lines.append("  │  Correlation Explanation:")
    for line in incident.correlation_explanation.split("\n")[:8]:
        lines.append(f"  │    {line}")
    lines.append("  └─────────────────────────────────────────")
    return "\n".join(lines)


def run_correlation(
    snapshot_path: Path,
    output_path: Path | None = None,
    window_seconds: float = 120.0,
    packet_loss_threshold: float = 5.0,
    latency_threshold_ms: float = 10.0,
    verbose: bool = False,
) -> CorrelationResult:
    """
    Run the correlation engine on a snapshot and return the result.

    Parameters
    ----------
    snapshot_path : Path
        Path to the evidence snapshot JSON file.
        The filename is stripped — only the contents are used.
    output_path : Path | None
        If provided, write the JSON result to this path.
    window_seconds : float
        Temporal correlation window in seconds (default: 120).
    packet_loss_threshold : float
        Packet loss % threshold for PACKET_LOSS_ELEVATED symptom (default: 5.0).
    latency_threshold_ms : float
        RTT threshold in ms for LATENCY_ELEVATED symptom (default: 10.0).
    verbose : bool
        Print detailed output.
    """
    print(f"\n{'='*70}")
    print("NEXORA — Phase 05 Incident Correlation Engine")
    print(f"{'='*70}")
    print(f"Input:   {snapshot_path.name}  (filename NOT passed to engine)")
    print(f"Window:  {window_seconds}s")
    print(f"Loss threshold: {packet_loss_threshold}%")
    print(f"Latency threshold: {latency_threshold_ms}ms")
    print(f"Time:    {datetime.now(UTC).isoformat()}")
    print(f"{'='*70}")

    # Load snapshot — use only contents, not the filename
    snapshot_dict = load_snapshot(snapshot_path)
    snapshot_id = snapshot_dict.get("snapshot_id", "unknown")
    total_records = len(snapshot_dict.get("evidence_records", []))
    router_ids = snapshot_dict.get("router_ids", [])

    print(f"\nSnapshot ID:      {snapshot_id}")
    print(f"Router scope:     {', '.join(router_ids)}")
    print(f"Evidence records: {total_records}")
    print(f"Captured at:      {snapshot_dict.get('captured_at', 'unknown')}")

    if snapshot_dict.get("collector_errors"):
        print(f"\n⚠ Collector errors: {len(snapshot_dict['collector_errors'])}")
        for err in snapshot_dict["collector_errors"][:3]:
            print(f"   {err}")

    print(f"\n{'─'*70}")
    print("Running correlation engine...")
    print(f"{'─'*70}")

    # Correlation — does NOT receive the filename
    engine = CorrelationEngine(
        window_seconds=window_seconds,
        packet_loss_threshold=packet_loss_threshold,
        latency_threshold_ms=latency_threshold_ms,
    )
    result = engine.correlate_snapshot_dict(snapshot_dict)

    print(f"\nCorrelation Result ID:  {result.result_id}")
    print(f"Engine version:         {result.engine_version}")
    print(f"Total records:          {result.total_evidence_records}")
    print(f"Anomalous records:      {result.anomalous_record_count}")
    print(f"Duplicates removed:     {result.duplicate_records_removed}")
    print(f"Ground-truth isolated:  {result.ground_truth_isolation_verified}")
    print(f"Incidents grouped:      {len(result.incidents)}")

    if result.correlation_notes:
        print("\nNotes:")
        for note in result.correlation_notes:
            print(f"  • {note}")

    print(f"\n{'─'*70}")
    print("INCIDENT GROUPS:")
    print(f"{'─'*70}")

    if not result.incidents:
        print("  (No incidents — all evidence records indicate healthy baseline)")
    else:
        for incident in result.incidents:
            print()
            print(format_incident_report(incident))

    # Save output if requested
    if output_path is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_path = (
            _PROJECT_ROOT / "evaluation" / "datasets" / "correlations"
            / f"cr-{ts}-{uuid.uuid4().hex[:6]}.json"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result_dict = result.model_dump(mode="json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, indent=2, sort_keys=True)

    print(f"\n{'='*70}")
    print(f"Output written to: {output_path}")
    print(f"{'='*70}\n")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NEXORA Phase 05 — Correlation Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "snapshot",
        type=Path,
        help="Path to the evidence snapshot JSON file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to write correlation result JSON (default: auto-generated).",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=120.0,
        help="Temporal correlation window in seconds (default: 120).",
    )
    parser.add_argument(
        "--loss-threshold",
        type=float,
        default=5.0,
        help="Packet loss %% threshold for elevated symptom (default: 5.0).",
    )
    parser.add_argument(
        "--latency-threshold",
        type=float,
        default=10.0,
        help="RTT threshold in ms for latency elevated symptom (default: 10.0).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print verbose output.",
    )
    args = parser.parse_args()

    snapshot_path: Path = args.snapshot.resolve()
    if not snapshot_path.exists():
        print(f"Error: snapshot file not found: {snapshot_path}", file=sys.stderr)
        sys.exit(1)

    run_correlation(
        snapshot_path=snapshot_path,
        output_path=args.output,
        window_seconds=args.window,
        packet_loss_threshold=args.loss_threshold,
        latency_threshold_ms=args.latency_threshold,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
