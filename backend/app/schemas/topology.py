"""
Topology domain models for the NEXORA diagnostic system.

Defines typed representations of the five-node FRRouting / OSPFv2 network laboratory,
including routers, interfaces, links, adjacencies, and topology snapshots.

These models are evidence-side contracts only; they capture observed or configured
topology state. They do NOT contain fault injection ground-truth labels.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RouterStatus(str, Enum):
    """Observed operational status of a router."""

    UP = "UP"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class InterfaceStatus(str, Enum):
    """Observed operational status of a network interface."""

    UP = "UP"
    DOWN = "DOWN"
    ADMIN_DOWN = "ADMIN_DOWN"
    UNKNOWN = "UNKNOWN"


class OSPFNeighbourState(str, Enum):
    """OSPF adjacency state machine values (RFC 2328, Section 10.1)."""

    DOWN = "DOWN"
    ATTEMPT = "ATTEMPT"
    INIT = "INIT"
    TWO_WAY = "2WAY"
    EXSTART = "EXSTART"
    EXCHANGE = "EXCHANGE"
    LOADING = "LOADING"
    FULL = "FULL"
    UNKNOWN = "UNKNOWN"


class ObservationStatus(str, Enum):
    """Status of an individual observation attempt.

    A missing observation MUST NOT be automatically interpreted as a failure.
    Missing data must be represented explicitly.
    """

    OBSERVED = "OBSERVED"
    UNKNOWN = "UNKNOWN"
    NOT_COLLECTED = "NOT_COLLECTED"
    COLLECTION_FAILED = "COLLECTION_FAILED"


# ---------------------------------------------------------------------------
# Validated IP type aliases
# ---------------------------------------------------------------------------


def _parse_ipv4_interface(value: str) -> str:
    """Validate and normalise an IPv4 interface address with prefix length."""
    try:
        iface = ipaddress.IPv4Interface(value)
    except ValueError as exc:
        raise ValueError(f"Invalid IPv4 interface address: {value!r}") from exc
    return str(iface)


def _parse_ipv4_address(value: str) -> str:
    """Validate a plain IPv4 address."""
    try:
        ipaddress.IPv4Address(value)
    except ValueError as exc:
        raise ValueError(f"Invalid IPv4 address: {value!r}") from exc
    return value


# ---------------------------------------------------------------------------
# Core topology models
# ---------------------------------------------------------------------------


class NetworkInterface(BaseModel):
    """A single network interface on a router."""

    model_config = ConfigDict(extra="forbid")

    interface_name: str = Field(
        description="Kernel interface name (e.g. 'eth1', 'lo', 'mgmt0').",
        min_length=1,
        max_length=15,
    )
    ipv4_address: str | None = Field(
        default=None,
        description="IPv4 address with prefix length (e.g. '10.0.12.1/30').",
    )
    status: InterfaceStatus = Field(
        default=InterfaceStatus.UNKNOWN,
        description="Observed operational status of this interface.",
    )
    is_ospf_passive: bool = Field(
        default=False,
        description="True if this interface is declared passive in OSPF "
        "(hellos neither sent nor received).",
    )
    ospf_area: str | None = Field(
        default=None,
        description="OSPF area this interface belongs to (e.g. '0.0.0.0'). "
        "None if not participating in OSPF.",
    )

    @field_validator("ipv4_address", mode="before")
    @classmethod
    def validate_ipv4_address(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _parse_ipv4_interface(v)


class Router(BaseModel):
    """A single FRRouting router node in the experimental topology."""

    model_config = ConfigDict(extra="forbid")

    router_id: str = Field(
        description="Stable human-readable router identifier (e.g. 'R1').",
        pattern=r"^R[1-9][0-9]*$",
    )
    ospf_router_id: str = Field(
        description="OSPF Router-ID in dotted-decimal notation (e.g. '1.1.1.1').",
    )
    loopback_address: str = Field(
        description="Loopback IPv4 address with /32 prefix (e.g. '192.168.255.1/32').",
    )
    role: str = Field(
        description="Human-readable role description (e.g. 'Core Gateway').",
        min_length=1,
        max_length=64,
    )
    status: RouterStatus = Field(
        default=RouterStatus.UNKNOWN,
        description="Observed operational status of this router.",
    )
    interfaces: list[NetworkInterface] = Field(
        default_factory=list,
        description="All network interfaces on this router.",
    )

    @field_validator("ospf_router_id", mode="before")
    @classmethod
    def validate_ospf_router_id(cls, v: str) -> str:
        return _parse_ipv4_address(v)

    @field_validator("loopback_address", mode="before")
    @classmethod
    def validate_loopback_address(cls, v: str) -> str:
        parsed = _parse_ipv4_interface(v)
        # Loopback addresses must be /32
        iface = ipaddress.IPv4Interface(parsed)
        if iface.network.prefixlen != 32:
            raise ValueError(f"Loopback address must be /32, got /{iface.network.prefixlen}")
        return parsed

    @model_validator(mode="after")
    def validate_no_duplicate_interface_names(self) -> Router:
        names = [iface.interface_name for iface in self.interfaces]
        if len(names) != len(set(names)):
            raise ValueError(f"Router {self.router_id} has duplicate interface names: {names}")
        return self


class NetworkLink(BaseModel):
    """A point-to-point link between two routers."""

    model_config = ConfigDict(extra="forbid")

    link_id: str = Field(
        description="Stable link identifier (e.g. 'L12' for the R1–R2 link).",
        pattern=r"^L[0-9]{2,}$",
    )
    subnet: str = Field(
        description="IPv4 /30 subnet for this point-to-point link (e.g. '10.0.12.0/30').",
    )
    router_a: str = Field(
        description="Router-ID of the first endpoint.",
        pattern=r"^R[1-9][0-9]*$",
    )
    interface_a: str = Field(
        description="Interface name on router_a for this link.",
        min_length=1,
        max_length=15,
    )
    address_a: str = Field(
        description="IPv4 address (with prefix) assigned to router_a's interface.",
    )
    router_b: str = Field(
        description="Router-ID of the second endpoint.",
        pattern=r"^R[1-9][0-9]*$",
    )
    interface_b: str = Field(
        description="Interface name on router_b for this link.",
        min_length=1,
        max_length=15,
    )
    address_b: str = Field(
        description="IPv4 address (with prefix) assigned to router_b's interface.",
    )
    ospf_cost: int = Field(
        default=1,
        ge=1,
        le=65535,
        description="OSPF link cost. Default 1 (reference-bandwidth = 100Mbps, "
        "10Gbps virtual links).",
    )

    @field_validator("subnet", mode="before")
    @classmethod
    def validate_subnet(cls, v: str) -> str:
        try:
            net = ipaddress.IPv4Network(v, strict=True)
        except ValueError as exc:
            raise ValueError(f"Invalid IPv4 subnet: {v!r}") from exc
        if net.prefixlen != 30:
            raise ValueError(f"P2P link subnets must be /30; got /{net.prefixlen} for {v!r}")
        return str(net)

    @field_validator("address_a", "address_b", mode="before")
    @classmethod
    def validate_endpoint_addresses(cls, v: str) -> str:
        return _parse_ipv4_interface(v)

    @model_validator(mode="after")
    def validate_endpoints_differ(self) -> NetworkLink:
        if self.router_a == self.router_b:
            raise ValueError(
                f"Link {self.link_id}: router_a and router_b must differ "
                f"(got both = {self.router_a!r})"
            )
        return self

    @model_validator(mode="after")
    def validate_addresses_in_subnet(self) -> NetworkLink:
        subnet = ipaddress.IPv4Network(self.subnet)
        for label, addr_str in [("address_a", self.address_a), ("address_b", self.address_b)]:
            iface = ipaddress.IPv4Interface(addr_str)
            if iface.ip not in subnet:
                raise ValueError(
                    f"Link {self.link_id}: {label} {addr_str!r} is not in subnet {self.subnet!r}"
                )
        return self


class RoutingAdjacency(BaseModel):
    """An observed OSPF adjacency between two routers."""

    model_config = ConfigDict(extra="forbid")

    local_router: str = Field(description="Router-ID of the local router.")
    neighbour_router: str = Field(description="Router-ID of the OSPF neighbour.")
    local_interface: str = Field(description="Local interface facing the neighbour.")
    neighbour_address: str = Field(description="IP address of the neighbour interface.")
    state: OSPFNeighbourState = Field(
        description="Current OSPF adjacency state.",
        default=OSPFNeighbourState.UNKNOWN,
    )
    observed_at: datetime = Field(
        description="UTC timestamp when this adjacency state was observed.",
    )

    @field_validator("neighbour_address", mode="before")
    @classmethod
    def validate_neighbour_address(cls, v: str) -> str:
        return _parse_ipv4_address(v)


class Topology(BaseModel):
    """A complete snapshot of the experimental network topology.

    This is a versioned, immutable snapshot. New snapshots replace old ones;
    they are never mutated in place. The snapshot_id ties evidence records to
    the topology context in which they were collected.
    """

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(
        description="Unique identifier for this topology snapshot (UUID or timestamp-based).",
        min_length=1,
    )
    captured_at: datetime = Field(
        description="UTC timestamp when this topology snapshot was captured.",
    )
    routers: list[Router] = Field(
        description="All routers in the topology.",
        min_length=1,
    )
    links: list[NetworkLink] = Field(
        description="All point-to-point links in the topology.",
        min_length=1,
    )
    adjacencies: list[RoutingAdjacency] = Field(
        default_factory=list,
        description="Currently observed OSPF adjacencies.",
    )

    @model_validator(mode="after")
    def validate_unique_router_ids(self) -> Topology:
        ids = [r.router_id for r in self.routers]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate router IDs in topology: {ids}")
        return self

    @model_validator(mode="after")
    def validate_unique_link_ids(self) -> Topology:
        ids = [lnk.link_id for lnk in self.links]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate link IDs in topology: {ids}")
        return self

    @model_validator(mode="after")
    def validate_link_endpoints_exist(self) -> Topology:
        router_ids = {r.router_id for r in self.routers}
        for link in self.links:
            if link.router_a not in router_ids:
                raise ValueError(
                    f"Link {link.link_id}: router_a={link.router_a!r} not in topology routers"
                )
            if link.router_b not in router_ids:
                raise ValueError(
                    f"Link {link.link_id}: router_b={link.router_b!r} not in topology routers"
                )
        return self

    @model_validator(mode="after")
    def validate_no_subnet_collisions(self) -> Topology:
        seen: dict[str, str] = {}
        for link in self.links:
            if link.subnet in seen:
                raise ValueError(
                    f"Subnet collision: {link.subnet!r} used by both "
                    f"{seen[link.subnet]} and {link.link_id}"
                )
            seen[link.subnet] = link.link_id
        return self
