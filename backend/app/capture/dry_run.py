"""Mock-only capture rehearsal. This module has no live execution option.

Run from repository root:
PYTHONPATH=backend backend/.venv/bin/python -m app.capture.dry_run --output-dir /tmp/new-directory
"""

from __future__ import annotations

import argparse
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lab.fault_injection.controller import FaultController
from lab.fault_injection.models import ActiveFaultLock, ExperimentState
from lab.fault_injection.scenarios import get_scenario

from app.capture.workflow import PLANS, CaptureRunner
from app.collectors.orchestrator import EvidenceSnapshot
from app.collectors.ping_collector import PingCollector
from app.collectors.transport import MockTransport
from app.schemas.evidence import InterfaceObservation, OSPFObservation, RouteObservation
from app.topology.graph import build_expected_topology_graph


class SyntheticClock:
    def __init__(self):
        self.start = datetime.now(UTC)
        self.elapsed = 0.0

    def now(self):
        self.elapsed += 0.001
        return self.start + timedelta(seconds=self.elapsed)

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds


class SyntheticController(FaultController):
    """Uses the real persistent lock methods, never scenario mutation methods."""

    synthetic = True

    def __init__(self, lock_file, clock):
        self.lock_file, self.clock = lock_file, clock
        self.injections = 0
        self.resets = 0
        self.reset_error = False
        self.inject_error = False
        self.inject_delay = 0

    def check_baseline(self, timeout_sec=30):
        return self.get_active_fault() is None, []

    def inject_fault(self, scenario_id, target=None, run_id=None, **parameters):
        scenario = get_scenario(scenario_id)
        scenario.validate_target(target, **parameters)
        start = self.clock.now()
        lock = ActiveFaultLock(
            run_id=run_id,
            scenario_id=scenario.scenario_id,
            fault_type=scenario.fault_type,
            target=target,
            injected_details={},
            state=ExperimentState.ACTIVE,
            started_at=start,
            injection_command_start=start,
            injection_command_end=self.clock.now(),
        )
        self._acquire_lock(lock)
        self.injections += 1
        self.clock.sleep(self.inject_delay)
        if self.inject_error:
            raise RuntimeError("Synthetic partial injection failure")
        return lock

    def reset_fault(self, expected_run_id=None, verify=True):
        active = self.get_active_fault()
        if active.run_id != expected_run_id:
            raise RuntimeError("Run ID mismatch")
        self.resets += 1
        if self.reset_error:
            raise RuntimeError("Synthetic reset failure")
        active.state = ExperimentState.RESTORING
        self._update_lock(active)
        self.clock.sleep(0.01)


