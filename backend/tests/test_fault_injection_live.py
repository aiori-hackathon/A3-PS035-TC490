"""
NEXORA Live Fault Injection Integration Tests
Team: A3-PS035-TC490 | Problem Statement: PS-035

OPTIONAL LIVE INTEGRATION TESTS FOR ALL FIVE FAULTS:
  F1: LINK_FAILURE
  F2: ROUTER_FAILURE
  F3: OSPF_CONFIGURATION_MISMATCH
  F4: PACKET_LOSS
  F5: HIGH_LATENCY

SAFETY GUARD:
These tests modify network state temporarily.
To prevent accidental execution during ordinary CI or fast test runs,
they are SKIPPED by default unless:
    NEXORA_RUN_FAULT_TESTS=1
is explicitly set in the environment.

Run explicitly with:
    cd backend && NEXORA_RUN_FAULT_TESTS=1 uv run pytest tests/test_fault_injection_live.py -v -s --timeout=300
"""

import os
import subprocess

import pytest
from lab.fault_injection.controller import FaultController
from lab.fault_injection.models import ExperimentOutcome, ScenarioID

CONTAINERS = ["nexora-r1", "nexora-r2", "nexora-r3", "nexora-r4", "nexora-r5"]


def _docker_running(container: str) -> bool:
    res = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return res.returncode == 0 and "true" in res.stdout.lower()


@pytest.fixture(scope="module", autouse=True)
def require_explicit_permission_and_lab():
    """Skip entirely unless NEXORA_RUN_FAULT_TESTS=1 and lab is running."""
    if os.environ.get("NEXORA_RUN_FAULT_TESTS") != "1":
        pytest.skip(
            "Live fault tests skipped to prevent accidental testbed disruption in CI. "
            "To execute live faults, run with: NEXORA_RUN_FAULT_TESTS=1 pytest tests/test_fault_injection_live.py"
        )
    running = [c for c in CONTAINERS if _docker_running(c)]
    if len(running) != 5:
        pytest.skip(f"Live lab routers not all running ({len(running)}/5). Start lab with './lab.sh up'")


@pytest.fixture(scope="module")
def controller():
    return FaultController()


class TestLiveFaultInjectionScenarios:
    """Live validation of all five fault scenarios with automatic recovery."""

    def test_live_f1_link_failure(self, controller: FaultController):
        """F1: Temporarily disable L12 data link, observe alternate routing, restore."""
        print("\n[LIVE FAULT TEST] Running F1: LINK_FAILURE on L12...")
        record = controller.run_experiment(
            ScenarioID.F1_LINK_FAILURE,
            target="L12",
            hold_sec=15,
        )
        assert record.experiment_outcome == ExperimentOutcome.SUCCESS
        assert record.scenario_id == ScenarioID.F1_LINK_FAILURE
        assert record.actual_fault_location.component_id == "L12"

        # Under fault, R1 loopback to R2 must still be reachable via alternate path
        assert record.fault_state_observations.loopback_pings.get("nexora-r1->nexora-r2") is True

        # Restored observation must show healthy baseline
        assert record.restoration_observations is not None
        assert record.restoration_observations.ospf_routes_count["nexora-r1"] >= 4

    def test_live_f2_router_failure(self, controller: FaultController):
        """F2: Stop router container R3, observe ring break, restart R3, verify recovery."""
        print("\n[LIVE FAULT TEST] Running F2: ROUTER_FAILURE on R3...")
        record = controller.run_experiment(
            ScenarioID.F2_ROUTER_FAILURE,
            target="R3",
            hold_sec=15,
        )
        assert record.experiment_outcome == ExperimentOutcome.SUCCESS
        assert record.scenario_id == ScenarioID.F2_ROUTER_FAILURE

        # During fault, R3 was down
        assert record.fault_state_observations.container_health["nexora-r3"] is False

        # Post restoration, R3 is running and reachable
        assert record.restoration_observations is not None
        assert record.restoration_observations.container_health["nexora-r3"] is True

    def test_live_f3_ospf_config_mismatch(self, controller: FaultController):
        """F3: Apply OSPF timer mismatch on L12, restore default OSPF config."""
        print("\n[LIVE FAULT TEST] Running F3: OSPF_CONFIG_MISMATCH on L12...")
        record = controller.run_experiment(
            ScenarioID.F3_OSPF_CONFIG_MISMATCH,
            target="L12",
            hold_sec=15,
            hello_interval=5,
            dead_interval=15,
        )
        assert record.experiment_outcome == ExperimentOutcome.SUCCESS
        assert record.scenario_id == ScenarioID.F3_OSPF_CONFIG_MISMATCH

    def test_live_f4_packet_loss(self, controller: FaultController):
        """F4: Inject 30% packet loss on L12 via tc netem, measure loss, restore."""
        print("\n[LIVE FAULT TEST] Running F4: PACKET_LOSS on L12 (30%)...")
        record = controller.run_experiment(
            ScenarioID.F4_PACKET_LOSS,
            target="L12",
            hold_sec=10,
            loss_pct=30,
        )
        assert record.experiment_outcome == ExperimentOutcome.SUCCESS
        assert record.scenario_id == ScenarioID.F4_PACKET_LOSS

        # Verify ping probes measured packets
        probe_out = record.fault_state_observations.probe_metrics.get("probe_ping_output", "")
        assert "packets transmitted" in probe_out

    def test_live_f5_high_latency(self, controller: FaultController):
        """F5: Inject 100ms delay on L12 via tc netem, measure RTT, restore."""
        print("\n[LIVE FAULT TEST] Running F5: HIGH_LATENCY on L12 (100ms)...")
        record = controller.run_experiment(
            ScenarioID.F5_HIGH_LATENCY,
            target="L12",
            hold_sec=10,
            delay_ms=100,
        )
        assert record.experiment_outcome == ExperimentOutcome.SUCCESS
        assert record.scenario_id == ScenarioID.F5_HIGH_LATENCY

        probe_out = record.fault_state_observations.probe_metrics.get("probe_ping_output", "")
        assert "packets transmitted" in probe_out

    def test_live_reports_generated(self, controller: FaultController):
        """Verify experiment reports were written to docs/phase-reports/."""
        reports = list(controller.reports_dir.glob("fault-*.json"))
        assert len(reports) >= 5, f"Expected at least 5 reports in {controller.reports_dir}, found {len(reports)}"
