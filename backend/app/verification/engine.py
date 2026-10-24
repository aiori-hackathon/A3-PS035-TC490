"""
Deterministic Counterfactual Verification Engine for NEXORA.

Implements the CounterfactualVerifier protocol. Given a candidate hypothesis,
generates expected network observations and tests them against actual neutral evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.collectors.normalizer import EvidenceNormalizer
from app.diagnosis.evidence import EvidenceContext, decode_state_tags, unique_records
from app.schemas.counterfactual import (
    CounterfactualVerdict,
    CounterfactualVerificationResult,
    Criticality,
    EvaluatedExpectation,
    ExpectationCategory,
    ExpectedObservation,
    ObservationMatch,
    VerificationReport,
)
from app.schemas.diagnosis import DiagnosisResult
from app.schemas.evidence import (
    EvidenceRecord,
    InterfaceObservation,
    OSPFObservation,
)
from app.schemas.hypothesis import (
    FaultHypothesis,
    FaultLocationKind,
    FaultType,
)
from app.schemas.incident import Incident, IncidentEvidenceReference
from app.schemas.probe import ProbeRequest, ProbeType
from app.schemas.topology import Topology
from app.verification.expectations import ExpectationGenerator

VERIFIER_VERSION = "phase07-counterfactual-v1.0"


class CounterfactualVerificationEngine:
    """Deterministic verification engine testing counterfactual hypothesis expectations."""

    def __init__(self) -> None:
        self.expectation_generator = ExpectationGenerator()

    def verify(
        self,
        hypothesis: FaultHypothesis,
        evidence: list[EvidenceRecord],
        topology: Topology,
    ) -> FaultHypothesis:
        """Verify a hypothesis and return an updated copy with counterfactual_verified set.

        Satisfies the CounterfactualVerifier protocol.
        """
        detailed = self.verify_hypothesis_detailed(hypothesis, evidence, topology)
        return hypothesis.model_copy(
            update={
                "counterfactual_verified": detailed.counterfactual_verified,
            }
        )

    def verify_hypothesis_detailed(
        self,
        hypothesis: FaultHypothesis,
        evidence: list[EvidenceRecord],
        topology: Topology,
        incident_window: tuple[datetime, datetime | None] | None = None,
    ) -> CounterfactualVerificationResult:
        """Evaluate all counterfactual expectations for a hypothesis against evidence."""
        # Filter evidence to incident window if supplied
        records = unique_records(evidence)
        if incident_window is not None:
            w_start, w_end = incident_window
            records = [
                r
                for r in records
                if r.observed_at >= w_start and (w_end is None or r.observed_at <= w_end)
            ]

        ctx = EvidenceContext(records, topology)
        expectations = self.expectation_generator.generate_expectations(hypothesis, topology)

        evaluated: list[EvaluatedExpectation] = []
        all_supporting: set[str] = set()
        all_contradicting: set[str] = set()
        missing_descs: list[str] = []
        recommended_probes: list[ProbeRequest] = []

        for exp in expectations:
            eval_res, probes = self._evaluate_single_expectation(exp, ctx, hypothesis.incident_id)
            evaluated.append(eval_res)
            all_supporting.update(eval_res.supporting_evidence_ids)
            all_contradicting.update(eval_res.contradicting_evidence_ids)
            if eval_res.match_status == ObservationMatch.MISSING:
                missing_descs.append(
                    f"{exp.expected_condition} on {exp.target_component} ({exp.rationale})"
                )
            recommended_probes.extend(probes)

        # Derive verdict
        has_contradiction = any(e.match_status == ObservationMatch.CONTRADICTED for e in evaluated)
        required_evals = [e for e in evaluated if e.expectation.criticality == Criticality.REQUIRED]
        required_supported = [
            e for e in required_evals if e.match_status == ObservationMatch.SUPPORTED
        ]
        required_missing = [e for e in required_evals if e.match_status == ObservationMatch.MISSING]

        if has_contradiction:
            verdict = CounterfactualVerdict.CONTRADICTED
            counterfactual_verified = False
            explanation = (
                f"Contradicted: Evidence directly refutes expected conditions for "
                f"{hypothesis.fault_type.value} at {hypothesis.fault_location.component_id}. "
                f"Found {len(all_contradicting)} contradicting observations."
            )
        elif len(required_supported) == len(required_evals) and len(required_evals) > 0:
            verdict = CounterfactualVerdict.SUPPORTED
            counterfactual_verified = True
            explanation = (
                f"Supported: All {len(required_evals)} required counterfactual expectations "
                f"matched observed evidence. Found {len(all_supporting)} supporting observation "
                f"records with zero contradictions."
            )
        elif len(required_missing) > 0 and len(required_supported) == 0:
            verdict = CounterfactualVerdict.INSUFFICIENT_EVIDENCE
            counterfactual_verified = None
            explanation = (
                f"Insufficient Evidence: Required observations for "
                f"{hypothesis.fault_type.value} at "
                f"{hypothesis.fault_location.component_id} are missing or uncollected."
            )
        else:
            verdict = CounterfactualVerdict.INCONCLUSIVE
            counterfactual_verified = None
            explanation = (
                f"Inconclusive: Some observations matched "
                f"({len(required_supported)}/{len(required_evals)} required), "
                f"but key expected evidence is incomplete without clear contradiction."
            )

        return CounterfactualVerificationResult(
            hypothesis=hypothesis,
            verdict=verdict,
            counterfactual_verified=counterfactual_verified,
            evaluated_expectations=evaluated,
            supporting_evidence_ids=sorted(all_supporting),
            contradictory_evidence_ids=sorted(all_contradicting),
            missing_evidence_descriptions=sorted(missing_descs),
            explanation=explanation,
            recommended_probes=recommended_probes,
        )

    def _evaluate_single_expectation(
        self,
        exp: ExpectedObservation,
        ctx: EvidenceContext,
        incident_id: str,
    ) -> tuple[EvaluatedExpectation, list[ProbeRequest]]:
        """Compare one expected observation against records in EvidenceContext."""
        category = exp.category
        comp = exp.target_component
        endpoint = exp.target_endpoint

        supporting: list[str] = []
        contradicting: list[str] = []
        probes: list[ProbeRequest] = []

        if category == ExpectationCategory.INTERFACE_STATE:
            # Handle link-level endpoint expectation or single interface expectation
            if comp in ctx.links:
                link = ctx.links[comp]
                obs_a = [
                    r
                    for r in ctx.records
                    if isinstance(r, InterfaceObservation)
                    and r.source_router == link.router_a
                    and r.source_interface == link.interface_a
                ]
                obs_b = [
                    r
                    for r in ctx.records
                    if isinstance(r, InterfaceObservation)
                    and r.source_router == link.router_b
                    and r.source_interface == link.interface_b
                ]

                if not obs_a and not obs_b:
                    probes.append(
                        ProbeRequest(
                            probe_id=f"probe-iface-{uuid4().hex[:8]}",
                            incident_id=incident_id,
                            probe_type=ProbeType.INTERFACE_STATE,
                            source_router=link.router_a,
                            target_interface=link.interface_a,
                            selection_reason=(
                                f"Verify operational state of {link.router_a} {link.interface_a} "
                                "for link failure verification"
                            ),
                            requested_at=datetime.now(UTC),
                        )
                    )
                    return (
                        EvaluatedExpectation(
                            expectation=exp,
                            match_status=ObservationMatch.MISSING,
                            explanation=(
                                "No operational status records collected for link "
                                f"endpoints on {comp}"
                            ),
                        ),
                        probes,
                    )

                states = []
                for r in obs_a + obs_b:
                    st = ctx.interface_state(r)
                    states.append((r, st))

                down_obs = [r for r, st in states if st == "down"]
                up_obs = [r for r, st in states if st == "up"]

                expected_down = "down" in exp.expected_condition.lower()
                if expected_down:
                    if down_obs:
                        # At least one endpoint is down
                        supporting.extend([r.evidence_id for r in down_obs])
                        status = ObservationMatch.SUPPORTED
                        expl = (
                            "Supported: Interface down confirmed on affected endpoint "
                            f"({down_obs[0].source_router} {down_obs[0].source_interface})"
                        )
                        if up_obs:
                            expl += (
                                f"; peer interface ({up_obs[0].source_router} "
                                f"{up_obs[0].source_interface}) carrier persistence noted"
                            )
                    else:
                        # Both endpoints observed UP directly contradicts physical link failure
                        contradicting.extend([r.evidence_id for r in up_obs])
                        status = ObservationMatch.CONTRADICTED
                        expl = (
                            f"Contradicted: Both endpoint interfaces ({link.router_a} "
                            f"{link.interface_a}, {link.router_b} {link.interface_b}) observed UP"
                        )
                else:  # expected UP
                    if down_obs:
                        contradicting.extend([r.evidence_id for r in down_obs])
                        status = ObservationMatch.CONTRADICTED
                        expl = (
                            "Contradicted: Interface observed DOWN on "
                            f"{down_obs[0].source_router} {down_obs[0].source_interface}"
                        )
                    else:
                        supporting.extend([r.evidence_id for r in up_obs])
                        status = ObservationMatch.SUPPORTED
                        expl = "Supported: Link endpoint interfaces confirmed UP"

                return (
                    EvaluatedExpectation(
                        expectation=exp,
                        match_status=status,
                        supporting_evidence_ids=supporting,
                        contradicting_evidence_ids=contradicting,
                        explanation=expl,
                    ),
                    probes,
                )

            # Single router interface check
            router = comp
            iface = endpoint
            matching_obs = [
                r
                for r in ctx.records
                if isinstance(r, InterfaceObservation)
                and r.source_router == router
                and r.source_interface == iface
            ]

            if not matching_obs:
                probes.append(
                    ProbeRequest(
                        probe_id=f"probe-iface-{uuid4().hex[:8]}",
                        incident_id=incident_id,
                        probe_type=ProbeType.INTERFACE_STATE,
                        source_router=router,
                        target_interface=iface,
                        selection_reason=(
                            f"Verify operational state of {router} {iface} "
                            "for counterfactual hypothesis"
                        ),
                        requested_at=datetime.now(UTC),
                    )
                )
                return (
                    EvaluatedExpectation(
                        expectation=exp,
                        match_status=ObservationMatch.MISSING,
                        explanation=(
                            "No operational status records collected for "
                            f"interface {router} {iface}"
                        ),
                    ),
                    probes,
                )

            expected_down = "down" in exp.expected_condition.lower()
            for r in matching_obs:
                st = ctx.interface_state(r)
                if expected_down:
                    if st == "down":
                        supporting.append(r.evidence_id)
                    elif st == "up":
                        contradicting.append(r.evidence_id)
                else:  # expected UP
                    if st == "up":
                        supporting.append(r.evidence_id)
                    elif st == "down":
                        contradicting.append(r.evidence_id)

            if contradicting:
                status = ObservationMatch.CONTRADICTED
                curr_state = ctx.interface_state(matching_obs[-1])
                exp_state = "DOWN" if expected_down else "UP"
                expl = (
                    f"Contradicted: Interface {router} {iface} observed "
                    f"{curr_state}, expected {exp_state}"
                )
            elif supporting:
                status = ObservationMatch.SUPPORTED
                expl = (
                    f"Supported: Interface {router} {iface} confirmed "
                    f"{'DOWN' if expected_down else 'UP'}"
                )
            else:
                status = ObservationMatch.INCONCLUSIVE
                expl = f"Interface {router} {iface} status unclear from observations"

            return (
                EvaluatedExpectation(
                    expectation=exp,
                    match_status=status,
                    supporting_evidence_ids=supporting,
                    contradicting_evidence_ids=contradicting,
                    explanation=expl,
                ),
                probes,
            )

        elif category == ExpectationCategory.OSPF_ADJACENCY:
            link_id = comp
            adj_records = ctx.adjacencies.get(link_id, [])
            expected_full = (
                "remain" in exp.expected_condition.lower()
                and "full" in exp.expected_condition.lower()
            )
            expected_nonfull = any(
                term in exp.expected_condition.lower()
                for term in ("non-full", "down", "loss", "lose", "lost", "fail")
            )

            if not adj_records:
                # If expecting non-full during router failure, check if neighbor records disappeared
                if exp.rationale and any(
                    term in exp.rationale.lower()
                    for term in ("dead", "crashed", "failure", "unresponsive")
                ):
                    peer = (
                        endpoint.split("->")[0].strip() if endpoint and "->" in endpoint else None
                    )
                    target_r = (
                        endpoint.split("->")[1].strip() if endpoint and "->" in endpoint else comp
                    )
                    if peer and target_r:
                        peer_ospf = [
                            r
                            for r in ctx.records
                            if isinstance(r, OSPFObservation) and r.source_router == peer
                        ]
                        if peer_ospf:
                            target_rid = (
                                ctx.routers[target_r].ospf_router_id
                                if target_r in ctx.routers
                                else None
                            )
                            neighbor_present = any(
                                r.neighbour_router_id == target_rid
                                and ctx.adjacency_state(r) == "full"
                                for r in peer_ospf
                            )
                            if not neighbor_present:
                                supporting.extend([r.evidence_id for r in peer_ospf[:1]])
                                return (
                                    EvaluatedExpectation(
                                        expectation=exp,
                                        match_status=ObservationMatch.SUPPORTED,
                                        supporting_evidence_ids=supporting,
                                        explanation=(
                                            f"Supported: Neighbor {target_r} absent from "
                                            f"{peer} OSPF neighbor table (adjacency lost)"
                                        ),
                                    ),
                                    probes,
                                )

                if link_id in ctx.links:
                    link = ctx.links[link_id]
                    probes.append(
                        ProbeRequest(
                            probe_id=f"probe-ospf-{uuid4().hex[:8]}",
                            incident_id=incident_id,
                            probe_type=ProbeType.OSPF_NEIGHBOUR,
                            source_router=link.router_a,
                            target_router=link.router_b,
                            selection_reason=f"Poll OSPF neighbor state on link {link_id}",
                            requested_at=datetime.now(UTC),
                        )
                    )
                return (
                    EvaluatedExpectation(
                        expectation=exp,
                        match_status=ObservationMatch.MISSING,
                        explanation=f"No OSPF adjacency records observed on link {link_id}",
                    ),
                    probes,
                )

            bad_obs = [r for r in adj_records if ctx.adjacency_state(r) != "full"]
            full_obs = [r for r in adj_records if ctx.adjacency_state(r) == "full"]

            if expected_nonfull:
                if bad_obs:
                    # Adjacency loss is directly confirmed on at least one endpoint
                    supporting.extend([r.evidence_id for r in bad_obs])
                    status = ObservationMatch.SUPPORTED
                    adj_st = ctx.adjacency_state(bad_obs[0])
                    expl = (
                        "Supported: OSPF adjacency loss confirmed on "
                        f"{bad_obs[0].source_router} (state: {adj_st})"
                    )
                    if full_obs:
                        expl += (
                            f"; peer {full_obs[0].source_router} reports Full "
                            "(protocol dead-timer lag)"
                        )
                else:
                    # Both directions remain Full -> contradicts adjacency loss
                    contradicting.extend([r.evidence_id for r in full_obs])
                    status = ObservationMatch.CONTRADICTED
                    expl = (
                        f"Contradicted: OSPF adjacency on {link_id} "
                        "remains FULL in all observed directions"
                    )
            elif expected_full:
                if bad_obs:
                    contradicting.extend([r.evidence_id for r in bad_obs])
                    status = ObservationMatch.CONTRADICTED
                    expl = (
                        f"Contradicted: OSPF adjacency on {link_id} observed "
                        f"{ctx.adjacency_state(bad_obs[0])}, expected FULL"
                    )
                else:
                    supporting.extend([r.evidence_id for r in full_obs])
                    status = ObservationMatch.SUPPORTED
                    expl = f"Supported: OSPF adjacency on {link_id} confirmed FULL"
            else:
                status = ObservationMatch.INCONCLUSIVE
                expl = f"OSPF adjacency observations on {link_id} inconclusive"

            return (
                EvaluatedExpectation(
                    expectation=exp,
                    match_status=status,
                    supporting_evidence_ids=supporting,
                    contradicting_evidence_ids=contradicting,
                    explanation=expl,
                ),
                probes,
            )

        elif category == ExpectationCategory.ROUTER_AVAILABILITY:
            router = comp
            failures = ctx.unavailable.get(router, []) or ctx.failures.get(router, [])
            live_records = ctx.live.get(router, [])

            if live_records:
                contradicting.extend([r.evidence_id for r in live_records[:2]])
                return (
                    EvaluatedExpectation(
                        expectation=exp,
                        match_status=ObservationMatch.CONTRADICTED,
                        contradicting_evidence_ids=contradicting,
                        explanation=(
                            f"Contradicted: Router {router} successfully "
                            "responded to telemetry polls"
                        ),
                    ),
                    probes,
                )

            if failures:
                supporting.extend([r.evidence_id for r in failures])
                return (
                    EvaluatedExpectation(
                        expectation=exp,
                        match_status=ObservationMatch.SUPPORTED,
                        supporting_evidence_ids=supporting,
                        explanation=(
                            f"Supported: Router {router} confirmed "
                            "unavailable/unresponsive during collection"
                        ),
                    ),
                    probes,
                )

            probes.append(
                ProbeRequest(
                    probe_id=f"probe-avail-{uuid4().hex[:8]}",
                    incident_id=incident_id,
                    probe_type=ProbeType.PING,
                    source_router=next(
                        r.router_id for r in ctx.routers.values() if r.router_id != router
                    ),
                    target_router=router,
                    target_address=ctx.routers[router].loopback_address
                    if router in ctx.routers
                    else None,
                    selection_reason=f"Probe reachability of router {router}",
                    requested_at=datetime.now(UTC),
                )
            )
            return (
                EvaluatedExpectation(
                    expectation=exp,
                    match_status=ObservationMatch.MISSING,
                    explanation=f"No telemetry attempts recorded for router {router}",
                ),
                probes,
            )

        elif category == ExpectationCategory.PACKET_LOSS:
            target_pings = []
            if comp in ctx.links:
                link_id = comp
                target_pings = [
                    p for p in ctx.pings if any(link_id in path.links for path in ctx.paths(p))
                ]
            elif comp in ctx.routers and endpoint:
                target_pings = [p for p in ctx.pings if p.target_address == endpoint]

            if not target_pings:
                if comp in ctx.links:
                    link = ctx.links[comp]
                    probes.append(
                        ProbeRequest(
                            probe_id=f"probe-loss-{uuid4().hex[:8]}",
                            incident_id=incident_id,
                            probe_type=ProbeType.PING,
                            source_router=link.router_a,
                            target_router=link.router_b,
                            target_address=link.address_b.split("/")[0],
                            selection_reason=f"Measure packet loss across link {comp}",
                            requested_at=datetime.now(UTC),
                        )
                    )
                return (
                    EvaluatedExpectation(
                        expectation=exp,
                        match_status=ObservationMatch.MISSING,
                        explanation=f"No ping probes traversed target {comp}",
                    ),
                    probes,
                )

            cond = exp.expected_condition.lower()
            if "partial" in cond:
                for p in target_pings:
                    if 5.0 <= p.packet_loss_pct < 100.0:
                        supporting.append(p.evidence_id)
                    elif p.packet_loss_pct == 0.0 or p.packet_loss_pct == 100.0:
                        contradicting.append(p.evidence_id)
            elif "negligible" in cond or "< 5.0%" in cond:
                for p in target_pings:
                    if p.packet_loss_pct < 5.0:
                        supporting.append(p.evidence_id)
                    elif p.packet_loss_pct >= 5.0:
                        contradicting.append(p.evidence_id)
            elif "fails" in cond or "100% packet loss" in cond:
                for p in target_pings:
                    if p.packet_loss_pct == 100.0:
                        supporting.append(p.evidence_id)
                    elif p.packet_loss_pct < 100.0:
                        contradicting.append(p.evidence_id)
            elif "succeeds" in cond or "< 100%" in cond:
                for p in target_pings:
                    if p.packet_loss_pct < 100.0:
                        supporting.append(p.evidence_id)
                    elif p.packet_loss_pct == 100.0:
                        contradicting.append(p.evidence_id)

            if contradicting and not supporting:
                status = ObservationMatch.CONTRADICTED
                loss_pct = target_pings[0].packet_loss_pct
                expl = (
                    f"Contradicted: Measured packet loss is {loss_pct:.1f}%, "
                    f"incompatible with expectation: {exp.expected_condition}"
                )
            elif supporting and not contradicting:
                status = ObservationMatch.SUPPORTED
                loss_pct = target_pings[0].packet_loss_pct
                expl = (
                    f"Supported: Measured packet loss is {loss_pct:.1f}%, "
                    f"matches expectation: {exp.expected_condition}"
                )
            elif supporting and contradicting:
                status = ObservationMatch.INCONCLUSIVE
                expl = "Mixed packet loss observations across multiple probe rounds"
            else:
                status = ObservationMatch.INCONCLUSIVE
                expl = "Probe packet loss measurements inconclusive"

            return (
                EvaluatedExpectation(
                    expectation=exp,
                    match_status=status,
                    supporting_evidence_ids=supporting,
                    contradicting_evidence_ids=contradicting,
                    explanation=expl,
                ),
                probes,
            )

        elif category == ExpectationCategory.RTT_LATENCY:
            target_pings = []
            if comp in ctx.links:
                link_id = comp
                target_pings = [
                    p for p in ctx.pings if any(link_id in path.links for path in ctx.paths(p))
                ]

            if not target_pings:
                if comp in ctx.links:
                    link = ctx.links[comp]
                    probes.append(
                        ProbeRequest(
                            probe_id=f"probe-rtt-{uuid4().hex[:8]}",
                            incident_id=incident_id,
                            probe_type=ProbeType.PING,
                            source_router=link.router_a,
                            target_router=link.router_b,
                            target_address=link.address_b.split("/")[0],
                            selection_reason=f"Measure round-trip latency across link {comp}",
                            requested_at=datetime.now(UTC),
                        )
                    )
                return (
                    EvaluatedExpectation(
                        expectation=exp,
                        match_status=ObservationMatch.MISSING,
                        explanation=f"No RTT latency measurements recorded across {comp}",
                    ),
                    probes,
                )

            expected_elevated = (
                "elevated" in exp.expected_condition.lower()
                or ">= 10.0ms" in exp.expected_condition.lower()
            )
            for p in target_pings:
                if p.rtt_avg_ms is not None:
                    if expected_elevated:
                        if p.rtt_avg_ms >= 10.0:
                            supporting.append(p.evidence_id)
                        else:
                            contradicting.append(p.evidence_id)
                    else:  # expected normal < 10ms
                        if p.rtt_avg_ms < 10.0:
                            supporting.append(p.evidence_id)
                        else:
                            contradicting.append(p.evidence_id)

            if contradicting:
                status = ObservationMatch.CONTRADICTED
                rtt_val = target_pings[0].rtt_avg_ms
                exp_rtt = "elevated" if expected_elevated else "normal"
                expl = (
                    f"Contradicted: Measured avg RTT is {rtt_val:.2f}ms, "
                    f"contradicts expected {exp_rtt} latency"
                )
            elif supporting:
                status = ObservationMatch.SUPPORTED
                rtt_val = target_pings[0].rtt_avg_ms
                exp_rtt = "elevated" if expected_elevated else "normal"
                expl = (
                    f"Supported: Measured avg RTT is {rtt_val:.2f}ms, "
                    f"matches expected {exp_rtt} latency"
                )
            else:
                status = ObservationMatch.INCONCLUSIVE
                expl = "RTT observations inconclusive"

            return (
                EvaluatedExpectation(
                    expectation=exp,
                    match_status=status,
                    supporting_evidence_ids=supporting,
                    contradicting_evidence_ids=contradicting,
                    explanation=expl,
                ),
                probes,
            )

        elif category == ExpectationCategory.CONFIGURATION_PARAM:
            # Confirmatory parameter check
            # Look for configuration evidence or protocol parameter records
            param_records = [
                r
                for r in ctx.records
                if "config" in str(r.source_type).lower() or "param" in str(r.source_type).lower()
            ]
            if not param_records:
                return (
                    EvaluatedExpectation(
                        expectation=exp,
                        match_status=ObservationMatch.MISSING,
                        explanation=(
                            "Direct OSPF timer configuration records not present "
                            "in telemetry; behavioral inference used"
                        ),
                    ),
                    probes,
                )
            return (
                EvaluatedExpectation(
                    expectation=exp,
                    match_status=ObservationMatch.INCONCLUSIVE,
                    explanation=(
                        "Configuration parameter records observed but require "
                        "offline parser validation"
                    ),
                ),
                probes,
            )

        # Fallback
        return (
            EvaluatedExpectation(
                expectation=exp,
                match_status=ObservationMatch.INCONCLUSIVE,
                explanation=f"Unsupported expectation category: {category}",
            ),
            probes,
        )

    def verify_diagnosis(
        self,
        diagnosis: DiagnosisResult,
        evidence: list[EvidenceRecord],
        topology: Topology,
        incident_window: tuple[datetime, datetime | None] | None = None,
    ) -> VerificationReport:
        """Verify the top ranked hypotheses and evaluate competing alternatives."""
        top_results: list[CounterfactualVerificationResult] = []
        competing_results: list[CounterfactualVerificationResult] = []

        # 1. Verify all top hypotheses present in diagnosis
        for rh in diagnosis.ranked_hypotheses:
            res = self.verify_hypothesis_detailed(
                rh.hypothesis, evidence, topology, incident_window
            )
            top_results.append(res)

        # 2. Reconstruct and verify competing alternatives if not already evaluated
        evaluated_keys = {
            (r.hypothesis.fault_type, r.hypothesis.fault_location.component_id) for r in top_results
        }

        # If we have a leading target, generate all other fault types on that component
        if top_results:
            primary_loc = top_results[0].hypothesis.fault_location
            incident_id = diagnosis.incident_id

            competing_types = (
                [FaultType.ROUTER_FAILURE]
                if primary_loc.kind == FaultLocationKind.ROUTER
                else [
                    FaultType.LINK_FAILURE,
                    FaultType.OSPF_CONFIGURATION_MISMATCH,
                    FaultType.PACKET_LOSS,
                    FaultType.HIGH_LATENCY,
                ]
            )

            for ft in competing_types:
                key = (ft, primary_loc.component_id)
                if key in evaluated_keys:
                    continue
                alt_hyp = FaultHypothesis(
                    hypothesis_id=f"h-alt-{ft.value.lower()}-{primary_loc.component_id.lower()}",
                    incident_id=incident_id,
                    fault_type=ft,
                    fault_location=primary_loc,
                    rule_score=0.0,
                )
                alt_res = self.verify_hypothesis_detailed(
                    alt_hyp, evidence, topology, incident_window
                )
                competing_results.append(alt_res)

        # Build summary
        top_name = (
            f"{top_results[0].hypothesis.fault_type.value} @ "
            f"{top_results[0].hypothesis.fault_location.component_id}"
            if top_results
            else "None"
        )
        top_verdict = top_results[0].verdict.value if top_results else "N/A"
        summary = (
            f"Counterfactual verification evaluated {len(top_results)} ranked hypotheses and "
            f"{len(competing_results)} competing alternatives. "
            f"Top-1 hypothesis {top_name} verdict: {top_verdict}."
        )

        return VerificationReport(
            incident_id=diagnosis.incident_id,
            verified_at=datetime.now(UTC),
            engine_version=VERIFIER_VERSION,
            top_hypotheses_verifications=top_results,
            competing_hypotheses_verifications=competing_results,
            summary=summary,
        )

    def verify_snapshot_dict(
        self,
        snapshot: dict[str, Any],
    ) -> list[VerificationReport]:
        """Strict neutral snapshot entry point: parses snapshot, diagnoses, and verifies."""
        EvidenceNormalizer.assert_no_ground_truth_leakage(snapshot)
        topology = Topology.model_validate(snapshot["topology"])
        records = [EvidenceNormalizer.deserialize_record(r) for r in snapshot["evidence_records"]]
        records = decode_state_tags(records, topology)

        w_start = datetime.fromisoformat(
            snapshot["collection_window_start"].replace("Z", "+00:00")
        )
        w_end = datetime.fromisoformat(
            snapshot["collection_window_end"].replace("Z", "+00:00")
        )

        from app.diagnosis.engine import DiagnosisEngine

        engine = DiagnosisEngine()
        try:
            diag_results = engine.diagnose_snapshot_dict(snapshot)
        except Exception:
            # Fallback to direct diagnosis if correlation explanation exceeds schema limit
            incident = Incident(
                incident_id=f"inc-{snapshot.get('snapshot_id', 'snap')}",
                detected_at=w_start,
                collection_window_start=w_start,
                collection_window_end=w_end,
                topology_snapshot_id=topology.snapshot_id,
                potentially_affected_routers=[r.router_id for r in topology.routers],
                potentially_affected_links=[link.link_id for link in topology.links],
                evidence_references=[
                    IncidentEvidenceReference(
                        evidence_id=r.evidence_id,
                        evidence_type=type(r).__name__,
                        added_at=r.collected_at,
                    )
                    for r in records
                ],
            )
            diag_results = [engine.diagnose(incident, records, topology)]

        reports: list[VerificationReport] = []
        for dr in diag_results:
            report = self.verify_diagnosis(
                diagnosis=dr,
                evidence=records,
                topology=topology,
                incident_window=(w_start, w_end),
            )
            reports.append(report)

        return reports