class SyntheticObserver:
    """Typed fixtures exercise serialization and provenance, not network accuracy."""

    def __init__(self, controller, clock):
        self.controller, self.clock = controller, clock
        self.baseline_ok = True
        self.recovery_ok = True
        self.manifests = True
        self.capture_error = False
        self.capture_delay = 0
        self.corrupt = None

    def begin(self, plan):
        pass

    def healthy(self):
        return self.recovery_ok if self.controller.resets else self.baseline_ok

    def manifested(self, plan):
        return self.manifests

    def capture(self, plan, collection_start):
        if self.capture_error:
            raise RuntimeError("Synthetic collector failure")
        self.clock.sleep(self.capture_delay)
        records = []
        topology = build_expected_topology_graph().topology
        faulty = plan.scenario_id

        def common(router, interface, source, event):
            return dict(
                evidence_id=f"ev-{uuid.uuid4().hex}",
                source_router=router,
                source_interface=interface,
                source_type=source,
                event_type=event,
                observed_at=self.clock.now(),
                collected_at=self.clock.now(),
                collection_method="PERIODIC_POLL",
                collection_status="OBSERVED",
            )

        for link in topology.links:
            for router, interface, peer, address in [
                (link.router_a, link.interface_a, link.router_b, link.address_b),
                (link.router_b, link.interface_b, link.router_a, link.address_a),
            ]:
                state = (
                    "down" if faulty == "F1_LINK_FAILURE" and link.link_id == plan.target else "up"
                )
                unavailable = faulty == "F2_ROUTER_FAILURE" and router == plan.target
                base = common(router, interface, "INTERFACE_POLL", "INTERFACE_STATE_OBSERVED")
                if unavailable:
                    base.update(
                        collection_status="COLLECTION_FAILED", event_type="ROUTER_UNAVAILABLE"
                    )
                records.append(InterfaceObservation(**base, observed_status=state))
                adjacency = (
                    "Down"
                    if (
                        faulty in {"F1_LINK_FAILURE", "F3_OSPF_CONFIG_MISMATCH"}
                        and link.link_id == plan.target
                    )
                    or (faulty == "F2_ROUTER_FAILURE" and plan.target in {router, peer})
                    else "Full"
                )
                base = common(router, interface, "OSPF_API", f"OSPF_NEIGHBOUR_{adjacency.upper()}")
                if unavailable:
                    base.update(
                        collection_status="COLLECTION_FAILED", event_type="ROUTER_UNAVAILABLE"
                    )
                records.append(
                    OSPFObservation(
                        **base,
                        neighbour_router_id=f"{peer[1:]}." * 3 + peer[1:],
                        neighbour_address=address.split("/")[0],
                        adjacency_state=adjacency,
                        observed_interface_config={"timerMsecs": {"hello": 10000, "dead": 40000}},
                        interface_config_observed_at=self.clock.now(),
                    )
                )
        records.append(
            RouteObservation(
                **common("R1", "eth1", "ROUTING_TABLE", "ROUTE_PRESENT"),
                destination_prefix="192.168.255.2/32",
                next_hop_address="10.0.12.2",
                next_hop_interface="eth1",
                route_type="O",
                metric=1,
                is_present=True,
            )
        )
        transport = MockTransport()
        collector = PingCollector(transport)
        collector.now_utc = self.clock.now
        lost = 6 if faulty == "F4_PACKET_LOSS" else 0
        rtt = 101.125 if faulty == "F5_HIGH_LATENCY" else 0.125
        for _ in range(plan.probe_rounds):
            for router, source, target in [
                ("R1", "10.0.12.1", "10.0.12.2"),
                ("R2", "10.0.12.2", "10.0.12.1"),
            ]:
                sent = plan.packet_count
                received = sent - min(lost, sent)
                output = (
                    f"{sent} packets transmitted, {received} received, "
                    f"{100 * (sent - received) / sent}% packet loss\n"
                    f"rtt min/avg/max/mdev = {rtt}/{rtt}/{rtt}/0.0 ms"
                )
                transport.set_response(router, ["ping", "-c"], 0, output)
                records.append(collector.probe(router, target, count=sent, source_address=source))
        end = self.clock.now()
        snapshot = EvidenceSnapshot(
            snapshot_id=f"obs-{uuid.uuid4().hex}",
            captured_at=end,
            collection_window_start=collection_start,
            collection_window_end=end,
            router_ids=["R1", "R2", "R3", "R4", "R5"],
            topology=topology,
            evidence_records=[r.model_dump(mode="json") for r in records],
            total_records=len(records),
            records_by_type=dict(Counter(r.source_type for r in records)),
        ).model_dump(mode="json")
        if self.corrupt:
            self.corrupt(snapshot)
        return snapshot


def run_dry(output_dir: Path):
    # The synthetic controller's files live only in this dedicated staging directory.
    control = output_dir.with_name(output_dir.name + "-control")
    control.mkdir(parents=True, exist_ok=False)
    clock = SyntheticClock()
    controller = SyntheticController(control / ".active_fault.json", clock)
    observer = SyntheticObserver(controller, clock)
    return CaptureRunner(
        controller,
        observer,
        output_dir,
        synthetic=True,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    ).run_sequence(PLANS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--dry-run", action="store_true", help="Always synthetic, even when omitted"
    )
    args = parser.parse_args()
    reports = run_dry(args.output_dir)
    successes = sum(r["status"] == "CAPTURED" for r in reports)
    print(f"SYNTHETIC ONLY: {successes}/{len(PLANS)} capture workflows completed.")
    print("No Docker operations. Empirical diagnostic accuracy: NOT MEASURED.")
    if successes != len(PLANS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
