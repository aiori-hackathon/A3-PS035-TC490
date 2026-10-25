"""
Safe active probe planning security policy and validation rules for NEXORA.

Enforces fail-closed safety boundaries:
1. Router and link allowlists derived from the approved topology.
2. Protection of management interfaces (eth0) and subnets (172.17.0.0/16).
3. Read-only probe types only; mutation or arbitrary execution strictly forbidden.
4. Bounded timeouts, packet counts, and recommendation budgets.
5. Command injection and untrusted input sanitization.
"""

from __future__ import annotations

import ipaddress
import re

from app.schemas.probe import (
    MAX_PROBE_TIMEOUT_S,
    ProbeCostEstimate,
    ProbeRequest,
    ProbeSafetyStatus,
    ProbeType,
    ResourceImpact,
)
from app.schemas.topology import Topology

DEFAULT_MAX_RECOMMENDED_PROBES = 5
DEFAULT_MAX_COST_BUDGET = 20.0
DEFAULT_MAX_PING_PACKETS = 5
DEFAULT_PROBE_TIMEOUT_S = 5

# Prohibited shell characters to prevent command injection
# Allows arrow notation '->' in descriptions but blocks bare redirection and command chaining
DISALLOWED_METAS = re.compile(r"[;&|`$\n\r]|(?<!-)>|<")

# Default management and infrastructure subnets prohibited from probing
PROTECTED_NETWORKS = [
    ipaddress.ip_network("172.17.0.0/16"),  # Standard Docker bridge management
    ipaddress.ip_network("172.18.0.0/16"),  # Extended Docker bridge
    ipaddress.ip_network("127.0.0.0/8"),   # Loopback host
    ipaddress.ip_network("0.0.0.0/8"),       # Default zero-network
    ipaddress.ip_network("224.0.0.0/4"),     # Multicast
    ipaddress.ip_network("255.255.255.255/32"),  # Broadcast
]

PROTECTED_INTERFACES = frozenset({"eth0", "docker0", "mgmt0", "br-mgmt"})


