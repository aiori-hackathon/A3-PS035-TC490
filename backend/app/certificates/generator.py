"""
NEXORA Auditable Evidence Certificate Generator (Phase 09).

Generates deterministic, auditable Evidence Certificates that consolidate:
- Original diagnosis result (scores, status, ranked hypotheses)
- Supporting and contradictory evidence references
- Counterfactual verification verdicts and expectations
- Missing required observations and collector failures
- Safe proposed active next checks (strictly NOT EXECUTED)
- Snapshot provenance and cryptographic SHA-256 digest integrity
- Structured 8-question root-cause explanations

DESIGN INVARIANTS:
1. Deterministic output: Identical inputs yield identical certificates and certificate IDs.
2. Ground-truth isolation: Pure neutral evidence context only; zero access to truth.json.
3. No mutation: Never alters original evidence records or diagnosis results.
4. Non-probabilistic disclaimers: Transparent heuristic scores without calibrated probabilities.
5. Fail-closed integrity: Unresolved evidence references or digest mismatches are flagged.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from app.certificates.explainer import ExplanationEngine
from app.certificates.integrity import compute_snapshot_digest, verify_snapshot_integrity
from app.diagnosis.engine import DiagnosisEngine
from app.probes.planner import ProbePlanner
from app.schemas.certificate import (
    CERTIFICATE_SCHEMA_VERSION,
    AuditableEvidenceCertificate,
    EvidenceReference,
    EvidenceRole,
)
from app.schemas.counterfactual import (
    CounterfactualVerdict,
    CounterfactualVerificationResult,
    VerificationReport,
)
from app.schemas.diagnosis import DiagnosisResult, DiagnosisStatus
from app.schemas.probe import PlannedProbe, ProbePlanReport
from app.schemas.topology import Topology
from app.topology.graph import build_expected_topology_graph
from app.verification.engine import CounterfactualVerificationEngine

CERTIFICATE_GENERATOR_VERSION = "phase09-certgen-v1.0"


class CertificateGenerator:
    """Consolidates diagnostic intelligence into certified, auditable evidence certificates."""

    def __init__(self) -> None:
        self.explainer = ExplanationEngine()
        self.diag_engine = DiagnosisEngine()
        self.verif_engine = CounterfactualVerificationEngine()
        self.probe_planner = ProbePlanner()

    def generate_certificate(
        self,
        snapshot: dict[str, Any],
        diagnosis: DiagnosisResult,
        verification_report: VerificationReport | None = None,
        probe_plan: ProbePlanReport | None = None,
        binding: dict[str, Any] | None = None,
        topology: Topology | None = None,
    ) -> AuditableEvidenceCertificate:
        """Generate a complete, deterministic AuditableEvidenceCertificate."""
        # 1. Extract Snapshot Identifiers & Raw Records
        snapshot_id = snapshot.get("snapshot_id")
        raw_records = snapshot.get("evidence_records", [])
        records_by_id: dict[str, dict[str, Any]] = {}
        for r in raw_records:
            if isinstance(r, dict) and "evidence_id" in r:
                records_by_id[r["evidence_id"]] = r
            elif hasattr(r, "evidence_id"):
                records_by_id[r.evidence_id] = r.model_dump(mode="json")

        # 2. Extract Hypothesis & Verdict
        top_ranked = diagnosis.ranked_hypotheses[0] if diagnosis.ranked_hypotheses else None
        top_h = top_ranked.hypothesis if top_ranked else None

        selected_hyp_id = top_h.hypothesis_id if top_h else None
        fault_type = top_h.fault_type if top_h else None
        fault_location = top_h.fault_location if top_h else None
        heuristic_score = top_h.rule_score if top_h else None

        # Find matching CounterfactualVerificationResult
        verif_result: CounterfactualVerificationResult | None = None
        if verification_report and top_h:
            for vr in verification_report.top_hypotheses_verifications:
                if vr.hypothesis.hypothesis_id == top_h.hypothesis_id:
                    verif_result = vr
                    break
            if not verif_result and verification_report.top_hypotheses_verifications:
                verif_result = verification_report.top_hypotheses_verifications[0]

        counterfactual_verdict: CounterfactualVerdict | None = (
            verif_result.verdict if verif_result else None
        )
        counterfactual_verified: bool | None = (
            verif_result.counterfactual_verified if verif_result else None
        )

        # 3. Resolve Supporting & Contradictory Evidence References
        supporting_ids = list(top_h.supporting_evidence_ids) if top_h else []
        contradicting_ids = list(top_h.contradictory_evidence_ids) if top_h else []
        if verif_result:
            supporting_ids.extend(verif_result.supporting_evidence_ids)
            contradicting_ids.extend(verif_result.contradictory_evidence_ids)
        supporting_ids = sorted(set(supporting_ids))
        contradicting_ids = sorted(set(contradicting_ids))

        supporting_refs: list[EvidenceReference] = []
        for eid in supporting_ids:
            if eid in records_by_id:
                supporting_refs.append(
                    self._build_evidence_reference(records_by_id[eid], EvidenceRole.SUPPORTING)
                )

        contradicting_refs: list[EvidenceReference] = []
        for eid in contradicting_ids:
            if eid in records_by_id:
                contradicting_refs.append(
                    self._build_evidence_reference(records_by_id[eid], EvidenceRole.CONTRADICTORY)
                )

        # 4. Collector Failures & Missing Evidence
        collector_failures: list[str] = []
        for r in raw_records:
            if isinstance(r, dict):
                status = r.get("collection_status")
                eid = r.get("evidence_id", "unknown")
                src = r.get("source_router", "unknown")
            else:
                status = getattr(r, "collection_status", None)
                eid = getattr(r, "evidence_id", "unknown")
                src = getattr(r, "source_router", "unknown")

            if status in {"COLLECTION_FAILED", "ObservationStatus.COLLECTION_FAILED"}:
                collector_failures.append(f"Failed collection on {src} ({eid})")

        missing_obs: list[str] = []
        if verif_result and verif_result.missing_evidence_descriptions:
            missing_obs.extend(verif_result.missing_evidence_descriptions)
        if diagnosis.evidence_certificate.missing_evidence_descriptions:
            missing_obs.extend(diagnosis.evidence_certificate.missing_evidence_descriptions)
        missing_obs = sorted(set(missing_obs))

        # 5. Integrity and Provenance Audit
        expected_digest = None
        source_run_id = None
        if binding:
            expected_digest = binding.get("snapshot_sha256")
            source_run_id = binding.get("run_id")
        elif snapshot.get("run_id"):
            source_run_id = snapshot.get("run_id")

        all_referenced_ids = sorted(set(supporting_ids + contradicting_ids))
        integrity_res = verify_snapshot_integrity(
            snapshot=snapshot,
            referenced_evidence_ids=all_referenced_ids,
            expected_digest=expected_digest,
            source_run_id=source_run_id,
        )

        computed_digest = integrity_res.computed_digest or compute_snapshot_digest(snapshot)

        # 6. Sufficiency Status
        sufficiency_status = (
            "SUFFICIENT"
            if diagnosis.status == DiagnosisStatus.DIAGNOSED
            and diagnosis.evidence_certificate.evidence_sufficiency_met
            else "INSUFFICIENT"
        )
        if diagnosis.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE:
            sufficiency_status = "ABSTAINED_INSUFFICIENT"
        elif diagnosis.status == DiagnosisStatus.AMBIGUOUS:
            sufficiency_status = "AMBIGUOUS"

        # 7. Safe Active Probe Recommendations (Phase 08)
        safe_probes: list[PlannedProbe] = []
        if probe_plan and probe_plan.recommended_probes:
            safe_probes = list(probe_plan.recommended_probes)

        # 8. Root-Cause Explanation
        explanation = self.explainer.generate_explanation(
            diagnosis=diagnosis,
            verification=verif_result,
            probe_plan=probe_plan,
            supporting_refs=supporting_refs,
            contradicting_refs=contradicting_refs,
            missing_observations=missing_obs,
            collector_failures=collector_failures,
        )

        # 9. Explicit Limitations
        limitations = [
            "Rule scores are dimensionless heuristic values in [0.0, 1.0] produced by "
            "deterministic rules; they are not calibrated statistical probabilities.",
            "All safe probe recommendations are proposed next checks and have NOT been "
            "executed (strictly PROPOSED_NOT_EXECUTED).",
            "Diagnosis and counterfactual verification are bounded to the observation "
            "window and collected snapshot evidence.",
            "Integrity verification confirms snapshot payload authenticity and evidence "
            "existence; it does not replace operational verification.",
        ]

        # 10. Deterministic Certificate ID Generation
        id_inputs = (
            f"{diagnosis.incident_id}:{snapshot_id or ''}:{computed_digest}:"
            f"{selected_hyp_id or 'none'}:{diagnosis.status.value}"
        )
        cert_id = f"cert-{hashlib.sha256(id_inputs.encode('utf-8')).hexdigest()[:16]}"

        return AuditableEvidenceCertificate(
            certificate_id=cert_id,
            schema_version=CERTIFICATE_SCHEMA_VERSION,
            created_at=datetime.now(UTC),
            snapshot_id=snapshot_id,
            snapshot_digest=computed_digest,
            source_run_id=source_run_id,
            incident_id=diagnosis.incident_id,
            selected_hypothesis_id=selected_hyp_id,
            fault_type=fault_type,
            fault_location=fault_location,
            diagnosis_status=diagnosis.status,
            original_heuristic_score=heuristic_score,
            counterfactual_verdict=counterfactual_verdict,
            counterfactual_verified=counterfactual_verified,
            supporting_evidence_references=supporting_refs,
            contradictory_evidence_references=contradicting_refs,
            missing_required_observations=missing_obs,
            collector_failures=collector_failures,
            evidence_coverage_pct=diagnosis.evidence_certificate.collection_coverage_pct,
            sufficiency_status=sufficiency_status,
            safe_probe_recommendations=safe_probes,
            explanation=explanation,
            limitations=limitations,
            integrity_result=integrity_res,
        )

    def generate_from_snapshot_dict(
        self,
        snapshot_dict: dict[str, Any],
        binding: dict[str, Any] | None = None,
    ) -> AuditableEvidenceCertificate:
        """Run full offline diagnosis, verification, probe planning, and certificate generation."""
        topo = build_expected_topology_graph().topology
        if "topology" in snapshot_dict and isinstance(snapshot_dict["topology"], dict):
            try:
                topo = Topology.model_validate(snapshot_dict["topology"])
            except Exception:
                topo = build_expected_topology_graph().topology

        # Diagnose with resilient fallback for correlation narrative length
        try:
            diag_results = self.diag_engine.diagnose_snapshot_dict(snapshot_dict)
            diag = diag_results[0]
        except Exception:
            from app.collectors.normalizer import EvidenceNormalizer
            from app.diagnosis.evidence import decode_state_tags
            from app.schemas.incident import Incident, IncidentEvidenceReference

            records = [
                EvidenceNormalizer.deserialize_record(r)
                for r in snapshot_dict.get("evidence_records", [])
            ]
            records = decode_state_tags(records, topo)
            w_start_str = snapshot_dict.get("collection_window_start", "2026-10-19T00:00:00Z")
            w_end_str = snapshot_dict.get("collection_window_end", "2026-10-19T00:05:00Z")
            w_start = datetime.fromisoformat(w_start_str.replace("Z", "+00:00"))
            w_end = datetime.fromisoformat(w_end_str.replace("Z", "+00:00"))

            incident = Incident(
                incident_id=f"inc-{snapshot_dict.get('snapshot_id', 'snap')}",
                detected_at=w_start,
                collection_window_start=w_start,
                collection_window_end=w_end,
                topology_snapshot_id=topo.snapshot_id,
                potentially_affected_routers=[r.router_id for r in topo.routers],
                potentially_affected_links=[link.link_id for link in topo.links],
                evidence_references=[
                    IncidentEvidenceReference(
                        evidence_id=r.evidence_id,
                        evidence_type=type(r).__name__,
                        added_at=r.collected_at,
                    )
                    for r in records
                ],
            )
            diag = self.diag_engine.diagnose(incident, records, topo)

        # Counterfactual Verification
        verif_results = self.verif_engine.verify_snapshot_dict(snapshot_dict)
        verif = verif_results[0] if verif_results else None

        # Probe Planning
        probe_plans = self.probe_planner.plan_snapshot_dict(snapshot_dict)
        plan = probe_plans[0] if probe_plans else None

        return self.generate_certificate(
            snapshot=snapshot_dict,
            diagnosis=diag,
            verification_report=verif,
            probe_plan=plan,
            binding=binding,
            topology=topo,
        )

    def _build_evidence_reference(
        self,
        rec: dict[str, Any],
        role: EvidenceRole,
    ) -> EvidenceReference:
        """Build a typed EvidenceReference from raw snapshot record dict."""
        eid = str(rec.get("evidence_id", "unknown"))
        router = str(rec.get("source_router", "R1"))
        iface = rec.get("source_interface")
        if iface is not None:
            iface = str(iface)
        event_type = str(rec.get("event_type", "TELEMETRY_OBSERVED"))

        obs_at_raw = rec.get("observed_at")
        if isinstance(obs_at_raw, datetime):
            if obs_at_raw.tzinfo:
                observed_at = obs_at_raw.astimezone(UTC)
            else:
                observed_at = obs_at_raw.replace(tzinfo=UTC)
        elif isinstance(obs_at_raw, str):
            try:
                observed_at = datetime.fromisoformat(obs_at_raw.replace("Z", "+00:00"))
            except ValueError:
                observed_at = datetime.now(UTC)
        else:
            observed_at = datetime.now(UTC)

        # Formulate concise summary
        st = rec.get("source_type")
        if st in {"INTERFACE_POLL", "EvidenceSourceType.INTERFACE_POLL"}:
            oper = rec.get("observed_status", "unknown")
            summary = f"Interface {iface or 'unknown'} status observed as {oper}"
        elif st in {"OSPF_API", "EvidenceSourceType.OSPF_API"}:
            neighbor = rec.get("neighbour_router_id", "unknown")
            adj = rec.get("adjacency_state", "unknown")
            summary = f"OSPF neighbor {neighbor} state is {adj}"
        elif st in {"ACTIVE_PING", "EvidenceSourceType.ACTIVE_PING"}:
            loss = rec.get("packet_loss_pct", 0.0)
            rtt = rec.get("rtt_avg_ms", 0.0)
            summary = f"Ping probe packet loss {loss}% with avg RTT {rtt}ms"
        elif st in {"SYSLOG", "EvidenceSourceType.SYSLOG"}:
            daemon = rec.get("process_name", "daemon")
            summary = f"Syslog event from {daemon}: {event_type}"
        else:
            summary = f"Observation {event_type} on {router}"

        return EvidenceReference(
            evidence_id=eid,
            source_router=router,
            source_interface=iface,
            event_type=event_type,
            observed_at=observed_at,
            role=role,
            summary=summary[:512],
        )
