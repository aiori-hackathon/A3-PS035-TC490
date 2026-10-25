"""
Safe active probe planning engine for the NEXORA diagnostic system.

Answers:
"What additional read-only observation would best help confirm or distinguish
the remaining fault hypotheses?"

STRICT INVARIANTS:
1. PLANNING ONLY: Probes are strictly PROPOSED / NOT EXECUTED.
2. Read-only probe types only: no router restart, interface shutdown, or config mutation.
3. Fail-closed safety boundary: all probes validated against approved topology and policy.
4. Fully deterministic ranking and tie-breaking.
5. Zero ground-truth access or leakage.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from app.collectors.normalizer import EvidenceNormalizer
from app.diagnosis.evidence import decode_state_tags
from app.probes.policy import (
    ProbeSafetyPolicy,
)
from app.probes.ranking import ProbeRankingEngine
from app.schemas.counterfactual import (
    Criticality,
    ExpectationCategory,
    ObservationMatch,
    VerificationReport,
)
from app.schemas.diagnosis import DiagnosisResult
from app.schemas.evidence import EvidenceRecord
from app.schemas.hypothesis import FaultHypothesis, FaultType
from app.schemas.probe import (
    DiscriminatingOutcomes,
    ExecutionAuthorizationState,
    PlannedProbe,
    ProbePlanReport,
    ProbeRequest,
    ProbeSafetyStatus,
    ProbeType,
)
from app.schemas.topology import Topology
from app.topology.graph import TopologyGraph

PLANNER_VERSION = "phase08-safe-probe-planner-v1.0"


class ProbePlanner:
    """Deterministic, topology-aware planner for safe read-only active diagnostic probes."""

    def __init__(
        self,
        safety_policy: ProbeSafetyPolicy | None = None,
        ranking_engine: ProbeRankingEngine | None = None,
    ) -> None:
        self.safety_policy = safety_policy or ProbeSafetyPolicy()
        self.ranking_engine = ranking_engine or ProbeRankingEngine()

    def plan_probes(
        self,
        diagnosis: DiagnosisResult,
        verification_report: VerificationReport,
        evidence: list[EvidenceRecord],
        topology: Topology,
        snapshot_id: str | None = None,
    ) -> ProbePlanReport:
        """Generate safe, ordered probe recommendations for an incident diagnosis."""
        # Initialize topology-aware policy boundaries
        policy = (
            ProbeSafetyPolicy(
                topology=topology,
                max_recommended_probes=self.safety_policy.max_recommended_probes,
                max_cost_budget=self.safety_policy.max_cost_budget,
            )
            if topology
            else self.safety_policy
        )
        topo_graph = TopologyGraph(topology)
        incident_id = diagnosis.incident_id
        candidate_probes: list[PlannedProbe] = []
        ambiguities_addressed: list[str] = []
        competing_hyp_ids: list[str] = [
            rh.hypothesis.hypothesis_id for rh in diagnosis.ranked_hypotheses
        ]

        # 1. Detect and resolve structural ambiguities (e.g. Stage 6 F2 Ambiguity)
        f2_probes = self._plan_router_link_ambiguity(
            diagnosis=diagnosis,
            verification_report=verification_report,
            topology=topology,
            topo_graph=topo_graph,
            incident_id=incident_id,
            snapshot_id=snapshot_id,
            ambiguities_out=ambiguities_addressed,
        )
        candidate_probes.extend(f2_probes)

        # 2. Plan probes for missing / inconclusive counterfactual expectations
        missing_probes = self._plan_missing_expectation_probes(
            verification_report=verification_report,
            topology=topology,
            topo_graph=topo_graph,
            incident_id=incident_id,
            snapshot_id=snapshot_id,
        )
        candidate_probes.extend(missing_probes)

        # 3. Plan targeted hypothesis discrimination probes for top candidates
        hyp_probes = self._plan_top_hypothesis_probes(
            diagnosis=diagnosis,
            verification_report=verification_report,
            topology=topology,
            topo_graph=topo_graph,
            incident_id=incident_id,
            snapshot_id=snapshot_id,
        )
        candidate_probes.extend(hyp_probes)

        # 4. Deduplicate candidate probes
        deduped = self._deduplicate_probes(candidate_probes)
        total_evaluated = len(deduped)

        # 5. Validate every candidate probe against fail-closed safety policy
        recommended: list[PlannedProbe] = []
        rejected: list[PlannedProbe] = []
        unsupported: list[PlannedProbe] = []

        cumulative_cost = 0.0
        sorted_candidates = self.ranking_engine.sort_probes(deduped)

        for probe in sorted_candidates:
            is_safe, status, rationale = policy.validate_request(probe.probe_request)
            if not is_safe:
                probe_copy = probe.model_copy(
                    update={
                        "safety_status": status,
                        "safety_rationale": rationale,
                        "execution_authorization": (
                            ExecutionAuthorizationState.REJECTED_POLICY
                            if status == ProbeSafetyStatus.POLICY_VIOLATION
                            else ExecutionAuthorizationState.REJECTED_UNSAFE
                        ),
                    }
                )
                if status == ProbeSafetyStatus.UNSUPPORTED_CAPABILITY:
                    unsupported.append(probe_copy)
                else:
                    rejected.append(probe_copy)
                continue

            # Check budget constraints
            if len(recommended) >= policy.max_recommended_probes:
                continue
            if (cumulative_cost + probe.cost.relative_cost_score) > policy.max_cost_budget:
                continue

            # Approved safe probe recommendation
            approved_probe = probe.model_copy(
                update={
                    "safety_status": ProbeSafetyStatus.SAFE,
                    "safety_rationale": rationale,
                    "execution_authorization": (ExecutionAuthorizationState.PROPOSED_NOT_EXECUTED),
                }
            )
            recommended.append(approved_probe)
            cumulative_cost += probe.cost.relative_cost_score

        # 6. Check for abstention condition
        is_abstention = False
        abstention_reason: str | None = None

        if not recommended:
            is_abstention = True
            if not candidate_probes:
                abstention_reason = (
                    "All counterfactual expectations are verified and no diagnostic "
                    "ambiguity remains; no additional observation is required."
                )
            else:
                abstention_reason = (
                    "All evaluated probe candidates were rejected by the fail-closed "
                    "safety policy or exceeded cost constraints."
                )

        # 7. Generate summary
        top_h = diagnosis.ranked_hypotheses[0].hypothesis if diagnosis.ranked_hypotheses else None
        top_name = (
            f"{top_h.fault_type.value} @ {top_h.fault_location.component_id}" if top_h else "None"
        )
        if is_abstention:
            summary = (
                f"Probe planner abstained: {abstention_reason} "
                f"(Evaluated {total_evaluated} candidate probes for incident {incident_id})."
            )
        else:
            summary = (
                f"Probe planner recommended {len(recommended)} safe read-only probe(s) "
                f"(evaluated {total_evaluated}, rejected {len(rejected)}, "
                f"unsupported {len(unsupported)}) to discriminate candidates for {top_name}. "
                f"Total relative cost: {cumulative_cost:.1f} / {policy.max_cost_budget:.1f}."
            )

        return ProbePlanReport(
            incident_id=incident_id,
            snapshot_id=snapshot_id,
            planned_at=datetime.now(UTC),
            planner_version=PLANNER_VERSION,
            total_probes_evaluated=total_evaluated,
            recommended_probes=recommended,
            rejected_probes=rejected,
            unsupported_probes=unsupported,
            competing_hypotheses_considered=sorted(competing_hyp_ids),
            ambiguities_addressed=sorted(ambiguities_addressed),
            is_abstention=is_abstention,
            abstention_reason=abstention_reason,
            summary=summary,
        )

    def _plan_router_link_ambiguity(
        self,
        diagnosis: DiagnosisResult,
        verification_report: VerificationReport,
        topology: Topology,
        topo_graph: TopologyGraph,
        incident_id: str,
        snapshot_id: str | None,
        ambiguities_out: list[str],
    ) -> list[PlannedProbe]:
        """Detect and generate safe discriminating probes for router vs adjacent link failures.

        Critical Stage 6 Scenario:
        In F2 router failure at R3, L23 and L34 also display OSPF adjacency loss.
        The planner recommends:
        1. Interface state check on surviving peers (R2 eth2, R4 eth1).
        2. Peer-side OSPF neighbor queries towards R3.
        3. Routing table inspection on non-adjacent router (R1) for R3 loopback.
        """
        probes: list[PlannedProbe] = []
        router_hyps = [
            rh.hypothesis
            for rh in diagnosis.ranked_hypotheses
            if rh.hypothesis.fault_type == FaultType.ROUTER_FAILURE
        ]
        link_hyps = [
            rh.hypothesis
            for rh in diagnosis.ranked_hypotheses
            if rh.hypothesis.fault_type == FaultType.LINK_FAILURE
        ]

        for rh in router_hyps:
            r_id = rh.fault_location.component_id
            adj_links = set(topo_graph.get_directly_connected_links(r_id))
            competing_links = [
                lh for lh in link_hyps if lh.fault_location.component_id in adj_links
            ]

            # In router failure, adjacent links always present a structural ambiguity
            # that must be discriminated from independent link failures
            if not competing_links:
                competing_links = [
                    FaultHypothesis(
                        hypothesis_id=f"h-manifest-link-{link_id.lower()}",
                        incident_id=incident_id,
                        fault_type=FaultType.LINK_FAILURE,
                        fault_location=rh.fault_location,
                        rule_score=0.5,
                    )
                    for link_id in sorted(adj_links)
                ]

            if competing_links:
                ambiguity_msg = (
                    f"Router-vs-Link ambiguity at {r_id}: Candidate ROUTER_FAILURE({r_id}) "
                    f"has adjacent links ({', '.join(sorted(adj_links))}) as competing hypotheses"
                )
                ambiguities_out.append(ambiguity_msg)

                # Find surviving peers of r_id
                neighbors = topo_graph.get_router_neighbours(r_id)
                for peer in sorted(neighbors):
                    # Find connecting link and peer interface
                    connecting_links = [
                        link
                        for link in topology.links
                        if (link.router_a == peer and link.router_b == r_id)
                        or (link.router_b == peer and link.router_a == r_id)
                    ]
                    if not connecting_links:
                        continue
                    link = connecting_links[0]
                    peer_iface = link.interface_a if link.router_a == peer else link.interface_b

                    # Probe 1: Peer-side interface operational state
                    p1 = self._build_planned_probe(
                        probe_type=ProbeType.INTERFACE_STATE,
                        source_router=peer,
                        target_interface=peer_iface,
                        target_component=link.link_id,
                        selection_reason=(
                            f"Check carrier state of {peer} interface {peer_iface} facing {r_id} "
                            f"to distinguish {r_id} router failure from physical link cut"
                        ),
                        incident_id=incident_id,
                        snapshot_id=snapshot_id,
                        related_hypothesis_id=rh.hypothesis_id,
                        related_fault_type=rh.fault_type.value,
                        discriminating_outcomes=DiscriminatingOutcomes(
                            observation_if_true=(
                                f"Peer interface {peer} {peer_iface} is UP with carrier present"
                            ),
                            observation_if_false=(
                                f"Peer interface {peer} {peer_iface} is DOWN with loss of carrier"
                            ),
                            hypotheses_supported_if_true=[f"ROUTER_FAILURE at {r_id}"],
                            hypotheses_contradicted_if_true=[
                                f"Physical link cut on {link.link_id}"
                            ],
                            hypotheses_supported_if_false=[f"LINK_FAILURE on {link.link_id}"],
                            hypotheses_contradicted_if_false=[
                                f"Pure isolated node outage at {r_id}"
                            ],
                        ),
                        is_ambiguity_resolver=True,
                        resolves_missing_required=True,
                        hop_distance=1,
                    )
                    probes.append(p1)

                    # Probe 2: Peer-side OSPF neighbor query
                    p2 = self._build_planned_probe(
                        probe_type=ProbeType.OSPF_NEIGHBOUR,
                        source_router=peer,
                        target_router=r_id,
                        target_component=link.link_id,
                        selection_reason=(
                            f"Poll OSPF neighbor state on {peer} towards {r_id} "
                            f"to verify bilateral adjacency status"
                        ),
                        incident_id=incident_id,
                        snapshot_id=snapshot_id,
                        related_hypothesis_id=rh.hypothesis_id,
                        related_fault_type=rh.fault_type.value,
                        discriminating_outcomes=DiscriminatingOutcomes(
                            observation_if_true=(
                                f"OSPF neighbor {r_id} is missing/DOWN from {peer}"
                            ),
                            observation_if_false=(f"OSPF neighbor {r_id} is FULL from {peer}"),
                            hypotheses_supported_if_true=[f"ROUTER_FAILURE at {r_id}"],
                            hypotheses_contradicted_if_true=[f"Normal operational state of {r_id}"],
                            hypotheses_supported_if_false=[
                                "Link failure localized to opposite interface"
                            ],
                            hypotheses_contradicted_if_false=[f"Total router failure at {r_id}"],
                        ),
                        is_ambiguity_resolver=True,
                        resolves_missing_required=False,
                        hop_distance=1,
                    )
                    probes.append(p2)

                # Probe 3: Remote routing table reachability from an ingress node
                ingress_routers = [
                    r.router_id
                    for r in topology.routers
                    if r.router_id not in neighbors and r.router_id != r_id
                ]
                if ingress_routers:
                    src_ingress = sorted(ingress_routers)[0]
                    target_router_obj = next(
                        (r for r in topology.routers if r.router_id == r_id), None
                    )
                    if target_router_obj and target_router_obj.loopback_address:
                        loopback_prefix = f"{target_router_obj.loopback_address.split('/')[0]}/32"
                        p3 = self._build_planned_probe(
                            probe_type=ProbeType.ROUTING_TABLE,
                            source_router=src_ingress,
                            target_prefix=loopback_prefix,
                            target_component=r_id,
                            selection_reason=(
                                f"Check if prefix {loopback_prefix} of router {r_id} "
                                f"is withdrawn in RIB of remote ingress node {src_ingress}"
                            ),
                            incident_id=incident_id,
                            snapshot_id=snapshot_id,
                            related_hypothesis_id=rh.hypothesis_id,
                            related_fault_type=rh.fault_type.value,
                            discriminating_outcomes=DiscriminatingOutcomes(
                                observation_if_true=(
                                    f"Prefix {loopback_prefix} absent in RIB on {src_ingress}"
                                ),
                                observation_if_false=(
                                    f"Prefix {loopback_prefix} is present in RIB on {src_ingress}"
                                ),
                                hypotheses_supported_if_true=[f"ROUTER_FAILURE at {r_id}"],
                                hypotheses_contradicted_if_true=[f"Unreachable router {r_id}"],
                                hypotheses_supported_if_false=[
                                    f"Normal routing reachability to {r_id}"
                                ],
                                hypotheses_contradicted_if_false=[f"Total outage of router {r_id}"],
                            ),
                            is_ambiguity_resolver=True,
                            resolves_missing_required=False,
                            hop_distance=2,
                        )
                        probes.append(p3)

        return probes

    def _plan_missing_expectation_probes(
        self,
        verification_report: VerificationReport,
        topology: Topology,
        topo_graph: TopologyGraph,
        incident_id: str,
        snapshot_id: str | None,
    ) -> list[PlannedProbe]:
        """Convert uncollected or inconclusive expectations into safe planned probes."""
        probes: list[PlannedProbe] = []
        all_results = (
            verification_report.top_hypotheses_verifications
            + verification_report.competing_hypotheses_verifications
        )

        for res in all_results:
            hyp = res.hypothesis
            for eval_exp in res.evaluated_expectations:
                if eval_exp.match_status not in (
                    ObservationMatch.MISSING,
                    ObservationMatch.INCONCLUSIVE,
                ):
                    continue

                exp = eval_exp.expectation
                is_missing_required = (
                    eval_exp.match_status == ObservationMatch.MISSING
                    and exp.criticality == Criticality.REQUIRED
                )
                is_inconclusive = eval_exp.match_status == ObservationMatch.INCONCLUSIVE

                planned = self._expectation_to_planned_probe(
                    exp=exp,
                    hypothesis=hyp,
                    topology=topology,
                    incident_id=incident_id,
                    snapshot_id=snapshot_id,
                    is_missing_required=is_missing_required,
                    is_inconclusive=is_inconclusive,
                )
                if planned:
                    probes.append(planned)

        return probes

    def _expectation_to_planned_probe(
        self,
        exp: Any,
        hypothesis: FaultHypothesis,
        topology: Topology,
        incident_id: str,
        snapshot_id: str | None,
        is_missing_required: bool,
        is_inconclusive: bool,
    ) -> PlannedProbe | None:
        """Map a missing or inconclusive expectation to a concrete PlannedProbe."""
        cat = exp.category
        comp = exp.target_component

        if cat == ExpectationCategory.INTERFACE_STATE:
            # Check if component is link
            link = next((lk for lk in topology.links if lk.link_id == comp), None)
            if link:
                return self._build_planned_probe(
                    probe_type=ProbeType.INTERFACE_STATE,
                    source_router=link.router_a,
                    target_interface=link.interface_a,
                    target_component=comp,
                    selection_reason=(
                        f"Verify operational carrier state on {link.router_a} {link.interface_a} "
                        f"to resolve missing link expectation for {comp}"
                    ),
                    incident_id=incident_id,
                    snapshot_id=snapshot_id,
                    related_hypothesis_id=hypothesis.hypothesis_id,
                    related_fault_type=hypothesis.fault_type.value,
                    discriminating_outcomes=DiscriminatingOutcomes(
                        observation_if_true=(
                            f"Interface {link.interface_a} observed {exp.expected_condition}"
                        ),
                        observation_if_false=(
                            f"Interface {link.interface_a} observed opposite condition"
                        ),
                        hypotheses_supported_if_true=[hypothesis.hypothesis_id],
                        hypotheses_contradicted_if_true=[],
                        hypotheses_supported_if_false=[],
                        hypotheses_contradicted_if_false=[hypothesis.hypothesis_id],
                    ),
                    resolves_missing_required=is_missing_required,
                    resolves_inconclusive=is_inconclusive,
                    hop_distance=1,
                )
            # Component is router interface
            router = next((r for r in topology.routers if r.router_id == comp), None)
            if router and exp.target_endpoint:
                return self._build_planned_probe(
                    probe_type=ProbeType.INTERFACE_STATE,
                    source_router=comp,
                    target_interface=exp.target_endpoint,
                    target_component=comp,
                    selection_reason=(
                        f"Inspect interface {comp} {exp.target_endpoint} operational state "
                        f"for counterfactual verification"
                    ),
                    incident_id=incident_id,
                    snapshot_id=snapshot_id,
                    related_hypothesis_id=hypothesis.hypothesis_id,
                    related_fault_type=hypothesis.fault_type.value,
                    discriminating_outcomes=DiscriminatingOutcomes(
                        observation_if_true=(
                            f"Interface {exp.target_endpoint} observed {exp.expected_condition}"
                        ),
                        observation_if_false=f"Interface {exp.target_endpoint} observed UP",
                        hypotheses_supported_if_true=[hypothesis.hypothesis_id],
                        hypotheses_contradicted_if_true=[],
                        hypotheses_supported_if_false=[],
                        hypotheses_contradicted_if_false=[hypothesis.hypothesis_id],
                    ),
                    resolves_missing_required=is_missing_required,
                    resolves_inconclusive=is_inconclusive,
                    hop_distance=0,
                )

        elif cat == ExpectationCategory.OSPF_ADJACENCY:
            link = next((lk for lk in topology.links if lk.link_id == comp), None)
            if link:
                return self._build_planned_probe(
                    probe_type=ProbeType.OSPF_NEIGHBOUR,
                    source_router=link.router_a,
                    target_router=link.router_b,
                    target_component=comp,
                    selection_reason=(
                        f"Poll OSPF state on link {comp} ({link.router_a} to {link.router_b})"
                    ),
                    incident_id=incident_id,
                    snapshot_id=snapshot_id,
                    related_hypothesis_id=hypothesis.hypothesis_id,
                    related_fault_type=hypothesis.fault_type.value,
                    discriminating_outcomes=DiscriminatingOutcomes(
                        observation_if_true=(
                            f"OSPF adjacency observed {exp.expected_condition}"
                        ),
                        observation_if_false="OSPF adjacency observed opposite state",
                        hypotheses_supported_if_true=[hypothesis.hypothesis_id],
                        hypotheses_contradicted_if_true=[],
                        hypotheses_supported_if_false=[],
                        hypotheses_contradicted_if_false=[hypothesis.hypothesis_id],
                    ),
                    resolves_missing_required=is_missing_required,
                    resolves_inconclusive=is_inconclusive,
                    hop_distance=1,
                )

        elif cat == ExpectationCategory.ROUTER_AVAILABILITY:
            # Ping loopback from adjacent router
            target_r = next((r for r in topology.routers if r.router_id == comp), None)
            if target_r and target_r.loopback_address:
                source_candidates = [
                    r.router_id for r in topology.routers if r.router_id != comp
                ]
                src = sorted(source_candidates)[0]
                target_ip = target_r.loopback_address.split("/")[0]
                return self._build_planned_probe(
                    probe_type=ProbeType.PING,
                    source_router=src,
                    target_router=comp,
                    target_address=target_ip,
                    target_component=comp,
                    selection_reason=(
                        f"Probe reachability of router {comp} loopback {target_ip} from {src}"
                    ),
                    incident_id=incident_id,
                    snapshot_id=snapshot_id,
                    related_hypothesis_id=hypothesis.hypothesis_id,
                    related_fault_type=hypothesis.fault_type.value,
                    discriminating_outcomes=DiscriminatingOutcomes(
                        observation_if_true="Ping fails with 100% loss (router unresponsive)",
                        observation_if_false="Ping succeeds with responses (router active)",
                        hypotheses_supported_if_true=[hypothesis.hypothesis_id],
                        hypotheses_contradicted_if_true=[],
                        hypotheses_supported_if_false=[],
                        hypotheses_contradicted_if_false=[hypothesis.hypothesis_id],
                    ),
                    resolves_missing_required=is_missing_required,
                    resolves_inconclusive=is_inconclusive,
                    hop_distance=1,
                )

        elif cat in (ExpectationCategory.PACKET_LOSS, ExpectationCategory.RTT_LATENCY):
            link = next((lk for lk in topology.links if lk.link_id == comp), None)
            if link and link.address_b:
                target_ip = link.address_b.split("/")[0]
                is_loss = cat == ExpectationCategory.PACKET_LOSS
                metric_name = "packet loss" if is_loss else "round-trip latency"
                return self._build_planned_probe(
                    probe_type=ProbeType.PING,
                    source_router=link.router_a,
                    target_router=link.router_b,
                    target_address=target_ip,
                    target_component=comp,
                    selection_reason=(
                        f"Execute bounded ICMP probe across link {comp} "
                        f"({link.router_a} to {target_ip}) to measure {metric_name}"
                    ),
                    incident_id=incident_id,
                    snapshot_id=snapshot_id,
                    related_hypothesis_id=hypothesis.hypothesis_id,
                    related_fault_type=hypothesis.fault_type.value,
                    discriminating_outcomes=DiscriminatingOutcomes(
                        observation_if_true=(
                            f"Ping measurement reflects {exp.expected_condition}"
                        ),
                        observation_if_false="Ping measurement shows baseline nominal metrics",
                        hypotheses_supported_if_true=[hypothesis.hypothesis_id],
                        hypotheses_contradicted_if_true=[],
                        hypotheses_supported_if_false=[],
                        hypotheses_contradicted_if_false=[hypothesis.hypothesis_id],
                    ),
                    resolves_missing_required=is_missing_required,
                    resolves_inconclusive=is_inconclusive,
                    hop_distance=1,
                )

        return None

    def _plan_top_hypothesis_probes(
        self,
        diagnosis: DiagnosisResult,
        verification_report: VerificationReport,
        topology: Topology,
        topo_graph: TopologyGraph,
        incident_id: str,
        snapshot_id: str | None,
    ) -> list[PlannedProbe]:
        """Plan confirmatory or discriminating checks for top ranked fault hypotheses."""
        probes: list[PlannedProbe] = []
        if not diagnosis.ranked_hypotheses:
            return probes

        top_h = diagnosis.ranked_hypotheses[0].hypothesis
        loc_id = top_h.fault_location.component_id

        # F1 Link Failure
        if top_h.fault_type == FaultType.LINK_FAILURE:
            link = next((lk for lk in topology.links if lk.link_id == loc_id), None)
            if link:
                p = self._build_planned_probe(
                    probe_type=ProbeType.INTERFACE_STATE,
                    source_router=link.router_a,
                    target_interface=link.interface_a,
                    target_component=loc_id,
                    selection_reason=(
                        f"Confirm operational link state of {link.router_a} {link.interface_a} "
                        f"for {loc_id}"
                    ),
                    incident_id=incident_id,
                    snapshot_id=snapshot_id,
                    related_hypothesis_id=top_h.hypothesis_id,
                    related_fault_type=top_h.fault_type.value,
                    discriminating_outcomes=DiscriminatingOutcomes(
                        observation_if_true=(
                            f"Interface {link.interface_a} on {link.router_a} is DOWN"
                        ),
                        observation_if_false=(
                            f"Interface {link.interface_a} on {link.router_a} is UP"
                        ),
                        hypotheses_supported_if_true=[f"LINK_FAILURE on {loc_id}"],
                        hypotheses_contradicted_if_true=[],
                        hypotheses_supported_if_false=[],
                        hypotheses_contradicted_if_false=[f"LINK_FAILURE on {loc_id}"],
                    ),
                    is_confirmatory_only=True,
                    hop_distance=0,
                )
                probes.append(p)

        # F3 OSPF Configuration Mismatch
        elif top_h.fault_type == FaultType.OSPF_CONFIGURATION_MISMATCH:
            link = next((lk for lk in topology.links if lk.link_id == loc_id), None)
            if link:
                # Query neighbor state on link
                p_ospf = self._build_planned_probe(
                    probe_type=ProbeType.OSPF_NEIGHBOUR,
                    source_router=link.router_a,
                    target_router=link.router_b,
                    target_component=loc_id,
                    selection_reason=(
                        f"Inspect OSPF neighbor state on {link.router_a} towards {link.router_b}"
                    ),
                    incident_id=incident_id,
                    snapshot_id=snapshot_id,
                    related_hypothesis_id=top_h.hypothesis_id,
                    related_fault_type=top_h.fault_type.value,
                    discriminating_outcomes=DiscriminatingOutcomes(
                        observation_if_true=(
                            "OSPF adjacency state is not FULL (INIT, EXSTART, or DOWN)"
                        ),
                        observation_if_false="OSPF adjacency state is FULL",
                        hypotheses_supported_if_true=[f"OSPF_CONFIGURATION_MISMATCH on {loc_id}"],
                        hypotheses_contradicted_if_true=[],
                        hypotheses_supported_if_false=[],
                        hypotheses_contradicted_if_false=[
                            f"OSPF_CONFIGURATION_MISMATCH on {loc_id}"
                        ],
                    ),
                    resolves_missing_required=True,
                    hop_distance=1,
                )
                probes.append(p_ospf)

        # F4 Packet Loss
        elif top_h.fault_type == FaultType.PACKET_LOSS:
            link = next((lk for lk in topology.links if lk.link_id == loc_id), None)
            if link and link.address_b:
                target_ip = link.address_b.split("/")[0]
                p_loss = self._build_planned_probe(
                    probe_type=ProbeType.PING,
                    source_router=link.router_a,
                    target_router=link.router_b,
                    target_address=target_ip,
                    target_component=loc_id,
                    selection_reason=(
                        f"Confirm packet loss rate on link {loc_id} "
                        f"({link.router_a} to {target_ip})"
                    ),
                    incident_id=incident_id,
                    snapshot_id=snapshot_id,
                    related_hypothesis_id=top_h.hypothesis_id,
                    related_fault_type=top_h.fault_type.value,
                    discriminating_outcomes=DiscriminatingOutcomes(
                        observation_if_true="Partial packet loss (10% to 50%) observed",
                        observation_if_false="0% packet loss (nominal) observed",
                        hypotheses_supported_if_true=[f"PACKET_LOSS on {loc_id}"],
                        hypotheses_contradicted_if_true=[],
                        hypotheses_supported_if_false=[],
                        hypotheses_contradicted_if_false=[f"PACKET_LOSS on {loc_id}"],
                    ),
                    is_confirmatory_only=True,
                    hop_distance=1,
                )
                probes.append(p_loss)

        # F5 High Latency
        elif top_h.fault_type == FaultType.HIGH_LATENCY:
            link = next((lk for lk in topology.links if lk.link_id == loc_id), None)
            if link and link.address_b:
                target_ip = link.address_b.split("/")[0]
                p_lat = self._build_planned_probe(
                    probe_type=ProbeType.PING,
                    source_router=link.router_a,
                    target_router=link.router_b,
                    target_address=target_ip,
                    target_component=loc_id,
                    selection_reason=(
                        f"Confirm round-trip latency across link {loc_id} "
                        f"({link.router_a} to {target_ip})"
                    ),
                    incident_id=incident_id,
                    snapshot_id=snapshot_id,
                    related_hypothesis_id=top_h.hypothesis_id,
                    related_fault_type=top_h.fault_type.value,
                    discriminating_outcomes=DiscriminatingOutcomes(
                        observation_if_true="Elevated round-trip time (avg RTT >= 10ms) observed",
                        observation_if_false="Normal baseline latency (avg RTT < 5ms) observed",
                        hypotheses_supported_if_true=[f"HIGH_LATENCY on {loc_id}"],
                        hypotheses_contradicted_if_true=[],
                        hypotheses_supported_if_false=[],
                        hypotheses_contradicted_if_false=[f"HIGH_LATENCY on {loc_id}"],
                    ),
                    is_confirmatory_only=True,
                    hop_distance=1,
                )
                probes.append(p_lat)

        return probes

    def _build_planned_probe(
        self,
        probe_type: ProbeType,
        source_router: str,
        target_component: str,
        selection_reason: str,
        incident_id: str,
        snapshot_id: str | None,
        discriminating_outcomes: DiscriminatingOutcomes,
        target_router: str | None = None,
        target_interface: str | None = None,
        target_address: str | None = None,
        target_prefix: str | None = None,
        related_hypothesis_id: str | None = None,
        related_fault_type: str | None = None,
        is_ambiguity_resolver: bool = False,
        resolves_missing_required: bool = False,
        resolves_inconclusive: bool = False,
        is_confirmatory_only: bool = False,
        hop_distance: int = 1,
    ) -> PlannedProbe:
        """Construct a validated PlannedProbe with deterministic plan_id and utility score."""
        # Derive deterministic signature
        sig = (
            f"{incident_id}:{probe_type.value}:{source_router}:{target_component}:"
            f"{target_router or ''}:{target_interface or ''}:"
            f"{target_address or ''}:{target_prefix or ''}"
        )
        plan_id = f"plan-{hashlib.sha256(sig.encode('utf-8')).hexdigest()[:12]}"
        req_id = f"req-{hashlib.sha256(sig.encode('utf-8')).hexdigest()[:8]}"

        cost = self.safety_policy.estimate_cost(probe_type)
        score, rationale = self.ranking_engine.compute_priority(
            probe_type=probe_type,
            source_router=source_router,
            target_component=target_component,
            cost=cost,
            is_ambiguity_resolver=is_ambiguity_resolver,
            resolves_missing_required=resolves_missing_required,
            resolves_inconclusive=resolves_inconclusive,
            is_confirmatory_only=is_confirmatory_only,
            hop_distance=hop_distance,
        )

        request = ProbeRequest(
            probe_id=req_id,
            incident_id=incident_id,
            probe_type=probe_type,
            source_router=source_router,
            target_router=target_router,
            target_address=target_address,
            target_interface=target_interface,
            target_prefix=target_prefix,
            selection_reason=selection_reason,
            timeout_s=cost.timeout_s,
            requested_at=datetime.now(UTC),
        )

        return PlannedProbe(
            plan_id=plan_id,
            incident_id=incident_id,
            snapshot_id=snapshot_id,
            probe_request=request,
            probe_type=probe_type,
            source_router=source_router,
            target_router=target_router,
            target_address=target_address,
            target_interface=target_interface,
            target_prefix=target_prefix,
            target_component=target_component,
            related_hypothesis_id=related_hypothesis_id,
            related_fault_type=related_fault_type,
            selection_reason=selection_reason,
            discriminating_outcomes=discriminating_outcomes,
            safety_status=ProbeSafetyStatus.SAFE,
            safety_rationale="Initial proposal awaiting policy check",
            cost=cost,
            priority_score=score,
            ranking_rationale=rationale,
            execution_authorization=ExecutionAuthorizationState.PROPOSED_NOT_EXECUTED,
        )

    def _deduplicate_probes(self, probes: list[PlannedProbe]) -> list[PlannedProbe]:
        """Deduplicate probes targeting the identical check, keeping highest priority score."""
        seen: dict[tuple, PlannedProbe] = {}
        for p in probes:
            key = (
                p.probe_type,
                p.source_router,
                p.target_router,
                p.target_interface,
                p.target_address,
                p.target_prefix,
            )
            if key not in seen or p.priority_score > seen[key].priority_score:
                seen[key] = p
        return list(seen.values())

    def plan_snapshot_dict(self, snapshot: dict[str, Any]) -> list[ProbePlanReport]:
        """Convenience entry point for neutral snapshots (offline evaluation)."""
        EvidenceNormalizer.assert_no_ground_truth_leakage(snapshot)
        topology = Topology.model_validate(snapshot["topology"])
        records = [EvidenceNormalizer.deserialize_record(r) for r in snapshot["evidence_records"]]
        records = decode_state_tags(records, topology)

        w_start = datetime.fromisoformat(snapshot["collection_window_start"].replace("Z", "+00:00"))
        w_end = datetime.fromisoformat(snapshot["collection_window_end"].replace("Z", "+00:00"))

        from app.diagnosis.engine import DiagnosisEngine
        from app.verification.engine import CounterfactualVerificationEngine

        diag_engine = DiagnosisEngine()
        verif_engine = CounterfactualVerificationEngine()

        try:
            diag_results = diag_engine.diagnose_snapshot_dict(snapshot)
        except Exception:
            from app.schemas.incident import Incident, IncidentEvidenceReference

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
            diag_results = [diag_engine.diagnose(incident, records, topology)]

        reports: list[ProbePlanReport] = []

        for dr in diag_results:
            verif_report = verif_engine.verify_diagnosis(
                diagnosis=dr,
                evidence=records,
                topology=topology,
                incident_window=(w_start, w_end),
            )
            plan = self.plan_probes(
                diagnosis=dr,
                verification_report=verif_report,
                evidence=records,
                topology=topology,
                snapshot_id=snapshot.get("snapshot_id"),
            )
            reports.append(plan)

        return reports
