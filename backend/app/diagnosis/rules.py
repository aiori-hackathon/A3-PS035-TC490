"""Bounded evidence-family rules. Scores are heuristic alignment, not probabilities."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.diagnosis.evidence import EvidenceContext
from app.schemas.evidence import EvidenceRecord
from app.schemas.hypothesis import FaultHypothesis, FaultType


@dataclass
class RuleTrace:
    score: float = 0.0
    supporting: set[str] = field(default_factory=set)
    contradicting: set[str] = field(default_factory=set)
    trace: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def apply(self, weight: float, records: list[EvidenceRecord], explanation: str) -> None:
        if not records:
            return
        ids = sorted({r.evidence_id for r in records})
        self.score += weight
        (self.supporting if weight >= 0 else self.contradicting).update(ids)
        # Keep traces bounded under alarm storms while retaining all IDs in fields.
        refs = ", ".join(ids[:8]) + (f", … ({len(ids)} IDs total)" if len(ids) > 8 else "")
        self.trace.append(f"{weight:+.2f}: {explanation} Evidence: [{refs}].")

    def finish(self, hypothesis: FaultHypothesis) -> FaultHypothesis:
        return hypothesis.model_copy(
            update={
                "rule_score": round(max(0.0, min(1.0, self.score)), 6),
                "supporting_evidence_ids": sorted(self.supporting - self.contradicting),
                "contradictory_evidence_ids": sorted(self.contradicting),
                "missing_evidence_descriptions": sorted(set(self.missing)),
                "reasoning_trace": self.trace,
                "counterfactual_verified": None,
            }
        )


def score_hypothesis(hypothesis: FaultHypothesis, ctx: EvidenceContext) -> FaultHypothesis:
    """Each rule is applied once per candidate, regardless of alarm/poll counts.

    Interface -> adjacency -> route withdrawal are dependent: adjacency can add
    only 0.15 to a physical failure; route/log volume adds zero. No scoring uses
    correlation edge counts or preexisting hypothesis scores/evidence references.
    """
    location = hypothesis.fault_location.component_id
    kind = hypothesis.fault_type
    result = RuleTrace()
    if kind == FaultType.ROUTER_FAILURE:
        unavailable = ctx.unavailable.get(location, [])
        failures = ctx.failures.get(location, [])
        result.apply(
            0.55 if unavailable else 0.15,
            unavailable or failures,
            "Router availability family (all collector failures capped together).",
        )
        incident_links = [link for link in ctx.links.values() if location in ctx.endpoints(link)]
        peer_losses = [
            r
            for link in incident_links
            for r in ctx.adjacencies[link.link_id]
            if r.source_router != location and ctx.adjacency_state(r) == "down"
        ]
        lost_links = {ctx.link_between(r.source_router, location) for r in peer_losses}
        if len(incident_links) >= 2 and len(lost_links) == len(incident_links):
            result.apply(0.30, peer_losses, "All incident links lost at independent peers.")
        elif peer_losses:
            result.apply(
                0.10, peer_losses, "Some peer adjacencies lost; router outage unconfirmed."
            )
            result.missing.append("Loss of adjacencies at every peer of the suspected router.")
        local_down = [
            r
            for link in incident_links
            for r in ctx.interfaces[link.link_id]
            if r.source_router == location and ctx.interface_state(r) == "down"
        ]
        if len({r.source_interface for r in local_down}) == len(incident_links) >= 2:
            result.apply(0.20, local_down, "All observed data interfaces are down.")
        lost_probes = [
            r
            for r in ctx.pings
            if r.packet_loss_pct == 100 and ctx.address_router.get(r.target_address) == location
        ]
        result.apply(0.15, lost_probes, "Complete measured reachability loss to this router.")
        # Direct polling of a router proves a response even if one local port is down.
        result.apply(-0.65, ctx.live.get(location, []), "Successful collection from this router.")
        full_peers = [
            r
            for link in incident_links
            for r in ctx.adjacencies[link.link_id]
            if r.source_router != location and ctx.adjacency_state(r) == "full"
        ]
        result.apply(
            -0.15,
            full_peers,
            "Peers still report FULL; may reflect dead-timer lag, but conflicts remain.",
        )
        if not unavailable:
            result.missing.append(
                "Direct router availability observation; timeout alone is unknown."
            )
        if not peer_losses and not lost_probes:
            result.missing.append("Independent peer adjacency or reachability loss corroboration.")
        return result.finish(hypothesis)

    link = ctx.links[location]
    interfaces = ctx.interfaces[location]
    adjacencies = ctx.adjacencies[location]
    down = [r for r in interfaces if ctx.interface_state(r) == "down"]
    up = [r for r in interfaces if ctx.interface_state(r) == "up"]
    bad = [r for r in adjacencies if ctx.adjacency_state(r) not in {"full", "unknown"}]
    full = [r for r in adjacencies if ctx.adjacency_state(r) == "full"]
    both_up = {r.source_router for r in up} == ctx.endpoints(link)
    both_down = {r.source_router for r in down} == ctx.endpoints(link)
    state_conflicts = [r for r in up if r.source_router in {d.source_router for d in down}]

    if kind == FaultType.LINK_FAILURE:
        result.apply(
            0.80 if both_down else 0.70,
            down,
            "Direct physical interface down family; repeated polls add no weight.",
        )
        result.apply(
            0.15 if down else 0.35,
            bad,
            "Adjacency-loss family; dependent on physical state when present.",
        )
        if both_up:
            result.apply(-0.55, up, "Both data interfaces are observed UP.")
        elif state_conflicts:
            result.apply(
                -0.40, state_conflicts, "Conflicting UP/DOWN observation of the same port."
            )
        result.apply(
            -0.10,
            full,
            "FULL adjacency conflicts with persistent link loss; dead-timer lag possible.",
        )
        if not down:
            result.missing.append("Direct down state on at least one endpoint interface.")
    elif kind == FaultType.OSPF_CONFIGURATION_MISMATCH:
        result.apply(0.40, bad, "Non-FULL OSPF adjacency on this topology link.")
        if bad:
            result.apply(
                0.40 if both_up else 0.12,
                up,
                "Physical state family: UP endpoints distinguish protocol from link fault.",
            )
        result.apply(-0.60, down, "Physical interface down explains adjacency loss.")
        same_direction_full = [r for r in full if r.source_router in {b.source_router for b in bad}]
        result.apply(
            -0.40 if same_direction_full else -0.10,
            full,
            "FULL observation conflicts with persistent adjacency mismatch.",
        )
        result.missing.append(
            "Observed OSPF area/hello/dead/authentication parameters to confirm mismatch; "
            "UP plus adjacency loss is a heuristic explanation, not parameter verification."
        )
        if not both_up:
            result.missing.append("UP observations at both physical endpoints.")
    else:
        is_loss = kind == FaultType.PACKET_LOSS
        abnormal = []
        normal = []
        trace_records = []
        for ping in ctx.pings:
            paths = ctx.paths(ping)
            if not any(location in path.links for path in paths):
                continue
            elevated = (
                (5.0 <= ping.packet_loss_pct < 100.0)
                if is_loss
                else (
                    ping.rtt_avg_ms is not None
                    and ping.rtt_avg_ms >= 10.0
                    and ping.packets_received > 0
                )
            )
            if elevated:
                abnormal.append(ping)
                trace_records.extend(
                    ctx.by_id[eid]
                    for path in paths
                    if location in path.links
                    for eid in path.evidence_ids
                )
            elif (
                ping.packet_loss_pct < 5.0
                if is_loss
                else ping.rtt_avg_ms is not None and ping.rtt_avg_ms < 10.0
            ):
                # A normal measurement constrains a link only if every possible
                # path contains it; a healthy alternate path does not refute it.
                if paths and all(location in path.links for path in paths):
                    normal.append(ping)
        result.apply(
            0.65,
            abnormal,
            "Measured partial loss" if is_loss else "Measured elevated round-trip time",
        )
        if abnormal:
            result.apply(0.0, trace_records, "Observed probe path constrains location.")
            if both_up:
                result.apply(0.0, up, "Link remains operational at both endpoints.")
            result.apply(0.0, full, "Routing adjacency remains operational.")
            inferred = any(
                not path.observed
                for ping in abnormal
                for path in ctx.paths(ping)
                if location in path.links
            )
            if inferred:
                result.missing.append(
                    "Probe path is inferred from equal-cost topology paths; collect a complete "
                    "matching traceroute or per-link measurements to verify localisation."
                )
        result.apply(-0.25, normal, "Normal probe on a path necessarily containing this link.")
        result.apply(-0.50, down, "Physical link loss explains the disruption.")
        if not abnormal:
            result.missing.append(
                "Typed partial-loss or RTT measurements on a known topology path."
            )

    # Preserve downstream evidence for audit, with NO additional weight.
    if result.supporting:
        missing_routes = [
            r for r in ctx.routes if not r.is_present and r.source_router in ctx.endpoints(link)
        ]
        result.apply(0.0, missing_routes, "Route absence is downstream context; zero added weight.")
    if not interfaces:
        result.missing.append("Physical interface observations on this link.")
    if not adjacencies:
        result.missing.append("OSPF adjacency observations on this link.")
    return result.finish(hypothesis)
