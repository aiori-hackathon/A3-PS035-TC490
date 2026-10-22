"""Offline Phase 06.1 evaluation with provenance and fault-time eligibility gates.

Every snapshot (including the healthy control) is diagnosed before any truth file
is opened or ``FaultInjectionRecord`` is imported. Only snapshot dictionaries cross
the inference boundary. The manifest, paths, and expected labels stay here.

Usage from ``backend``::

    uv run python -m app.evaluation.phase06
    uv run python -m app.evaluation.phase06 --output-dir /tmp/nexora-evaluation

Unbound, unknown-timing, pre-fault and post-recovery captures are NOT EVALUABLE.
Accuracy denominators include only verified fault-active cases. Historical output
file names are preserved for CLI compatibility.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evaluation.timing import audit_timing
from app.schemas.diagnosis import DiagnosisResult, DiagnosisStatus

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MANIFEST = Path("evaluation/datasets/phase06_manifest.json")

DiagnoseSnapshot = Callable[[dict], list[DiagnosisResult]]


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _default_inference(snapshot: dict) -> list[DiagnosisResult]:
    # Keep the offline truth model out of this import path.
    from app.diagnosis.engine import DiagnosisEngine

    return DiagnosisEngine().diagnose_snapshot_dict(snapshot)


def _load_truth(path: Path) -> Any:
    # ISOLATION BOUNDARY: called only after ALL inference and neutral artifacts finish.
    from app.evaluation.ground_truth import FaultInjectionRecord

    return FaultInjectionRecord.model_validate(_load_json(path))


def rank_snapshot_hypotheses(results: list[DiagnosisResult]) -> list[dict]:
    """Merge incident rankings into one deterministic snapshot ranking.

    One type/location pair can occupy at most one slot. Highest score wins;
    score ties use fault type and component ID. Insufficient results abstain and
    contribute no candidates, even if their diagnostic audit includes candidates.
    Ambiguous results retain tentative rankings and are counted separately.
    """
    candidates: dict[tuple[str, str], dict] = {}
    for result in results:
        if result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE:
            continue
        for ranked in result.ranked_hypotheses:
            hypothesis = ranked.hypothesis
            key = (hypothesis.fault_type.value, hypothesis.fault_location.component_id)
            candidate = {
                "fault_type": key[0],
                "component_id": key[1],
                "rule_score": hypothesis.rule_score,
                "hypothesis_id": hypothesis.hypothesis_id,
                "incident_id": result.incident_id,
            }
            existing = candidates.get(key)
            if existing is None or (
                -candidate["rule_score"], candidate["hypothesis_id"]
            ) < (-existing["rule_score"], existing["hypothesis_id"]):
                candidates[key] = candidate
    return sorted(
        candidates.values(),
        key=lambda item: (-item["rule_score"], item["fault_type"], item["component_id"]),
    )


def accepted_snapshot_top1(results: list[DiagnosisResult]) -> dict | None:
    """Select an accepted diagnosis, abstaining on close distinct incident roots.

    Multiple incident diagnoses do not establish one global root. When two
    distinct accepted roots are within 0.10 heuristic score, global Top-1 abstains;
    the merged Top-3 can still describe those competing incident roots.
    """
    accepted = [
        result.top1_hypothesis for result in results
        if result.status == DiagnosisStatus.DIAGNOSED and result.top1_hypothesis is not None
    ]
    if not accepted:
        return None
    winner = min(
        accepted,
        key=lambda item: (
            -item.rule_score, item.fault_type.value, item.fault_location.component_id,
            item.hypothesis_id,
        ),
    )
    winner_key = (winner.fault_type, winner.fault_location.component_id)
    if any(
        (candidate.fault_type, candidate.fault_location.component_id) != winner_key
        and winner.rule_score - candidate.rule_score <= 0.10 + 1e-9
        for candidate in accepted
    ):
        return None
    return {
        "fault_type": winner.fault_type.value,
        "component_id": winner.fault_location.component_id,
        "rule_score": winner.rule_score,
        "hypothesis_id": winner.hypothesis_id,
        "incident_id": winner.incident_id,
    }


def _case_report(
    case: dict, snapshot: dict, results: list[DiagnosisResult], truth: Any,
    capture_binding: dict | None = None,
) -> dict:
    ranking = rank_snapshot_hypotheses(results)
    accepted_top1 = accepted_snapshot_top1(results)
    expected = (truth.seeded_fault_type.value, truth.actual_fault_location_id)
    predicted = [(item["fault_type"], item["component_id"]) for item in ranking[:3]]
    timing = audit_timing(snapshot, results, truth, capture_binding)
    synthetic = (capture_binding or {}).get("synthetic") is True
    valid = timing["evaluable"] and not synthetic
    statuses = Counter(result.status.value for result in results)
    snapshot_ambiguous = accepted_top1 is None and any(
        result.status == DiagnosisStatus.DIAGNOSED and result.top1_hypothesis is not None
        for result in results
    )
    top1_type = bool(accepted_top1 and accepted_top1["fault_type"] == expected[0])
    top1_location = bool(accepted_top1 and accepted_top1["component_id"] == expected[1])
    return {
        "case_id": case["case_id"],
        "snapshot_path": case["snapshot_path"],
        "truth_path": case["truth_path"],
        "declared_truth_run_id": getattr(truth, "run_id", None),
        "expected_fault_type": expected[0],
        "expected_component_id": expected[1],
        "evaluation_status": (
            "SYNTHETIC_VALIDATION_ONLY" if synthetic else "EVALUABLE" if valid else "NOT EVALUABLE"
        ),
        "synthetic": synthetic,
        "timing": timing,
        "top1": accepted_top1,
        "top3": ranking[:3],
        # None means excluded, not a hit or a miss. Predictions remain intact for audit.
        "top1_correct": (top1_type and top1_location) if valid else None,
        "top3_correct": (expected in predicted) if valid else None,
        "top1_fault_type_correct": top1_type if valid else None,
        "top1_location_correct": top1_location if valid else None,
        "top3_fault_type_correct": any(p[0] == expected[0] for p in predicted) if valid else None,
        "top3_location_correct": any(p[1] == expected[1] for p in predicted) if valid else None,
        "abstained": accepted_top1 is None,
        "ambiguous": DiagnosisStatus.AMBIGUOUS.value in statuses or snapshot_ambiguous,
        "snapshot_top1_ambiguous": snapshot_ambiguous,
        "diagnosis_status_counts": dict(sorted(statuses.items())),
        "diagnosis_count": len(results),
        "diagnosis_summaries": [
            {
                "result_id": result.result_id,
                "status": result.status.value,
                "reasoning_summary": result.evidence_certificate.reasoning_summary,
                "missing_information": result.missing_information,
                "total_evidence_count": result.evidence_certificate.total_evidence_count,
                "collection_coverage_pct": result.evidence_certificate.collection_coverage_pct,
            }
            for result in results
        ],
        "evidence_sufficiency_met": bool(results) and all(
            result.evidence_certificate.evidence_sufficiency_met for result in results
        ),
        "limitations": timing["reasons"],
    }


def _coverage(cases: list[dict]) -> dict:
    count = len(cases)
    accepted = sum(not case["abstained"] for case in cases)
    return {
        "case_count": count,
        "accepted_top1_count": accepted,
        "accepted_top1_rate": accepted / count if count else None,
        "abstention_count": count - accepted,
        "abstention_rate": (count - accepted) / count if count else None,
        "ambiguous_case_count": sum(case["ambiguous"] for case in cases),
        "sufficient_case_count": sum(case["evidence_sufficiency_met"] for case in cases),
    }


def _valid_metrics(cases: list[dict]) -> dict:
    valid = [case for case in cases if case["evaluation_status"] == "EVALUABLE"]
    metrics = {"case_count": len(valid)}
    for field in (
        "top1_correct", "top3_correct", "top1_fault_type_correct", "top1_location_correct",
        "top3_fault_type_correct", "top3_location_correct",
    ):
        metrics[field] = sum(case[field] for case in valid)
        metrics[field.replace("correct", "accuracy")] = (
            metrics[field] / len(valid) if valid else None
        )
    return metrics


def _format_report(report: dict) -> str:
    metrics = report["valid_fault_metrics"]
    denominator = metrics["case_count"]
    accuracy = (
        f"Top-1 {metrics['top1_correct']}/{denominator}; "
        f"Top-3 {metrics['top3_correct']}/{denominator}"
        if denominator else "Top-1 N/A; Top-3 N/A (zero evaluable fault-active cases)"
    )
    coverage = report["coverage"]["all_cases"]
    lines = [
        "# Phase 06.1 offline evaluation",
        "",
        f"Engine: {', '.join(report['engine_versions']) or 'no diagnosis results'}.",
        "Scores are deterministic heuristics, not calibrated probabilities.",
        "",
        f"**Valid fault-time results: {accuracy}.**",
        f"Raw abstentions: {coverage['abstention_count']}/{coverage['case_count']}. "
        "Coverage and abstention describe completed inference, independent of truth validity.",
        "NOT EVALUABLE cases receive neither accuracy credit nor penalty; correctness is null.",
        "For eligible cases, Top-1 requires an accepted DIAGNOSED root; AMBIGUOUS may retain "
        "tentative Top-3 credit. INSUFFICIENT_EVIDENCE abstains at both ranks.",
        "",
        "| Case | Declared type/location | Accepted Top-1 | Evaluation | "
        "Declared interval timing | Actual capture timing |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in report["cases"]:
        top1 = case["top1"]
        prediction = f"{top1['fault_type']} / {top1['component_id']}" if top1 else "abstained"
        lines.append(
            f"| {case['case_id']} | {case['expected_fault_type']} / "
            f"{case['expected_component_id']} | {prediction} | {case['evaluation_status']} | "
            f"{case['timing']['declared_capture_timing']} | "
            f"{case['timing']['actual_capture_timing']} |"
        )
    lines += [
        "",
        "Timing relative to an unbound historical truth record is diagnostic audit information, "
        "not proof of the state of the snapshot's own experiment. No missing time is invented.",
        "",
        "| Case | Injection → recorded recovery (UTC) | Snapshot window (UTC) | "
        "All observations / collections (UTC) |",
        "| --- | --- | --- | --- |",
    ]
    for case in report["cases"]:
        timing = case["timing"]
        observed = timing["observation_range"]
        collected = timing["collection_range"]
        lines.append(
            f"| {case['case_id']} | {timing['injection_timestamp']} → "
            f"{timing['recovery_timestamp']} | {timing['collection_window_start']} → "
            f"{timing['collection_window_end']} | {observed['start']} → {observed['end']} / "
            f"{collected['start']} → {collected['end']} |"
        )
    lines += [
        "",
        f"Declared healthy baseline: {report['baseline']['diagnosis_count']} diagnosis results; "
        f"any fault candidate: {report['baseline']['false_positive']}; "
        f"accepted fault: {report['baseline']['accepted_false_positive']}.",
        "The baseline is a separately declared control, excluded from fault accuracy denominators.",
        "",
        "Every inference call and neutral diagnosis artifact write completed before truth or "
        "capture bindings were read. No metadata is used to filter or rerun inference.",
        "",
        "Exact Top-1/Top-3 correctness requires type AND location in the same hypothesis. "
        "The JSON reports type and location correctness separately, plus eligible-case and "
        "all-case coverage, timestamp validity, and each real evidence ID's timestamps/roles.",
        "",
        "## Limitations", "",
    ]
    lines += [f"- {limitation}" for limitation in report["limitations"]]
    lines += ["", "## Per-snapshot reasoning", ""]
    for case in report["cases"]:
        top3 = "; ".join(
            f"{item['fault_type']} / {item['component_id']} ({item['rule_score']:.3f})"
            for item in case["top3"]
        ) or "no sufficient ranking"
        lines += [f"### Case {case['case_id']}", "", f"Top-3: {top3}.", ""]
        for summary in case["diagnosis_summaries"]:
            lines.append(
                f"- {summary['status']} using {summary['total_evidence_count']} evidence "
                f"records; represented collection coverage "
                f"{summary['collection_coverage_pct']:.2f}%: {summary['reasoning_summary']}"
            )
            if summary["missing_information"]:
                lines.append("  Missing: " + "; ".join(summary["missing_information"]))
        lines += [f"- {reason}" for reason in case["limitations"]]
        lines.append("")
    return "\n".join(lines) + "\n"


def run_offline_evaluation(
    project_root: Path = _PROJECT_ROOT,
    manifest_path: Path | None = None,
    output_dir: Path | None = None,
    diagnose_snapshot: DiagnoseSnapshot | None = None,
) -> dict:
    """Run every inference first, then compare completed results to offline truth."""
    manifest_path = manifest_path or project_root / _DEFAULT_MANIFEST
    output_dir = output_dir or project_root / "evaluation/reports"
    manifest = _load_json(manifest_path)
    cases = manifest["cases"]
    case_ids = [case["case_id"] for case in cases]
    if not cases or len(set(case_ids)) != len(case_ids):
        raise ValueError("The evaluation manifest requires nonempty, unique case IDs")
    if any(not case_id.isalnum() for case_id in case_ids):
        raise ValueError("Case IDs must be neutral alphanumeric identifiers")
    inference = diagnose_snapshot or _default_inference
    completed: list[tuple[dict, dict, list[DiagnosisResult]]] = []
    baseline_snapshot = _load_json(project_root / manifest["baseline_snapshot_path"])
    baseline_results = inference(baseline_snapshot)
    _write_json(output_dir / "phase06-diagnoses/control.json", {
        "diagnoses": [result.model_dump(mode="json") for result in baseline_results],
    })
    for case in cases:
        snapshot = _load_json(project_root / case["snapshot_path"])
        results = inference(snapshot)
        completed.append((case, snapshot, results))
        _write_json(output_dir / f"phase06-diagnoses/diagnosis-{case['case_id']}.json", {
            "diagnoses": [result.model_dump(mode="json") for result in results],
        })

    # No inference is permitted below this boundary. The truth model is lazy-loaded here.
    evaluated_cases = [
        _case_report(
            case, snapshot, results, _load_truth(project_root / case["truth_path"]),
            _load_json(project_root / case["capture_binding_path"])
            if case.get("capture_binding_path") else None,
        )
        for case, snapshot, results in completed
    ]
    valid_cases = [case for case in evaluated_cases if case["evaluation_status"] == "EVALUABLE"]
    baseline_ranking = rank_snapshot_hypotheses(baseline_results)
    versions = {
        result.engine_version for result in baseline_results
    } | {
        result.engine_version for _, _, results in completed for result in results
    }
    limitations = list(manifest.get("limitations", []))
    if len(valid_cases) != len(evaluated_cases):
        limitations.append(
            f"{len(evaluated_cases) - len(valid_cases)}/{len(evaluated_cases)} cases are "
            "NOT EVALUABLE. Fault accuracy excludes them; additional aligned, lossless "
            "recordings with contemporaneous capture/run bindings are required."
        )
    report = {
        "phase": "06.1",
        "schema_version": "2.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "engine_versions": sorted(versions),
        "ground_truth_loaded_after_all_inference": True,
        "ranking_policy": "unique type/location; score descending; type/location ascending",
        "abstention_policy": (
            "No accepted DIAGNOSED top1 or distinct accepted roots within 0.10 score; "
            "AMBIGUOUS may retain Top3 credit for eligible cases"
        ),
        "valid_fault_metrics": _valid_metrics(evaluated_cases),
        "coverage": {
            "all_cases": _coverage(evaluated_cases),
            "valid_cases": _coverage(valid_cases),
        },
        "timestamp_validity": {
            "fault_case_count": len(evaluated_cases),
            "synthetic_validation_case_count": sum(case["synthetic"] for case in evaluated_cases),
            "evaluable_case_count": len(valid_cases),
            "not_evaluable_case_count": len(evaluated_cases) - len(valid_cases),
            "association_valid_case_count": sum(
                case["timing"]["association_valid"] for case in evaluated_cases
            ),
            "declared_window_timing_counts": dict(sorted(Counter(
                case["timing"]["declared_window_timing"] for case in evaluated_cases
            ).items())),
            "actual_capture_timing_counts": dict(sorted(Counter(
                case["timing"]["actual_capture_timing"] for case in evaluated_cases
            ).items())),
        },
        "cases": evaluated_cases,
        "baseline": {
            "category": "HEALTHY_BASELINE",
            "provenance": "Separately declared control; not a fault-active accuracy case",
            "diagnosis_count": len(baseline_results),
            "false_positive": bool(baseline_ranking),
            "accepted_false_positive": accepted_snapshot_top1(baseline_results) is not None,
            "top3": baseline_ranking[:3],
        },
        "limitations": limitations,
    }
    _write_json(output_dir / "phase06-results.json", report)
    (output_dir / "phase06-evaluation.md").write_text(_format_report(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    report = run_offline_evaluation(manifest_path=args.manifest, output_dir=args.output_dir)
    metrics = report["valid_fault_metrics"]
    count = metrics["case_count"]
    scores = (
        f"Top-1 {metrics['top1_correct']}/{count}; Top-3 {metrics['top3_correct']}/{count}"
        if count else "Top-1 N/A; Top-3 N/A (zero evaluable fault-active cases)"
    )
    print(f"Phase 06.1: {scores}.")
    print(f"NOT EVALUABLE: {report['timestamp_validity']['not_evaluable_case_count']} cases.")
    print(f"Raw abstentions: {report['coverage']['all_cases']['abstention_count']} cases.")


if __name__ == "__main__":
    main()