class ProbeSafetyPolicy:
    """Deterministic, fail-closed safety policy for active probe planning."""

    def __init__(
        self,
        topology: Topology | None = None,
        max_recommended_probes: int = DEFAULT_MAX_RECOMMENDED_PROBES,
        max_cost_budget: float = DEFAULT_MAX_COST_BUDGET,
    ) -> None:
        self.max_recommended_probes = max_recommended_probes
        self.max_cost_budget = max_cost_budget
        self._init_topology_boundaries(topology)

    def _init_topology_boundaries(self, topology: Topology | None) -> None:
        """Derive strict allowlists from approved network topology."""
        if topology is None:
            self.approved_routers: frozenset[str] = frozenset({"R1", "R2", "R3", "R4", "R5"})
            self.approved_links: frozenset[str] = frozenset(
                {"L12", "L14", "L23", "L34", "L45"}
            )
            self.approved_interfaces: dict[str, frozenset[str]] = {
                "R1": frozenset({"eth1", "eth2", "lo"}),
                "R2": frozenset({"eth1", "eth2", "lo"}),
                "R3": frozenset({"eth1", "eth2", "lo"}),
                "R4": frozenset({"eth1", "eth2", "lo"}),
                "R5": frozenset({"eth1", "eth2", "lo"}),
            }
            self.approved_addresses: frozenset[str] = frozenset(
                {
                    "192.168.255.1",
                    "192.168.255.2",
                    "192.168.255.3",
                    "192.168.255.4",
                    "192.168.255.5",
                    "192.168.12.1",
                    "192.168.12.2",
                    "192.168.14.1",
                    "192.168.14.2",
                    "192.168.23.1",
                    "192.168.23.2",
                    "192.168.34.1",
                    "192.168.34.2",
                    "192.168.45.1",
                    "192.168.45.2",
                }
            )
            return

        self.approved_routers = frozenset(r.router_id for r in topology.routers)
        self.approved_links = frozenset(link.link_id for link in topology.links)

        iface_map: dict[str, set[str]] = {r.router_id: {"lo"} for r in topology.routers}
        addresses: set[str] = set()

        for r in topology.routers:
            if r.loopback_address:
                addresses.add(r.loopback_address.split("/")[0])
            for iface in r.interfaces:
                iface_map[r.router_id].add(iface.interface_name)
                addr = getattr(iface, "ipv4_address", None) or getattr(iface, "ip_address", None)
                if addr:
                    addresses.add(str(addr).split("/")[0])

        for link in topology.links:
            if link.address_a:
                addresses.add(link.address_a.split("/")[0])
            if link.address_b:
                addresses.add(link.address_b.split("/")[0])

        self.approved_interfaces = {r_id: frozenset(s) for r_id, s in iface_map.items()}
        self.approved_addresses = frozenset(addresses)

    def validate_request(
        self,
        request: ProbeRequest,
    ) -> tuple[bool, ProbeSafetyStatus, str]:
        """Audit a single probe request against fail-closed safety constraints.

        Returns (is_safe, safety_status, rationale).
        """
        # 1. Sanitize string fields against command injection
        for field_name, value in (
            ("probe_id", request.probe_id),
            ("selection_reason", request.selection_reason),
            ("target_interface", request.target_interface),
            ("target_address", request.target_address),
            ("target_prefix", request.target_prefix),
        ):
            if value and DISALLOWED_METAS.search(value):
                return (
                    False,
                    ProbeSafetyStatus.POLICY_VIOLATION,
                    f"Command injection metacharacter detected in field {field_name}",
                )

        # 2. Router allowlist validation
        if request.source_router not in self.approved_routers:
            return (
                False,
                ProbeSafetyStatus.UNSAFE,
                f"Source router {request.source_router} is not in approved topology allowlist",
            )

        if request.target_router and request.target_router not in self.approved_routers:
            return (
                False,
                ProbeSafetyStatus.UNSAFE,
                f"Target router {request.target_router} is not in approved topology allowlist",
            )

        # 3. Timeout bounds validation
        if not (1 <= request.timeout_s <= MAX_PROBE_TIMEOUT_S):
            return (
                False,
                ProbeSafetyStatus.POLICY_VIOLATION,
                f"Timeout {request.timeout_s}s exceeds allowed range [1, {MAX_PROBE_TIMEOUT_S}]",
            )

        # 4. Probe-type-specific checks
        ptype = request.probe_type

        if ptype == ProbeType.INTERFACE_STATE:
            iface = request.target_interface
            if not iface:
                return False, ProbeSafetyStatus.UNSAFE, "Missing target interface"
            if iface in PROTECTED_INTERFACES:
                return (
                    False,
                    ProbeSafetyStatus.POLICY_VIOLATION,
                    f"Target interface {iface} is a protected management interface",
                )
            allowed_router_ifaces = self.approved_interfaces.get(
                request.source_router, frozenset()
            )
            if iface not in allowed_router_ifaces:
                return (
                    False,
                    ProbeSafetyStatus.UNSAFE,
                    f"Interface {iface} is not known on router {request.source_router}",
                )

        elif ptype in (ProbeType.PING, ProbeType.TRACEROUTE):
            addr_str = request.target_address
            if not addr_str:
                return False, ProbeSafetyStatus.UNSAFE, f"Missing target address for {ptype.value}"
            # Extract plain IP
            plain_ip = addr_str.split("/")[0]
            try:
                ip_obj = ipaddress.ip_address(plain_ip)
            except ValueError:
                return False, ProbeSafetyStatus.UNSAFE, f"Invalid IPv4 target address: {plain_ip}"

            # Check protected management subnets
            for protected_net in PROTECTED_NETWORKS:
                if ip_obj in protected_net:
                    return (
                        False,
                        ProbeSafetyStatus.POLICY_VIOLATION,
                        f"Target address {plain_ip} is in protected subnet {protected_net}",
                    )

            # Check topology address allowlist
            if plain_ip not in self.approved_addresses:
                return (
                    False,
                    ProbeSafetyStatus.UNSAFE,
                    f"Target address {plain_ip} is outside approved network topology",
                )

        elif ptype == ProbeType.OSPF_NEIGHBOUR:
            target_r = request.target_router
            if not target_r:
                return False, ProbeSafetyStatus.UNSAFE, "OSPF neighbor probe requires target_router"
            if target_r == request.source_router:
                return (
                    False,
                    ProbeSafetyStatus.UNSAFE,
                    "Source and target router cannot be identical",
                )

        elif ptype == ProbeType.ROUTING_TABLE:
            prefix_str = request.target_prefix
            if not prefix_str:
                return False, ProbeSafetyStatus.UNSAFE, "Routing table probe requires target_prefix"
            try:
                net = ipaddress.ip_network(prefix_str, strict=False)
            except ValueError:
                return False, ProbeSafetyStatus.UNSAFE, f"Invalid IPv4 prefix: {prefix_str}"
            # Ensure not querying management network
            for protected_net in PROTECTED_NETWORKS:
                if net.overlaps(protected_net):
                    return (
                        False,
                        ProbeSafetyStatus.POLICY_VIOLATION,
                        f"Target prefix {prefix_str} overlaps protected subnet {protected_net}",
                    )

        else:
            return (
                False,
                ProbeSafetyStatus.UNSUPPORTED_CAPABILITY,
                f"Unsupported probe type: {ptype}",
            )

        return (
            True,
            ProbeSafetyStatus.SAFE,
            "Read-only diagnostic query within approved topology bounds; fail-closed verified",
        )

    def estimate_cost(self, probe_type: ProbeType, timeout_s: int = 5) -> ProbeCostEstimate:
        """Calculate deterministic operational overhead estimate."""
        if probe_type == ProbeType.INTERFACE_STATE:
            return ProbeCostEstimate(
                packet_count=1,
                timeout_s=min(timeout_s, 2),
                estimated_rtt_overhead_ms=5.0,
                resource_impact=ResourceImpact.LOW,
                relative_cost_score=1.0,
            )
        if probe_type == ProbeType.ROUTING_TABLE:
            return ProbeCostEstimate(
                packet_count=1,
                timeout_s=min(timeout_s, 3),
                estimated_rtt_overhead_ms=10.0,
                resource_impact=ResourceImpact.LOW,
                relative_cost_score=1.5,
            )
        if probe_type == ProbeType.OSPF_NEIGHBOUR:
            return ProbeCostEstimate(
                packet_count=1,
                timeout_s=min(timeout_s, 3),
                estimated_rtt_overhead_ms=15.0,
                resource_impact=ResourceImpact.LOW,
                relative_cost_score=2.0,
            )
        if probe_type == ProbeType.PING:
            return ProbeCostEstimate(
                packet_count=DEFAULT_MAX_PING_PACKETS,
                timeout_s=min(timeout_s, 5),
                estimated_rtt_overhead_ms=50.0,
                resource_impact=ResourceImpact.MEDIUM,
                relative_cost_score=3.0,
            )
        if probe_type == ProbeType.TRACEROUTE:
            return ProbeCostEstimate(
                packet_count=9,
                timeout_s=min(timeout_s, 10),
                estimated_rtt_overhead_ms=150.0,
                resource_impact=ResourceImpact.HIGH,
                relative_cost_score=5.0,
            )
        # Default fallback
        return ProbeCostEstimate(
            packet_count=1,
            timeout_s=timeout_s,
            estimated_rtt_overhead_ms=50.0,
            resource_impact=ResourceImpact.LOW,
            relative_cost_score=2.5,
        )
