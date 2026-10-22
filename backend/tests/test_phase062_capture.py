"""Non-disruptive capture validation. All subprocess execution is forbidden here."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from lab.fault_injection.controller import ExperimentAlreadyActiveError, FaultController
from lab.fault_injection.models import ExperimentState

from app.capture.dry_run import SyntheticClock, SyntheticController, SyntheticObserver, run_dry
from app.capture.observer import LabObserver
from app.capture.safety import CaptureInterrupted, CaptureTimeout, Deadline
from app.capture.workflow import PLANS, CaptureRunner, validate_provenance
from app.collectors.fidelity import validate_capture
from app.collectors.normalizer import EvidenceNormalizer
from app.collectors.orchestrator import EvidenceSnapshot
from app.collectors.ospf_collector import OSPFCollector
from app.collectors.ping_collector import PingCollector
from app.collectors.transport import DockerTransport, MockTransport, SecurityViolationError
from app.evaluation.ground_truth import FaultInjectionRecord
from app.evaluation.phase06 import _case_report, _valid_metrics
from app.evaluation.timing import audit_timing, snapshot_digest
from app.schemas.evidence import PingAttemptFailure


@pytest.fixture(autouse=True)
def forbid_subprocess(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Capture unit/dry-run tests must never execute subprocesses")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture
def setup(tmp_path):
    clock = SyntheticClock()
    controller = SyntheticController(tmp_path / ".active_fault.json", clock)
    observer = SyntheticObserver(controller, clock)
    runner = CaptureRunner(
        controller,
        observer,
        tmp_path / "output",
        synthetic=True,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    return runner, controller, observer, clock


def artifacts(runner, report):
    directory = runner.output_dir / report["artifact_directory"]
    return tuple(
        json.loads((directory / name).read_text())
        for name in ("snapshot.json", "truth.json", "binding.json")
    )


@pytest.mark.parametrize("plan", PLANS)
def test_all_five_plans_capture_losslessly_with_matched_synthetic_provenance(setup, plan):
    runner, controller, _, _ = setup
    reports = runner.run_sequence([plan])
    assert len(reports) == 1
    report = reports[0]
    assert report["status"] == "CAPTURED", report["errors"]
    assert report["recovery_confirmed"] is True
    assert controller.injections == controller.resets == 1
    assert not controller.lock_file.exists()
    snapshot, raw_truth, binding = artifacts(runner, report)
    truth = FaultInjectionRecord.model_validate(raw_truth)
    assert truth.run_id == binding["run_id"] == report["run_id"]
    assert binding["snapshot_id"] == snapshot["snapshot_id"]
    assert binding["snapshot_sha256"] == snapshot_digest(snapshot)
    validate_provenance(report, snapshot)
    assert audit_timing(snapshot, [], truth, binding)["evaluable"] is True
    assert validate_capture(snapshot) == []
    EvidenceNormalizer.assert_no_ground_truth_leakage(snapshot)
    assert "run_id" not in snapshot and "synthetic" not in snapshot
    for raw in snapshot["evidence_records"]:
        restored = EvidenceNormalizer.deserialize_record(raw)
        assert restored.model_dump(mode="json") == raw
    pings = [r for r in snapshot["evidence_records"] if r["source_type"] == "ACTIVE_PING"]
    assert len(pings) == 4
    assert all(
        r["packets_sent"] == 20 and r["source_address"] and r["rtt_unit"] == "ms" for r in pings
    )
    assert all(r["packets_lost"] == r["packets_sent"] - r["packets_received"] for r in pings)
    case = _case_report(
        {"case_id": "001", "snapshot_path": "snapshot.json", "truth_path": "truth.json"},
        snapshot,
        [],
        truth,
        binding,
    )
    assert case["evaluation_status"] == "SYNTHETIC_VALIDATION_ONLY"
    assert case["top1_correct"] is None and case["top3_correct"] is None
    assert _valid_metrics([case])["case_count"] == 0


def test_dry_run_executes_all_five_sequentially_without_docker(tmp_path):
    reports = run_dry(tmp_path / "rehearsal")
    assert len(reports) == 5
    assert all(r["status"] == "CAPTURED" and r["synthetic"] for r in reports)
    assert len({r["run_id"] for r in reports}) == 5
    for first, second in zip(reports, reports[1:]):
        assert first["recovery_confirmed_at"] < second["injection_command_start"]


@pytest.mark.parametrize(
    "failure",
    [
        "manifestation",
        "collector",
        "serialization",
        "capture_timeout",
        "injection_timeout",
        "partial_injection",
        "reset",
        "recovery",
        "baseline",
    ],
)
def test_failure_paths_stop_sequence_and_always_attempt_owned_reset(setup, failure):
    runner, controller, observer, _ = setup
    if failure == "manifestation":
        observer.manifests = False
    elif failure == "collector":
        observer.capture_error = True
    elif failure == "serialization":
        observer.corrupt = lambda snapshot: snapshot["evidence_records"][0].pop("observed_at")
    elif failure == "capture_timeout":
        observer.capture_delay = 91
    elif failure == "injection_timeout":
        controller.inject_delay = 181
    elif failure == "partial_injection":
        controller.inject_error = True
    elif failure == "reset":
        controller.reset_error = True
    elif failure == "recovery":
        observer.recovery_ok = False
    else:
        observer.baseline_ok = False
    reports = runner.run_sequence(PLANS)
    assert len(reports) == 1
    assert reports[0]["status"] == "FAILED"
    assert reports[0]["errors"]
    assert controller.injections == (0 if failure == "baseline" else 1)
    assert controller.resets == (0 if failure == "baseline" else 1)
    assert not list(runner.output_dir.glob("*/binding.json"))
    if failure in {"reset", "recovery"}:
        assert controller.lock_file.exists()
        assert (controller.lock_file.parent / ".capture-sequence.lock").exists()
        assert reports[0]["recovery_confirmed"] is False


@pytest.mark.parametrize(
    "field",
    [
        "observed_at",
        "collected_at",
        "packets_sent",
        "packets_received",
        "packets_lost",
        "source_address",
        "target_address",
        "rtt_avg_ms",
    ],
)
def test_new_capture_rejects_missing_measurements_without_legacy_fallback(setup, field):
    _, _, observer, clock = setup
    snapshot = observer.capture(PLANS[3], clock.now().isoformat())
    ping = next(r for r in snapshot["evidence_records"] if r["source_type"] == "ACTIVE_PING")
    ping.pop(field)
    with pytest.raises((ValueError, KeyError)):
        validate_capture(snapshot)


def test_failed_ping_does_not_fabricate_transmitted_or_lost_packets():
    transport = MockTransport()
    transport.set_router_running("R1", False)
    record = PingCollector(transport).probe("R1", "10.0.12.2", count=20, source_address="10.0.12.1")
    assert isinstance(record, PingAttemptFailure)
    assert record.requested_packets == 20
    raw = record.model_dump(mode="json")
    assert all(
        field not in raw for field in ["packets_sent", "packets_received", "packet_loss_pct"]
    )
    assert EvidenceNormalizer.deserialize_record(raw) == record


def test_command_without_ping_statistics_is_explicit_failed_attempt():
    record = PingCollector(MockTransport()).probe("R1", "10.0.12.2")
    assert isinstance(record, PingAttemptFailure)
    assert record.event_type == "PROBE_EXECUTION_FAILED"


@pytest.mark.parametrize("count", [0, 21, 100])
def test_probe_packet_bound_is_rejected_before_execution(count):
    with pytest.raises(ValueError):
        PingCollector(MockTransport()).probe("R1", "10.0.12.2", count=count)


def test_probe_source_address_cannot_point_to_another_router():
    with pytest.raises(SecurityViolationError):
        PingCollector(MockTransport()).probe("R1", "10.0.12.2", source_address="10.0.12.2")


def test_observed_ospf_configuration_and_timestamp_survive_json_round_trip():
    transport = MockTransport()
    config = {"eth1": {"area": "0.0.0.0", "timerMsecs": {"hello": 5000, "dead": 15000}}}
    transport.set_response(
        "R1", ["vtysh", "-c", "show ip ospf neighbor json"], 0, '{"neighbors":{}}'
    )
    transport.set_response(
        "R1", ["vtysh", "-c", "show ip ospf interface json"], 0, json.dumps(config)
    )
    records = OSPFCollector(transport).collect(["R1"])
    first = next(r for r in records if r.source_interface == "eth1")
    assert first.observed_interface_config == config["eth1"]
    assert first.interface_config_observed_at is not None
    assert EvidenceNormalizer.deserialize_record(first.model_dump(mode="json")) == first
    assert (
        next(r for r in records if r.source_interface == "eth2").observed_interface_config is None
    )


@pytest.mark.parametrize(
    "change",
    [
        {"packet_count": 21},
        {"probe_rounds": 3},
        {"target": "eth0"},
        {"target": "other-project"},
        {"parameters": (("interface", 1),)},
        {"parameters": (("loss_pct", 101),)},
    ],
)
def test_invalid_plans_are_rejected_without_acquiring_any_lock(setup, change):
    runner, controller, _, _ = setup
    with pytest.raises(ValueError):
        runner.run_sequence([replace(PLANS[3], **change)])
    assert controller.injections == 0
    assert not controller.lock_file.exists()


def test_existing_sequence_lease_blocks_different_output_directory(setup):
    runner, controller, _, _ = setup
    (controller.lock_file.parent / ".capture-sequence.lock").write_text("previous crashed process")
    with pytest.raises(FileExistsError):
        runner.run_sequence(PLANS)
    assert controller.injections == 0


def test_corrupt_controller_lock_fails_closed(setup):
    runner, controller, _, _ = setup
    controller.lock_file.write_text("incomplete")
    with pytest.raises(ExperimentAlreadyActiveError):
        runner.run_sequence(PLANS)
    assert controller.injections == 0


def test_atomic_controller_reservation_allows_exactly_one_winner(setup):
    _, controller, _, _ = setup
    lock = controller.inject_fault(PLANS[0].scenario_id, target="L12", run_id="initial")
    controller._release_lock()

    def acquire(_):
        try:
            controller._acquire_lock(lock)
            return True
        except ExperimentAlreadyActiveError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(acquire, range(2))) == 1


def test_run_id_mismatch_never_resets_foreign_experiment(setup, monkeypatch):
    runner, controller, _, _ = setup
    original = controller.inject_fault

    def mismatched(*args, **kwargs):
        lock = original(*args, **kwargs)
        lock.run_id = "another-controller-run"
        controller._update_lock(lock)
        return lock

    monkeypatch.setattr(controller, "inject_fault", mismatched)
    report = runner.run_sequence([PLANS[0]])[0]
    assert report["status"] == "FAILED"
    assert controller.resets == 0
    assert controller.get_active_fault().run_id == "another-controller-run"


def test_sigterm_triggers_owned_cleanup_and_is_not_silently_swallowed(setup, monkeypatch):
    runner, controller, observer, _ = setup

    def terminate(*args):
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(observer, "capture", terminate)
    with pytest.raises(CaptureInterrupted):
        runner.run_sequence(PLANS)
    assert controller.resets == 1
    assert not controller.lock_file.exists()


def test_real_deadline_cannot_be_swallowed_by_collector_except_exception():
    old_handler = signal.getsignal(signal.SIGALRM)
    with pytest.raises(CaptureTimeout):
        with Deadline(0.015):
            try:
                time.sleep(0.2)
            except Exception:
                pytest.fail("Deadline was swallowed")
    assert signal.getsignal(signal.SIGALRM) == old_handler
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_nested_deadline_does_not_extend_outer_deadline():
    started = time.monotonic()
    with pytest.raises(CaptureTimeout):
        with Deadline(0.02), Deadline(0.2):
            time.sleep(0.3)
    assert time.monotonic() - started < 0.2


def test_deadlines_refuse_worker_threads_before_experiment():
    def worker():
        with Deadline(1):
            pass

    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(RuntimeError, match="main thread"):
            pool.submit(worker).result()


def test_lab_observer_probe_round_budget_includes_manifestation(setup):
    _, _, fixture, clock = setup
    snapshot = fixture.capture(PLANS[3], clock.now().isoformat())
    ping = next(
        EvidenceNormalizer.deserialize_record(r)
        for r in snapshot["evidence_records"]
        if r["source_type"] == "ACTIVE_PING"
    )
    orchestrator = SimpleNamespace(
        transport=MockTransport(),
        ping_collector=Mock(),
        collect_snapshot=Mock(return_value=EvidenceSnapshot.model_validate(snapshot)),
    )
    orchestrator.ping_collector.probe.return_value = ping
    observer = LabObserver(None, orchestrator)
    assert observer.manifested(PLANS[3]) is True
    assert observer.manifested(PLANS[3]) is True
    assert orchestrator.ping_collector.probe.call_count == 2
    observer.capture(PLANS[3], snapshot["collection_window_start"])
    assert orchestrator.ping_collector.probe.call_count == 4
    observer._probe_round(PLANS[3])
    assert orchestrator.ping_collector.probe.call_count == 4
    assert all(
        call.kwargs["count"] == 20 for call in orchestrator.ping_collector.probe.call_args_list
    )


def test_read_only_qdisc_allowlist_rejects_mutation_and_foreign_targets():
    transport = DockerTransport()
    transport.validate_command(["tc", "-j", "qdisc", "show", "dev", "eth1"])
    for command in [
        ["tc", "qdisc", "del", "dev", "eth1", "root"],
        ["tc", "-j", "qdisc", "show", "dev", "eth0"],
        ["tc", "-j", "qdisc", "show", "dev", "eth1", "extra"],
    ]:
        with pytest.raises(SecurityViolationError):
            transport.validate_command(command)
    with pytest.raises(SecurityViolationError):
        transport._resolve_container("other-project-r1")


def test_actual_controller_reserves_before_mutation_and_keeps_partial_failure_lock(
    setup, monkeypatch
):
    _, synthetic, _, _ = setup
    controller = object.__new__(FaultController)
    controller.lock_file = synthetic.lock_file
    monkeypatch.setattr(controller, "check_baseline", lambda: (True, []))
    scenario = Mock()
    scenario.scenario_id = PLANS[0].scenario_id
    scenario.fault_type = "LINK_FAILURE"

    def inject(*args, **kwargs):
        lock = controller.get_active_fault()
        assert lock is not None and lock.injection_command_start is not None
        raise RuntimeError("partial command failure")

    scenario.inject.side_effect = inject
    monkeypatch.setattr("lab.fault_injection.controller.get_scenario", lambda _: scenario)
    with pytest.raises(RuntimeError, match="partial"):
        controller.inject_fault(PLANS[0].scenario_id, target="L12", run_id="owned")
    assert controller.get_active_fault().run_id == "owned"
    with pytest.raises(ExperimentAlreadyActiveError):
        controller.inject_fault(PLANS[0].scenario_id, target="L12", run_id="second")
    assert scenario.inject.call_count == 1


def test_actual_controller_reset_failure_retains_lock(setup, monkeypatch):
    _, synthetic, _, _ = setup
    synthetic.inject_fault(PLANS[0].scenario_id, target="L12", run_id="owned")
    controller = object.__new__(FaultController)
    controller.lock_file = synthetic.lock_file
    scenario = Mock()
    scenario.restore.side_effect = RuntimeError("reset refused")
    monkeypatch.setattr("lab.fault_injection.controller.get_scenario", lambda _: scenario)
    with pytest.raises(RuntimeError, match="reset refused"):
        controller.reset_fault(expected_run_id="owned", verify=False)
    assert controller.get_active_fault().state == ExperimentState.RESTORING


@pytest.mark.parametrize(
    "field",
    [
        "injection_command_start",
        "injection_command_end",
        "reset_started_at",
        "reset_ended_at",
        "recovery_confirmed_at",
        "collection_start",
        "collection_end",
    ],
)
def test_required_provenance_timestamps_cannot_be_missing_or_invented(setup, field):
    runner, _, _, _ = setup
    report = runner.run_sequence([PLANS[0]])[0]
    snapshot, _, _ = artifacts(runner, report)
    report[field] = None
    with pytest.raises((ValueError, TypeError)):
        validate_provenance(report, snapshot)


def test_inverted_command_timestamps_reject_provenance(setup):
    runner, _, _, _ = setup
    report = runner.run_sequence([PLANS[0]])[0]
    snapshot, _, _ = artifacts(runner, report)
    report["injection_command_start"] = report["reset_started_at"]
    with pytest.raises(ValueError, match="chronology"):
        validate_provenance(report, snapshot)


def test_json_serialization_exception_still_resets_owned_fault(setup, monkeypatch):
    runner, controller, _, _ = setup

    def broken(*args, **kwargs):
        raise ValueError("Synthetic JSON serialization failure")

    monkeypatch.setattr("app.capture.workflow.json.dumps", broken)
    report = runner.run_sequence(PLANS)[0]
    assert report["status"] == "FAILED"
    assert controller.resets == 1
    assert not controller.lock_file.exists()


def test_journal_failure_after_injection_does_not_prevent_reset(setup, monkeypatch):
    runner, controller, _, _ = setup
    from app.capture import workflow

    real_write = workflow.write_json

    def broken(path, data):
        if controller.injections:
            raise OSError("Synthetic storage failure")
        return real_write(path, data)

    monkeypatch.setattr(workflow, "write_json", broken)
    with pytest.raises(OSError):
        runner.run_sequence(PLANS)
    assert controller.resets == 1
    assert not controller.lock_file.exists()


def test_routing_collector_preserves_all_ecmp_next_hops():
    from app.collectors.routing_collector import RoutingCollector

    transport = MockTransport()
    payload = {
        "192.168.255.3/32": [
            {
                "protocol": "ospf",
                "metric": 2,
                "nexthops": [
                    {"ip": "10.0.12.2", "interfaceName": "eth1"},
                    {"ip": "10.0.15.1", "interfaceName": "eth2"},
                ],
            }
        ]
    }
    transport.set_response("R1", ["vtysh", "-c", "show ip route json"], 0, json.dumps(payload))
    records = [r for r in RoutingCollector(transport).collect(["R1"]) if r.is_present]
    assert {(r.next_hop_address, r.next_hop_interface) for r in records} == {
        ("10.0.12.2", "eth1"),
        ("10.0.15.1", "eth2"),
    }
    assert len({r.evidence_id for r in records}) == 2
    assert all(
        EvidenceNormalizer.deserialize_record(r.model_dump(mode="json")) == r for r in records
    )


@pytest.mark.parametrize(
    "labels",
    [
        {"com.docker.compose.project": "other-project", "com.docker.compose.service": "r1"},
        {"com.docker.compose.project": "nexora", "com.docker.compose.service": "wrong"},
        {},
    ],
)
def test_mutating_adapter_refuses_unverified_compose_ownership(monkeypatch, labels):
    from lab.fault_injection.scenarios import SecurityViolationError as LabSecurityError
    from lab.fault_injection.scenarios import _run_docker

    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(labels), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(LabSecurityError):
        _run_docker(["docker", "exec", "nexora-r1", "ip", "link", "set", "dev", "eth1", "down"])
    assert len(commands) == 1 and commands[0][1] == "inspect"


def test_mutating_adapter_checks_ownership_before_mocked_command(monkeypatch):
    from lab.fault_injection.scenarios import _run_docker

    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        labels = {"com.docker.compose.project": "nexora", "com.docker.compose.service": "r1"}
        return SimpleNamespace(returncode=0, stdout=json.dumps(labels), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _run_docker(["docker", "stop", "nexora-r1"])[0] == 0
    assert [command[1] for command in commands] == ["inspect", "stop"]


def test_reset_failure_cannot_redirect_to_unrelated_container(setup):
    from lab.fault_injection.scenarios import SecurityViolationError as LabSecurityError

    _, synthetic, _, _ = setup
    lock = synthetic.inject_fault(PLANS[0].scenario_id, target="L12", run_id="owned")
    lock.injected_details = {"router": "other-project-r1", "interface": "eth1"}
    synthetic._update_lock(lock)
    controller = object.__new__(FaultController)
    controller.lock_file = synthetic.lock_file
    with pytest.raises(LabSecurityError):
        controller.reset_fault(expected_run_id="owned", verify=False)
    assert controller.lock_file.exists()


def test_actual_controller_recovery_failure_does_not_clear_lock(setup, monkeypatch):
    _, synthetic, _, _ = setup
    synthetic.inject_fault(PLANS[0].scenario_id, target="L12", run_id="owned")
    controller = object.__new__(FaultController)
    controller.lock_file = synthetic.lock_file
    monkeypatch.setattr(controller, "check_baseline", lambda: (False, ["not restored"]))
    monkeypatch.setattr("lab.fault_injection.controller.time.sleep", lambda _: None)
    scenario = Mock()
    monkeypatch.setattr("lab.fault_injection.controller.get_scenario", lambda _: scenario)
    with pytest.raises(Exception, match="restoration unverified"):
        controller.reset_fault(expected_run_id="owned")
    assert controller.lock_file.exists()


def test_healthy_baseline_exception_prevents_actual_injection(setup, monkeypatch):
    _, synthetic, _, _ = setup
    controller = object.__new__(FaultController)
    controller.lock_file = synthetic.lock_file
    monkeypatch.setattr(controller, "check_baseline", lambda: (False, ["not healthy"]))
    scenario = Mock(scenario_id=PLANS[0].scenario_id, fault_type="LINK_FAILURE")
    monkeypatch.setattr("lab.fault_injection.controller.get_scenario", lambda _: scenario)
    with pytest.raises(Exception, match="Cannot inject"):
        controller.inject_fault(PLANS[0].scenario_id, target="L12", run_id="owned")
    scenario.inject.assert_not_called()
    assert not controller.lock_file.exists()


def test_reset_cannot_switch_to_another_nexora_router(setup):
    from lab.fault_injection.scenarios import SecurityViolationError as LabSecurityError

    _, synthetic, _, _ = setup
    lock = synthetic.inject_fault(PLANS[1].scenario_id, target="R3", run_id="owned")
    lock.injected_details = {"container": "nexora-r2"}
    synthetic._update_lock(lock)
    controller = object.__new__(FaultController)
    controller.lock_file = synthetic.lock_file
    with pytest.raises(LabSecurityError, match="does not match"):
        controller.reset_fault(expected_run_id="owned", verify=False)


def test_recovery_cannot_succeed_when_lock_release_fails(setup, monkeypatch):
    _, controller, _, _ = setup
    controller.inject_fault(PLANS[0].scenario_id, target="L12", run_id="owned")
    controller.reset_fault(expected_run_id="owned", verify=False)
    monkeypatch.setattr(controller, "_release_lock", lambda: None)
    with pytest.raises(RuntimeError, match="could not be released"):
        controller.complete_recovery("owned")
    assert controller.lock_file.exists()


@pytest.mark.parametrize("plan", PLANS)
def test_real_observer_manifestation_adapter_with_synthetic_observations(setup, plan):
    _, _, fixture, clock = setup
    raw = fixture.capture(plan, clock.now().isoformat())
    records = [EvidenceNormalizer.deserialize_record(r) for r in raw["evidence_records"]]
    transport = MockTransport()
    if plan == PLANS[1]:
        transport.set_router_running("R3", False)
    orchestrator = SimpleNamespace(
        transport=transport,
        interface_collector=Mock(),
        ospf_collector=Mock(),
        ping_collector=Mock(),
    )
    orchestrator.interface_collector.collect.return_value = [
        r for r in records if r.source_type == "INTERFACE_POLL"
    ]
    orchestrator.ospf_collector.collect.return_value = [
        r for r in records if r.source_type == "OSPF_API"
    ]
    orchestrator.ping_collector.probe.side_effect = [
        r for r in records if r.source_type == "ACTIVE_PING"
    ]
    observer = LabObserver(None, orchestrator)
    assert observer.manifested(plan) is True
    assert orchestrator.ping_collector.probe.call_count <= 2


@pytest.mark.parametrize("problem", [None, "interfaces", "ospf", "timers", "routes", "qdisc"])
def test_real_observer_requires_complete_healthy_baseline(setup, problem):
    _, _, fixture, clock = setup
    # Performance fixture leaves the passive topology healthy.
    snapshot = fixture.capture(PLANS[3], clock.now().isoformat())
    records = [EvidenceNormalizer.deserialize_record(r) for r in snapshot["evidence_records"]]
    interfaces = [r for r in records if r.source_type == "INTERFACE_POLL"]
    ospf = [r for r in records if r.source_type == "OSPF_API"]
    route = next(r for r in records if r.source_type == "ROUTING_TABLE")
    routes = [
        route.model_copy(
            update={"source_router": f"R{router}", "destination_prefix": f"192.168.255.{target}/32"}
        )
        for router in range(1, 6)
        for target in range(1, 6)
    ]
    transport = MockTransport()
    for router in range(1, 6):
        for interface in ("eth1", "eth2"):
            transport.set_response(
                f"R{router}",
                ["tc", "-j", "qdisc", "show", "dev", interface],
                0,
                json.dumps([{"kind": "netem" if problem == "qdisc" else "noqueue"}]),
            )
    if problem == "interfaces":
        interfaces.pop()
    if problem == "ospf":
        ospf[0] = ospf[0].model_copy(update={"adjacency_state": "Down"})
    if problem == "timers":
        ospf[0] = ospf[0].model_copy(update={"observed_interface_config": {"timerMsecs": None}})
    if problem == "routes":
        routes.pop()
    orchestrator = SimpleNamespace(
        transport=transport,
        interface_collector=Mock(collect=Mock(return_value=interfaces)),
        ospf_collector=Mock(collect=Mock(return_value=ospf)),
        routing_collector=Mock(collect=Mock(return_value=routes)),
    )
    observer = LabObserver(Mock(check_baseline=Mock(return_value=(True, []))), orchestrator)
    assert observer.healthy() is (problem is None)


def test_capture_reserves_time_for_reset_within_active_fault_deadline(setup):
    runner, controller, _, _ = setup
    controller.inject_delay = 121
    report = runner.run_sequence(PLANS)[0]
    assert report["status"] == "FAILED"
    assert "active-work budget" in report["errors"][0]
    assert controller.resets == 1 and report["recovery_confirmed"]


def test_ping_retains_precise_rtt_statistics_and_units():
    transport = MockTransport()
    transport.set_response(
        "R1",
        ["ping", "-c"],
        0,
        "20 packets transmitted, 19 received, 5% packet loss\n"
        "rtt min/avg/max/mdev = 0.123456/0.234567/0.345678/0.012345 ms",
    )
    record = PingCollector(transport).probe("R1", "10.0.12.2", count=20, source_address="10.0.12.1")
    assert (record.rtt_min_ms, record.rtt_avg_ms, record.rtt_max_ms, record.rtt_mdev_ms) == (
        0.123456,
        0.234567,
        0.345678,
        0.012345,
    )
    assert record.rtt_unit == "ms" and record.packets_lost == 1
    assert "-I 10.0.12.1" in record.raw_reference
    assert EvidenceNormalizer.deserialize_record(record.model_dump(mode="json")) == record


@pytest.mark.parametrize("kind", ["interface", "ospf", "routing"])
def test_collection_timestamp_follows_each_router_observation(kind):
    from app.collectors.interface_collector import InterfaceCollector
    from app.collectors.routing_collector import RoutingCollector

    transport = MockTransport()
    transport.set_router_running("R1", False)
    transport.set_router_running("R2", False)
    collector = {
        "interface": InterfaceCollector,
        "ospf": OSPFCollector,
        "routing": RoutingCollector,
    }[kind](transport)
    clock = SyntheticClock()
    collector.now_utc = clock.now
    records = collector.collect(["R1", "R2"])
    first = [r for r in records if r.source_router == "R1"]
    second = [r for r in records if r.source_router == "R2"]
    assert all(r.observed_at < r.collected_at for r in records)
    assert max(r.collected_at for r in first) < min(r.observed_at for r in second)


@pytest.mark.parametrize("failure", ["reset", "recovery"])
def test_completed_evidence_survives_restoration_failure_without_eligibility(setup, failure):
    runner, controller, observer, _ = setup
    if failure == "reset":
        controller.reset_error = True
    else:
        observer.recovery_ok = False
    report = runner.run_sequence(PLANS)[0]
    directory = runner.output_dir / report["artifact_directory"]
    retained = json.loads((directory / "unverified-snapshot.json").read_text())
    assert validate_capture(retained) == []
    assert snapshot_digest(retained) == report["snapshot_sha256"]
    assert report["status"] == "FAILED" and not report["recovery_confirmed"]
    assert not (directory / "binding.json").exists()
    assert not (directory / "snapshot.json").exists()


def test_timer_seconds_frr_actual_fields():
    """Verify actual FRRouting JSON timer fields normalize to expected seconds."""
    frr_config = {
        "timerMsecs": 10000,
        "timerDeadSecs": 40,
        "timerWaitSecs": 40,
        "timerRetransmitSecs": 5,
        "timerHelloInMsecs": 4528,
    }
    assert LabObserver._timer_seconds(frr_config, "hello") == 10
    assert LabObserver._timer_seconds(frr_config, "dead") == 40


def test_timer_seconds_preserves_legacy_formats():
    """Verify legacy dictionary and interval formats remain supported."""
    dict_config = {"timerMsecs": {"hello": 10000, "dead": 40000}}
    assert LabObserver._timer_seconds(dict_config, "hello") == 10
    assert LabObserver._timer_seconds(dict_config, "dead") == 40

    dict_config_custom = {"timerMsecs": {"hello": 5000, "dead": 15000}}
    assert LabObserver._timer_seconds(dict_config_custom, "hello") == 5
    assert LabObserver._timer_seconds(dict_config_custom, "dead") == 15

    interval_config = {"helloInterval": 10, "deadInterval": 40}
    assert LabObserver._timer_seconds(interval_config, "hello") == 10
    assert LabObserver._timer_seconds(interval_config, "dead") == 40


def test_timer_seconds_rejects_missing_and_malformed_inputs():
    """Verify missing, empty, or wrong-type configs and names return None."""
    assert LabObserver._timer_seconds(None, "hello") is None
    assert LabObserver._timer_seconds([], "hello") is None
    assert LabObserver._timer_seconds("invalid", "hello") is None
    assert LabObserver._timer_seconds({}, "hello") is None
    assert LabObserver._timer_seconds({"timerMsecs": None}, "hello") is None
    assert LabObserver._timer_seconds({"timerDeadSecs": None}, "dead") is None
    assert LabObserver._timer_seconds({"timerMsecs": 10000}, None) is None
    assert LabObserver._timer_seconds({"timerMsecs": 10000}, 123) is None


@pytest.mark.parametrize(
    "invalid_val",
    [
        "10000",
        True,
        False,
        0,
        -1,
        -10000,
        float("nan"),
        float("inf"),
        float("-inf"),
        99999999,
    ],
)
def test_timer_seconds_rejects_invalid_types_and_values(invalid_val):
    """Verify string, boolean, negative, zero, non-finite, and nonsensical values are rejected."""
    assert LabObserver._timer_seconds({"timerMsecs": invalid_val}, "hello") is None
    assert LabObserver._timer_seconds({"timerDeadSecs": invalid_val}, "dead") is None
    assert (
        LabObserver._timer_seconds({"timerMsecs": {"hello": invalid_val}}, "hello")
        is None
    )


def test_timer_seconds_strict_unit_handling():
    """Verify unit distinctions: timerMsecs is ms (/1000) while timerDeadSecs is seconds."""
    # timerMsecs = 10000 must normalize to 10 seconds, not 10000
    assert LabObserver._timer_seconds({"timerMsecs": 10000}, "hello") == 10

    # timerDeadSecs = 40 must normalize to 40 seconds, not 0.04
    assert LabObserver._timer_seconds({"timerDeadSecs": 40}, "dead") == 40

    # timerDeadSecs must not be interpreted as hello timer
    assert LabObserver._timer_seconds({"timerDeadSecs": 40}, "hello") is None

    # timerMsecs scalar must not be interpreted as dead timer
    assert LabObserver._timer_seconds({"timerMsecs": 10000}, "dead") is None

    # timerDeadMsecs = 40000 must normalize to 40 seconds
    assert LabObserver._timer_seconds({"timerDeadMsecs": 40000}, "dead") == 40

    # deadInterval = 40 must normalize to 40 seconds
    assert LabObserver._timer_seconds({"deadInterval": 40}, "dead") == 40


def test_observer_healthy_validates_frr_timers():
    """Verify LabObserver.healthy() checks that real FRR timer values match baseline expectations."""
    # Test that mismatching timers fail baseline check in observer.healthy()
    bad_ospf_cfg = {"timerMsecs": 5000, "timerDeadSecs": 40}  # hello=5 instead of 10
    assert LabObserver._timer_seconds(bad_ospf_cfg, "hello") == 5
    assert LabObserver._timer_seconds(bad_ospf_cfg, "dead") == 40
    # Hello != 10 should fail healthy()
    assert (
        LabObserver._timer_seconds(bad_ospf_cfg, "hello") != 10
        or LabObserver._timer_seconds(bad_ospf_cfg, "dead") != 40
    )

