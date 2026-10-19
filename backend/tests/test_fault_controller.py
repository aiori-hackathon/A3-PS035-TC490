"""
NEXORA Fault Controller Unit Tests
Team: A3-PS035-TC490 | Problem Statement: PS-035

Tests safety boundaries, target validations, parameter constraints,
concurrency locks, and ground-truth isolation.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from lab.fault_injection.controller import (
    ExperimentAlreadyActiveError,
    FaultController,
)
from lab.fault_injection.models import (
    ActiveFaultLock,
    ExperimentOutcome,
    ExperimentRecord,
    ExperimentState,
    NetworkObservation,
    ScenarioID,
)
from lab.fault_injection.scenarios import (
    InvalidTargetError,
    SecurityViolationError,
    get_scenario,
)

from app.evaluation.ground_truth import FaultInjectionRecord
from app.schemas.hypothesis import FaultLocationKind, FaultType


class TestScenarioValidation:
    """Validate target restrictions, forbidden interface guards, and parameter boundaries."""

    def test_all_five_scenarios_registered(self):
        expected = [
            ScenarioID.F1_LINK_FAILURE,
            ScenarioID.F2_ROUTER_FAILURE,
            ScenarioID.F3_OSPF_CONFIG_MISMATCH,
            ScenarioID.F4_PACKET_LOSS,
            ScenarioID.F5_HIGH_LATENCY,
        ]
        for sid in expected:
            sc = get_scenario(sid)
            assert sc.scenario_id == sid

    def test_invalid_scenario_id_rejected(self):
        with pytest.raises(InvalidTargetError, match="Invalid scenario ID"):
            get_scenario("F99_NON_EXISTENT")

    @pytest.mark.parametrize("forbidden", ["eth0", "mgmt", "mgmt0", "lo"])
    def test_f1_refuses_management_interface(self, forbidden: str):
        sc = get_scenario(ScenarioID.F1_LINK_FAILURE)
        with pytest.raises(SecurityViolationError, match="strictly forbidden"):
            sc.validate_target(forbidden)

    @pytest.mark.parametrize("forbidden", ["eth0", "mgmt", "mgmt0", "lo"])
    def test_f4_refuses_management_interface(self, forbidden: str):
        sc = get_scenario(ScenarioID.F4_PACKET_LOSS)
        with pytest.raises(SecurityViolationError, match="strictly forbidden|management"):
            sc.validate_target(forbidden)
        with pytest.raises(SecurityViolationError, match="management"):
            sc.validate_target("R1", interface=forbidden)

    @pytest.mark.parametrize("forbidden", ["eth0", "mgmt", "mgmt0", "lo"])
    def test_f5_refuses_management_interface(self, forbidden: str):
        sc = get_scenario(ScenarioID.F5_HIGH_LATENCY)
        with pytest.raises(SecurityViolationError, match="strictly forbidden|management"):
            sc.validate_target(forbidden)
        with pytest.raises(SecurityViolationError, match="management"):
            sc.validate_target("R1", interface=forbidden)

    def test_f1_invalid_link_rejected(self):
        sc = get_scenario(ScenarioID.F1_LINK_FAILURE)
        with pytest.raises(InvalidTargetError, match="not an approved link"):
            sc.validate_target("L99")
        with pytest.raises(InvalidTargetError, match="not an approved link"):
            sc.validate_target("R1")

    def test_f2_invalid_router_rejected(self):
        sc = get_scenario(ScenarioID.F2_ROUTER_FAILURE)
        with pytest.raises(InvalidTargetError, match="not an approved router"):
            sc.validate_target("R99")
        with pytest.raises(InvalidTargetError, match="not an approved router"):
            sc.validate_target("L12")

    def test_f4_packet_loss_bounds(self):
        sc = get_scenario(ScenarioID.F4_PACKET_LOSS)
        # Valid
        sc.validate_target("L12", loss_pct=1)
        sc.validate_target("L12", loss_pct=50)
        sc.validate_target("L12", loss_pct=100)

        # Invalid bounds
        with pytest.raises(ValueError, match="between 1 and 100"):
            sc.validate_target("L12", loss_pct=0)
        with pytest.raises(ValueError, match="between 1 and 100"):
            sc.validate_target("L12", loss_pct=101)
        with pytest.raises(ValueError, match="between 1 and 100"):
            sc.validate_target("L12", loss_pct="invalid")

    def test_f5_latency_bounds(self):
        sc = get_scenario(ScenarioID.F5_HIGH_LATENCY)
        # Valid
        sc.validate_target("L12", delay_ms=10)
        sc.validate_target("L12", delay_ms=500)
        sc.validate_target("L12", delay_ms=2000)

        # Invalid bounds
        with pytest.raises(ValueError, match="between 1 and 2000"):
            sc.validate_target("L12", delay_ms=0)
        with pytest.raises(ValueError, match="between 1 and 2000"):
            sc.validate_target("L12", delay_ms=2001)


class TestFaultLocationMapping:
    """Verify scenarios output correct typed FaultLocation objects."""

    def test_f1_link_fault_location(self):
        sc = get_scenario(ScenarioID.F1_LINK_FAILURE)
        loc = sc.get_fault_location("L12")
        assert loc.kind == FaultLocationKind.LINK
        assert loc.component_id == "L12"
        assert set(loc.affected_routers) == {"R1", "R2"}

    def test_f2_router_fault_location(self):
        sc = get_scenario(ScenarioID.F2_ROUTER_FAILURE)
        loc = sc.get_fault_location("R3")
        assert loc.kind == FaultLocationKind.ROUTER
        assert loc.component_id == "R3"
        assert loc.affected_routers == ["R3"]

    def test_f3_config_mismatch_location(self):
        sc = get_scenario(ScenarioID.F3_OSPF_CONFIG_MISMATCH)
        loc = sc.get_fault_location("L34")
        assert loc.kind == FaultLocationKind.LINK
        assert loc.component_id == "L34"
        assert set(loc.affected_routers) == {"R3", "R4"}


class TestConcurrencyAndLock:
    """Verify single-active-experiment lock mechanics and idempotency."""

    def test_lock_creation_and_release(self, tmp_path: Path):
        lock_file = tmp_path / ".active_fault.json"
        reports_dir = tmp_path / "reports"
        controller = FaultController(lock_file=lock_file, reports_dir=reports_dir)

        assert controller.get_active_fault() is None

        lock = ActiveFaultLock(
            run_id="test-run-1",
            scenario_id=ScenarioID.F1_LINK_FAILURE,
            fault_type=FaultType.LINK_FAILURE,
            target="L12",
            injected_details={"router": "nexora-r1"},
            state=ExperimentState.ACTIVE,
            started_at=datetime.now(UTC),
        )
        controller._acquire_lock(lock)
        assert lock_file.exists()

        active = controller.get_active_fault()
        assert active is not None
        assert active.run_id == "test-run-1"
        assert active.target == "L12"

        # Attempting second acquisition must fail
        with pytest.raises(ExperimentAlreadyActiveError, match="already active"):
            controller._acquire_lock(lock)

        controller._release_lock()
        assert not lock_file.exists()
        assert controller.get_active_fault() is None

    def test_reset_idempotent_when_no_active_fault(self, tmp_path: Path):
        lock_file = tmp_path / ".active_fault.json"
        controller = FaultController(lock_file=lock_file, reports_dir=tmp_path / "reports")
        # Calling reset when idle does not raise an exception
        controller.reset_fault()


class TestGroundTruthIsolation:
    """Verify ground truth records are strictly isolated from inference."""

    def test_fault_injection_record_offline_only(self):
        now = datetime.now(UTC)
        gt = FaultInjectionRecord(
            run_id="exp-1234",
            scenario_id="F1_LINK_FAILURE",
            seeded_fault_type=FaultType.LINK_FAILURE,
            actual_fault_location_id="L12",
            injection_timestamp=now,
            recovery_timestamp=now,
            experiment_seed=42,
        )
        assert gt.is_ground_truth_label_safe_for_inference() is False

    def test_experiment_record_serialization(self):
        now = datetime.now(UTC)
        obs = NetworkObservation(
            timestamp=now,
            container_health={"nexora-r1": True},
            ospf_neighbors={"nexora-r1": {"2.2.2.2": "Full"}},
            ospf_routes_count={"nexora-r1": 10},
            loopback_pings={"r1->r2": True},
            probe_metrics={},
        )
        sc = get_scenario(ScenarioID.F1_LINK_FAILURE)
        loc = sc.get_fault_location("L12")

        rec = ExperimentRecord(
            run_id="run-001",
            scenario_id=ScenarioID.F1_LINK_FAILURE,
            fault_type=FaultType.LINK_FAILURE,
            actual_fault_location=loc,
            affected_components=["L12", "nexora-r1", "nexora-r2"],
            parameters={},
            injection_timestamp=now,
            observation_timestamps=[now],
            recovery_timestamp=now,
            baseline_observations=obs,
            fault_state_observations=obs,
            restoration_observations=obs,
            experiment_outcome=ExperimentOutcome.SUCCESS,
            errors=[],
        )
        json_str = rec.model_dump_json()
        restored = ExperimentRecord.model_validate_json(json_str)
        assert restored.run_id == "run-001"
        assert restored.experiment_outcome == ExperimentOutcome.SUCCESS
