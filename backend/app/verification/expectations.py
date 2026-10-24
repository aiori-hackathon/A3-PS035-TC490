"""
Topology-aware counterfactual expectation models for NEXORA.

Generates explicit, falsifiable predictions for what network telemetry WOULD
look like if a given fault hypothesis were active on the network.
"""

from __future__ import annotations

from app.schemas.counterfactual import (
    Criticality,
    ExpectationCategory,
    ExpectedObservation,
)
from app.schemas.hypothesis import FaultHypothesis, FaultType
from app.schemas.topology import NetworkLink, Topology


class ExpectationGenerator:
    """Generates topology-aware counterfactual expectations for any candidate hypothesis."""

    def generate_expectations(
        self,
        hypothesis: FaultHypothesis,
        topology: Topology,
    ) -> list[ExpectedObservation]:
        """Produce expected observations for the hypothesis given the network topology."""
        fault_type = hypothesis.fault_type
        target_id = hypothesis.fault_location.component_id

        if fault_type == FaultType.LINK_FAILURE:
            return self._expectations_link_failure(target_id, topology)
        elif fault_type == FaultType.ROUTER_FAILURE:
            return self._expectations_router_failure(target_id, topology)
        elif fault_type == FaultType.OSPF_CONFIGURATION_MISMATCH:
            return self._expectations_ospf_mismatch(target_id, topology)
        elif fault_type == FaultType.PACKET_LOSS:
            return self._expectations_packet_loss(target_id, topology)
        elif fault_type == FaultType.HIGH_LATENCY:
            return self._expectations_high_latency(target_id, topology)
        else:
            raise ValueError(f"Unsupported fault type for expectation generation: {fault_type}")

    def _get_link(self, link_id: str, topology: Topology) -> NetworkLink:
        for link in topology.links:
            if link.link_id == link_id:
                return link
        raise ValueError(f"Link '{link_id}' not found in topology")

    def _expectations_link_failure(
        self,
        link_id: str,
        topology: Topology,
    ) -> list[ExpectedObservation]:
        link = self._get_link(link_id, topology)
        endpoint_desc = (
            f"{link.router_a}:{link.interface_a}/{link.router_b}:{link.interface_b}"
        )
        return [
            ExpectedObservation(
                expectation_id=f"exp-lf-{link_id.lower()}-iface-endpoint-down",
                category=ExpectationCategory.INTERFACE_STATE,
                target_component=link_id,
                target_endpoint=endpoint_desc,
                expected_condition="Physical interface observed DOWN on affected endpoint",
                criticality=Criticality.REQUIRED,
                rationale=(
                    f"Physical link failure disrupts carrier on at least one endpoint of {link_id}"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-lf-{link_id.lower()}-ospf-down",
                category=ExpectationCategory.OSPF_ADJACENCY,
                target_component=link_id,
                target_endpoint=f"{link.router_a}<->{link.router_b}",
                expected_condition="OSPF adjacency loss (non-FULL on at least one peer endpoint)",
                criticality=Criticality.REQUIRED,
                rationale=(
                    "Loss of physical layer prevents OSPF hello exchange; "
                    "dead-timer lag may briefly delay peer detection"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-lf-{link_id.lower()}-ping-unreachable",
                category=ExpectationCategory.PACKET_LOSS,
                target_component=link_id,
                target_endpoint=f"{link.address_a}<->{link.address_b}",
                expected_condition="Direct ping reachability fails (100% packet loss)",
                criticality=Criticality.CONFIRMATORY,
                rationale="Frames cannot traverse a severed physical link",
            ),
        ]

    def _expectations_router_failure(
        self,
        router_id: str,
        topology: Topology,
    ) -> list[ExpectedObservation]:
        router = next((r for r in topology.routers if r.router_id == router_id), None)
        if not router:
            raise ValueError(f"Router '{router_id}' not found in topology")

        incident_links = [
            link for link in topology.links if router_id in (link.router_a, link.router_b)
        ]

        expectations: list[ExpectedObservation] = [
            ExpectedObservation(
                expectation_id=f"exp-rf-{router_id.lower()}-unavailable",
                category=ExpectationCategory.ROUTER_AVAILABILITY,
                target_component=router_id,
                target_endpoint=None,
                expected_condition="Router unavailable / unresponsive to telemetry collection",
                criticality=Criticality.REQUIRED,
                rationale=(
                    f"A crashed or stopped router ({router_id}) cannot execute commands "
                    "or respond to management polls"
                ),
            ),
        ]

        # Peer OSPF loss for all incident links
        for link in incident_links:
            peer = link.router_b if link.router_a == router_id else link.router_a
            expectations.append(
                ExpectedObservation(
                    expectation_id=f"exp-rf-{router_id.lower()}-ospf-{peer.lower()}-down",
                    category=ExpectationCategory.OSPF_ADJACENCY,
                    target_component=link.link_id,
                    target_endpoint=f"{peer}->{router_id}",
                    expected_condition=f"Peer router {peer} loses OSPF adjacency to {router_id}",
                    criticality=Criticality.REQUIRED,
                    rationale=(
                        f"Absence of OSPF hellos from crashed {router_id} causes "
                        f"neighbor dead-timer expiry on {peer}"
                    ),
                )
            )

        # Loopback unreachable
        if router.loopback_address:
            expectations.append(
                ExpectedObservation(
                    expectation_id=f"exp-rf-{router_id.lower()}-loopback-unreachable",
                    category=ExpectationCategory.PACKET_LOSS,
                    target_component=router_id,
                    target_endpoint=router.loopback_address,
                    expected_condition=(
                        f"Ping to loopback {router.loopback_address} fails (100% packet loss)"
                    ),
                    criticality=Criticality.CONFIRMATORY,
                    rationale=f"Host network stack is offline on crashed router {router_id}",
                )
            )

        return expectations

    def _expectations_ospf_mismatch(
        self,
        link_id: str,
        topology: Topology,
    ) -> list[ExpectedObservation]:
        link = self._get_link(link_id, topology)
        return [
            ExpectedObservation(
                expectation_id=f"exp-om-{link_id.lower()}-iface-a-up",
                category=ExpectationCategory.INTERFACE_STATE,
                target_component=link.router_a,
                target_endpoint=link.interface_a,
                expected_condition="Interface observed UP",
                criticality=Criticality.REQUIRED,
                rationale=(
                    "Configuration mismatch is a control-plane defect; "
                    f"physical carrier on {link.router_a} remains UP"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-om-{link_id.lower()}-iface-b-up",
                category=ExpectationCategory.INTERFACE_STATE,
                target_component=link.router_b,
                target_endpoint=link.interface_b,
                expected_condition="Interface observed UP",
                criticality=Criticality.REQUIRED,
                rationale=(
                    "Configuration mismatch is a control-plane defect; "
                    f"physical carrier on {link.router_b} remains UP"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-om-{link_id.lower()}-ospf-nonfull",
                category=ExpectationCategory.OSPF_ADJACENCY,
                target_component=link_id,
                target_endpoint=f"{link.router_a}<->{link.router_b}",
                expected_condition="OSPF adjacency non-FULL (DOWN, Init, 2-Way, or missing)",
                criticality=Criticality.REQUIRED,
                rationale=(
                    "Incompatible timer/area parameters prevent OSPF "
                    "state machine convergence to Full"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-om-{link_id.lower()}-dataplane-reachable",
                category=ExpectationCategory.PACKET_LOSS,
                target_component=link_id,
                target_endpoint=f"{link.address_a}<->{link.address_b}",
                expected_condition="Direct IP ping reachability succeeds (packet loss < 100%)",
                criticality=Criticality.CONFIRMATORY,
                rationale=(
                    "Data plane and IP interfaces remain functional "
                    "despite control plane protocol mismatch"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-om-{link_id.lower()}-param-discrepancy",
                category=ExpectationCategory.CONFIGURATION_PARAM,
                target_component=link_id,
                target_endpoint=f"{link.router_a}<->{link.router_b}",
                expected_condition=(
                    "Direct disagreement in hello/dead timers or area configuration"
                ),
                criticality=Criticality.CONFIRMATORY,
                rationale="Inspection of router interface timers proves parameter incompatibility",
            ),
        ]

    def _expectations_packet_loss(
        self,
        link_id: str,
        topology: Topology,
    ) -> list[ExpectedObservation]:
        link = self._get_link(link_id, topology)
        return [
            ExpectedObservation(
                expectation_id=f"exp-pl-{link_id.lower()}-iface-a-up",
                category=ExpectationCategory.INTERFACE_STATE,
                target_component=link.router_a,
                target_endpoint=link.interface_a,
                expected_condition="Interface observed UP",
                criticality=Criticality.REQUIRED,
                rationale=(
                    "Link packet loss occurs over an active physical medium; "
                    f"{link.router_a} {link.interface_a} remains UP"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-pl-{link_id.lower()}-iface-b-up",
                category=ExpectationCategory.INTERFACE_STATE,
                target_component=link.router_b,
                target_endpoint=link.interface_b,
                expected_condition="Interface observed UP",
                criticality=Criticality.REQUIRED,
                rationale=(
                    "Link packet loss occurs over an active physical medium; "
                    f"{link.router_b} {link.interface_b} remains UP"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-pl-{link_id.lower()}-loss-measured",
                category=ExpectationCategory.PACKET_LOSS,
                target_component=link_id,
                target_endpoint=f"{link.address_a}<->{link.address_b}",
                expected_condition="Measured partial packet loss (5.0% <= loss < 100.0%)",
                criticality=Criticality.REQUIRED,
                rationale=(
                    "Stochastic or congestion-induced packet dropping "
                    "manifests as partial packet loss"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-pl-{link_id.lower()}-rtt-normal",
                category=ExpectationCategory.RTT_LATENCY,
                target_component=link_id,
                target_endpoint=f"{link.address_a}<->{link.address_b}",
                expected_condition=(
                    "RTT on successfully received packets within normal bounds (< 10.0ms)"
                ),
                criticality=Criticality.CONFIRMATORY,
                rationale=(
                    "Packet dropping without queueing delay maintains "
                    "normal round-trip transit times"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-pl-{link_id.lower()}-ospf-full",
                category=ExpectationCategory.OSPF_ADJACENCY,
                target_component=link_id,
                target_endpoint=f"{link.router_a}<->{link.router_b}",
                expected_condition="OSPF adjacency remains FULL",
                criticality=Criticality.CONFIRMATORY,
                rationale=(
                    "Moderate packet loss allows sufficient hellos to refresh adjacency "
                    "before dead timer expiry"
                ),
            ),
        ]

    def _expectations_high_latency(
        self,
        link_id: str,
        topology: Topology,
    ) -> list[ExpectedObservation]:
        link = self._get_link(link_id, topology)
        return [
            ExpectedObservation(
                expectation_id=f"exp-hl-{link_id.lower()}-iface-a-up",
                category=ExpectationCategory.INTERFACE_STATE,
                target_component=link.router_a,
                target_endpoint=link.interface_a,
                expected_condition="Interface observed UP",
                criticality=Criticality.REQUIRED,
                rationale=(
                    "Queueing delay occurs across an operational physical interface on "
                    f"{link.router_a} {link.interface_a}"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-hl-{link_id.lower()}-iface-b-up",
                category=ExpectationCategory.INTERFACE_STATE,
                target_component=link.router_b,
                target_endpoint=link.interface_b,
                expected_condition="Interface observed UP",
                criticality=Criticality.REQUIRED,
                rationale=(
                    "Queueing delay occurs across an operational physical interface on "
                    f"{link.router_b} {link.interface_b}"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-hl-{link_id.lower()}-rtt-elevated",
                category=ExpectationCategory.RTT_LATENCY,
                target_component=link_id,
                target_endpoint=f"{link.address_a}<->{link.address_b}",
                expected_condition="Measured round-trip time is elevated (average RTT >= 10.0ms)",
                criticality=Criticality.REQUIRED,
                rationale=(
                    "Netem queueing or buffering increases end-to-end packet propagation delay"
                ),
            ),
            ExpectedObservation(
                expectation_id=f"exp-hl-{link_id.lower()}-loss-low",
                category=ExpectationCategory.PACKET_LOSS,
                target_component=link_id,
                target_endpoint=f"{link.address_a}<->{link.address_b}",
                expected_condition="Packet loss remains negligible (< 5.0%)",
                criticality=Criticality.CONFIRMATORY,
                rationale="Pure propagation delay queues and delays packets without dropping them",
            ),
            ExpectedObservation(
                expectation_id=f"exp-hl-{link_id.lower()}-ospf-full",
                category=ExpectationCategory.OSPF_ADJACENCY,
                target_component=link_id,
                target_endpoint=f"{link.router_a}<->{link.router_b}",
                expected_condition="OSPF adjacency remains FULL",
                criticality=Criticality.CONFIRMATORY,
                rationale=(
                    "Sub-second or bounded latency does not exceed the 40-second OSPF dead timer"
                ),
            ),
        ]
