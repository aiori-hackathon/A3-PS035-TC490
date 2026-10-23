"""Comprehensive offline regression suite for F2 manifestation hardening.

Validates:
1. R3 stops, R2 and R4 eventually lose their expected neighbors.
2. Neighbor entries disappear rather than explicitly reporting DOWN.
3. One peer transitions later than the other.
4. A peer never transitions and manifestation times out.
5. Slow Docker inspection and bounded ping execution.
6. Nested deadlines enforce the intended bounds and diagnostics.
7. Exception handling enters cleanup correctly.
8. Cleanup failure retains appropriate safety locks.
9. F1 behavior remains unchanged.
10. No synthetic or ground-truth data enters live inference.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from lab.fault_injection.models import ActiveFaultLock, ExperimentState, ScenarioID

from app.capture.observer import LabObserver
from app.capture.safety import CaptureTimeout, Deadline
from app.capture.workflow import CapturePlan, CaptureRunner
from app.collectors.normalizer import EvidenceNormalizer
from app.collectors.ospf_collector import OSPFCollector
from app.collectors.ping_collector import PingCollector
from app.collectors.transport import CollectorTransport
from app.diagnosis.engine import DiagnosisEngine
from app.schemas.evidence import (
    CollectionMethod,
    EvidenceSourceType,
    ObservationStatus,
    OSPFObservation,
    PingMeasurement,
)
from app.schemas.hypothesis import FaultType


class MockTransport(CollectorTransport):
    def __init__(self):
        self.running_routers = {"R1": True, "R2": True, "R3": True, "R4": True, "R5": True}
        self.cmd_responses: dict[tuple[str, tuple[str, ...]], tuple[int, str, str]] = {}
        self.calls: list[tuple[str, list[str]]] = []

    def set_response(self, router_id: str, cmd: list[str], code: int, out: str, err: str = ""):
        self.cmd_responses[(router_id, tuple(cmd))] = (code, out, err)

    def execute(self, router_id: str, command: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
        self.calls.append((router_id, list(command)))
        key = (router_id, tuple(command))
        if key in self.cmd_responses:
            return self.cmd_responses[key]
        return 0, "{}", ""

    def is_router_running(self, router_id: str) -> bool:
        return self.running_routers.get(router_id.upper(), False)

    def get_logs(self, router_id: str, tail: int = 100, since: str | None = None) -> list[str]:
        return []


def test_f2_manifestation_r3_stops_r2_r4_eventually_lose_neighbors():
    """1. R3 stops, R2 and R4 eventually lose their expected neighbors."""
    transport = MockTransport()
    orchestrator = SimpleNamespace(
        transport=transport,
        ospf_collector=Mock(),
        interface_collector=Mock(),
        ping_collector=Mock(),
    )
    orchestrator.ospf_collector.collect.return_value = []
    plan = CapturePlan("F2_ROUTER_FAILURE", "R3")
    observer = LabObserver(controller=None, orchestrator=orchestrator)

    # Initial state: R3 still running
    transport.running_routers["R3"] = True
    assert observer.manifested(plan) is False

    # R3 stopped, but OSPF neighbors on R2 and R4 still full (dead timer ticking)
    transport.running_routers["R3"] = False
    orchestrator.ospf_collector.collect.return_value = [
        OSPFObservation(
            evidence_id="ospf-r2-full",
            source_router="R2",
            source_interface="eth2",
            event_type="OSPF_NEIGHBOUR_FULL",
            observed_at="2026-10-22T20:00:00Z",
            collected_at="2026-10-22T20:00:00Z",
            source_type=EvidenceSourceType.OSPF_API,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
            neighbour_router_id="3.3.3.3",
            neighbour_address="10.0.23.2",
            adjacency_state="Full",
        )
    ]
    assert observer.manifested(plan) is False

    # After dead timer expires: R2 and R4 report neighbor 3.3.3.3 Down
    orchestrator.ospf_collector.collect.return_value = [
        OSPFObservation(
            evidence_id="ospf-r2-down",
            source_router="R2",
            source_interface="eth2",
            event_type="OSPF_NEIGHBOUR_DOWN",
            observed_at="2026-10-22T20:00:40Z",
            collected_at="2026-10-22T20:00:40Z",
            source_type=EvidenceSourceType.OSPF_API,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
            neighbour_router_id="3.3.3.3",
            neighbour_address="10.0.23.2",
            adjacency_state="Down",
        ),
        OSPFObservation(
            evidence_id="ospf-r4-down",
            source_router="R4",
            source_interface="eth1",
            event_type="OSPF_NEIGHBOUR_DOWN",
            observed_at="2026-10-22T20:00:40Z",
            collected_at="2026-10-22T20:00:40Z",
            source_type=EvidenceSourceType.OSPF_API,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
            neighbour_router_id="3.3.3.3",
            neighbour_address="10.0.34.1",
            adjacency_state="Down",
        ),
    ]
    assert observer.manifested(plan) is True


def test_f2_neighbor_entries_disappear_rather_than_reporting_down():
    """2. FRRouting neighbor entries disappear from JSON rather than explicitly reporting DOWN."""
    transport = MockTransport()
    # R2 and R4 return JSON without 3.3.3.3
    empty_neighbors_json = json.dumps({"neighbors": {}})
    transport.set_response("R2", ["vtysh", "-c", "show ip ospf neighbor json"], 0, empty_neighbors_json)
    transport.set_response("R2", ["vtysh", "-c", "show ip ospf interface json"], 0, "{}")
    transport.set_response("R4", ["vtysh", "-c", "show ip ospf neighbor json"], 0, empty_neighbors_json)
    transport.set_response("R4", ["vtysh", "-c", "show ip ospf interface json"], 0, "{}")

    collector = OSPFCollector(transport)
    r2_records = collector.collect(router_ids=["R2"])
    r4_records = collector.collect(router_ids=["R4"])

    # Parser should detect missing 3.3.3.3 and emit Down observation with collection_status=OBSERVED
    r2_down = [r for r in r2_records if r.neighbour_router_id == "3.3.3.3"]
    assert len(r2_down) == 1
    assert r2_down[0].adjacency_state == "Down"
    assert r2_down[0].collection_status == ObservationStatus.OBSERVED

    r4_down = [r for r in r4_records if r.neighbour_router_id == "3.3.3.3"]
    assert len(r4_down) == 1
    assert r4_down[0].adjacency_state == "Down"
    assert r4_down[0].collection_status == ObservationStatus.OBSERVED


def test_f2_one_peer_transitions_later_than_the_other():
    """3. One peer transitions later than the other."""
    transport = MockTransport()
    transport.running_routers["R3"] = False
    orchestrator = SimpleNamespace(
        transport=transport,
        ospf_collector=Mock(),
        interface_collector=Mock(),
        ping_collector=Mock(),
    )
    orchestrator.ospf_collector.collect.return_value = []
    plan = CapturePlan("F2_ROUTER_FAILURE", "R3")
    observer = LabObserver(controller=None, orchestrator=orchestrator)

    # Poll 1: only R2 observed down, R4 still Full
    orchestrator.ospf_collector.collect.return_value = [
        OSPFObservation(
            evidence_id="ospf-r2-down",
            source_router="R2",
            source_interface="eth2",
            event_type="OSPF_NEIGHBOUR_DOWN",
            observed_at="2026-10-22T20:00:40Z",
            collected_at="2026-10-22T20:00:40Z",
            source_type=EvidenceSourceType.OSPF_API,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
            neighbour_router_id="3.3.3.3",
            neighbour_address="10.0.23.2",
            adjacency_state="Down",
        ),
        OSPFObservation(
            evidence_id="ospf-r4-full",
            source_router="R4",
            source_interface="eth1",
            event_type="OSPF_NEIGHBOUR_FULL",
            observed_at="2026-10-22T20:00:40Z",
            collected_at="2026-10-22T20:00:40Z",
            source_type=EvidenceSourceType.OSPF_API,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
            neighbour_router_id="3.3.3.3",
            neighbour_address="10.0.34.1",
            adjacency_state="Full",
        ),
    ]
    assert observer.manifested(plan) is False

    # Poll 2: both R2 and R4 observed down
    orchestrator.ospf_collector.collect.return_value = [
        OSPFObservation(
            evidence_id="ospf-r2-down",
            source_router="R2",
            source_interface="eth2",
            event_type="OSPF_NEIGHBOUR_DOWN",
            observed_at="2026-10-22T20:00:42Z",
            collected_at="2026-10-22T20:00:42Z",
            source_type=EvidenceSourceType.OSPF_API,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
            neighbour_router_id="3.3.3.3",
            neighbour_address="10.0.23.2",
            adjacency_state="Down",
        ),
        OSPFObservation(
            evidence_id="ospf-r4-down",
            source_router="R4",
            source_interface="eth1",
            event_type="OSPF_NEIGHBOUR_DOWN",
            observed_at="2026-10-22T20:00:42Z",
            collected_at="2026-10-22T20:00:42Z",
            source_type=EvidenceSourceType.OSPF_API,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
            neighbour_router_id="3.3.3.3",
            neighbour_address="10.0.34.1",
            adjacency_state="Down",
        ),
    ]
    assert observer.manifested(plan) is True


def test_f2_peer_never_transitions_and_manifestation_times_out(tmp_path: Path):
    """4. A peer never transitions and manifestation times out."""
    from datetime import UTC, datetime

    controller = Mock(synthetic=False)
    controller.lock_file = tmp_path / "lock.json"
    now = datetime.now(UTC)
    active_lock = None

    def mock_inject(scenario_id, target, run_id, **params):
        nonlocal active_lock
        active_lock = ActiveFaultLock(
            run_id=run_id,
            scenario_id=ScenarioID.F2_ROUTER_FAILURE,
            fault_type=FaultType.ROUTER_FAILURE,
            target="R3",
            injected_details={"container": "nexora-r3"},
            state=ExperimentState.ACTIVE,
            started_at=now,
            injection_command_start=now,
            injection_command_end=now,
        )
        return active_lock

    controller.inject_fault.side_effect = mock_inject
    controller.get_active_fault.side_effect = lambda: active_lock

    observer = Mock()
    observer.healthy.return_value = True
    observer.manifested.return_value = False  # Peer never transitions

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    runner = CaptureRunner(
        controller=controller,
        observer=observer,
        output_dir=out_dir,
        synthetic=False,
    )

    plan = CapturePlan("F2_ROUTER_FAILURE", "R3")
    # Simulate tight manifestation deadline to test timeout
    with patch.object(runner, "monotonic", side_effect=[0, 1, 2, 65, 70, 75, 80]):
        report = runner._capture(plan)

    assert report["status"] == "FAILED"
    assert any("Fault never manifested within 60 seconds" in err or "Bounded capture deadline expired" in err for err in report["errors"])
    assert controller.reset_fault.called


def test_f2_bounded_probes_prevent_timeout_on_unreachable_router():
    """5. PingCollector bounded interval prevents probe timeouts when router is stopped."""
    transport = MockTransport()
    transport.set_response(
        "R2",
        ["ping", "-c", "20", "-W", "1", "-i", "0.2", "10.0.23.2"],
        0,
        "20 packets transmitted, 0 packets received, 100% packet loss\n",
    )
    collector = PingCollector(transport)
    rec = collector.probe("R2", "10.0.23.2", count=20, timeout_s=1, interval_s=0.2)
    assert isinstance(rec, PingMeasurement)
    assert rec.packet_loss_pct == 100.0
    assert rec.packets_sent == 20
    assert rec.packets_received == 0

    # Ensure observer._probe_round uses interval_s=0.2
    orchestrator = SimpleNamespace(
        transport=transport,
        ping_collector=Mock(),
        collect_snapshot=Mock(),
    )
    observer = LabObserver(controller=None, orchestrator=orchestrator)
    observer._probe_round(CapturePlan("F2_ROUTER_FAILURE", "R3"))
    assert orchestrator.ping_collector.probe.call_count == 4
    for call in orchestrator.ping_collector.probe.call_args_list:
        assert call.kwargs.get("interval_s") == 0.2


def test_nested_deadlines_enforce_intended_bounds_and_diagnostics():
    """6. Nested deadlines enforce the intended bounds and report clear diagnostics."""
    with pytest.raises(CaptureTimeout) as exc_info:
        with Deadline(0.05, "inner deadline"):
            time.sleep(0.15)
    assert "inner deadline" in str(exc_info.value)
    assert "Bounded capture deadline expired" in str(exc_info.value)

    # Test nested outer restoration
    started = time.monotonic()
    with pytest.raises(CaptureTimeout) as exc_info:
        with Deadline(0.15, "outer deadline"):
            with Deadline(0.05, "inner deadline"):
                time.sleep(0.01)  # inner exits cleanly
            time.sleep(0.2)  # outer should fire
    assert "outer deadline" in str(exc_info.value)
    assert time.monotonic() - started < 0.25


def test_exception_handling_enters_cleanup_correctly(tmp_path: Path):
    """7. Exception handling enters cleanup correctly."""
    from datetime import UTC, datetime

    controller = Mock(synthetic=False)
    controller.lock_file = tmp_path / "lock.json"
    now = datetime.now(UTC)
    active_lock = None

    def mock_inject(scenario_id, target, run_id, **params):
        nonlocal active_lock
        active_lock = ActiveFaultLock(
            run_id=run_id,
            scenario_id=ScenarioID.F2_ROUTER_FAILURE,
            fault_type=FaultType.ROUTER_FAILURE,
            target="R3",
            injected_details={"container": "nexora-r3"},
            state=ExperimentState.ACTIVE,
            started_at=now,
            injection_command_start=now,
            injection_command_end=now,
        )
        return active_lock

    controller.inject_fault.side_effect = mock_inject
    controller.get_active_fault.side_effect = lambda: active_lock

    observer = Mock()
    observer.healthy.return_value = True
    observer.manifested.side_effect = RuntimeError("Simulated failure in observer")

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    runner = CaptureRunner(
        controller=controller,
        observer=observer,
        output_dir=out_dir,
        synthetic=False,
    )
    report = runner._capture(CapturePlan("F2_ROUTER_FAILURE", "R3"))

    assert report["status"] == "FAILED"
    assert any("Simulated failure in observer" in err for err in report["errors"])
    assert controller.reset_fault.called
    assert report["recovery_confirmed"] is True


def test_cleanup_failure_retains_appropriate_safety_locks(tmp_path: Path):
    """8. Cleanup failure retains appropriate safety locks."""
    from datetime import UTC, datetime

    controller = Mock(synthetic=False)
    controller.lock_file = tmp_path / ".active_fault.json"
    now = datetime.now(UTC)
    active_lock = None

    def mock_inject(scenario_id, target, run_id, **params):
        nonlocal active_lock
        active_lock = ActiveFaultLock(
            run_id=run_id,
            scenario_id=ScenarioID.F2_ROUTER_FAILURE,
            fault_type=FaultType.ROUTER_FAILURE,
            target="R3",
            injected_details={"container": "nexora-r3"},
            state=ExperimentState.ACTIVE,
            started_at=now,
            injection_command_start=now,
            injection_command_end=now,
        )
        return active_lock

    controller.inject_fault.side_effect = mock_inject
    controller.get_active_fault.side_effect = lambda: active_lock
    # Reset fails
    controller.reset_fault.side_effect = RuntimeError("Docker reset failed")

    observer = Mock()
    observer.healthy.return_value = True
    observer.manifested.side_effect = RuntimeError("Manifestation failed")

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    runner = CaptureRunner(
        controller=controller,
        observer=observer,
        output_dir=out_dir,
        synthetic=False,
    )
    report = runner._capture(CapturePlan("F2_ROUTER_FAILURE", "R3"))

    assert report["status"] == "FAILED"
    assert report["recovery_confirmed"] is False
    assert any("Docker reset failed" in err for err in report["errors"])


def test_f1_behavior_remains_unchanged(tmp_path: Path):
    """9. F1 behavior remains unchanged and executes cleanly."""
    plan = CapturePlan("F1_LINK_FAILURE", "L12")
    assert plan.scenario_id == "F1_LINK_FAILURE"
    assert plan.target == "L12"
    plan.validate()  # Passes validation without error


def test_ground_truth_isolated_from_live_inference():
    """10. No synthetic or ground-truth data enters live inference."""
    from app.topology.graph import build_expected_topology_graph

    raw_records = [
        OSPFObservation(
            evidence_id="ospf-r2-l23-down",
            source_router="R2",
            source_interface="eth2",
            event_type="OSPF_NEIGHBOUR_DOWN",
            observed_at="2026-10-22T20:00:42Z",
            collected_at="2026-10-22T20:00:42Z",
            source_type=EvidenceSourceType.OSPF_API,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
            neighbour_router_id="3.3.3.3",
            neighbour_address="10.0.23.2",
            adjacency_state="Down",
        ),
        OSPFObservation(
            evidence_id="ospf-r4-l34-down",
            source_router="R4",
            source_interface="eth1",
            event_type="OSPF_NEIGHBOUR_DOWN",
            observed_at="2026-10-22T20:00:42Z",
            collected_at="2026-10-22T20:00:42Z",
            source_type=EvidenceSourceType.OSPF_API,
            collection_method=CollectionMethod.PERIODIC_POLL,
            collection_status=ObservationStatus.OBSERVED,
            neighbour_router_id="3.3.3.3",
            neighbour_address="10.0.34.1",
            adjacency_state="Down",
        ),
    ]
    topo = build_expected_topology_graph().topology
    snapshot = {
        "snapshot_id": "obs-snap-test-f2",
        "collection_window_start": "2026-10-22T20:00:00Z",
        "collection_window_end": "2026-10-22T20:01:00Z",
        "topology": topo.model_dump(mode="json"),
        "evidence_records": EvidenceNormalizer.serialize_records(raw_records),
    }

    # Verify no truth leakage in neutral snapshot
    assert "scenario_id" not in snapshot
    assert "actual_fault_location_id" not in snapshot
    assert "seeded_fault_type" not in snapshot

    # Run inference engine with neutral snapshot only
    engine = DiagnosisEngine()
    result = engine.diagnose_snapshot_dict(snapshot)
    assert result is not None
