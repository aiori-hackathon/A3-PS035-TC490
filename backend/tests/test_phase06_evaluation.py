"""Offline evaluation boundaries, honest ranking metrics, and recorded-data limits."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation import phase06
from app.evaluation.timing import snapshot_digest
from app.schemas.diagnosis import (
    DiagnosisResult,
    DiagnosisStatus,
    EvidenceCertificate,
    RankedHypothesis,
)
from app.schemas.hypothesis import FaultHypothesis, FaultLocation, FaultType

_NOW = datetime(2026, 10, 20, 8, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[2]


def _hypothesis(
    fault_type: FaultType = FaultType.LINK_FAILURE,
    component: str = "L12",
    score: float = 0.8,
    suffix: str = "a",
) -> FaultHypothesis:
    return FaultHypothesis(
        hypothesis_id=f"hyp-{suffix}", incident_id="inc-1", fault_type=fault_type,
        fault_location=FaultLocation(
            kind="ROUTER" if component.startswith("R") else "LINK", component_id=component,
        ),
        rule_score=score, supporting_evidence_ids=["ev-real-observation"],
        reasoning_trace=["Observed ev-real-observation"],
    )


def _result(
    hypotheses: list[FaultHypothesis],
    status: DiagnosisStatus = DiagnosisStatus.DIAGNOSED,
) -> DiagnosisResult:
    return DiagnosisResult(
        result_id="result-1", incident_id="inc-1", diagnosed_at=_NOW, engine_version="test-06",
        status=status,
        ranked_hypotheses=[
            RankedHypothesis(rank=index + 1, hypothesis=hypothesis)
            for index, hypothesis in enumerate(hypotheses)
        ],
        top1_hypothesis=hypotheses[0] if hypotheses and status == DiagnosisStatus.DIAGNOSED else None,
        top3_hypotheses=hypotheses[:3] if status != DiagnosisStatus.INSUFFICIENT_EVIDENCE else [],
        evidence_certificate=EvidenceCertificate(
            certificate_id="cert-1", incident_id="inc-1", generated_at=_NOW,
            total_evidence_count=1, supporting_evidence_count=bool(hypotheses),
            contradictory_evidence_count=0, evidence_sufficiency_met=status == DiagnosisStatus.DIAGNOSED,
            collection_coverage_pct=100, reasoning_summary="Observed ev-real-observation",
        ),
        missing_information=["Need a second independent observation"]
        if status == DiagnosisStatus.INSUFFICIENT_EVIDENCE else [],
    )


def _snapshot() -> dict:
    return {
        "snapshot_id": "neutral-observation",
        "captured_at": (_NOW + timedelta(seconds=20)).isoformat(),
        "collection_window_start": _NOW.isoformat(),
        "collection_window_end": (_NOW + timedelta(seconds=20)).isoformat(),
        "evidence_records": [{
            "evidence_id": "ev-real-observation",
            "observed_at": _NOW.isoformat(),
            "collected_at": _NOW.isoformat(),
        }],
    }


def _truth(
    fault_type: FaultType = FaultType.LINK_FAILURE, component: str = "L12",
) -> SimpleNamespace:
    return SimpleNamespace(
        run_id="synthetic-test-run",
        seeded_fault_type=fault_type, actual_fault_location_id=component,
        injection_timestamp=_NOW - timedelta(seconds=1),
        recovery_timestamp=_NOW + timedelta(seconds=21),
    )


def _binding(snapshot: dict | None = None) -> dict:
    snapshot = snapshot or _snapshot()
    return {
        "run_id": "synthetic-test-run",
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_sha256": snapshot_digest(snapshot),
        "reset_started_at": (_NOW + timedelta(seconds=21)).isoformat(),
    }


def _case() -> dict:
    return {"case_id": "001", "snapshot_path": "observation.json", "truth_path": "label.json"}


def test_exact_type_and_location_are_required_for_both_metrics():
    correct = _hypothesis()
    same_type_wrong_location = _hypothesis(component="L23", suffix="b")
    same_location_wrong_type = _hypothesis(fault_type=FaultType.PACKET_LOSS, suffix="c")
    for wrong in [same_type_wrong_location, same_location_wrong_type]:
        report = phase06._case_report(_case(), _snapshot(), [_result([wrong])], _truth(), _binding())
        assert report["top1_correct"] is False
        assert report["top3_correct"] is False
    report = phase06._case_report(_case(), _snapshot(), [_result([correct])], _truth(), _binding())
    assert report["top1_correct"] is True
    assert report["top3_correct"] is True
    assert report["timing"]["evaluable"] is True


def test_insufficient_evidence_candidates_never_receive_ranking_credit():
    result = _result([_hypothesis()], DiagnosisStatus.INSUFFICIENT_EVIDENCE)
    report = phase06._case_report(_case(), _snapshot(), [result], _truth(), _binding())
    assert report["abstained"] is True
    assert report["top1"] is None
    assert report["top3"] == []
    assert not report["top1_correct"] and not report["top3_correct"]
    assert report["diagnosis_summaries"][0]["missing_information"]


def test_ambiguous_ranking_can_hit_top3_without_claiming_an_accepted_top1():
    result = _result([_hypothesis()], DiagnosisStatus.AMBIGUOUS)
    report = phase06._case_report(_case(), _snapshot(), [result], _truth(), _binding())
    assert report["ambiguous"] is True
    assert report["abstained"] is True
    assert report["top1"] is None
    assert report["top1_correct"] is False
    assert report["top3_correct"] is True


def test_snapshot_ranking_is_stable_and_deduplicates_type_location_pairs():
    a = _hypothesis(component="L12", score=0.8, suffix="a")
    duplicate = _hypothesis(component="L12", score=0.7, suffix="duplicate")
    b = _hypothesis(component="L23", score=0.8, suffix="b")
    c = _hypothesis(fault_type=FaultType.PACKET_LOSS, score=0.8, suffix="c")
    first = phase06.rank_snapshot_hypotheses([_result([c, b]), _result([duplicate, a])])
    second = phase06.rank_snapshot_hypotheses([_result([a, duplicate]), _result([b, c])])
    assert first == second
    assert [item["hypothesis_id"] for item in first] == ["hyp-a", "hyp-b", "hyp-c"]


def test_top1_is_taken_from_accepted_field_instead_of_merged_tentative_ranking():
    tentative = _result([_hypothesis(score=0.99, suffix="tentative")], DiagnosisStatus.AMBIGUOUS)
    accepted = _result([_hypothesis(component="L23", score=0.7, suffix="accepted")])
    winner = phase06.accepted_snapshot_top1([tentative, accepted])
    assert winner["hypothesis_id"] == "hyp-accepted"


@pytest.mark.parametrize("second_score", [0.9, 0.85, 0.8])
def test_close_distinct_accepted_incident_roots_abstain_at_global_top1(second_score):
    results = [
        _result([_hypothesis(score=0.9)]),
        _result([_hypothesis(component="L23", score=second_score, suffix="other")]),
    ]
    assert phase06.accepted_snapshot_top1(results) is None
    report = phase06._case_report(_case(), _snapshot(), results, _truth(), _binding())
    assert report["snapshot_top1_ambiguous"] is True
    assert report["top1_correct"] is False
    assert report["top3_correct"] is True


def test_duplicate_accepted_roots_do_not_create_global_ambiguity():
    results = [_result([_hypothesis(score=0.9)]), _result([_hypothesis(score=0.9, suffix="copy")])]
    assert phase06.accepted_snapshot_top1(results)["component_id"] == "L12"


def test_separated_accepted_incident_roots_select_strongest_global_top1():
    results = [
        _result([_hypothesis(score=0.9)]),
        _result([_hypothesis(component="L23", score=0.79, suffix="other")]),
    ]
    assert phase06.accepted_snapshot_top1(results)["component_id"] == "L12"


def test_top3_excludes_the_fourth_candidate():
    candidates = [_hypothesis(component=component, score=score, suffix=component) for component, score in [
        ("L23", 0.9), ("L34", 0.8), ("L45", 0.7), ("L12", 0.6),
    ]]
    report = phase06._case_report(_case(), _snapshot(), [_result(candidates)], _truth(), _binding())
    assert len(report["top3"]) == 3
    assert report["top3_correct"] is False


def test_temporal_mismatch_is_visible_and_does_not_change_predictions():
    truth = _truth()
    truth.recovery_timestamp = _NOW - timedelta(hours=1)
    truth.injection_timestamp = _NOW - timedelta(hours=2)
    binding = _binding() | {"reset_started_at": truth.recovery_timestamp.isoformat()}
    report = phase06._case_report(_case(), _snapshot(), [_result([_hypothesis()])], truth, binding)
    assert report["top1_correct"] is None
    assert report["top3_correct"] is None
    assert report["top1"]["component_id"] == "L12"
    assert report["evaluation_status"] == "NOT EVALUABLE"
    assert report["timing"]["evaluable"] is False
    assert report["timing"]["actual_capture_timing"] == "POST_FAULT_RECOVERY"
    assert report["limitations"]


def _write_fixture_manifest(tmp_path: Path, case_count: int = 5) -> Path:
    cases = []
    (tmp_path / "control.json").write_text(json.dumps(_snapshot()))
    for number in range(case_count):
        snapshot = _snapshot() | {"snapshot_id": f"observation-{number}"}
        snapshot_path = f"observation-{number}.json"
        (tmp_path / snapshot_path).write_text(json.dumps(snapshot))
        binding_path = f"binding-{number}.json"
        (tmp_path / binding_path).write_text(json.dumps(_binding(snapshot)))
        cases.append({
            "case_id": f"{number + 1:03}", "snapshot_path": snapshot_path,
            "truth_path": f"never-opened-before-inference-{number}.json",
            "capture_binding_path": binding_path,
        })
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"baseline_snapshot_path": "control.json", "cases": cases}))
    return manifest


def test_all_inference_and_neutral_artifacts_finish_before_first_truth_load(tmp_path, monkeypatch):
    manifest = _write_fixture_manifest(tmp_path)
    output = tmp_path / "reports"
    calls = []
    original_load_json = phase06._load_json

    def load_json(path):
        if path.name.startswith("binding-"):
            assert len([call for call in calls if call[0] == "inference"]) == 6
            assert len(list((output / "phase06-diagnoses").glob("*.json"))) == 6
        return original_load_json(path)

    def inference(snapshot):
        assert isinstance(snapshot, dict)
        assert "truth_path" not in snapshot and "snapshot_path" not in snapshot
        assert "capture_binding_path" not in snapshot and "run_id" not in snapshot
        calls.append(("inference", snapshot["snapshot_id"]))
        return [] if snapshot["snapshot_id"] == "neutral-observation" else [_result([_hypothesis()])]

    def load_truth(path):
        assert len([call for call in calls if call[0] == "inference"]) == 6
        assert len(list((output / "phase06-diagnoses").glob("*.json"))) == 6
        calls.append(("truth", path.name))
        return _truth()

    monkeypatch.setattr(phase06, "_load_truth", load_truth)
    monkeypatch.setattr(phase06, "_load_json", load_json)
    report = phase06.run_offline_evaluation(tmp_path, manifest, output, inference)
    assert [call[0] for call in calls] == ["inference"] * 6 + ["truth"] * 5
    assert report["valid_fault_metrics"]["case_count"] == 5
    assert report["valid_fault_metrics"]["top1_accuracy"] == 1
    assert report["baseline"]["false_positive"] is False
    artifacts = list((output / "phase06-diagnoses").glob("*.json"))
    for artifact in artifacts:
        serialized = artifact.read_text()
        assert "seeded_fault_type" not in serialized
        assert "expected_fault_type" not in serialized
        assert "truth_path" not in serialized
        assert "capture_binding_path" not in serialized
    assert (output / "phase06-results.json").is_file()
    assert (output / "phase06-evaluation.md").is_file()


def test_missing_truth_fails_only_after_all_observations_were_diagnosed(tmp_path):
    manifest = _write_fixture_manifest(tmp_path)
    calls = []

    def inference(snapshot):
        calls.append(snapshot)
        return []

    with pytest.raises(FileNotFoundError):
        phase06.run_offline_evaluation(tmp_path, manifest, tmp_path / "reports", inference)
    assert len(calls) == 6


def test_ground_truth_import_is_lazy_in_evaluation_module():
    module = ast.parse(Path(phase06.__file__).read_text())
    top_level_imports = [
        node.module for node in module.body if isinstance(node, ast.ImportFrom)
    ]
    assert "app.evaluation.ground_truth" not in top_level_imports


@pytest.mark.parametrize("case_ids", [["001", "001"], ["../escape"], []])
def test_invalid_manifest_case_identifiers_are_rejected_before_inference(tmp_path, case_ids):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [{"case_id": case_id} for case_id in case_ids]}))
    with pytest.raises(ValueError, match="case IDs|Case IDs"):
        phase06.run_offline_evaluation(tmp_path, manifest, tmp_path / "reports", lambda _: [])


def test_real_manifest_has_five_unique_fault_snapshots_and_separate_baseline():
    manifest = json.loads((_ROOT / "evaluation/datasets/phase06_manifest.json").read_text())
    assert len(manifest["cases"]) == 5
    assert len({case["snapshot_path"] for case in manifest["cases"]}) == 5
    assert all((_ROOT / case["snapshot_path"]).is_file() for case in manifest["cases"])
    assert all((_ROOT / case["truth_path"]).is_file() for case in manifest["cases"])
    assert "baseline" in manifest["baseline_snapshot_path"]


def test_all_recorded_snapshots_evaluate_with_explicit_temporal_and_metric_limits(tmp_path):
    report = phase06.run_offline_evaluation(output_dir=tmp_path)
    assert report["valid_fault_metrics"]["case_count"] == 0
    assert len(report["cases"]) == 5
    assert report["valid_fault_metrics"]["top1_accuracy"] is None
    assert report["valid_fault_metrics"]["top3_accuracy"] is None
    assert report["timestamp_validity"]["evaluable_case_count"] == 0
    assert report["timestamp_validity"]["not_evaluable_case_count"] == 5
    assert report["coverage"]["all_cases"]["case_count"] == 5
    assert report["coverage"]["all_cases"]["abstention_count"] == 3
    assert report["coverage"]["valid_cases"]["abstention_rate"] is None
    assert report["ground_truth_loaded_after_all_inference"] is True
    assert report["baseline"]["false_positive"] is False
    assert len(list((tmp_path / "phase06-diagnoses").glob("*.json"))) == 6
    assert any("dropped typed" in limitation for limitation in report["limitations"])
    for case in report["cases"]:
        assert case["timing"]["evaluable"] is False
        assert case["timing"]["declared_capture_timing"] == "POST_FAULT_RECOVERY"
        assert case["timing"]["actual_capture_timing"] == "UNKNOWN_TIMING"
        assert case["evaluation_status"] == "NOT EVALUABLE"
        assert case["top1_correct"] is None
        assert case["top3_correct"] is None
        assert case["limitations"]
        assert len(case["top3"]) <= 3


def test_type_and_location_metrics_are_independent_but_exact_hits_require_one_pair():
    wrong_location = _hypothesis(component="L23", score=0.9)
    wrong_type = _hypothesis(fault_type=FaultType.PACKET_LOSS, score=0.8, suffix="b")
    report = phase06._case_report(
        _case(), _snapshot(), [_result([wrong_location, wrong_type])], _truth(), _binding(),
    )
    assert report["top1_fault_type_correct"] is True
    assert report["top1_location_correct"] is False
    assert report["top3_fault_type_correct"] is True
    assert report["top3_location_correct"] is True
    assert report["top1_correct"] is False
    assert report["top3_correct"] is False  # separate partial matches must not become one hit


def test_ineligible_correct_and_wrong_predictions_neither_help_nor_hurt_valid_accuracy():
    correct = [_result([_hypothesis()])]
    wrong = [_result([_hypothesis(component="L23")])]
    valid = phase06._case_report(_case(), _snapshot(), correct, _truth(), _binding())
    invalid_hit = phase06._case_report(_case(), _snapshot(), correct, _truth())
    invalid_miss = phase06._case_report(_case(), _snapshot(), wrong, _truth())
    metrics = phase06._valid_metrics([valid, invalid_hit, invalid_miss])
    assert metrics["case_count"] == 1
    assert metrics["top1_correct"] == 1 and metrics["top1_accuracy"] == 1
    assert metrics["top3_correct"] == 1 and metrics["top3_accuracy"] == 1
    for case in [invalid_hit, invalid_miss]:
        assert all(case[field] is None for field in [
            "top1_correct", "top3_correct", "top1_fault_type_correct",
            "top1_location_correct", "top3_fault_type_correct", "top3_location_correct",
        ])
    assert phase06._coverage([valid, invalid_hit, invalid_miss])["accepted_top1_count"] == 3


def test_valid_abstention_is_a_miss_but_unbound_abstention_is_excluded():
    results = [_result([_hypothesis()], DiagnosisStatus.INSUFFICIENT_EVIDENCE)]
    valid = phase06._case_report(_case(), _snapshot(), results, _truth(), _binding())
    unbound = phase06._case_report(_case(), _snapshot(), results, _truth())
    metrics = phase06._valid_metrics([valid, unbound])
    assert metrics["case_count"] == 1
    assert metrics["top1_accuracy"] == 0 and metrics["top3_accuracy"] == 0
    assert unbound["top1_correct"] is None and unbound["top3_correct"] is None
    assert phase06._coverage([valid, unbound])["abstention_rate"] == 1


def test_truth_changes_only_scoring_metadata_not_predictions_or_neutral_artifacts(
    tmp_path, monkeypatch,
):
    manifest = _write_fixture_manifest(tmp_path, case_count=1)
    prediction = _result([_hypothesis()])
    calls = []

    def inference(snapshot):
        calls.append(snapshot)
        return [prediction]

    monkeypatch.setattr(phase06, "_load_truth", lambda _: _truth())
    first = phase06.run_offline_evaluation(tmp_path, manifest, tmp_path / "first", inference)
    monkeypatch.setattr(
        phase06, "_load_truth", lambda _: _truth(FaultType.HIGH_LATENCY, "L51"),
    )
    second = phase06.run_offline_evaluation(tmp_path, manifest, tmp_path / "second", inference)
    assert calls[:2] == calls[2:]
    assert first["cases"][0]["top1"] == second["cases"][0]["top1"]
    assert first["cases"][0]["top3"] == second["cases"][0]["top3"]
    assert first["valid_fault_metrics"]["top1_accuracy"] == 1
    assert second["valid_fault_metrics"]["top1_accuracy"] == 0
    for name in ["control.json", "diagnosis-001.json"]:
        assert (tmp_path / "first/phase06-diagnoses" / name).read_bytes() == (
            tmp_path / "second/phase06-diagnoses" / name
        ).read_bytes()


def test_wrong_binding_in_evaluator_is_not_evaluable_despite_matching_times_and_labels(
    tmp_path, monkeypatch,
):
    manifest = _write_fixture_manifest(tmp_path, case_count=1)
    binding_path = tmp_path / "binding-0.json"
    binding = json.loads(binding_path.read_text())
    binding["run_id"] = "different-experiment-with-the-same-scenario"
    binding_path.write_text(json.dumps(binding))
    monkeypatch.setattr(phase06, "_load_truth", lambda _: _truth())
    report = phase06.run_offline_evaluation(
        tmp_path, manifest, tmp_path / "reports", lambda _: [_result([_hypothesis()])],
    )
    assert report["cases"][0]["top1"] is not None
    assert report["cases"][0]["evaluation_status"] == "NOT EVALUABLE"
    assert report["valid_fault_metrics"]["case_count"] == 0
    assert report["valid_fault_metrics"]["top1_accuracy"] is None
    assert report["baseline"]["category"] == "HEALTHY_BASELINE"
    assert "N/A" in (tmp_path / "reports/phase06-evaluation.md").read_text()
