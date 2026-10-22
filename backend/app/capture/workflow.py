"""Sequential bounded capture. No diagnosis execution and no implicit live backend."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.capture.safety import (
    CaptureInterrupted,
    CaptureTimeout,
    Deadline,
    termination_cleanup,
    write_json,
)
from app.collectors.fidelity import utc_now, validate_capture
from app.evaluation.timing import audit_timing, snapshot_digest


@dataclass(frozen=True)
class CapturePlan:
    scenario_id: str
    target: str
    parameters: tuple[tuple[str, int], ...] = ()
    packet_count: int = 20
    probe_rounds: int = 2

    def validate(self):
        from lab.fault_injection.models import APPROVED_LINKS, APPROVED_ROUTERS, ScenarioID
        from lab.fault_injection.scenarios import get_scenario

        scenario = get_scenario(self.scenario_id)
        allowed = (
            APPROVED_ROUTERS
            if scenario.scenario_id == ScenarioID.F2_ROUTER_FAILURE
            else APPROVED_LINKS
        )
        if self.target not in allowed:
            raise ValueError("Capture target is not an approved canonical NEXORA component")
        if (
            type(self.packet_count) is not int
            or type(self.probe_rounds) is not int
            or not 1 <= self.packet_count <= 20
            or not 1 <= self.probe_rounds <= 2
        ):
            raise ValueError("Capture probes limited to 20 packets and two rounds")
        known = {
            "F1_LINK_FAILURE": {},
            "F2_ROUTER_FAILURE": {},
            "F3_OSPF_CONFIG_MISMATCH": {"hello_interval": (1, 10), "dead_interval": (1, 40)},
            "F4_PACKET_LOSS": {"loss_pct": (1, 99)},
            "F5_HIGH_LATENCY": {"delay_ms": (1, 1000)},
        }[scenario.scenario_id.value]
        if len(dict(self.parameters)) != len(self.parameters):
            raise ValueError("Repeated parameter")
        for name, value in self.parameters:
            if (
                name not in known
                or type(value) is not int
                or not known[name][0] <= value <= known[name][1]
            ):
                raise ValueError("Unapproved capture parameter")
        scenario.validate_target(self.target, **dict(self.parameters))


PLANS = (
    CapturePlan("F1_LINK_FAILURE", "L12"),
    CapturePlan("F2_ROUTER_FAILURE", "R3"),
    CapturePlan("F3_OSPF_CONFIG_MISMATCH", "L12", (("hello_interval", 5), ("dead_interval", 15))),
    CapturePlan("F4_PACKET_LOSS", "L12", (("loss_pct", 30),)),
    CapturePlan("F5_HIGH_LATENCY", "L12", (("delay_ms", 100),)),
)


def validate_provenance(report: dict, snapshot: dict) -> None:
    fields = [
        "baseline_verified_at",
        "injection_command_start",
        "injection_command_end",
        "collection_start",
        "collection_end",
        "reset_started_at",
        "reset_ended_at",
        "recovery_confirmed_at",
    ]
    stamps = [datetime.fromisoformat(report[field]) for field in fields]
    if any(stamp.tzinfo is None or stamp.utcoffset() is None for stamp in stamps):
        raise ValueError("Missing timezone in capture provenance")
    if any(left > right for left, right in zip(stamps, stamps[1:])):
        raise ValueError("Capture provenance chronology is inconsistent")
    if stamps[4] >= stamps[5]:
        raise ValueError("Capture did not finish before reset")
    if stamps[3] != datetime.fromisoformat(snapshot["collection_window_start"]) or (
        stamps[4] != datetime.fromisoformat(snapshot["collection_window_end"])
    ):
        raise ValueError("Snapshot window differs from capture provenance")


class CaptureRunner:
    """Controller/observer are explicit dependencies. Constructor runs no Docker.

    A lease survives failure/crash and blocks later sequences until reviewed.
    Success artifacts are published only after strict fidelity, provenance and
    recovery checks. The directory is newly created and never overwrites history.
    """

    def __init__(
        self,
        controller,
        observer,
        output_dir: Path,
        *,
        synthetic: bool = False,
        now=utc_now,
        monotonic=time.monotonic,
        sleep=time.sleep,
        deadline=Deadline,
    ):
        self.controller, self.observer, self.output_dir = controller, observer, output_dir
        self.synthetic = synthetic or getattr(controller, "synthetic", False)
        self.now, self.monotonic = now, monotonic
        self.sleep, self.deadline = sleep, deadline

    def run_sequence(self, plans=PLANS) -> list[dict]:
        plans = tuple(plans)
        if not plans:
            raise ValueError("No capture plans")
        for plan in plans:
            plan.validate()
        self.output_dir.mkdir(parents=True, exist_ok=False)
        lease = self.controller.lock_file.with_name(".capture-sequence.lock")
        # Common controller directory, NOT output directory: different destinations cannot race.
        with lease.open("x", encoding="utf-8") as stream:
            stream.write(str(self.output_dir.resolve()))
            stream.flush()
            os.fsync(stream.fileno())
        reports = []
        try:
            with termination_cleanup():
                for plan in plans:
                    if self.controller.get_active_fault() is not None:
                        raise RuntimeError("Existing active fault; capture refused")
                    report = self._capture(plan)
                    reports.append(report)
                    if report["status"] != "CAPTURED":
                        break  # No retries or next injection after any failed experiment.
        except BaseException:
            # Persistent lease is intentionally retained for manual review.
            raise
        else:
            if all(r["recovery_confirmed"] for r in reports):
                lease.unlink()
        write_json(
            self.output_dir / "capture-index.json",
            {
                "synthetic": self.synthetic,
                "reports": reports,
                "empirical_accuracy": "NOT MEASURED",
            },
        )
        return reports

    def _capture(self, plan: CapturePlan) -> dict:
        from lab.fault_injection.scenarios import get_scenario

        from app.evaluation.ground_truth import FaultInjectionRecord

        run_id = f"exp-{uuid.uuid4().hex}"
        directory = self.output_dir / uuid.uuid4().hex
        directory.mkdir()
        report = {
            "artifact_directory": directory.name,
            "run_id": run_id,
            "scenario_id": plan.scenario_id,
            "target": plan.target,
            "synthetic": self.synthetic,
            "status": "FAILED",
            "recovery_confirmed": False,
            "injection_command_start": None,
            "injection_command_end": None,
            "collection_start": None,
            "collection_end": None,
            "reset_started_at": None,
            "reset_ended_at": None,
            "recovery_confirmed_at": None,
            "errors": [],
        }
        snapshot = None
        caught = None
        missing = []

        def checkpoint():
            write_json(directory / "provenance.json", report)

        checkpoint()
        try:
            with self.deadline(60):
                if not self.observer.healthy():
                    raise RuntimeError("Healthy NEXORA baseline was not verified")
            report["baseline_verified_at"] = self.now().isoformat()
            self.observer.begin(plan)
            # Reserve 60 of the 180 seconds for reset commands. Recovery checks
            # happen after reset; a failed reset cannot guarantee fault removal.
            with self.deadline(120):
                active_started = self.monotonic()
                # Controller separately timestamps the exact scenario-command call,
                # after its own baseline check and atomic reservation.
                lock = self.controller.inject_fault(
                    plan.scenario_id,
                    target=plan.target,
                    run_id=run_id,
                    **dict(plan.parameters),
                )
                if self.monotonic() - active_started >= 120:
                    raise CaptureTimeout("Injection exhausted active-work budget; reset required")
                if lock.run_id != run_id:
                    raise ValueError("Controller run ID mismatch")
                report["injection_command_start"] = lock.injection_command_start.isoformat()
                report["injection_command_end"] = lock.injection_command_end.isoformat()
                checkpoint()
                # Capture window includes manifestation observations reused by final
                # collection, so the SAME 90-second budget covers both phases.
                with self.deadline(90):
                    capture_started = self.monotonic()
                    report["collection_start"] = self.now().isoformat()
                    with self.deadline(60):
                        while not self.observer.manifested(plan):
                            if self.monotonic() - capture_started >= 60:
                                raise CaptureTimeout("Fault never manifested within 60 seconds")
                            self.sleep(1)
                    snapshot = self.observer.capture(plan, report["collection_start"])
                    report["collection_end"] = snapshot["collection_window_end"]
                    if self.monotonic() - capture_started >= 90:
                        raise CaptureTimeout("Active capture exceeded 90 seconds")
                    if self.monotonic() - active_started >= 120:
                        raise CaptureTimeout("Active-work budget expired; reset reserve required")
                    missing = validate_capture(snapshot)
                    # Exercise actual JSON serialization before reset, not only model_dump.
                    snapshot = json.loads(json.dumps(snapshot, allow_nan=False))
                    validate_capture(snapshot)
                    report["snapshot_id"] = snapshot["snapshot_id"]
                    report["snapshot_sha256"] = snapshot_digest(snapshot)
                    # Preserve completed evidence even if reset/recovery fails.
                    # This file is quarantined: no truth/binding or success status
                    # exists until restoration and provenance are validated.
                    write_json(directory / "unverified-snapshot.json", snapshot)
                    checkpoint()
        except (
            Exception,
            CaptureTimeout,
            CaptureInterrupted,
            KeyboardInterrupt,
            SystemExit,
        ) as exc:
            caught = exc
            report["errors"].append(f"{type(exc).__name__}: {exc}")
        finally:
            # A failed/partial injection may have left a PRE_VALIDATING lock.
            # Never reset a different run, even when inject() failed or timed out.
            try:
                active = self.controller.get_active_fault()
                if active is not None and active.run_id == run_id:
                    if active.injection_command_start is not None:
                        report["injection_command_start"] = (
                            active.injection_command_start.isoformat()
                        )
                    if active.injection_command_end is not None:
                        report["injection_command_end"] = active.injection_command_end.isoformat()
                    report["reset_started_at"] = self.now().isoformat()
                    # Do not perform artifact I/O before reset: a blocked journal
                    # must not consume the cleanup reserve. The controller persists
                    # its RESTORING state as part of the bounded reset operation.
                    with self.deadline(60):
                        self.controller.reset_fault(expected_run_id=run_id, verify=False)
                    report["reset_ended_at"] = self.now().isoformat()
                    with self.deadline(60):
                        recovery_start = self.monotonic()
                        while not self.observer.healthy():
                            if self.monotonic() - recovery_start >= 60:
                                raise CaptureTimeout("Baseline restoration unverified")
                            self.sleep(1)
                    report["recovery_confirmed_at"] = self.now().isoformat()
                    self.controller.complete_recovery(run_id)
                    report["recovery_confirmed"] = True
                elif active is not None:
                    raise RuntimeError("Run ID mismatch; foreign active fault was not reset")
                elif report["injection_command_start"] is not None:
                    raise RuntimeError("Controller lock vanished; restoration cannot be certified")
            except (
                Exception,
                CaptureTimeout,
                CaptureInterrupted,
                KeyboardInterrupt,
                SystemExit,
            ) as exc:
                report["errors"].append(f"Restoration failed: {type(exc).__name__}: {exc}")
            checkpoint()
        if isinstance(caught, (CaptureInterrupted, KeyboardInterrupt, SystemExit)):
            raise caught
        if report["errors"] or snapshot is None or not report["recovery_confirmed"]:
            return report
        try:
            validate_provenance(report, snapshot)
            scenario = get_scenario(plan.scenario_id)
            truth = FaultInjectionRecord(
                run_id=run_id,
                scenario_id=plan.scenario_id,
                seeded_fault_type=scenario.fault_type,
                actual_fault_location_id=plan.target,
                injection_timestamp=report["injection_command_end"],
                recovery_timestamp=report["recovery_confirmed_at"],
                experiment_seed=0,
                lab_operator_notes="Synthetic fixture, not empirical"
                if self.synthetic
                else "Capture workflow; stochastic netem seed not controlled (0 is unspecified).",
            )
            binding = {
                "run_id": run_id,
                "snapshot_id": snapshot["snapshot_id"],
                "snapshot_sha256": snapshot_digest(snapshot),
                "reset_started_at": report["reset_started_at"],
                "synthetic": self.synthetic,
            }
            if not audit_timing(snapshot, [], truth, binding)["evaluable"]:
                raise ValueError("Capture does not meet Phase06.1 timing/provenance eligibility")
            write_json(directory / "snapshot.json", snapshot)
            write_json(directory / "truth.json", truth.model_dump(mode="json"))
            write_json(directory / "binding.json", binding)
            report["missing_measurements"] = missing
            report["status"] = "CAPTURED"
        except Exception as exc:
            report["errors"].append(f"Artifact validation/persistence failed: {exc}")
        checkpoint()
        return report
