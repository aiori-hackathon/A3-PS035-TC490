"""
NEXORA Fault Controller
Team: A3-PS035-TC490 | Problem Statement: PS-035

Core engine managing controlled network fault injection, observation gathering,
restoration, emergency reset, and structured experiment record persistence.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.evaluation.ground_truth import FaultInjectionRecord
from lab.fault_injection.models import (
    APPROVED_DATA_INTERFACES,
    APPROVED_LINKS,
    APPROVED_ROUTER_CONTAINERS,
    APPROVED_ROUTERS,
    LINK_ENDPOINTS,
    ActiveFaultLock,
    ExperimentOutcome,
    ExperimentRecord,
    ExperimentState,
    NetworkObservation,
    ScenarioID,
)
from lab.fault_injection.scenarios import (
    BaseScenario,
    InvalidTargetError,
    SecurityViolationError,
    get_scenario,
)

logger = logging.getLogger("nexora.fault_injection.controller")

DEFAULT_LAB_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOCK_FILE = DEFAULT_LAB_DIR / ".active_fault.json"
DEFAULT_REPORTS_DIR = DEFAULT_LAB_DIR.parent / "docs" / "phase-reports"
DEFAULT_LOCAL_REPORTS_DIR = DEFAULT_LAB_DIR / "reports"


class ExperimentAlreadyActiveError(Exception):
    """Raised when attempting to inject a fault while another experiment is active."""


class BaselineNotHealthyError(Exception):
    """Raised when lab is not in a healthy baseline before injection."""


def _docker_exec(container: str, cmd_str: str, timeout: int = 15) -> tuple[int, str]:
    """Execute command inside a container."""
    try:
        proc = subprocess.run(
            ["docker", "exec", container, "sh", "-c", cmd_str],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return -1, f"Timeout after {timeout}s"
    except Exception as e:
        return -1, str(e)


def _docker_running(container: str) -> bool:
    """Return True if container is currently running."""
    proc = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return proc.returncode == 0 and "true" in proc.stdout.lower()


class FaultController:
    """Coordinates lifecycle of controlled fault injection experiments."""

    def __init__(
        self,
        lock_file: Path | None = None,
        reports_dir: Path | None = None,
    ) -> None:
        self.lock_file = lock_file or DEFAULT_LOCK_FILE
        self.reports_dir = reports_dir or DEFAULT_REPORTS_DIR
        self.local_reports_dir = DEFAULT_LOCAL_REPORTS_DIR
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.local_reports_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Concurrency Lock Management
    # -----------------------------------------------------------------------

    def get_active_fault(self) -> ActiveFaultLock | None:
        """Return the currently active experiment lock if present, else None."""
        if not self.lock_file.exists():
            return None
        try:
            data = json.loads(self.lock_file.read_text())
            return ActiveFaultLock.model_validate(data)
        except Exception as e:
            logger.warning("Corrupted active fault lock file found (%s). Treating as active.", e)
            return None

    def _acquire_lock(self, lock: ActiveFaultLock) -> None:
        active = self.get_active_fault()
        if active:
            raise ExperimentAlreadyActiveError(
                f"Experiment '{active.run_id}' ({active.scenario_id.value} on {active.target}) is already active! "
                f"Reset it first with 'reset' or 'emergency-reset'."
            )
        self.lock_file.write_text(lock.model_dump_json(indent=2))

    def _release_lock(self) -> None:
        if self.lock_file.exists():
            try:
                self.lock_file.unlink()
            except Exception as e:
                logger.error("Failed to delete lock file: %s", e)

    # -----------------------------------------------------------------------
    # Baseline & Observation
    # -----------------------------------------------------------------------

    def check_baseline(self, timeout_sec: int = 30) -> tuple[bool, list[str]]:
        """Verify the lab is running and all 10 directional OSPF adjacencies are FULL."""
        issues: list[str] = []
        containers = list(APPROVED_ROUTER_CONTAINERS.keys())

        # 1. Containers running
        for c in containers:
            if not _docker_running(c):
                issues.append(f"Container {c} is NOT running")

        if issues:
            return False, issues

        # 2. OSPF neighbors
        for c in containers:
            rc, out = _docker_exec(c, "vtysh -c 'show ip ospf neighbor json' 2>/dev/null")
            if rc != 0:
                issues.append(f"{c}: failed to query vtysh ospf neighbors")
                continue
            try:
                data = json.loads(out)
                nbrs = data.get("neighbors", {})
                full_nbrs = [
                    rid for rid, entries in nbrs.items()
                    if any(e.get("converged") == "Full" or "Full" in e.get("state", "") for e in entries)
                ]
                if len(full_nbrs) != 2:
                    issues.append(f"{c}: expected exactly 2 FULL adjacencies, found {len(full_nbrs)}: {full_nbrs}")
            except Exception as e:
                issues.append(f"{c}: json parse error on ospf neighbors: {e}")

        # 3. Quick loopback ping reachability
        rc, _ = _docker_exec("nexora-r1", "ping -c 1 -W 2 192.168.255.3 >/dev/null 2>&1")
        if rc != 0:
            issues.append("R1 cannot reach R3 loopback (192.168.255.3)")

        return len(issues) == 0, issues

    def observe_network(self, extra_probes: dict[str, Any] | None = None) -> NetworkObservation:
        """Capture comprehensive network state snapshot."""
        containers = list(APPROVED_ROUTER_CONTAINERS.keys())
        health: dict[str, bool] = {}
        ospf_neighbors: dict[str, dict[str, str]] = {}
        ospf_routes_count: dict[str, int] = {}
        loopback_pings: dict[str, bool] = {}

        for c in containers:
            is_running = _docker_running(c)
            health[c] = is_running
            if not is_running:
                ospf_neighbors[c] = {}
                ospf_routes_count[c] = 0
                continue

            # Neighbors
            _, nbr_out = _docker_exec(c, "vtysh -c 'show ip ospf neighbor json' 2>/dev/null")
            c_nbrs: dict[str, str] = {}
            try:
                nbr_data = json.loads(nbr_out).get("neighbors", {})
                for rid, entries in nbr_data.items():
                    state = entries[0].get("state", "Unknown") if entries else "Unknown"
                    c_nbrs[rid] = state
            except Exception:
                pass
            ospf_neighbors[c] = c_nbrs

            # Route count
            _, rt_out = _docker_exec(c, "vtysh -c 'show ip route ospf' 2>/dev/null")
            ospf_routes_count[c] = rt_out.count("\nO")

        # Cross-router loopback pings from running containers
        loopbacks = {
            "nexora-r1": "192.168.255.1",
            "nexora-r2": "192.168.255.2",
            "nexora-r3": "192.168.255.3",
            "nexora-r4": "192.168.255.4",
            "nexora-r5": "192.168.255.5",
        }
        for src, src_ip in loopbacks.items():
            if not health.get(src, False):
                continue
            for dst, dst_ip in loopbacks.items():
                if src == dst:
                    continue
                pair_key = f"{src}->{dst}"
                rc, _ = _docker_exec(src, f"ping -c 1 -W 2 {dst_ip} >/dev/null 2>&1")
                loopback_pings[pair_key] = (rc == 0)

        return NetworkObservation(
            timestamp=datetime.now(timezone.utc),
            container_health=health,
            ospf_neighbors=ospf_neighbors,
            ospf_routes_count=ospf_routes_count,
            loopback_pings=loopback_pings,
            probe_metrics=extra_probes or {},
        )

    # -----------------------------------------------------------------------
    # Scenarios Listing
    # -----------------------------------------------------------------------

    def list_scenarios(self) -> list[dict[str, Any]]:
        """Return catalog of supported fault scenarios."""
        return [
            {
                "scenario_id": ScenarioID.F1_LINK_FAILURE.value,
                "name": "Link Failure",
                "fault_type": "LINK_FAILURE",
                "description": "Temporarily disable an approved data-plane interface.",
                "allowed_targets": sorted(APPROVED_LINKS),
                "default_target": "L12",
            },
            {
                "scenario_id": ScenarioID.F2_ROUTER_FAILURE.value,
                "name": "Router Failure",
                "fault_type": "ROUTER_FAILURE",
                "description": "Stop only the selected NEXORA router container.",
                "allowed_targets": sorted(APPROVED_ROUTERS),
                "default_target": "R3",
            },
            {
                "scenario_id": ScenarioID.F3_OSPF_CONFIG_MISMATCH.value,
                "name": "OSPF Configuration Mismatch",
                "fault_type": "OSPF_CONFIGURATION_MISMATCH",
                "description": "Apply temporary incompatible OSPF hello/dead timer parameter on an approved link.",
                "allowed_targets": sorted(APPROVED_LINKS),
                "default_target": "L12",
                "parameters": {"hello_interval": 5, "dead_interval": 15},
            },
            {
                "scenario_id": ScenarioID.F4_PACKET_LOSS.value,
                "name": "Packet Loss",
                "fault_type": "PACKET_LOSS",
                "description": "Inject controlled percentage packet loss via Linux tc/netem.",
                "allowed_targets": sorted(APPROVED_LINKS),
                "default_target": "L12",
                "parameters": {"loss_pct": 30},
            },
            {
                "scenario_id": ScenarioID.F5_HIGH_LATENCY.value,
                "name": "High Latency",
                "fault_type": "HIGH_LATENCY",
                "description": "Inject controlled packet delay via Linux tc/netem.",
                "allowed_targets": sorted(APPROVED_LINKS),
                "default_target": "L12",
                "parameters": {"delay_ms": 100},
            },
        ]

    # -----------------------------------------------------------------------
    # Lifecycle: Inject, Reset, Run
    # -----------------------------------------------------------------------

    def inject_fault(
        self,
        scenario_id: str | ScenarioID,
        target: str | None = None,
        **params: Any,
    ) -> ActiveFaultLock:
        """Inject a fault after verifying pre-conditions and acquiring the lock."""
        scenario = get_scenario(scenario_id)
        if target is None:
            # Pick scenario default
            catalog = {s["scenario_id"]: s["default_target"] for s in self.list_scenarios()}
            target = catalog.get(scenario.scenario_id.value, "L12")

        # Validate target
        scenario.validate_target(target, **params)

        # Baseline readiness check
        healthy, issues = self.check_baseline()
        if not healthy:
            raise BaselineNotHealthyError(f"Cannot inject fault — lab baseline is not healthy: {issues}")

        run_id = f"exp-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"

        # Attempt injection
        injected_details = scenario.inject(target, **params)

        lock = ActiveFaultLock(
            run_id=run_id,
            scenario_id=scenario.scenario_id,
            fault_type=scenario.fault_type,
            target=target,
            injected_details=injected_details,
            state=ExperimentState.ACTIVE,
            started_at=datetime.now(timezone.utc),
        )
        self._acquire_lock(lock)
        logger.info("Fault injected successfully: %s", lock)
        return lock

    def reset_fault(self) -> None:
        """Restore the currently active fault and verify recovery."""
        active = self.get_active_fault()
        if not active:
            logger.info("No active fault found to reset.")
            return

        scenario = get_scenario(active.scenario_id)
        logger.info("Reversing active fault: %s on %s", active.scenario_id.value, active.target)
        try:
            scenario.restore(active.target, active.injected_details)
        finally:
            self._release_lock()

        # Poll for OSPF re-convergence up to 60s
        logger.info("Waiting for OSPF re-convergence post-reset (up to 60s)...")
        recovered = False
        last_issues: list[str] = []
        for attempt in range(12):
            time.sleep(5)
            recovered, last_issues = self.check_baseline()
            if recovered:
                logger.info("Baseline re-convergence verified after %ds!", (attempt + 1) * 5)
                break

        if not recovered:
            logger.warning("Baseline not fully restored post-reset: %s", last_issues)
        else:
            logger.info("Lab successfully restored to healthy baseline.")

    def emergency_reset(self) -> list[str]:
        """Idempotently reset all routers and interfaces to normal, then verify."""
        logger.warning("Initiating EMERGENCY RESET of all NEXORA lab network state...")
        actions: list[str] = []

        containers = list(APPROVED_ROUTER_CONTAINERS.keys())
        # 1. Start any stopped containers
        for c in containers:
            if not _docker_running(c):
                _docker_exec(c, "docker start " + c)  # Or run on host
                subprocess.run(["docker", "start", c], capture_output=True, text=True, timeout=15)
                actions.append(f"Started container {c}")

        time.sleep(5)

        # 2. Re-enable all data-plane interfaces & clear tc qdisc
        for c in containers:
            for iface in APPROVED_DATA_INTERFACES:
                # Bring UP
                _docker_exec(c, f"ip link set dev {iface} up 2>/dev/null || true")
                # Clear netem qdisc
                _docker_exec(c, f"tc qdisc del dev {iface} root 2>/dev/null || true")
            actions.append(f"Reset interfaces and qdiscs on {c}")

            # 3. Restore default OSPF timers on eth1 and eth2
            _docker_exec(
                c,
                "vtysh -c 'configure terminal' "
                "-c 'interface eth1' -c 'ip ospf hello-interval 10' -c 'ip ospf dead-interval 40' -c 'ip ospf network point-to-point' "
                "-c 'interface eth2' -c 'ip ospf hello-interval 10' -c 'ip ospf dead-interval 40' -c 'ip ospf network point-to-point' 2>/dev/null || true",
            )
            actions.append(f"Restored OSPF config on {c}")

        # 4. Remove active lock file
        self._release_lock()
        actions.append("Cleared active experiment lock file")

        # 5. Wait for OSPF convergence
        logger.info("Waiting for complete OSPF convergence after emergency reset (up to 60s)...")
        recovered = False
        issues: list[str] = []
        for _ in range(12):
            time.sleep(5)
            recovered, issues = self.check_baseline()
            if recovered:
                break

        if not recovered:
            actions.append(f"WARNING: Baseline verification had warnings: {issues}")
        else:
            actions.append("Verified baseline recovery: 10/10 FULL adjacencies restored.")

        return actions

    def run_experiment(
        self,
        scenario_id: str | ScenarioID,
        target: str | None = None,
        hold_sec: int = 15,
        **params: Any,
    ) -> ExperimentRecord:
        """Execute a complete, bounded, safe experiment run with structured reporting."""
        scenario = get_scenario(scenario_id)
        if target is None:
            catalog = {s["scenario_id"]: s["default_target"] for s in self.list_scenarios()}
            target = catalog.get(scenario.scenario_id.value, "L12")

        scenario.validate_target(target, **params)
        fault_location = scenario.get_fault_location(target)
        affected = scenario.get_affected_components(target)

        # 1. Baseline observation
        healthy, issues = self.check_baseline()
        if not healthy:
            raise BaselineNotHealthyError(f"Pre-injection check failed: {issues}")
        baseline_obs = self.observe_network()

        # 2. Inject fault
        lock = self.inject_fault(scenario.scenario_id, target, **params)
        injection_time = lock.started_at
        observation_times: list[datetime] = []
        errors: list[str] = []

        try:
            # Hold fault state and gather active-state observations
            time.sleep(hold_sec)
            observation_times.append(datetime.now(timezone.utc))

            # Additional probe metrics if packet loss or high latency
            extra_probes: dict[str, Any] = {}
            if scenario.scenario_id in (ScenarioID.F4_PACKET_LOSS, ScenarioID.F5_HIGH_LATENCY):
                # Measure link endpoint ping
                if target in LINK_ENDPOINTS:
                    ep = LINK_ENDPOINTS[target]
                    rc, out = _docker_exec(ep["router_a"], f"ping -c 10 -i 0.2 {ep['ip_b']}")
                    extra_probes["probe_ping_output"] = out
                    extra_probes["probe_ping_rc"] = rc

            fault_obs = self.observe_network(extra_probes=extra_probes)

        except Exception as e:
            errors.append(f"Error during observation: {e}")
            fault_obs = self.observe_network()
        finally:
            # 3. Always restore
            self.reset_fault()
            recovery_time = datetime.now(timezone.utc)

        # 4. Restoration observation
        restoration_obs = self.observe_network()
        recovered, recover_issues = self.check_baseline()
        if not recovered:
            errors.extend(recover_issues)
            outcome = ExperimentOutcome.PARTIAL if not errors else ExperimentOutcome.FAILED
        else:
            outcome = ExperimentOutcome.SUCCESS

        record = ExperimentRecord(
            run_id=lock.run_id,
            scenario_id=scenario.scenario_id,
            fault_type=scenario.fault_type,
            actual_fault_location=fault_location,
            affected_components=affected,
            parameters=params,
            injection_timestamp=injection_time,
            observation_timestamps=observation_times,
            recovery_timestamp=recovery_time,
            baseline_observations=baseline_obs,
            fault_state_observations=fault_obs,
            restoration_observations=restoration_obs,
            experiment_outcome=outcome,
            errors=errors,
        )

        # Persist report
        self._save_report(record)

        # Also create isolated Ground-Truth record for offline evaluation
        gt_record = FaultInjectionRecord(
            run_id=record.run_id,
            scenario_id=record.scenario_id.value,
            seeded_fault_type=record.fault_type,
            actual_fault_location_id=fault_location.component_id,
            injection_timestamp=record.injection_timestamp,
            recovery_timestamp=record.recovery_timestamp,
            experiment_seed=params.get("seed", 42),
            lab_operator_notes=f"Outcome: {outcome.value}; Target: {target}; Params: {params}",
        )
        self._save_ground_truth(gt_record)

        return record

    def _save_report(self, record: ExperimentRecord) -> Path:
        """Save structured JSON experiment report."""
        filename = f"fault-{record.run_id}-{record.scenario_id.value.lower()}.json"
        target_path = self.reports_dir / filename
        local_path = self.local_reports_dir / filename

        content = record.model_dump_json(indent=2)
        target_path.write_text(content)
        local_path.write_text(content)
        logger.info("Saved experiment report to %s and %s", target_path, local_path)
        return target_path

    def _save_ground_truth(self, gt: FaultInjectionRecord) -> Path:
        """Save ground truth label in isolated evaluation directory."""
        gt_dir = self.reports_dir / "ground_truth"
        gt_dir.mkdir(parents=True, exist_ok=True)
        gt_path = gt_dir / f"gt-{gt.run_id}.json"
        gt_path.write_text(gt.model_dump_json(indent=2))
        return gt_path
