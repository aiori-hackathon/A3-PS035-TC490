"""Synthetic adversarial checks for capture identity and evidence timing audits.

These fixtures validate audit mechanics. They do not replace, relabel, or repair
any historical observation or ground-truth record.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.evaluation.timing import audit_timing, snapshot_digest
from app.schemas.diagnosis import (
    DiagnosisResult,
    EvidenceCertificate,
    RankedHypothesis,
)
from app.schemas.hypothesis import FaultHypothesis, FaultLocation

_INJECTION = datetime(2026, 10, 20, 9, tzinfo=UTC)
_RECOVERY = _INJECTION + timedelta(minutes=10)
_DEFAULT_BINDING = object()


def _timestamp(seconds: float) -> str:
    return (_INJECTION + timedelta(seconds=seconds)).isoformat()


def _record(evidence_id: str = "ev-support", observed: float = 60, collected: float = 61) -> dict:
    return {
        "evidence_id": evidence_id,
        "observed_at": _timestamp(observed),
        "collected_at": _timestamp(collected),
        "source_router": "R1",
        "source_type": "INTERFACE_POLL",
        "source_interface": "eth1",
        "event_type": "INTERFACE_DOWN_OBSERVED",
        "collection_status": "OBSERVED",
        "collection_method": "PERIODIC_POLL",
    }


def _snapshot(records: list[dict] | None = None, start: float = 30, end: float = 540) -> dict:
    return {
        "snapshot_id": "capture-synthetic-001",
        "captured_at": _timestamp(end),
        "collection_window_start": _timestamp(start),
        "collection_window_end": _timestamp(end),
        "evidence_records": [_record()] if records is None else records,
    }


def _truth() -> SimpleNamespace:
    return SimpleNamespace(
        run_id="synthetic-run-001",
        injection_timestamp=_INJECTION,
        recovery_timestamp=_RECOVERY,
    )


def _binding(snapshot: dict, truth: SimpleNamespace | None = None) -> dict:
    truth = truth or _truth()
    return {
        "run_id": truth.run_id,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_sha256": snapshot_digest(snapshot),
        "reset_started_at": _RECOVERY.isoformat(),
    }


def _result(
    support: list[str] | None = None,
    contradiction: list[str] | None = None,
) -> DiagnosisResult:
    support = ["ev-support"] if support is None else support
    contradiction = [] if contradiction is None else contradiction
    hypothesis = FaultHypothesis(
        hypothesis_id="hyp-synthetic", incident_id="incident-synthetic",
        fault_type="LINK_FAILURE",
        fault_location=FaultLocation(kind="LINK", component_id="L12"),
        rule_score=0.8,
        supporting_evidence_ids=support,
        contradictory_evidence_ids=contradiction,
        reasoning_trace=["Synthetic audit fixture references actual fixture evidence IDs."],
    )
    return DiagnosisResult(
        result_id="diagnosis-synthetic", incident_id="incident-synthetic",
        diagnosed_at=_RECOVERY, engine_version="timing-test",
        status="DIAGNOSED",
        ranked_hypotheses=[RankedHypothesis(rank=1, hypothesis=hypothesis)],
        top1_hypothesis=hypothesis, top3_hypotheses=[hypothesis],
        evidence_certificate=EvidenceCertificate(
            certificate_id="certificate-synthetic", incident_id="incident-synthetic",
            generated_at=_RECOVERY, total_evidence_count=len(set(support + contradiction)),
            supporting_evidence_count=len(support), contradictory_evidence_count=len(contradiction),
            evidence_sufficiency_met=True, collection_coverage_pct=100,
            reasoning_summary="Synthetic timing audit only.",
        ),
    )


def _audit(
    snapshot: dict | None = None,
    results: list[DiagnosisResult] | None = None,
    truth: SimpleNamespace | None = None,
    binding: dict | None | object = _DEFAULT_BINDING,
) -> dict:
    snapshot = _snapshot() if snapshot is None else snapshot
    results = [_result()] if results is None else results
    truth = _truth() if truth is None else truth
    if binding is _DEFAULT_BINDING:
        binding = _binding(snapshot, truth)
    return audit_timing(snapshot, results, truth, binding)


def test_bound_fault_active_capture_is_evaluable_and_has_complete_audit_fields():
    report = _audit()
    assert report["evaluable"] is True
    assert report["association_valid"] is True
    assert report["window_valid"] is True
    assert report["actual_capture_timing"] == "FAULT_ACTIVE"
    assert report["declared_window_timing"] == "FAULT_ACTIVE"
    assert report["used_evidence_ids"] == ["ev-support"]
    assert report["missing_referenced_evidence_ids"] == []
    assert report["observation_counts"]["FAULT_ACTIVE"] == 1
    assert report["collection_counts"]["FAULT_ACTIVE"] == 1
    assert report["observation_range"]["start"]
    assert report["observation_range"]["end"]
    assert report["collection_range"]["start"]
    assert report["collection_range"]["end"]
    assert report["reasons"] == []


@pytest.mark.parametrize("binding", [None, {}])
def test_missing_binding_does_not_establish_actual_capture_timing(binding):
    report = _audit(binding=binding)
    assert report["association_valid"] is False
    assert report["actual_capture_timing"] == "UNKNOWN_TIMING"
    assert report["declared_window_timing"] == "FAULT_ACTIVE"
    assert report["evaluable"] is False
    assert report["reasons"]


@pytest.mark.parametrize("field,value", [
    ("run_id", "another-run"),
    ("snapshot_id", "another-capture"),
    ("snapshot_sha256", "0" * 64),
])
def test_wrong_run_snapshot_or_content_hash_rejects_capture_association(field, value):
    snapshot = _snapshot()
    binding = _binding(snapshot)
    binding[field] = value
    report = _audit(snapshot, binding=binding)
    assert report["association_valid"] is False
    assert report["actual_capture_timing"] == "UNKNOWN_TIMING"
    assert report["declared_window_timing"] == "FAULT_ACTIVE"
    assert report["evaluable"] is False
    assert report["reasons"]


def test_digest_is_canonical_for_dictionary_order_and_sensitive_to_evidence_content():
    snapshot = _snapshot()
    reordered = {key: snapshot[key] for key in reversed(snapshot)}
    reordered["evidence_records"] = [dict(reversed(list(snapshot["evidence_records"][0].items())))]
    digest = snapshot_digest(snapshot)
    assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")
    assert snapshot_digest(reordered) == digest
    changed = deepcopy(snapshot)
    changed["evidence_records"][0]["observed_at"] = _timestamp(62)
    assert snapshot_digest(changed) != digest


def test_digest_binding_detects_snapshot_changes_after_capture_binding():
    snapshot = _snapshot()
    binding = _binding(snapshot)
    snapshot["evidence_records"][0]["event_type"] = "INTERFACE_UP_OBSERVED"
    report = _audit(snapshot, binding=binding)
    assert report["association_valid"] is False
    assert report["evaluable"] is False


def test_injection_boundary_is_inclusive_for_observation_collection_and_window():
    snapshot = _snapshot([_record(observed=0, collected=0)], start=0)
    report = _audit(snapshot)
    assert report["evaluable"] is True
    assert report["records"][0]["observed_timing"] == "FAULT_ACTIVE"
    assert report["records"][0]["collected_timing"] == "FAULT_ACTIVE"


@pytest.mark.parametrize("observed,collected", [(600, 600), (599, 600), (600, 601)])
def test_recovery_boundary_is_exclusive_for_each_evidence_timestamp(observed, collected):
    snapshot = _snapshot([_record(observed=observed, collected=collected)], start=0, end=610)
    report = _audit(snapshot)
    assert report["evaluable"] is False
    assert report["records"][0]["collected_timing"] == "POST_FAULT_RECOVERY"
    if observed == 600:
        assert report["records"][0]["observed_timing"] == "POST_FAULT_RECOVERY"


def test_declared_window_ending_exactly_at_recovery_is_not_evaluable():
    report = _audit(_snapshot(end=600))
    assert report["evaluable"] is False
    assert report["declared_window_timing"] != "FAULT_ACTIVE"
    assert report["reasons"]


def test_complete_post_recovery_capture_is_classified_without_accuracy_eligibility():
    report = _audit(_snapshot([_record(observed=650, collected=651)], start=630, end=700))
    assert report["association_valid"] is True
    assert report["actual_capture_timing"] == "POST_FAULT_RECOVERY"
    assert report["declared_window_timing"] == "POST_FAULT_RECOVERY"
    assert report["evaluable"] is False


def test_complete_before_injection_capture_is_classified_without_accuracy_eligibility():
    report = _audit(_snapshot([_record(observed=-60, collected=-59)], start=-90, end=-30))
    assert report["actual_capture_timing"] == "BEFORE_FAULT"
    assert report["declared_window_timing"] == "BEFORE_FAULT"
    assert report["evaluable"] is False


def test_mixed_capture_retains_per_record_observation_and_collection_categories():
    snapshot = _snapshot([
        _record("ev-before", observed=-60, collected=-59),
        _record("ev-active", observed=60, collected=61),
        _record("ev-after", observed=650, collected=651),
    ], start=-90, end=700)
    report = _audit(snapshot, [_result(["ev-active"], ["ev-after"])])
    assert report["actual_capture_timing"] == "MIXED"
    assert report["declared_window_timing"] == "MIXED"
    assert report["evaluable"] is False
    for counts in [report["observation_counts"], report["collection_counts"]]:
        assert counts["BEFORE_FAULT"] == 1
        assert counts["FAULT_ACTIVE"] == 1
        assert counts["POST_FAULT_RECOVERY"] == 1


@pytest.mark.parametrize("field", ["injection_timestamp", "recovery_timestamp"])
@pytest.mark.parametrize("invalid", [None, "not-a-timestamp", "2026-10-20T09:00:00"])
def test_missing_invalid_or_naive_truth_times_are_unknown_instead_of_open_intervals(field, invalid):
    truth = _truth()
    setattr(truth, field, invalid)
    report = _audit(truth=truth)
    assert report["evaluable"] is False
    assert report["actual_capture_timing"] == "UNKNOWN_TIMING"
    assert report["declared_window_timing"] == "UNKNOWN_TIMING"
    assert report["reasons"]


def test_absent_recovery_attribute_is_unknown_instead_of_ongoing_fault():
    truth = _truth()
    del truth.recovery_timestamp
    report = _audit(truth=truth)
    assert report["evaluable"] is False
    assert report["actual_capture_timing"] == "UNKNOWN_TIMING"


def test_naive_datetime_objects_in_truth_are_invalid():
    truth = _truth()
    truth.injection_timestamp = _INJECTION.replace(tzinfo=None)
    report = _audit(truth=truth)
    assert report["evaluable"] is False
    assert report["actual_capture_timing"] == "UNKNOWN_TIMING"


def test_recovery_before_injection_is_invalid():
    truth = _truth()
    truth.recovery_timestamp = _INJECTION - timedelta(seconds=1)
    report = _audit(truth=truth)
    assert report["evaluable"] is False
    assert report["actual_capture_timing"] == "UNKNOWN_TIMING"
    assert report["declared_window_timing"] == "UNKNOWN_TIMING"


@pytest.mark.parametrize("field", ["observed_at", "collected_at"])
@pytest.mark.parametrize("invalid", [None, "invalid", "2026-10-20T09:01:00"])
def test_missing_invalid_and_naive_evidence_times_fail_closed(field, invalid):
    record = _record()
    record[field] = invalid
    report = _audit(_snapshot([record]))
    assert report["evaluable"] is False
    timing_field = "observed_timing" if field == "observed_at" else "collected_timing"
    assert report["records"][0][timing_field] == "UNKNOWN_TIMING"
    assert report["reasons"]


@pytest.mark.parametrize("field", ["collection_window_start", "collection_window_end", "captured_at"])
def test_naive_snapshot_times_are_rejected(field):
    snapshot = _snapshot()
    snapshot[field] = "2026-10-20T09:01:00"
    report = _audit(snapshot)
    assert report["evaluable"] is False
    assert report["reasons"]


def test_reversed_declared_collection_window_is_invalid():
    report = _audit(_snapshot(start=400, end=300))
    assert report["window_valid"] is False
    assert report["evaluable"] is False


def test_observation_after_collection_is_corrupt_chronology():
    report = _audit(_snapshot([_record(observed=90, collected=60)]))
    assert report["evaluable"] is False
    assert report["reasons"]


@pytest.mark.parametrize("observed,collected", [(29, 31), (539, 541)])
def test_both_observation_and_collection_must_be_inside_the_declared_window(observed, collected):
    report = _audit(_snapshot([_record(observed=observed, collected=collected)]))
    assert report["actual_capture_timing"] == "FAULT_ACTIVE"
    assert report["evaluable"] is False
    assert report["reasons"]


def test_empty_snapshot_has_no_evaluable_evidence_even_when_window_is_active():
    report = _audit(_snapshot([]), results=[])
    assert report["evaluable"] is False
    assert report["actual_capture_timing"] == "UNKNOWN_TIMING"
    assert report["records"] == []
    assert report["reasons"]


def test_timezone_offsets_represent_the_same_active_instants():
    snapshot = _snapshot()
    offset = timezone(timedelta(hours=5, minutes=30))
    for field in ["collection_window_start", "collection_window_end", "captured_at"]:
        snapshot[field] = datetime.fromisoformat(snapshot[field]).astimezone(offset).isoformat()
    for field in ["observed_at", "collected_at"]:
        original = snapshot["evidence_records"][0][field]
        snapshot["evidence_records"][0][field] = datetime.fromisoformat(original).astimezone(offset).isoformat()
    truth = _truth()
    truth.injection_timestamp = truth.injection_timestamp.astimezone(offset)
    truth.recovery_timestamp = truth.recovery_timestamp.astimezone(offset)
    report = _audit(snapshot, truth=truth)
    assert report["evaluable"] is True
    assert report["actual_capture_timing"] == "FAULT_ACTIVE"


def test_missing_referenced_evidence_ids_invalidate_evaluation():
    report = _audit(results=[_result(["ev-support", "ev-missing-support"], ["ev-missing-conflict"])])
    assert report["evaluable"] is False
    assert set(report["missing_referenced_evidence_ids"]) == {
        "ev-missing-support", "ev-missing-conflict",
    }
    assert {"ev-support", "ev-missing-support", "ev-missing-conflict"} <= set(report["used_evidence_ids"])


def test_support_and_contradiction_timestamps_are_audited_with_real_reference_roles():
    snapshot = _snapshot([_record(), _record("ev-conflict", observed=80, collected=81)])
    report = _audit(snapshot, [_result(contradiction=["ev-conflict"])])
    assert report["evaluable"] is True
    rows = {row["evidence_id"]: row for row in report["records"]}
    assert rows["ev-support"]["roles"] == ["SUPPORT"]
    assert rows["ev-conflict"]["roles"] == ["CONTRADICTION"]
    assert rows["ev-support"]["observed_at"]
    assert rows["ev-conflict"]["collected_at"]
    assert rows["ev-conflict"]["observed_timing"] == "FAULT_ACTIVE"
    assert rows["ev-conflict"]["collected_timing"] == "FAULT_ACTIVE"


def test_evidence_can_have_both_roles_across_competing_ranked_hypotheses():
    snapshot = _snapshot([_record(), _record("ev-other", observed=80, collected=81)])
    result = _result(["ev-support"], ["ev-other"])
    competitor = result.ranked_hypotheses[0].hypothesis.model_copy(update={
        "hypothesis_id": "hyp-competing",
        "supporting_evidence_ids": ["ev-other"],
        "contradictory_evidence_ids": ["ev-support"],
    })
    result = DiagnosisResult.model_validate(result.model_dump() | {
        "ranked_hypotheses": result.ranked_hypotheses + [RankedHypothesis(rank=2, hypothesis=competitor)],
        "top3_hypotheses": [result.top1_hypothesis, competitor],
    })
    report = _audit(snapshot, [result])
    assert report["evaluable"] is True
    assert set(report["used_evidence_ids"]) == {"ev-support", "ev-other"}
    assert all(set(row["roles"]) == {"SUPPORT", "CONTRADICTION"} for row in report["records"])


def test_unreferenced_records_are_still_audited_and_can_invalidate_capture():
    snapshot = _snapshot([_record(), _record("ev-unreferenced", observed=650, collected=651)])
    report = _audit(snapshot)
    assert report["evaluable"] is False
    rows = {row["evidence_id"]: row for row in report["records"]}
    assert rows["ev-unreferenced"]["roles"] == []
    assert rows["ev-unreferenced"]["observed_timing"] == "POST_FAULT_RECOVERY"


def test_exact_duplicate_records_do_not_invalidate_evaluation():
    record = _record()
    report = _audit(_snapshot([record, deepcopy(record)]))
    assert report["evaluable"] is True
    assert report["association_valid"] is True
    assert report["missing_referenced_evidence_ids"] == []


def test_conflicting_timestamp_payloads_under_one_evidence_id_fail_closed():
    report = _audit(_snapshot([_record(), _record(observed=90, collected=91)]))
    assert report["evaluable"] is False
    assert report["reasons"]


def test_audit_does_not_mutate_snapshot_results_truth_or_capture_binding():
    snapshot = _snapshot()
    result = _result()
    truth = _truth()
    binding = _binding(snapshot, truth)
    before = (deepcopy(snapshot), result.model_dump(), deepcopy(vars(truth)), deepcopy(binding))
    audit_timing(snapshot, [result], truth, binding)
    assert snapshot == before[0]
    assert result.model_dump() == before[1]
    assert vars(truth) == before[2]
    assert binding == before[3]


@pytest.mark.parametrize("reset_started_at", [
    None, "invalid", "2026-10-20T09:05:00", _timestamp(-1), _timestamp(601),
])
def test_unrecorded_or_invalid_reset_boundary_cannot_certify_fault_activity(reset_started_at):
    snapshot = _snapshot()
    binding = _binding(snapshot) | {"reset_started_at": reset_started_at}
    report = _audit(snapshot, binding=binding)
    assert report["association_valid"] is True
    assert report["evaluable"] is False
    assert report["actual_capture_timing"] == "UNKNOWN_TIMING"


def test_capture_during_controller_convergence_is_not_fault_active():
    snapshot = _snapshot([_record(observed=400, collected=401)], start=390, end=500)
    binding = _binding(snapshot) | {"reset_started_at": _timestamp(300)}
    report = _audit(snapshot, binding=binding)
    assert report["declared_window_timing"] == "FAULT_ACTIVE"
    assert report["records"][0]["observed_timing"] == "FAULT_ACTIVE"
    assert report["records"][0]["actual_observed_timing"] == "UNKNOWN_TIMING"
    assert report["actual_capture_timing"] == "UNKNOWN_TIMING"
    assert report["evaluable"] is False


def test_capture_completed_before_reset_can_precede_later_convergence_recovery():
    snapshot = _snapshot([_record(observed=60, collected=61)], start=30, end=200)
    binding = _binding(snapshot) | {"reset_started_at": _timestamp(300)}
    report = _audit(snapshot, binding=binding)
    assert report["evaluable"] is True
    assert report["actual_capture_timing"] == "FAULT_ACTIVE"


def test_window_ending_exactly_when_reset_begins_is_not_fault_active():
    snapshot = _snapshot(end=300)
    binding = _binding(snapshot) | {"reset_started_at": _timestamp(300)}
    assert _audit(snapshot, binding=binding)["evaluable"] is False
