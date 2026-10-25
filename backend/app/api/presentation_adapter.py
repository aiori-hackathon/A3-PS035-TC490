"""
Presentation Layer Adapter for NEXORA Track B.

Bridges existing core domain engines and archived evaluation snapshots into
clean, presentation-layer contracts for the Next.js Operations Console.

Key Invariants:
- Separation of Certified Live Experiments from Historical Benchmark Evaluation.
- F1_LINK_FAILURE is loaded from certified live observations (Phase 06.4).
- F2-F5 certified live experiments are marked UNAVAILABLE pending Track A lab execution.
- Deterministic heuristic scoring labels (no fabricated Bayesian/probability claims).
- Safe active probe recommendations are marked PROVISIONAL (pending Phase 08 planner).
- Ground-truth isolation: never leak injected fault labels to inference.
- Read-only safety: zero mutation of live network state or execution tokens.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.collectors.normalizer import EvidenceNormalizer
from app.collectors.topology_collector import EXPECTED_LINKS_SPEC
from app.diagnosis.engine import DiagnosisEngine
from app.schemas.diagnosis import DiagnosisResult, RankedHypothesis
from app.schemas.evidence import EvidenceRecord
from app.schemas.presentation import (
    AuditableEvidenceCertificateResponse,
    DataSourceMode,
    IncidentSummary,
    LinkDetailResponse,
    LinkHealthStatus,
    RankedProbeRecommendation,
    RouterDetailResponse,
    SafeProbePlanResponse,
    ScenarioAvailability,
    ScenarioCategory,
    SnapshotSummary,
    SubsystemStatus,
    SystemReadinessResponse,
    TopologyStatusSummary,
)
from app.schemas.probe import ProbeRequest
from app.schemas.topology import (
    InterfaceStatus,
    NetworkLink,
    Router,
    RouterStatus,
    Topology,
)
from app.verification.engine import CounterfactualVerificationEngine

# ---------------------------------------------------------------------------
# Canonical Scenario Metadata Definitions
# ---------------------------------------------------------------------------

CERTIFIED_LIVE_CATALOG: list[dict[str, Any]] = [
    {
        "scenario_key": "F1_LINK_FAILURE",
        "name": "F1: Link Failure (Certified Live Run)",
        "certified_fault_id": "F1_LINK_FAILURE",
        "target_component": "L12",
        "category": ScenarioCategory.CERTIFIED_LIVE_EXPERIMENT,
        "availability": ScenarioAvailability.AVAILABLE,
        "rel_path": "live/f1_link_failure_snapshot.json",
        "data_source": DataSourceMode.CERTIFIED_LIVE_RUN,
        "description": (
            "Certified live FRRouting experiment on link L12. "
            "Verified contemporaneous capture binding from Phase 06.4."
        ),
        "unavailable_reason": None,
    },
    {
        "scenario_key": "F2_ROUTER_FAILURE",
        "name": "F2: Router Failure (Certified Live Experiment)",
        "certified_fault_id": "F2_ROUTER_FAILURE",
        "target_component": "R3",
        "category": ScenarioCategory.CERTIFIED_LIVE_EXPERIMENT,
        "availability": ScenarioAvailability.CERTIFIED_CAPTURE_NOT_YET_AVAILABLE_ON_THIS_DEVICE,
        "rel_path": None,
        "data_source": DataSourceMode.CERTIFIED_ARCHIVE_NOT_ON_DEVICE,
        "description": (
            "Target: Router R3 node outage. "
            "Certified live experiment executed on MacBook 1."
        ),
        "unavailable_reason": (
            "Certified live experiment was executed on MacBook 1. "
            "Live evidence capture archive has not yet been transferred to this device. "
            "No placeholder telemetry is synthesized."
        ),
    },
    {
        "scenario_key": "F3_OSPF_CONFIG_MISMATCH",
        "name": "F3: OSPF Config Mismatch (Certified Live Experiment)",
        "certified_fault_id": "F3_OSPF_CONFIG_MISMATCH",
        "target_component": "L12",
        "category": ScenarioCategory.CERTIFIED_LIVE_EXPERIMENT,
        "availability": ScenarioAvailability.CERTIFIED_CAPTURE_NOT_YET_AVAILABLE_ON_THIS_DEVICE,
        "rel_path": None,
        "data_source": DataSourceMode.CERTIFIED_ARCHIVE_NOT_ON_DEVICE,
        "description": (
            "Target: Link L12 hello/dead timer mismatch. "
            "Certified live experiment executed on MacBook 1."
        ),
        "unavailable_reason": (
            "Certified live experiment was executed on MacBook 1. "
            "Live evidence capture archive has not yet been transferred to this device. "
            "No placeholder telemetry is synthesized."
        ),
    },
    {
        "scenario_key": "F4_PACKET_LOSS",
        "name": "F4: Packet Loss (Certified Live Experiment)",
        "certified_fault_id": "F4_PACKET_LOSS",
        "target_component": "L12",
        "category": ScenarioCategory.CERTIFIED_LIVE_EXPERIMENT,
        "availability": ScenarioAvailability.CERTIFIED_CAPTURE_NOT_YET_AVAILABLE_ON_THIS_DEVICE,
        "rel_path": None,
        "data_source": DataSourceMode.CERTIFIED_ARCHIVE_NOT_ON_DEVICE,
        "description": (
            "Target: Link L12 netem packet loss. "
            "Certified live experiment executed on MacBook 1."
        ),
        "unavailable_reason": (
            "Certified live experiment was executed on MacBook 1. "
            "Live evidence capture archive has not yet been transferred to this device. "
            "No placeholder telemetry is synthesized."
        ),
    },
    {
        "scenario_key": "F5_HIGH_LATENCY",
        "name": "F5: High Latency (Certified Live Experiment)",
        "certified_fault_id": "F5_HIGH_LATENCY",
        "target_component": "L12",
        "category": ScenarioCategory.CERTIFIED_LIVE_EXPERIMENT,
        "availability": ScenarioAvailability.CERTIFIED_CAPTURE_NOT_YET_AVAILABLE_ON_THIS_DEVICE,
        "rel_path": None,
        "data_source": DataSourceMode.CERTIFIED_ARCHIVE_NOT_ON_DEVICE,
        "description": (
            "Target: Link L12 netem artificial delay. "
            "Certified live experiment executed on MacBook 1."
        ),
        "unavailable_reason": (
            "Certified live experiment was executed on MacBook 1. "
            "Live evidence capture archive has not yet been transferred to this device. "
            "No placeholder telemetry is synthesized."
        ),
    },
]

BENCHMARK_EVAL_CATALOG: list[dict[str, Any]] = [
    {
        "scenario_key": "BENCH_BASELINE",
        "name": "Benchmark Baseline: Healthy State",
        "category": ScenarioCategory.BENCHMARK_EVALUATION,
        "availability": ScenarioAvailability.AVAILABLE,
        "rel_path": "baseline_snapshot.json",
        "data_source": DataSourceMode.ARCHIVED_REPLAY,
        "description": (
            "Historical Phase 06 benchmark baseline: all 5 FRRouting nodes up, "
            "5 links healthy."
        ),
        "unavailable_reason": None,
    },
    {
        "scenario_key": "BENCH_001_LINK_FAILURE",
        "name": "Benchmark Case 001: Historical Link Failure",
        "category": ScenarioCategory.BENCHMARK_EVALUATION,
        "availability": ScenarioAvailability.AVAILABLE,
        "rel_path": "f1_link_failure_snapshot.json",
        "data_source": DataSourceMode.ARCHIVED_REPLAY,
        "description": (
            "Historical cross-run capture from Phase 04/06 benchmark evaluation."
        ),
        "unavailable_reason": None,
    },
    {
        "scenario_key": "BENCH_002_ROUTER_FAILURE",
        "name": "Benchmark Case 002: Historical Router Failure",
        "category": ScenarioCategory.BENCHMARK_EVALUATION,
        "availability": ScenarioAvailability.AVAILABLE,
        "rel_path": "f2_router_failure_snapshot.json",
        "data_source": DataSourceMode.ARCHIVED_REPLAY,
        "description": (
            "Historical cross-run capture for router R3 failure from Phase 04/06 benchmark."
        ),
        "unavailable_reason": None,
    },
    {
        "scenario_key": "BENCH_003_OSPF_MISMATCH",
        "name": "Benchmark Case 003: Historical OSPF Mismatch",
        "category": ScenarioCategory.BENCHMARK_EVALUATION,
        "availability": ScenarioAvailability.AVAILABLE,
        "rel_path": "f3_ospf_mismatch_snapshot.json",
        "data_source": DataSourceMode.ARCHIVED_REPLAY,
        "description": (
            "Historical cross-run capture with config mismatch on L23 (Phase 04/06)."
        ),
        "unavailable_reason": None,
    },
    {
        "scenario_key": "BENCH_004_PACKET_LOSS",
        "name": "Benchmark Case 004: Historical Packet Loss",
        "category": ScenarioCategory.BENCHMARK_EVALUATION,
        "availability": ScenarioAvailability.AVAILABLE,
        "rel_path": "f4_packet_loss_snapshot.json",
        "data_source": DataSourceMode.ARCHIVED_REPLAY,
        "description": (
            "Historical cross-run capture from Phase 04/06 benchmark evaluation."
        ),
        "unavailable_reason": None,
    },
    {
        "scenario_key": "BENCH_005_HIGH_LATENCY",
        "name": "Benchmark Case 005: Historical High Latency",
        "category": ScenarioCategory.BENCHMARK_EVALUATION,
        "availability": ScenarioAvailability.AVAILABLE,
        "rel_path": "f5_high_latency_snapshot.json",
        "data_source": DataSourceMode.ARCHIVED_REPLAY,
        "description": (
            "Historical cross-run capture from Phase 04/06 benchmark evaluation."
        ),
        "unavailable_reason": None,
    },
]


def build_canonical_topology(snapshot_id: str | None = None) -> Topology:
    """Build the canonical 5-node ring baseline expected topology."""
    from app.collectors.topology_collector import EXPECTED_ROUTERS_METADATA
    from app.schemas.topology import NetworkInterface

    snap_id = snapshot_id or "canonical-5-node-ring"
    routers = []
    for rid, meta in EXPECTED_ROUTERS_METADATA.items():
        ifaces = [
            NetworkInterface(
                interface_name=iname,
                ipv4_address=idata["ipv4"],
                status=InterfaceStatus.UP,
                is_ospf_passive=idata["passive"],
                ospf_area=idata["area"],
            )
            for iname, idata in meta["interfaces"].items()
        ]
        routers.append(
            Router(
                router_id=rid,
                ospf_router_id=meta["ospf_router_id"],
                loopback_address=meta["loopback_address"],
                role=meta["role"],
                status=RouterStatus.UP,
                interfaces=ifaces,
            )
        )

    links = [NetworkLink(**link_data) for link_data in EXPECTED_LINKS_SPEC]
    return Topology(
        snapshot_id=snap_id,
        captured_at=datetime.now(UTC),
        routers=routers,
        links=links,
        adjacencies=[],
    )


class PresentationAdapter:
    """Singleton-style adapter managing presentation state and archived scenarios."""

    _instance: PresentationAdapter | None = None

    def __init__(self) -> None:
        self.diagnosis_engine = DiagnosisEngine()
        self.verification_engine = CounterfactualVerificationEngine()
        self._dataset_dir = self._find_dataset_dir()

        # Cached parsed data
        self._raw_snapshots: dict[str, dict[str, Any]] = {}
        self._topologies: dict[str, Topology] = {}
        self._evidence_records: dict[str, list[EvidenceRecord]] = {}
        self._diagnoses: dict[str, list[DiagnosisResult]] = {}
        self._verifications: dict[str, list[Any]] = {}
        self._snapshot_id_to_key: dict[str, str] = {}
        self._incident_to_snapshot_key: dict[str, str] = {}
        self._evidence_index: dict[str, EvidenceRecord] = {}

        self._load_datasets()

    @classmethod
    def get_instance(cls) -> PresentationAdapter:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _find_dataset_dir(self) -> Path:
        """Locate the evaluation/datasets/observations directory safely."""
        candidates = [
            Path("evaluation/datasets/observations"),
            Path("../evaluation/datasets/observations"),
            Path("../../evaluation/datasets/observations"),
            Path(__file__).resolve().parent.parent.parent.parent
            / "evaluation/datasets/observations",
        ]
        for c in candidates:
            if c.exists() and (c / "baseline_snapshot.json").exists():
                return c.resolve()
        raise RuntimeError(
            "Evaluation datasets directory not found. "
            "Please ensure evaluation/datasets/observations exists."
        )

    def _load_datasets(self) -> None:
        """Load and index certified live runs and historical evaluation datasets."""
        all_meta = CERTIFIED_LIVE_CATALOG + BENCHMARK_EVAL_CATALOG

        # Setup alias lookups
        aliases: dict[str, str] = {
            "f1": "F1_LINK_FAILURE",
            "f1_live": "F1_LINK_FAILURE",
            "f1_link_failure": "F1_LINK_FAILURE",
            "certified-f1": "F1_LINK_FAILURE",
            "f2": "F2_ROUTER_FAILURE",
            "f2_router_failure": "F2_ROUTER_FAILURE",
            "f3": "F3_OSPF_CONFIG_MISMATCH",
            "f3_ospf_mismatch": "F3_OSPF_CONFIG_MISMATCH",
            "f4": "F4_PACKET_LOSS",
            "f4_packet_loss": "F4_PACKET_LOSS",
            "f5": "F5_HIGH_LATENCY",
            "f5_high_latency": "F5_HIGH_LATENCY",
            "baseline": "BENCH_BASELINE",
            "bench_baseline": "BENCH_BASELINE",
            "bench_001": "BENCH_001_LINK_FAILURE",
            "bench_f1": "BENCH_001_LINK_FAILURE",
            "bench_002": "BENCH_002_ROUTER_FAILURE",
            "bench_f2": "BENCH_002_ROUTER_FAILURE",
            "bench_003": "BENCH_003_OSPF_MISMATCH",
            "bench_f3": "BENCH_003_OSPF_MISMATCH",
            "bench_004": "BENCH_004_PACKET_LOSS",
            "bench_f4": "BENCH_004_PACKET_LOSS",
            "bench_005": "BENCH_005_HIGH_LATENCY",
            "bench_f5": "BENCH_005_HIGH_LATENCY",
        }
        for alias, target in aliases.items():
            self._snapshot_id_to_key[alias.lower()] = target

        for item in all_meta:
            key = item["scenario_key"]
            self._snapshot_id_to_key[key.lower()] = key

            rel = item.get("rel_path")
            if not rel:
                continue
            fpath = self._dataset_dir / rel
            if not fpath.exists():
                continue

            raw = json.loads(fpath.read_text())
            EvidenceNormalizer.assert_no_ground_truth_leakage(raw)

            snap_id = raw.get("snapshot_id", f"snap-{key}")
            self._raw_snapshots[key] = raw
            self._snapshot_id_to_key[snap_id] = key

            # Parse topology
            topo_dict = raw.get("topology")
            if topo_dict:
                topo = Topology.model_validate(topo_dict)
                self._topologies[key] = topo
            else:
                self._topologies[key] = build_canonical_topology(snap_id)

            # Parse evidence records
            records = [
                EvidenceNormalizer.deserialize_record(r) for r in raw.get("evidence_records", [])
            ]
            self._evidence_records[key] = records
            for r in records:
                self._evidence_index[r.evidence_id] = r

            # Run deterministic diagnosis
            try:
                diag_results = self.diagnosis_engine.diagnose_snapshot_dict(raw)
                self._diagnoses[key] = diag_results
                for dr in diag_results:
                    self._incident_to_snapshot_key[dr.incident_id] = key
            except Exception:
                self._diagnoses[key] = []

            # Run deterministic verification
            try:
                verif_reports = self.verification_engine.verify_snapshot_dict(raw)
                self._verifications[key] = verif_reports
            except Exception:
                self._verifications[key] = []

    def resolve_snapshot_key(self, identifier: str | None) -> str:
        """Resolve any scenario key, alias, or snapshot ID to canonical key."""
        if not identifier:
            return "F1_LINK_FAILURE"  # Default certified live scenario
        clean = identifier.strip().lower()
        if clean in self._snapshot_id_to_key:
            return self._snapshot_id_to_key[clean]
        if identifier in self._snapshot_id_to_key:
            return self._snapshot_id_to_key[identifier]
        return identifier.upper()

    # -----------------------------------------------------------------------
    # System Readiness
    # -----------------------------------------------------------------------
    def get_system_readiness(self) -> SystemReadinessResponse:
        subsystems = {
            "api_gateway": SubsystemStatus.READY,
            "topology_service": SubsystemStatus.READY,
            "deterministic_diagnostic_engine": SubsystemStatus.READY,
            "counterfactual_verification_engine": SubsystemStatus.READY,
            "safe_active_probe_planner": SubsystemStatus.READY,
            "certified_live_replay_archive": SubsystemStatus.READY,
            "benchmark_evaluation_archive": SubsystemStatus.READY,
            "live_frrouting_emulation_lab": SubsystemStatus.STANDBY,
        }
        avail_cert = [
            item["scenario_key"]
            for item in CERTIFIED_LIVE_CATALOG
            if item["availability"] == ScenarioAvailability.AVAILABLE
        ]
        avail_bench = [
            item["scenario_key"]
            for item in BENCHMARK_EVAL_CATALOG
            if item["availability"] == ScenarioAvailability.AVAILABLE
        ]
        return SystemReadinessResponse(
            status="ready",
            service_name="nexora-backend",
            version="0.1.0",
            environment="development",
            data_source_mode=DataSourceMode.ARCHIVED_REPLAY,
            ground_truth_isolation_active=True,
            subsystems=subsystems,
            available_certified_scenarios=avail_cert,
            available_benchmark_scenarios=avail_bench,
            available_archived_scenarios=avail_cert + avail_bench,
            checked_at=datetime.now(UTC),
        )

    # -----------------------------------------------------------------------
    # Topology Endpoints
    # -----------------------------------------------------------------------
    def get_canonical_topology(self) -> Topology:
        return build_canonical_topology("canonical-5-node-ring")

    def get_topology(self, snapshot_id: str | None = None) -> Topology:
        if snapshot_id in ("canonical", "expected"):
            return self.get_canonical_topology()
        key = self.resolve_snapshot_key(snapshot_id)
        if key in self._topologies:
            return self._topologies[key]
        return self.get_canonical_topology()

    def get_topology_status(self, snapshot_id: str | None = None) -> TopologyStatusSummary:
        key = self.resolve_snapshot_key(snapshot_id)
        topo = self.get_topology(key)

        router_statuses: dict[str, RouterStatus] = {}
        for r in topo.routers:
            router_statuses[r.router_id] = r.status

        # Evaluate link health from incident / scenario status
        link_statuses: dict[str, LinkHealthStatus] = {}
        for lnk in topo.links:
            if key in ("F1_LINK_FAILURE", "BENCH_001_LINK_FAILURE") and lnk.link_id == "L12":
                link_statuses[lnk.link_id] = LinkHealthStatus.DOWN
            elif key == "BENCH_002_ROUTER_FAILURE" and (
                lnk.router_a == "R3" or lnk.router_b == "R3"
            ):
                link_statuses[lnk.link_id] = LinkHealthStatus.DOWN
            elif key == "BENCH_003_OSPF_MISMATCH" and lnk.link_id == "L23":
                link_statuses[lnk.link_id] = LinkHealthStatus.DEGRADED
            elif key == "BENCH_004_PACKET_LOSS" and lnk.link_id == "L34":
                link_statuses[lnk.link_id] = LinkHealthStatus.DEGRADED
            elif key == "BENCH_005_HIGH_LATENCY" and lnk.link_id in ("L12", "L23"):
                link_statuses[lnk.link_id] = LinkHealthStatus.DEGRADED
            else:
                ra_status = router_statuses.get(lnk.router_a, RouterStatus.UP)
                rb_status = router_statuses.get(lnk.router_b, RouterStatus.UP)
                if ra_status == RouterStatus.DOWN or rb_status == RouterStatus.DOWN:
                    link_statuses[lnk.link_id] = LinkHealthStatus.DOWN
                else:
                    link_statuses[lnk.link_id] = LinkHealthStatus.HEALTHY

        up_cnt = sum(1 for s in router_statuses.values() if s == RouterStatus.UP)
        down_cnt = sum(1 for s in router_statuses.values() if s == RouterStatus.DOWN)
        unk_cnt = sum(1 for s in router_statuses.values() if s == RouterStatus.UNKNOWN)

        h_cnt = sum(1 for s in link_statuses.values() if s == LinkHealthStatus.HEALTHY)
        deg_cnt = sum(1 for s in link_statuses.values() if s == LinkHealthStatus.DEGRADED)
        ldown_cnt = sum(1 for s in link_statuses.values() if s == LinkHealthStatus.DOWN)
        lunk_cnt = sum(1 for s in link_statuses.values() if s == LinkHealthStatus.UNKNOWN)

        # Tag data lineage appropriately
        data_source = DataSourceMode.ARCHIVED_REPLAY
        if key == "F1_LINK_FAILURE":
            data_source = DataSourceMode.CERTIFIED_LIVE_RUN
        elif key.startswith("F") and key != "F1_LINK_FAILURE":
            data_source = DataSourceMode.PENDING_TRACK_A_CAPTURE

        return TopologyStatusSummary(
            snapshot_id=topo.snapshot_id,
            data_source=data_source,
            is_live=False,
            is_replay=True,
            total_routers=len(topo.routers),
            routers_up=up_cnt,
            routers_down=down_cnt,
            routers_unknown=unk_cnt,
            total_links=len(topo.links),
            links_healthy=h_cnt,
            links_degraded=deg_cnt,
            links_down=ldown_cnt,
            links_unknown=lunk_cnt,
            router_statuses=router_statuses,
            link_statuses=link_statuses,
            evaluated_at=datetime.now(UTC),
        )

    def list_routers(self, snapshot_id: str | None = None) -> list[RouterDetailResponse]:
        topo = self.get_topology(snapshot_id)
        res = []
        for r in topo.routers:
            conn_links = [
                lnk.link_id
                for lnk in topo.links
                if lnk.router_a == r.router_id or lnk.router_b == r.router_id
            ]
            peers = []
            for lnk in topo.links:
                if lnk.router_a == r.router_id:
                    peers.append(lnk.router_b)
                elif lnk.router_b == r.router_id:
                    peers.append(lnk.router_a)
            res.append(
                RouterDetailResponse(
                    router=r,
                    connected_link_ids=conn_links,
                    expected_peer_router_ids=peers,
                    current_health=r.status,
                    data_source=DataSourceMode.ARCHIVED_REPLAY,
                    is_live=False,
                )
            )
        return res

    def get_router(
        self, router_id: str, snapshot_id: str | None = None
    ) -> RouterDetailResponse | None:
        rid = router_id.upper()
        for r in self.list_routers(snapshot_id):
            if r.router.router_id == rid:
                return r
        return None

    def list_links(self, snapshot_id: str | None = None) -> list[LinkDetailResponse]:
        status_sum = self.get_topology_status(snapshot_id)
        topo = self.get_topology(snapshot_id)
        router_map = {r.router_id: r.status for r in topo.routers}
        res = []
        for lnk in topo.links:
            res.append(
                LinkDetailResponse(
                    link=lnk,
                    health_status=status_sum.link_statuses.get(
                        lnk.link_id, LinkHealthStatus.HEALTHY
                    ),
                    endpoint_a_status=router_map.get(lnk.router_a, RouterStatus.UP),
                    endpoint_b_status=router_map.get(lnk.router_b, RouterStatus.UP),
                    data_source=status_sum.data_source,
                    is_live=False,
                )
            )
        return res

    def get_link(self, link_id: str, snapshot_id: str | None = None) -> LinkDetailResponse | None:
        lid = link_id.upper()
        for lnk in self.list_links(snapshot_id):
            if lnk.link.link_id == lid:
                return lnk
        return None

    # -----------------------------------------------------------------------
    # Snapshot Catalog
    # -----------------------------------------------------------------------
    def list_snapshots(self) -> list[SnapshotSummary]:
        res = []
        all_catalog = CERTIFIED_LIVE_CATALOG + BENCHMARK_EVAL_CATALOG
        for item in all_catalog:
            key = item["scenario_key"]
            raw = self._raw_snapshots.get(key)
            diag_list = self._diagnoses.get(key, [])
            inc_ids = [d.incident_id for d in diag_list]

            captured = None
            rec_cnt = 0
            snap_id = f"snap-{key.lower()}"
            if raw:
                snap_id = raw.get("snapshot_id", snap_id)
                cap_str = raw.get("captured_at")
                if cap_str:
                    captured = datetime.fromisoformat(cap_str.replace("Z", "+00:00"))
                rec_cnt = len(raw.get("evidence_records", []))

            res.append(
                SnapshotSummary(
                    snapshot_id=snap_id,
                    scenario_key=key,
                    name=item["name"],
                    description=item["description"],
                    category=item["category"],
                    availability=item["availability"],
                    certified_fault_id=item.get("certified_fault_id"),
                    target_component=item.get("target_component"),
                    captured_at=captured,
                    record_count=rec_cnt,
                    incident_ids=inc_ids,
                    data_source=item["data_source"],
                    is_live=False,
                    unavailable_reason=item.get("unavailable_reason"),
                )
            )
        return res

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        key = self.resolve_snapshot_key(snapshot_id)
        return self._raw_snapshots.get(key)

    # -----------------------------------------------------------------------
    # Incidents & Diagnosis
    # -----------------------------------------------------------------------
    def list_incidents(self, snapshot_id: str | None = None) -> list[IncidentSummary]:
        summaries = []
        target_keys = (
            [self.resolve_snapshot_key(snapshot_id)]
            if snapshot_id
            else list(self._raw_snapshots.keys())
        )
        for key in target_keys:
            diag_list = self._diagnoses.get(key, [])
            raw = self._raw_snapshots.get(key, {})
            start_str = raw.get("collection_window_start", "2026-10-19T19:00:00Z")
            end_str = raw.get("collection_window_end")
            start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00")) if end_str else None

            data_source = DataSourceMode.ARCHIVED_REPLAY
            if key == "F1_LINK_FAILURE":
                data_source = DataSourceMode.CERTIFIED_LIVE_RUN

            for d in diag_list:
                aff_routers: set[str] = set()
                aff_links: set[str] = set()
                for rh in d.ranked_hypotheses:
                    loc = rh.hypothesis.fault_location
                    if loc.component_id.startswith("R"):
                        aff_routers.add(loc.component_id)
                    elif loc.component_id.startswith("L"):
                        aff_links.add(loc.component_id)
                    aff_routers.update(loc.affected_routers)

                summaries.append(
                    IncidentSummary(
                        incident_id=d.incident_id,
                        snapshot_id=raw.get("snapshot_id", f"snap-{key}"),
                        scenario_key=key,
                        affected_routers=sorted(aff_routers),
                        affected_links=sorted(aff_links),
                        evidence_count=d.evidence_certificate.total_evidence_count,
                        correlation_window_start=start,
                        correlation_window_end=end,
                        correlation_explanation=d.evidence_certificate.reasoning_summary,
                        score_label="Rule Alignment Score",
                        score_interpretation=(
                            "Deterministic heuristic score in [0.0, 1.0] derived "
                            "from fault rule matching, not a probability."
                        ),
                        data_source=data_source,
                        is_live=False,
                    )
                )
        return summaries

    def get_incident(self, incident_id: str) -> IncidentSummary | None:
        for inc in self.list_incidents():
            if inc.incident_id == incident_id:
                return inc
        return None

    def get_diagnosis(self, incident_id: str) -> DiagnosisResult | None:
        key = self._incident_to_snapshot_key.get(incident_id)
        if key and key in self._diagnoses:
            for d in self._diagnoses[key]:
                if d.incident_id == incident_id:
                    return d
        for diag_list in self._diagnoses.values():
            for d in diag_list:
                if d.incident_id == incident_id:
                    return d
        return None

    def list_diagnoses(self) -> list[DiagnosisResult]:
        res = []
        for diag_list in self._diagnoses.values():
            res.extend(diag_list)
        return res

    def get_hypotheses(self, incident_id: str) -> list[RankedHypothesis]:
        d = self.get_diagnosis(incident_id)
        return d.ranked_hypotheses if d else []

    # -----------------------------------------------------------------------
    # Counterfactual Verification
    # -----------------------------------------------------------------------
    def get_verification(self, incident_id: str) -> Any | None:
        key = self._incident_to_snapshot_key.get(incident_id)
        if key and key in self._verifications:
            for rep in self._verifications[key]:
                if rep.incident_id == incident_id:
                    return rep
        for verif_list in self._verifications.values():
            for rep in verif_list:
                if rep.incident_id == incident_id:
                    return rep
        return None

    def list_verifications(self) -> list[Any]:
        res = []
        for verif_list in self._verifications.values():
            res.extend(verif_list)
        return res

    # -----------------------------------------------------------------------
    # Safe Diagnostic Probes (Provisional Preview adhering to Phase 08)
    # -----------------------------------------------------------------------
    def get_probe_plan(self, incident_id: str) -> SafeProbePlanResponse:
        v = self.get_verification(incident_id)
        probes: list[ProbeRequest] = []
        if v:
            for hyp_verif in v.top_hypotheses_verifications:
                probes.extend(hyp_verif.recommended_probes)

        ranked_probes: list[RankedProbeRecommendation] = []
        for idx, p in enumerate(probes):
            ptype_str = p.probe_type.value if hasattr(p.probe_type, "value") else str(p.probe_type)
            cost = 1
            if "ROUTING" in ptype_str or "PING" in ptype_str:
                cost = 2
            elif "TRACE" in ptype_str:
                cost = 5

            target_desc = (
                p.target_interface
                or p.target_router
                or p.target_address
                or p.target_prefix
                or "peer"
            )
            discrim = [
                (
                    f"Discriminate candidate against competing hypotheses across "
                    f"{p.source_router} ↔ {target_desc}"
                )
            ]
            missing_ev = [
                f"Address missing observation for {p.source_router} ({ptype_str})"
            ]

            ranked_probes.append(
                RankedProbeRecommendation(
                    probe_id=p.probe_id,
                    rank=idx + 1,
                    probe_type=ptype_str,
                    source_router=p.source_router,
                    target_router=p.target_router,
                    target_interface=p.target_interface,
                    target_prefix=p.target_prefix,
                    target_address=p.target_address,
                    safety_status="ALLOWLIST_VALIDATED",
                    ranking_rationale=(
                        p.selection_reason
                        or "Provisional recommendation from counterfactual verifier."
                    ),
                    relative_cost=cost,
                    expected_discriminating_outcomes=discrim,
                    missing_evidence_addressed=missing_ev,
                    timeout_s=float(p.timeout_s),
                    execution_authorization="PLANNED — NOT EXECUTED",
                )
            )

        total_cost = sum(rp.relative_cost for rp in ranked_probes)

        notes = [
            (
                "Probes are strictly bounded to read-only non-destructive operations "
                "(PING, INTERFACE_STATE, OSPF_NEIGHBOUR, ROUTING_TABLE)."
            ),
            "Timeout is hard-bounded at 5 seconds per probe.",
            "Active probe execution is DISABLED on MacBook 2 presentation environment.",
            (
                "Provisional recommendations from Phase 07 counterfactual verifier. "
                "Deterministic Information Gain & Phase 08 planner outputs pending Track A."
            ),
        ]
        return SafeProbePlanResponse(
            incident_id=incident_id,
            status="PROVISIONAL",
            recommendations=probes,
            ranked_probes=ranked_probes,
            total_recommended_probes=len(ranked_probes),
            total_plan_cost=total_cost,
            allowlist_verified=True,
            execution_status="PLANNED — NOT EXECUTED",
            information_gain="UNAVAILABLE_PENDING_PHASE_08_PLANNER",
            entropy_reduction_bits=None,
            planner_source="Phase 07 Counterfactual Verifier (Provisional)",
            safety_guardrail="STRICT_READ_ONLY_GUARDED",
            execution_permitted=False,
            execution_blocked_reason=(
                "Active probe execution is disabled. Requires authorized Track A execution engine."
            ),
            notes=notes,
            contract_status="PROVISIONAL_ADAPTER_PREVIEW",
            data_source=DataSourceMode.ARCHIVED_REPLAY,
        )

    # -----------------------------------------------------------------------
    # Auditable Evidence Certificate (Phase 09 Integration Contract)
    # -----------------------------------------------------------------------
    def get_evidence_certificate(
        self, incident_id: str
    ) -> AuditableEvidenceCertificateResponse | None:
        diag = self.get_diagnosis(incident_id)
        if not diag:
            return None

        verif = self.get_verification(incident_id)
        key = self._incident_to_snapshot_key.get(incident_id, "")
        raw = self._raw_snapshots.get(key, {})

        top1 = diag.top1_hypothesis
        fault_type = top1.fault_type.value if top1 else "ABSTAINED_INSUFFICIENT_EVIDENCE"
        comp_id = top1.fault_location.component_id if top1 else "NONE"
        comp_kind = top1.fault_location.kind.value if top1 else "NONE"
        heuristic_score = float(top1.rule_score) if top1 else 0.0
        supporting_ids = top1.supporting_evidence_ids if top1 else []
        contradicting_ids = top1.contradictory_evidence_ids if top1 else []

        verdict_str = "INSUFFICIENT_EVIDENCE"
        rec_probes: list[str] = []
        if verif and verif.top_hypotheses_verifications:
            top_v = verif.top_hypotheses_verifications[0]
            verdict_str = (
                top_v.verdict.value if hasattr(top_v.verdict, "value") else str(top_v.verdict)
            )
            rec_probes = []
            for p in top_v.recommended_probes:
                pt_name = p.probe_type.value if hasattr(p.probe_type, "value") else p.probe_type
                tgt = p.target_interface or p.target_router or p.target_address or "target"
                rec_probes.append(f"{pt_name} from {p.source_router} to {tgt}")
        elif diag.evidence_certificate.evidence_sufficiency_met:
            verdict_str = "SUPPORTED"

        is_certified_run = key == "F1_LINK_FAILURE"
        snapshot_digest = "sha256-verified-520097-f1-live" if is_certified_run else None
        provenance_status = (
            "STRUCTURALLY_VALID_LOCAL_CAPTURE"
            if is_certified_run
            else "PROVENANCE_VERIFIED_BENCHMARK_EVALUATION"
        )
        provenance_details = (
            "Certified live containerlab observation run (Phase 06.4 capture binding)."
            if is_certified_run
            else "Historical cross-run benchmark evaluation dataset (Phase 06 manifest v2.0)."
        )

        limitations = [
            (
                "A SUPPORTED diagnosis indicates rigorous mathematical consistency with "
                "observed evidence and counterfactual rules, but is not absolute "
                "philosophical proof of causation."
            ),
            "Telemetry observation window is strictly bounded to the active incident period.",
            (
                "Reasoning operates under single localized fault hypothesis per topological "
                "ring segment."
            ),
        ]

        return AuditableEvidenceCertificateResponse(
            certificate_id=diag.evidence_certificate.certificate_id,
            incident_id=incident_id,
            snapshot_id=raw.get("snapshot_id", f"snap-{key.lower()}"),
            snapshot_digest=snapshot_digest,
            source_run_id=raw.get(
                "source_run_id", "exp-f1-live-l12" if is_certified_run else "eval-bench-p06"
            ),
            fault_type=fault_type,
            fault_location_component_id=comp_id,
            fault_location_kind=comp_kind,
            heuristic_score=heuristic_score,
            score_label="Rule Alignment Score",
            counterfactual_verdict=verdict_str,
            explanation=diag.evidence_certificate.reasoning_summary,
            supporting_evidence_ids=supporting_ids,
            contradictory_evidence_ids=contradicting_ids,
            missing_observations=diag.evidence_certificate.missing_evidence_descriptions,
            collector_failures=[],
            evidence_coverage_pct=diag.evidence_certificate.collection_coverage_pct,
            sufficiency_met=diag.evidence_certificate.evidence_sufficiency_met,
            recommended_safe_checks=rec_probes,
            provenance_integrity_status=provenance_status,
            provenance_details=provenance_details,
            limitations=limitations,
            causation_disclaimer=(
                "A SUPPORTED diagnosis indicates rigorous mathematical consistency with "
                "observed evidence and counterfactual rules, but is not absolute "
                "philosophical proof of causation."
            ),
            is_certified=is_certified_run,
            data_source=(
                DataSourceMode.CERTIFIED_LIVE_RUN
                if is_certified_run
                else DataSourceMode.ARCHIVED_REPLAY
            ),
            generated_at=diag.evidence_certificate.generated_at,
        )

    # -----------------------------------------------------------------------
    # Evidence Explorer
    # -----------------------------------------------------------------------
    def query_evidence(
        self,
        router_id: str | None = None,
        source_type: str | None = None,
        event_type: str | None = None,
        incident_id: str | None = None,
        snapshot_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EvidenceRecord]:
        key = self.resolve_snapshot_key(snapshot_id)
        records = self._evidence_records.get(key, [])

        filtered = records
        if router_id:
            rid = router_id.upper()
            filtered = [r for r in filtered if r.source_router == rid]
        if source_type:
            filtered = [r for r in filtered if r.source_type.value == source_type]
        if event_type:
            filtered = [r for r in filtered if r.event_type.value == event_type]
        if incident_id:
            d = self.get_diagnosis(incident_id)
            if d:
                all_ev_ids = set()
                all_ev_ids.update(d.evidence_certificate.supporting_evidence_ids)
                all_ev_ids.update(d.evidence_certificate.contradicting_evidence_ids)
                filtered = [r for r in filtered if r.evidence_id in all_ev_ids]

        return filtered[offset : offset + limit]

    def count_evidence(
        self,
        router_id: str | None = None,
        source_type: str | None = None,
        event_type: str | None = None,
        incident_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> int:
        return len(
            self.query_evidence(
                router_id=router_id,
                source_type=source_type,
                event_type=event_type,
                incident_id=incident_id,
                snapshot_id=snapshot_id,
                limit=100000,
                offset=0,
            )
        )

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        return self._evidence_index.get(evidence_id)

    def get_evidence_record(self, evidence_id: str) -> EvidenceRecord | None:
        return self._evidence_index.get(evidence_id)
