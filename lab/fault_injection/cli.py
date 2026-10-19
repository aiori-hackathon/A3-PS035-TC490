"""
NEXORA Fault Controller CLI
Team: A3-PS035-TC490 | Problem Statement: PS-035

CLI entry point for fault injection, observation, and emergency recovery.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from lab.fault_injection.controller import (
    BaselineNotHealthyError,
    ExperimentAlreadyActiveError,
    FaultController,
)
from lab.fault_injection.scenarios import (
    InvalidTargetError,
    SecurityViolationError,
)


def format_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="nexora-fault",
        description="NEXORA Controlled Network Fault Injection Controller",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. list
    subparsers.add_parser("list", help="List all available fault scenarios")

    # 2. baseline
    subparsers.add_parser("baseline", help="Check baseline network health")

    # 3. status
    subparsers.add_parser("status", help="Inspect currently active fault experiment")

    # 4. observe
    subparsers.add_parser("observe", help="Capture and print current network observations")

    # 5. inject
    inject_p = subparsers.add_parser("inject", help="Inject a single fault into the lab")
    inject_p.add_argument("scenario", help="Scenario ID (e.g. F1, F2, F3, F4, F5)")
    inject_p.add_argument("--target", default=None, help="Target link (e.g. L12) or router (e.g. R3)")
    inject_p.add_argument("--loss-pct", type=int, default=30, help="Packet loss percentage for F4 (1-100)")
    inject_p.add_argument("--delay-ms", type=int, default=100, help="Latency delay in ms for F5 (1-2000)")
    inject_p.add_argument("--hello-interval", type=int, default=5, help="OSPF hello interval for F3")
    inject_p.add_argument("--dead-interval", type=int, default=15, help="OSPF dead interval for F3")

    # 6. reset
    subparsers.add_parser("reset", help="Reset active fault and verify baseline recovery")

    # 7. emergency-reset
    subparsers.add_parser("emergency-reset", help="Idempotently reset all interfaces, qdiscs, and OSPF configs")

    # 8. run
    run_p = subparsers.add_parser("run", help="Run complete experiment lifecycle with structured report")
    run_p.add_argument("scenario", help="Scenario ID (e.g. F1, F2, F3, F4, F5)")
    run_p.add_argument("--target", default=None, help="Target link or router")
    run_p.add_argument("--hold-sec", type=int, default=15, help="Seconds to hold fault before reset (default: 15)")
    run_p.add_argument("--loss-pct", type=int, default=30, help="Packet loss percentage for F4 (1-100)")
    run_p.add_argument("--delay-ms", type=int, default=100, help="Latency delay in ms for F5 (1-2000)")
    run_p.add_argument("--hello-interval", type=int, default=5, help="OSPF hello interval for F3")
    run_p.add_argument("--dead-interval", type=int, default=15, help="OSPF dead interval for F3")

    args = parser.parse_args()
    controller = FaultController()

    try:
        if args.command == "list":
            scenarios = controller.list_scenarios()
            print(format_json(scenarios))

        elif args.command == "baseline":
            healthy, issues = controller.check_baseline()
            if healthy:
                print("BASELINE HEALTHY: 5/5 containers running, 10/10 FULL OSPF adjacencies.")
                sys.exit(0)
            else:
                print("BASELINE UNHEALTHY:")
                for issue in issues:
                    print(f"  - {issue}")
                sys.exit(1)

        elif args.command == "status":
            active = controller.get_active_fault()
            if active:
                print("ACTIVE EXPERIMENT:")
                print(format_json(active.model_dump()))
            else:
                print("No active experiment. Lab is IDLE.")

        elif args.command == "observe":
            obs = controller.observe_network()
            print(format_json(obs.model_dump()))

        elif args.command == "inject":
            params = {}
            if args.loss_pct is not None:
                params["loss_pct"] = args.loss_pct
            if args.delay_ms is not None:
                params["delay_ms"] = args.delay_ms
            if args.hello_interval is not None:
                params["hello_interval"] = args.hello_interval
            if args.dead_interval is not None:
                params["dead_interval"] = args.dead_interval

            lock = controller.inject_fault(args.scenario, target=args.target, **params)
            print("FAULT INJECTED:")
            print(format_json(lock.model_dump()))

        elif args.command == "reset":
            controller.reset_fault()
            print("RESET COMPLETE: Baseline verified.")

        elif args.command == "emergency-reset":
            actions = controller.emergency_reset()
            print("EMERGENCY RESET ACTIONS PERFORMED:")
            for act in actions:
                print(f"  ✓ {act}")

        elif args.command == "run":
            params = {}
            if args.loss_pct is not None:
                params["loss_pct"] = args.loss_pct
            if args.delay_ms is not None:
                params["delay_ms"] = args.delay_ms
            if args.hello_interval is not None:
                params["hello_interval"] = args.hello_interval
            if args.dead_interval is not None:
                params["dead_interval"] = args.dead_interval

            record = controller.run_experiment(
                args.scenario,
                target=args.target,
                hold_sec=args.hold_sec,
                **params,
            )
            print("EXPERIMENT RUN COMPLETE:")
            print(format_json(record.model_dump()))
            if record.experiment_outcome.value != "SUCCESS":
                sys.exit(1)

    except (SecurityViolationError, InvalidTargetError, ExperimentAlreadyActiveError, BaselineNotHealthyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"UNEXPECTED ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
