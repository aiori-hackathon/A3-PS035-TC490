"""Phase 06 deterministic diagnosis pipeline using the Phase 01 contracts.

No collection commands, remediation, ground truth, labels or file paths enter
this module. Recorded observations go through correlation before diagnosis.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.collectors.normalizer import EvidenceNormalizer
from app.core.config import Settings, get_settings
from app.correlation.engine import CorrelationEngine
from app.diagnosis.evidence import EvidenceContext, decode_state_tags, unique_records
from app.diagnosis.rules import score_hypothesis
from app.schemas.diagnosis import (
    DiagnosisResult,
    DiagnosisStatus,
    EvidenceCertificate,
    RankedHypothesis,
)
from app.schemas.evidence import EvidenceRecord
from app.schemas.hypothesis import FaultHypothesis, FaultLocation, FaultLocationKind, FaultType
from app.schemas.incident import Incident, IncidentEvidenceReference
from app.schemas.topology import Topology

ENGINE_VERSION = "phase06-rules-v1.1"


class HypothesisGenerator:
    """Generate type/location alternatives only where observations implicate them."""

    def generate(
        self, incident: Incident, evidence: list[EvidenceRecord], topology: Topology
    ) -> list[FaultHypothesis]:
        ctx = EvidenceContext(evidence, topology)
        return self._generate(incident, ctx)

    def _generate(
        self, incident: Incident, ctx: EvidenceContext, seed_ids: set[str] | None = None
    ) -> list[FaultHypothesis]:
        def seeded(record: EvidenceRecord) -> bool:
            return seed_ids is None or record.evidence_id in seed_ids

        links: set[str] = set()
        routers = {router for router, rows in ctx.failures.items() if any(map(seeded, rows))}
        for link_id in ctx.links:
            if any(
                seeded(r) and ctx.interface_state(r) == "down" for r in ctx.interfaces[link_id]
            ) or any(
                seeded(r) and ctx.adjacency_state(r) not in {"full", "unknown"}
                for r in ctx.adjacencies[link_id]
            ):
                links.add(link_id)
                routers.update(ctx.endpoints(ctx.links[link_id]))
        for ping in ctx.pings:
            if not seeded(ping):
                continue
            if ping.packet_loss_pct >= 5 or (ping.rtt_avg_ms is not None and ping.rtt_avg_ms >= 10):
                for path in ctx.paths(ping):
                    links.update(path.links)
                target = ctx.address_router.get(ping.target_address)
                if ping.packet_loss_pct == 100 and target:
                    routers.add(target)
        for router in routers:
            links.update(
                link.link_id for link in ctx.links.values() if router in ctx.endpoints(link)
            )
        candidates = []
        for fault_type in FaultType:
            locations = sorted(routers if fault_type == FaultType.ROUTER_FAILURE else links)
            for location in locations:
                router_kind = fault_type == FaultType.ROUTER_FAILURE
                candidates.append(
                    FaultHypothesis(
                        hypothesis_id=f"h-{fault_type.value.lower()}-{location.lower()}",
                        incident_id=incident.incident_id,
                        fault_type=fault_type,
                        fault_location=FaultLocation(
                            kind=FaultLocationKind.ROUTER
                            if router_kind
                            else FaultLocationKind.LINK,
                            component_id=location,
                            affected_routers=(
                                [location]
                                if router_kind
                                else sorted(ctx.endpoints(ctx.links[location]))
                            ),
                        ),
                        rule_score=0,
                    )
                )
        return candidates


class RuleBasedDiagnoser:
    def score_and_rank(
        self, hypotheses: list[FaultHypothesis], evidence: list[EvidenceRecord], topology: Topology
    ) -> list[RankedHypothesis]:
        ctx = EvidenceContext(evidence, topology)
        scored = {}
        for hypothesis in hypotheses:
            key = (hypothesis.fault_type, hypothesis.fault_location.component_id)
            # Recompute all evidence/scoring fields; prior hypothesis contents are not features.
            scored[key] = score_hypothesis(hypothesis, ctx)
        ordered = sorted(
            (h for h in scored.values() if h.rule_score > 0 and h.supporting_evidence_ids),
            key=lambda h: (-h.rule_score, h.fault_type.value, h.fault_location.component_id),
        )
        return [RankedHypothesis(rank=i, hypothesis=h) for i, h in enumerate(ordered, 1)]


@dataclass(frozen=True)
class SufficiencyAssessment:
    status: DiagnosisStatus
    coverage_pct: float
    missing: list[str]

    @property
    def met(self) -> bool:
        return self.status != DiagnosisStatus.INSUFFICIENT_EVIDENCE


class EvidenceSufficiencyEvaluator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def assess(self, ranked: list[RankedHypothesis], ctx: EvidenceContext) -> SufficiencyAssessment:
        settings = self.settings
        coverage = ctx.coverage()
        missing = []
        if not ranked:
            missing.append(
                "No supported fault candidate. Healthy observations do not imply a fault; "
                "untyped measurements or absent data cannot establish network health."
            )
        else:
            top = ranked[0].hypothesis
            missing.extend(top.missing_evidence_descriptions)
            if top.rule_score < settings.DIAGNOSIS_MIN_SCORE:
                missing.append(f"Leading rule score below {settings.DIAGNOSIS_MIN_SCORE:.2f}.")
            points = len(ctx.primary_points(top.supporting_evidence_ids))
            if points < settings.DIAGNOSIS_MIN_PRIMARY_POINTS:
                missing.append(
                    "Too few independent primary observation points: "
                    f"{points}/{settings.DIAGNOSIS_MIN_PRIMARY_POINTS}."
                )
        if coverage < settings.DIAGNOSIS_MIN_COVERAGE_PCT:
            missing.append(
                f"Usable collection coverage {coverage:.2f}% is below "
                f"{settings.DIAGNOSIS_MIN_COVERAGE_PCT:.2f}% of represented attempts."
            )
        insufficient = (
            not ranked
            or coverage < settings.DIAGNOSIS_MIN_COVERAGE_PCT
            or ranked[0].hypothesis.rule_score < settings.DIAGNOSIS_MIN_SCORE
            or len(ctx.primary_points(ranked[0].hypothesis.supporting_evidence_ids))
            < settings.DIAGNOSIS_MIN_PRIMARY_POINTS
        )
        status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
        if not insufficient:
            margin = (
                ranked[0].hypothesis.rule_score - ranked[1].hypothesis.rule_score
                if len(ranked) > 1
                else ranked[0].hypothesis.rule_score
            )
            if margin + 1e-9 < settings.DIAGNOSIS_MIN_MARGIN:
                status = DiagnosisStatus.AMBIGUOUS
                missing.append(
                    f"Leading score margin {margin:.2f} is below "
                    f"{settings.DIAGNOSIS_MIN_MARGIN:.2f}; competing causes remain."
                )
            else:
                status = DiagnosisStatus.DIAGNOSED
        return SufficiencyAssessment(status, coverage, sorted(set(missing)))

    def evaluate(
        self,
        ranked_hypotheses: list[RankedHypothesis],
        evidence: list[EvidenceRecord],
        topology: Topology | None = None,
    ) -> tuple[bool, float, list[str]]:
        # The Phase01 protocol lacks topology. Without that context we cannot
        # verify independent points or coverage, so conservatively abstain.
        if topology is None:
            return False, 0.0, ["Topology context required for sufficiency assessment."]
        assessment = self.assess(ranked_hypotheses, EvidenceContext(evidence, topology))
        return assessment.met, assessment.coverage_pct, assessment.missing


class EvidenceCertificateBuilder:
    def build(
        self,
        incident: Incident,
        evidence: list[EvidenceRecord],
        ranked_hypotheses: list[RankedHypothesis],
        sufficiency_met: bool,
        coverage_pct: float,
        missing_info: list[str],
        reasoning_summary: str,
    ) -> EvidenceCertificate:
        top = ranked_hypotheses[0].hypothesis if ranked_hypotheses else None
        return EvidenceCertificate(
            certificate_id=f"cert-{uuid4().hex}",
            incident_id=incident.incident_id,
            generated_at=datetime.now(UTC),
            total_evidence_count=len(unique_records(evidence)),
            supporting_evidence_count=len(top.supporting_evidence_ids) if top else 0,
            contradictory_evidence_count=len(top.contradictory_evidence_ids) if top else 0,
            missing_evidence_descriptions=missing_info,
            evidence_sufficiency_met=sufficiency_met,
            collection_coverage_pct=coverage_pct,
            reasoning_summary=reasoning_summary[:4096],
        )


class DiagnosisEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.generator = HypothesisGenerator()
        self.diagnoser = RuleBasedDiagnoser()
        self.sufficiency = EvidenceSufficiencyEvaluator(settings)
        self.certificates = EvidenceCertificateBuilder()

    def diagnose(
        self,
        incident: Incident,
        evidence: list[EvidenceRecord],
        topology: Topology,
    ) -> DiagnosisResult:
        """Diagnose an already correlated Incident using its collected observations."""
        return self._diagnose(incident, evidence, topology)

    def _diagnose(
        self,
        incident: Incident,
        evidence: list[EvidenceRecord],
        topology: Topology,
        *,
        candidate_evidence_ids: set[str] | None = None,
    ) -> DiagnosisResult:
        EvidenceNormalizer.assert_no_ground_truth_leakage(incident.model_dump(mode="json"))
        EvidenceNormalizer.assert_no_ground_truth_leakage(topology.model_dump(mode="json"))
        # IDs and notes are never features. Explicit scope and time boundaries are.
        records = [
            r
            for r in unique_records(evidence)
            if r.observed_at >= incident.collection_window_start
            and (
                incident.collection_window_end is None
                or r.observed_at <= incident.collection_window_end
            )
            and (r.incident_id is None or r.incident_id == incident.incident_id)
        ]
        ctx = EvidenceContext(records, topology)
        candidates = self.generator._generate(incident, ctx, candidate_evidence_ids)
        ranked = self.diagnoser.score_and_rank(candidates, ctx.records, topology)
        assessment = self.sufficiency.assess(ranked, ctx)
        summary = f"{assessment.status.value}. "
        if ranked:
            top = ranked[0].hypothesis
            summary += (
                f"Leading candidate {top.fault_type.value} at "
                f"{top.fault_location.component_id}, heuristic score {top.rule_score:.2f}. "
                + " ".join(top.reasoning_trace)
            )
        else:
            summary += "No evidence-supported fault candidate was generated."
        summary += " Scores are heuristic alignment values, not calibrated probabilities."
        return DiagnosisResult(
            result_id=f"dr-{uuid4().hex}",
            incident_id=incident.incident_id,
            diagnosed_at=datetime.now(UTC),
            engine_version=ENGINE_VERSION,
            status=assessment.status,
            ranked_hypotheses=ranked,
            top1_hypothesis=(
                ranked[0].hypothesis if assessment.status == DiagnosisStatus.DIAGNOSED else None
            ),
            top3_hypotheses=[rh.hypothesis for rh in ranked[:3]],
            evidence_certificate=self.certificates.build(
                incident,
                ctx.records,
                ranked,
                assessment.met,
                assessment.coverage_pct,
                assessment.missing,
                summary,
            ),
            missing_information=assessment.missing,
        )

    def diagnose_snapshot_dict(self, snapshot: dict[str, Any]) -> list[DiagnosisResult]:
        """Strict offline/live adapter: payload only; never receives a filename.

        Missing/malformed topology or records raise validation errors instead of
        fabricating expected observations. Legacy state tags preserve real IDs.
        """
        EvidenceNormalizer.assert_no_ground_truth_leakage(snapshot)
        topology = Topology.model_validate(snapshot["topology"])
        records = [EvidenceNormalizer.deserialize_record(r) for r in snapshot["evidence_records"]]
        records = decode_state_tags(records, topology)
        start = datetime.fromisoformat(snapshot["collection_window_start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(snapshot["collection_window_end"].replace("Z", "+00:00"))
        if start.tzinfo is None or end.tzinfo is None or end < start:
            raise ValueError("Snapshot collection window must be ordered and timezone aware")
        records = [r for r in records if start <= r.observed_at <= end]
        partitions: dict[str | None, list[EvidenceRecord]] = {}
        for record in records:
            partitions.setdefault(record.incident_id, []).append(record)
        groups = [
            (group, binding, partition)
            for binding, partition in sorted(partitions.items(), key=lambda item: item[0] or "")
            for group in CorrelationEngine().correlate_records(partition, topology).incidents
        ]
        if not groups:
            return [
                self.diagnose(
                    Incident(
                        incident_id="incident-empty",
                        detected_at=start,
                        collection_window_start=start,
                        collection_window_end=end,
                        topology_snapshot_id=topology.snapshot_id,
                    ),
                    [],
                    topology,
                )
            ]
        results = []
        for group, binding, partition in groups:
            group_ids = set(group.evidence_ids)
            # Include healthy context in this temporal slice, necessary for
            # contradictions and sufficiency; candidate generation remains local.
            scoped = [
                r
                for r in partition
                if group.correlation_window_start <= r.observed_at <= group.correlation_window_end
            ]
            identity = hashlib.sha256("|".join(sorted(group_ids)).encode()).hexdigest()[:16]
            incident = Incident(
                incident_id=binding or f"incident-{identity}",
                detected_at=group.correlation_window_start,
                collection_window_start=max(start, group.correlation_window_start),
                collection_window_end=min(end, group.correlation_window_end),
                topology_snapshot_id=topology.snapshot_id,
                potentially_affected_routers=group.affected_routers,
                potentially_affected_links=group.affected_links,
                evidence_references=[
                    IncidentEvidenceReference(
                        evidence_id=r.evidence_id,
                        evidence_type=type(r).__name__,
                        added_at=r.collected_at,
                    )
                    for r in scoped
                ],
            )
            symptom_ids = {
                eid for symptom in group.symptoms for eid in symptom.supporting_evidence_ids
            }
            # Healthy/unknown groups have no anomalous candidates. Context is
            # still scored, but a separate spatial incident cannot seed causes.
            results.append(
                self._diagnose(
                    incident,
                    scoped,
                    topology,
                    candidate_evidence_ids=symptom_ids,
                )
            )
        return results
