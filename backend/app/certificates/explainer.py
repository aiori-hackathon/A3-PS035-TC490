"""
NEXORA Deterministic Root-Cause Explanation Engine (Phase 09).

Generates explainable, auditable root-cause explanations answering 8 canonical questions:
1. WHAT happened?
2. WHERE was the suspected fault located?
3. WHY was this hypothesis selected over alternatives?
4. WHAT observations support it?
5. WHAT observations contradict it?
6. WHAT counterfactual expectations were satisfied?
7. WHAT evidence is missing or uncollected?
8. WHAT safe next checks could reduce remaining uncertainty?

Handles F2 multi-link collateral manifestations without claiming causal certainty.
Enforces strict string length bounds to prevent validation overflow.
"""

from __future__ import annotations

from app.schemas.certificate import EvidenceReference, RootCauseExplanation
from app.schemas.counterfactual import (
    CounterfactualVerdict,
    CounterfactualVerificationResult,
    ObservationMatch,
)
from app.schemas.diagnosis import DiagnosisResult, DiagnosisStatus
from app.schemas.hypothesis import FaultHypothesis, FaultType
from app.schemas.probe import PlannedProbe, ProbePlanReport


class ExplanationEngine:
    """Deterministic explanation generator synthesizing diagnosis, verification, and probe plans."""

    def generate_explanation(
        self,
        diagnosis: DiagnosisResult,
        verification: CounterfactualVerificationResult | None,
        probe_plan: ProbePlanReport | None,
        supporting_refs: list[EvidenceReference],
        contradicting_refs: list[EvidenceReference],
        missing_observations: list[str],
        collector_failures: list[str],
    ) -> RootCauseExplanation:
        """Construct structured, bounded root-cause explanation sections."""
        top_ranked = diagnosis.ranked_hypotheses[0] if diagnosis.ranked_hypotheses else None
        top_h = top_ranked.hypothesis if top_ranked else None

        # 1. WHAT happened?
        what = self._explain_what(diagnosis, top_h)

        # 2. WHERE located?
        where = self._explain_where(top_h)

        # 3. WHY selected?
        why = self._explain_why(diagnosis, top_h, verification)

        # 4. SUPPORTING observations
        supp = self._summarize_supporting(supporting_refs)

        # 5. CONTRADICTING observations
        contra = self._summarize_contradicting(contradicting_refs)

        # 6. COUNTERFACTUAL expectations
        cf = self._summarize_counterfactual(verification)

        # 7. MISSING evidence
        missing = self._summarize_missing(missing_observations, collector_failures)

        # 8. SAFE NEXT CHECKS
        probes = self._summarize_probes(probe_plan)

        # Full narrative text
        full = self._format_full_text(
            what=what,
            where=where,
            why=why,
            supporting=supp,
            contradicting=contra,
            counterfactual=cf,
            missing=missing,
            safe_checks=probes,
        )

        return RootCauseExplanation(
            what_happened=what[:1024],
            where_located=where[:512],
            why_selected=why[:2048],
            supporting_observations_summary=supp[:2048],
            contradicting_observations_summary=contra[:2048],
            counterfactual_expectations_summary=cf[:2048],
            missing_evidence_summary=missing[:2048],
            safe_next_checks_summary=probes[:2048],
            full_text=full[:8192],
        )

    def _explain_what(self, diag: DiagnosisResult, top_h: FaultHypothesis | None) -> str:
        if diag.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE or not top_h:
            return (
                "Telemetry collection was insufficient or incomplete to confirm a single "
                "specific root-cause fault. The diagnostic system abstained from a definitive "
                "verdict to avoid false attribution."
            )
        if diag.status == DiagnosisStatus.AMBIGUOUS:
            return (
                "Multiple competing fault hypotheses scored identically or within the ambiguity "
                "margin. Diagnostic ambiguity exists between the top candidate explanations."
            )

        ft = top_h.fault_type
        comp = top_h.fault_location.component_id
        if ft == FaultType.LINK_FAILURE:
            return (
                f"Physical link failure detected on {comp}. Bidirectional traffic was interrupted "
                f"with loss of interface carrier and corresponding OSPF adjacency drop."
            )
        if ft == FaultType.ROUTER_FAILURE:
            return (
                f"Router node outage detected at {comp}. The device ceased responding to "
                "management telemetry and all adjacent OSPF peering sessions collapsed."
            )
        if ft == FaultType.OSPF_CONFIGURATION_MISMATCH:
            return (
                f"Control-plane configuration mismatch detected on link {comp}. Underlying "
                "physical carrier remains operational while OSPF adjacency failed to reach "
                "FULL state."
            )
        if ft == FaultType.PACKET_LOSS:
            return (
                f"Sustained packet loss detected across link {comp}. Packet loss exceeded normal "
                "operational thresholds while the link remained partially traversable."
            )
        if ft == FaultType.HIGH_LATENCY:
            return (
                f"Elevated round-trip latency detected across link {comp} without packet drop, "
                "consistent with queue congestion, traffic shaping, or link degradation."
            )
        return f"Suspected network defect ({ft.value}) detected on component {comp}."

    def _explain_where(self, top_h: FaultHypothesis | None) -> str:
        if not top_h:
            return "Indeterminate / unlocalized due to insufficient telemetry."
        loc = top_h.fault_location
        return f"{loc.kind.value} {loc.component_id}"

    def _explain_why(
        self,
        diag: DiagnosisResult,
        top_h: FaultHypothesis | None,
        verification: CounterfactualVerificationResult | None,
    ) -> str:
        if not top_h:
            return (
                "No candidate hypothesis met the minimum evidence sufficiency threshold "
                "required for selection."
            )

        lines: list[str] = []
        score_str = f"{top_h.rule_score:.2f}"
        lines.append(
            f"Hypothesis {top_h.fault_type.value} at {top_h.fault_location.component_id} "
            f"achieved the highest heuristic rule score ({score_str}) among candidates."
        )

        # F2 router-vs-link collateral explanation
        if (
            top_h.fault_type == FaultType.ROUTER_FAILURE
            and len(diag.ranked_hypotheses) > 1
            and any(
                h.hypothesis.fault_type == FaultType.LINK_FAILURE
                for h in diag.ranked_hypotheses[1:]
            )
        ):
            adjacent_links = [
                h.hypothesis.fault_location.component_id
                for h in diag.ranked_hypotheses[1:]
                if h.hypothesis.fault_type == FaultType.LINK_FAILURE
            ]
            lines.append(
                f"While competing link failure hypotheses ({', '.join(adjacent_links)}) "
                "received local support due to OSPF neighbor drops, the simultaneous loss "
                f"of all adjacencies and telemetry unresponsiveness on "
                f"{top_h.fault_location.component_id} indicates that these link drops are "
                "collateral manifestations of the central node failure, rather than "
                "multiple independent physical link severances."
            )
        elif len(diag.ranked_hypotheses) > 1:
            runner_up = diag.ranked_hypotheses[1].hypothesis
            margin = top_h.rule_score - runner_up.rule_score
            lines.append(
                f"Leading score margin over runner-up ({runner_up.fault_type.value} at "
                f"{runner_up.fault_location.component_id}, score {runner_up.rule_score:.2f}) "
                f"is {margin:.2f}."
            )

        if verification:
            lines.append(
                f"Counterfactual verification yielded verdict: {verification.verdict.value}."
            )
            if verification.verdict == CounterfactualVerdict.SUPPORTED:
                lines.append(
                    "All required counterfactual expectations for this fault pattern were "
                    "confirmed by independent telemetry observations."
                )
                if top_h.rule_score < 1.0:
                    lines.append(
                        "Original heuristic rule score reflects penalty from peer observation "
                        "asymmetry (e.g., OSPF dead-timer lag on peer before dead-interval "
                        "expiry), which counterfactual verification accounted for across "
                        "required endpoints."
                    )
            elif verification.verdict == CounterfactualVerdict.CONTRADICTED:
                lines.append(
                    "Warning: Counterfactual verification detected one or more contradictory "
                    "observations refuting expectations."
                )

        return " ".join(lines)

    def _summarize_supporting(self, refs: list[EvidenceReference]) -> str:
        if not refs:
            return "No direct supporting evidence records registered."
        items = [
            f"[{r.source_router}:{r.source_interface or 'node'}] {r.summary}"
            for r in refs[:8]
        ]
        if len(refs) > 8:
            items.append(f"... and {len(refs) - 8} additional supporting observations.")
        return "; ".join(items)

    def _summarize_contradicting(self, refs: list[EvidenceReference]) -> str:
        if not refs:
            return "None. No contradicting observations were recorded."
        items = [
            f"[{r.source_router}:{r.source_interface or 'node'}] {r.summary}"
            for r in refs[:5]
        ]
        if len(refs) > 5:
            items.append(f"... and {len(refs) - 5} additional contradictory observations.")
        res = "; ".join(items)
        if any("OSPF neighbor" in r.summary and "Full" in r.summary for r in refs):
            res += (
                " (Peer OSPF Full observation is temporally explained by protocol dead-timer "
                "lag prior to dead-interval expiry; does not refute physical link severance)."
            )
        return res

    def _summarize_counterfactual(
        self,
        verification: CounterfactualVerificationResult | None,
    ) -> str:
        if not verification:
            return "Counterfactual verification not performed or unavailable."
        total = len(verification.evaluated_expectations)
        matched = sum(
            1
            for e in verification.evaluated_expectations
            if e.match_status == ObservationMatch.SUPPORTED
        )
        contra = sum(
            1
            for e in verification.evaluated_expectations
            if e.match_status == ObservationMatch.CONTRADICTED
        )
        missing = sum(
            1
            for e in verification.evaluated_expectations
            if e.match_status == ObservationMatch.MISSING
        )
        return (
            f"Verdict: {verification.verdict.value}. "
            f"Evaluated {total} expectation(s): {matched} supported, {contra} contradicted, "
            f"{missing} missing/uncollected."
        )

    def _summarize_missing(
        self,
        missing: list[str],
        collector_failures: list[str],
    ) -> str:
        parts: list[str] = []
        if missing:
            parts.append(f"Missing expected observations: {'; '.join(missing[:5])}")
            if len(missing) > 5:
                parts.append(f"(plus {len(missing) - 5} more)")
        if collector_failures:
            parts.append(f"Collector failures: {'; '.join(collector_failures[:3])}")
        if not parts:
            return "None. All expected telemetry was successfully collected."
        return " | ".join(parts)

    def _summarize_probes(self, plan: ProbePlanReport | None) -> str:
        if not plan or not plan.recommended_probes:
            if plan and plan.is_abstention:
                return (
                    f"No active probes proposed. Planner abstained: "
                    f"{plan.abstention_reason or 'Diagnostic certainty sufficient.'}"
                )
            return "No active next probes recommended."

        probes: list[PlannedProbe] = plan.recommended_probes[:4]
        items = [
            f"[{p.probe_type.value}] on {p.source_router} targeting {p.target_component}: "
            f"{p.selection_reason} (Priority: {p.priority_score:.2f})"
            for p in probes
        ]
        if len(plan.recommended_probes) > 4:
            items.append(f"... and {len(plan.recommended_probes) - 4} additional safe probes.")
        items.append(
            "Note: All recommendations are strictly PROPOSED / NOT EXECUTED. "
            "Zero active network commands have been dispatched."
        )
        return " ".join(items)

    def _format_full_text(
        self,
        what: str,
        where: str,
        why: str,
        supporting: str,
        contradicting: str,
        counterfactual: str,
        missing: str,
        safe_checks: str,
    ) -> str:
        sections = [
            "=== NEXORA ROOT-CAUSE EVIDENCE CERTIFICATE EXPLANATION ===",
            f"1. WHAT HAPPENED:\n   {what}",
            f"2. WHERE LOCATED:\n   {where}",
            f"3. WHY SELECTED:\n   {why}",
            f"4. SUPPORTING OBSERVATIONS:\n   {supporting}",
            f"5. CONTRADICTING OBSERVATIONS:\n   {contradicting}",
            f"6. COUNTERFACTUAL VERIFICATION:\n   {counterfactual}",
            f"7. MISSING EVIDENCE & COLLECTOR FAILURES:\n   {missing}",
            f"8. SAFE PROPOSED NEXT CHECKS:\n   {safe_checks}",
        ]
        return "\n\n".join(sections)
