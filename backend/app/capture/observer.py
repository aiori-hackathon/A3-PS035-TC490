"""Bounded capture adapter over the existing read-only collectors."""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime

from app.collectors.fidelity import utc_now
from app.collectors.normalizer import EvidenceNormalizer
from app.schemas.evidence import (
    InterfaceObservation,
    ObservationStatus,
    OSPFObservation,
    PingMeasurement,
    RouteObservation,
)


class LabObserver:
    def __init__(self, controller, orchestrator):
        self.controller = controller
        self.orchestrator = orchestrator
        self.transport = orchestrator.transport
        self.begin(None)

    def begin(self, plan):
        self.probe_records = []
        self.rounds = 0

    @staticmethod
    def _timer_seconds(config, name):
        if not isinstance(config, dict) or not isinstance(name, str):
            return None

        name_lower = name.strip().lower()
        cap_name = name_lower.capitalize()

        def _validate(val, is_msec=False):
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                return None
            if math.isnan(val) or math.isinf(val):
                return None
            if val <= 0:
                return None
            sec = val / 1000 if is_msec else val
            if sec <= 0 or sec > 86400:
                return None
            return int(sec) if sec == int(sec) else sec

        # 1. Nested dictionary in timerMsecs, e.g. {"timerMsecs": {"hello": 10000, "dead": 40000}}
        timers = config.get("timerMsecs")
        if isinstance(timers, dict):
            raw = timers.get(name_lower) or timers.get(name)
            res = _validate(raw, is_msec=True)
            if res is not None:
                return res

        # 2. FRRouting actual field formats:
        # Hello timer in FRR is named 'timerMsecs' (integer milliseconds)
        if name_lower == "hello":
            if isinstance(timers, (int, float)) and not isinstance(timers, bool):
                res = _validate(timers, is_msec=True)
                if res is not None:
                    return res

        # Dead timer in FRR is named 'timerDeadSecs' (integer seconds)
        # Also check timer{CapName}Secs (e.g. timerDeadSecs, timerWaitSecs)
        key_secs = f"timer{cap_name}Secs"
        if key_secs in config:
            res = _validate(config.get(key_secs), is_msec=False)
            if res is not None:
                return res

        # timer{CapName}Msecs (if dead or hello specified in ms)
        key_msecs = f"timer{cap_name}Msecs"
        if key_msecs in config:
            res = _validate(config.get(key_msecs), is_msec=True)
            if res is not None:
                return res

        # 3. {name}Interval (e.g. helloInterval, deadInterval - in seconds)
        interval_key = f"{name_lower}Interval"
        if interval_key in config:
            res = _validate(config.get(interval_key), is_msec=False)
            if res is not None:
                return res

        # {name}IntervalSecs / {name}IntervalMsecs
        if f"{name_lower}IntervalSecs" in config:
            res = _validate(config.get(f"{name_lower}IntervalSecs"), is_msec=False)
            if res is not None:
                return res
        if f"{name_lower}IntervalMsecs" in config:
            res = _validate(config.get(f"{name_lower}IntervalMsecs"), is_msec=True)
            if res is not None:
                return res

        return None

    def healthy(self):
        healthy, _ = self.controller.check_baseline()
        if not healthy:
            return False
        interfaces = self.orchestrator.interface_collector.collect()
        ports = {
            (r.source_router, r.source_interface)
            for r in interfaces
            if isinstance(r, InterfaceObservation)
            and r.source_interface in {"eth1", "eth2"}
            and r.collection_status == ObservationStatus.OBSERVED
            and r.observed_status.lower() == "up"
        }
        if len(ports) != 10:
            return False
        ospf = self.orchestrator.ospf_collector.collect()
        if len(ospf) != 10 or any(
            not isinstance(r, OSPFObservation)
            or r.collection_status != ObservationStatus.OBSERVED
            or r.adjacency_state.lower() != "full"
            or self._timer_seconds(r.observed_interface_config, "hello") != 10
            or self._timer_seconds(r.observed_interface_config, "dead") != 40
            for r in ospf
        ):
            return False
        routes = self.orchestrator.routing_collector.collect()
        present = {
            (r.source_router, r.destination_prefix)
            for r in routes
            if isinstance(r, RouteObservation)
            and r.is_present
            and r.collection_status == ObservationStatus.OBSERVED
        }
        if (
            not {
                (f"R{router}", f"192.168.255.{target}/32")
                for router in range(1, 6)
                for target in range(1, 6)
            }
            <= present
        ):
            return False
        for router, interface in sorted(ports):
            code, out, _ = self.transport.execute(
                router,
                ["tc", "-j", "qdisc", "show", "dev", interface],
                timeout=3,
            )
            try:
                rows = json.loads(out)
            except ValueError:
                return False
            if (
                code
                or not isinstance(rows, list)
                or not rows
                or any(
                    not isinstance(r, dict)
                    or r.get("kind") not in {"noqueue", "fq_codel", "pfifo_fast"}
                    for r in rows
                )
            ):
                return False  # Unknown shaping is not an approved baseline.
        return True

    def _probe_round(self, plan):
        from lab.fault_injection.models import APPROVED_ROUTER_CONTAINERS, LINK_ENDPOINTS

        if self.rounds >= plan.probe_rounds:
            return
        links = (
            [plan.target]
            if plan.target in LINK_ENDPOINTS
            else [
                key
                for key, ep in LINK_ENDPOINTS.items()
                if plan.target
                in {
                    APPROVED_ROUTER_CONTAINERS[ep["router_a"]],
                    APPROVED_ROUTER_CONTAINERS[ep["router_b"]],
                }
            ]
        )
        for link in links:
            endpoint = LINK_ENDPOINTS[link]
            for source, peer in (("a", "b"), ("b", "a")):
                self.probe_records.append(
                    self.orchestrator.ping_collector.probe(
                        APPROVED_ROUTER_CONTAINERS[endpoint[f"router_{source}"]],
                        endpoint[f"ip_{peer}"],
                        count=plan.packet_count,
                        timeout_s=1,
                        source_address=endpoint[f"ip_{source}"],
                        interval_s=0.2,
                    )
                )
        self.rounds += 1

    def manifested(self, plan):
        from lab.fault_injection.models import APPROVED_ROUTER_CONTAINERS, LINK_ENDPOINTS

        if plan.scenario_id in {"F4_PACKET_LOSS", "F5_HIGH_LATENCY"}:
            if not self.rounds:
                self._probe_round(plan)  # One manifestation round, reused in the final snapshot.
            observed = [
                r
                for r in self.probe_records
                if isinstance(r, PingMeasurement)
                and r.collection_status == ObservationStatus.OBSERVED
            ]
            if plan.scenario_id == "F4_PACKET_LOSS":
                return any(0 < r.packet_loss_pct < 100 for r in observed)
            return any(r.rtt_avg_ms is not None and r.rtt_avg_ms >= 10 for r in observed)
        ospf = self.orchestrator.ospf_collector.collect()
        lost = [
            r
            for r in ospf
            if isinstance(r, OSPFObservation)
            and r.collection_status == ObservationStatus.OBSERVED
            and r.adjacency_state.lower() not in {"full", "unknown"}
        ]
        if plan.scenario_id == "F2_ROUTER_FAILURE":
            target_clean = plan.target.strip().upper()
            router_num = target_clean.lstrip("R")
            expected = f"{router_num}.{router_num}.{router_num}.{router_num}"
            return (
                not self.transport.is_router_running(target_clean)
                and len({r.source_router for r in lost if r.neighbour_router_id == expected}) == 2
            )
        endpoint = LINK_ENDPOINTS[plan.target]
        ports = {
            (APPROVED_ROUTER_CONTAINERS[endpoint[f"router_{side}"]], endpoint[f"interface_{side}"])
            for side in ("a", "b")
        }
        relevant = [
            r
            for r in self.orchestrator.interface_collector.collect()
            if (r.source_router, r.source_interface) in ports
            and isinstance(r, InterfaceObservation)
            and r.collection_status == ObservationStatus.OBSERVED
        ]
        adjacency_lost = any((r.source_router, r.source_interface) in ports for r in lost)
        if plan.scenario_id == "F1_LINK_FAILURE":
            return adjacency_lost and any(
                r.observed_status.lower() in {"down", "admin-down"} for r in relevant
            )
        return (
            adjacency_lost
            and len(relevant) == 2
            and all(r.observed_status.lower() == "up" for r in relevant)
        )

    def capture(self, plan, collection_start):
        snapshot = self.orchestrator.collect_snapshot(include_probes=False, include_logs=False)
        while self.rounds < plan.probe_rounds:
            self._probe_round(plan)
        snapshot.evidence_records.extend(EvidenceNormalizer.serialize_records(self.probe_records))
        snapshot.collection_window_start = datetime.fromisoformat(collection_start)
        snapshot.collection_window_end = utc_now()
        snapshot.captured_at = snapshot.collection_window_end
        snapshot.total_records = len(snapshot.evidence_records)
        snapshot.records_by_type = dict(
            Counter(r["source_type"] for r in snapshot.evidence_records)
        )
        return snapshot.model_dump(mode="json")
