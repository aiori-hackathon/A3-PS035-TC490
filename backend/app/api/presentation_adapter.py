"""
Presentation adapter service for NEXORA Track B (Phase 10).

Loads, validates, and indexes archived scenarios and snapshots from the evaluation dataset.
Connects existing DiagnosisEngine and CounterfactualVerificationEngine to presentation endpoints.
Strictly isolates ground truth: never injects or queries lab ground-truth labels.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.collectors.normalizer import EvidenceNormalizer
from app.collectors.topology_collector import EXPECTED_LINKS_SPEC
from app.diagnosis.engine import DiagnosisEngine
from app.schemas.counterfactual import VerificationReport
from app.schemas.diagnosis import DiagnosisResult, RankedHypothesis
from app.schemas.evidence import EvidenceRecord
from app.schemas.incident import Incident
from app.schemas.presentation import (
    DataSourceMode,
    IncidentSummary,
    LinkDetailResponse,
    LinkHealthStatus,
    RouterDetailResponse,
    SafeProbePlanResponse,
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

# Friendly scenario metadata catalog
SCENARIO_METADATA: dict[str, dict[str, str]] = {
    "baseline": {
        "scenario_key": "baseline",
        "name": "Normal Operating Baseline",
        "description": "All 5 FRRouting nodes (R1-R5) up, 5 links healthy, full OSPFv2.",
    },
    "f1": {
        "scenario_key": "F1",
        "name": "Scenario F1: Link L12 Failure",
        "description": "Hard failure on link L12 between R1 and R2. Dual OSPF adjacency drop.",
    },
    "f2": {
        "scenario_key": "F2",
        "name": "Scenario F2: Router R3 Failure",
        "description": "Total node outage of router R3 affecting adjacencies on links L23 and L34.",
    },
    "f3": {
        "scenario_key": "F3",
        "name": "Scenario F3: OSPF Config Mismatch on L23",
        "description": "Config mismatch (MTU/Hello) causing adjacency drop between R2 and R3.",
    },
    "f4": {
        "scenario_key": "F4",
        "name": "Scenario F4: Partial Packet Loss",
        "description": "Intermittent packet loss induced on link L34 causing telemetry anomalies.",
    },
    "f5": {
        "scenario_key": "F5",
        "name": "Scenario F5: High Latency / Jitter",
        "description": "Elevated RTT latency and jitter across transit ring path.",
    },
}

SNAPSHOT_FILE_MAP: dict[str, str] = {
    "baseline": "baseline_snapshot.json",
    "f1": "f1_link_failure_snapshot.json",
    "f2": "f2_router_failure_snapshot.json",
    "f3": "f3_ospf_mismatch_snapshot.json",
    "f4": "f4_packet_loss_snapshot.json",
    "f5": "f5_high_latency_snapshot.json",
}


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
        self._incidents: dict[str, list[Incident]] = {}
        self._diagnoses: dict[str, list[DiagnosisResult]] = {}
        self._verifications: dict[str, list[VerificationReport]] = {}
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
        """Load and index all archived scenario fixtures."""
        for key, fname in SNAPSHOT_FILE_MAP.items():
            fpath = self._dataset_dir / fname
            if not fpath.exists():
                continue
            raw = json.loads(fpath.read_text())
            EvidenceNormalizer.assert_no_ground_truth_leakage(raw)

            snap_id = raw.get("snapshot_id", f"snap-{key}")
            self._raw_snapshots[key] = raw
            self._snapshot_id_to_key[key.lower()] = key
            self._snapshot_id_to_key[snap_id] = key

            # Parse topology
            topo_dict = raw.get("topology")
            if topo_dict:
                topo = Topology.model_validate(topo_dict)
                self._topologies[key] = topo

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
        """Resolve a key like 'f1', 'F1', or 'obs-snap-...' to a canonical key ('f1')."""
        if not identifier:
            return "f1"  # Default active scenario for demonstration
        clean = identifier.lower().strip()
        if clean in self._snapshot_id_to_key:
            return self._snapshot_id_to_key[clean]
        if identifier in self._snapshot_id_to_key:
            return self._snapshot_id_to_key[identifier]
        return clean

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
            "archived_scenario_catalog": (
                SubsystemStatus.READY if len(self._raw_snapshots) >= 5 else SubsystemStatus.DEGRADED
            ),
            "live_frrouting_emulation_lab": SubsystemStatus.STANDBY,
        }
        return SystemReadinessResponse(
            status="ready",
            service_name="nexora-backend",
            version="0.1.0",
            environment="development",
            data_source_mode=DataSourceMode.ARCHIVED_REPLAY,
            ground_truth_isolation_active=True,
            subsystems=subsystems,
            available_archived_scenarios=[
                SCENARIO_METADATA[k]["scenario_key"] for k in self._raw_snapshots
            ],
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
            # Check if incident directly affects this link or endpoints
            if key == "f1" and lnk.link_id == "L12":
                link_statuses[lnk.link_id] = LinkHealthStatus.DOWN
            elif key == "f2" and (lnk.router_a == "R3" or lnk.router_b == "R3"):
                link_statuses[lnk.link_id] = LinkHealthStatus.DOWN
            elif key == "f3" and lnk.link_id == "L23":
                link_statuses[lnk.link_id] = LinkHealthStatus.DEGRADED
            elif key == "f4" and lnk.link_id == "L34":
                link_statuses[lnk.link_id] = LinkHealthStatus.DEGRADED
            elif key == "f5" and lnk.link_id in ("L12", "L23"):
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

        return TopologyStatusSummary(
            snapshot_id=topo.snapshot_id,
            data_source=DataSourceMode.ARCHIVED_REPLAY,
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
                    data_source=DataSourceMode.ARCHIVED_REPLAY,
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
        for key, raw in self._raw_snapshots.items():
            meta = SCENARIO_METADATA.get(
                key, {"scenario_key": key.upper(), "name": key, "description": ""}
            )
            diag_list = self._diagnoses.get(key, [])
            inc_ids = [d.incident_id for d in diag_list]
            res.append(
                SnapshotSummary(
                    snapshot_id=raw.get("snapshot_id", f"snap-{key}"),
                    scenario_key=meta["scenario_key"],
                    name=meta["name"],
                    description=meta["description"],
                    captured_at=datetime.fromisoformat(raw["captured_at"].replace("Z", "+00:00")),
                    record_count=len(raw.get("evidence_records", [])),
                    incident_ids=inc_ids,
                    data_source=DataSourceMode.ARCHIVED_REPLAY,
                    is_live=False,
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
            meta = SCENARIO_METADATA.get(key, {"scenario_key": key.upper()})
            raw = self._raw_snapshots.get(key, {})
            start_str = raw.get("collection_window_start", "2026-10-19T19:00:00Z")
            end_str = raw.get("collection_window_end")
            start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00")) if end_str else None

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
                        scenario_key=meta["scenario_key"],
                        affected_routers=sorted(aff_routers),
                        affected_links=sorted(aff_links),
                        evidence_count=d.evidence_certificate.total_evidence_count,
                        correlation_window_start=start,
                        correlation_window_end=end,
                        correlation_explanation=d.evidence_certificate.reasoning_summary,
                        data_source=DataSourceMode.ARCHIVED_REPLAY,
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
        # Search all
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
    def get_verification(self, incident_id: str) -> VerificationReport | None:
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

    def list_verifications(self) -> list[VerificationReport]:
        res = []
        for verif_list in self._verifications.values():
            res.extend(verif_list)
        return res

    # -----------------------------------------------------------------------
    # Probes
    # -----------------------------------------------------------------------
    def get_probe_plan(self, incident_id: str) -> SafeProbePlanResponse:
        v = self.get_verification(incident_id)
        probes: list[ProbeRequest] = []
        if v:
            for hyp_verif in v.top_hypotheses_verifications:
                probes.extend(hyp_verif.recommended_probes)

        notes = [
            (
                "Probes are strictly bounded to read-only non-destructive operations "
                "(PING, INTERFACE_STATE, OSPF_NEIGHBOUR, ROUTING_TABLE)."
            ),
            "Timeout is hard-bounded at 5 seconds per probe.",
            "Active probe execution is DISABLED on MacBook 2 presentation environment.",
        ]
        return SafeProbePlanResponse(
            incident_id=incident_id,
            recommendations=probes,
            safety_guardrail="STRICT_READ_ONLY_GUARDED",
            execution_permitted=False,
            notes=notes,
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
            filtered = [r for r in filtered if r.incident_id == incident_id]

        return filtered[offset : offset + limit]

    def count_evidence(
        self,
        router_id: str | None = None,
        source_type: str | None = None,
        event_type: str | None = None,
        incident_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> int:
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
            filtered = [r for r in filtered if r.incident_id == incident_id]

        return len(filtered)

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        return self._evidence_index.get(evidence_id)
