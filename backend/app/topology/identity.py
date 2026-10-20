"""
NEXORA router identity mapping and validation utilities (Phase 05).

Provides validated bidirectional mappings between:
  - Stable router IDs (e.g. 'R1') — human-readable labels
  - OSPF Router-IDs (e.g. '1.1.1.1') — dotted-decimal protocol IDs
  - Loopback addresses (e.g. '192.168.255.1') — reachability addresses

IMPORTANT: These are distinct identifiers.
  - OSPF Router-ID: configured in FRR as 'router-id X.X.X.X', appears in
    'show ip ospf neighbor json' as the neighbour key (e.g. "2.2.2.2").
  - Loopback address: the IPv4 address assigned to the loopback interface.
    In the NEXORA lab the loopback address is NOT the same as the OSPF Router-ID.
    OSPF Router-ID: N.N.N.N (e.g. 1.1.1.1)
    Loopback IP:    192.168.255.N (e.g. 192.168.255.1)
  - Link interface address: IP address of a point-to-point link endpoint,
    e.g. '10.0.12.2'. This appears in 'show ip ospf neighbor json' as the
    'address' field.

Phase 04 report used '192.168.255.2' to refer to R2 in one description.
This was imprecise terminology in the report narrative. The OSPFCollector
correctly stores the OSPF Router-ID ('2.2.2.2') in neighbour_router_id,
not the loopback address.

Resolution validated against:
  - lab/configs/r*/frr.conf: router-id N.N.N.N confirms Router-ID values.
  - EXPECTED_ROUTERS_METADATA in topology_collector.py: confirms loopback IPs.
  - EXPECTED_OSPF_NEIGHBOURS in ospf_collector.py: confirms nbr_router_id values.
  - Live FRR JSON: 'show ip ospf neighbor json' keys are OSPF Router-IDs.
"""

from __future__ import annotations

import ipaddress
import re

# ---------------------------------------------------------------------------
# Validated identity mapping tables
# ---------------------------------------------------------------------------

# router_id → OSPF Router-ID (from FRR 'router-id' config)
ROUTER_TO_OSPF_ID: dict[str, str] = {
    "R1": "1.1.1.1",
    "R2": "2.2.2.2",
    "R3": "3.3.3.3",
    "R4": "4.4.4.4",
    "R5": "5.5.5.5",
}

# OSPF Router-ID → router_id (reverse lookup)
OSPF_ID_TO_ROUTER: dict[str, str] = {v: k for k, v in ROUTER_TO_OSPF_ID.items()}

# router_id → loopback IPv4 address (without prefix length)
ROUTER_TO_LOOPBACK_IP: dict[str, str] = {
    "R1": "192.168.255.1",
    "R2": "192.168.255.2",
    "R3": "192.168.255.3",
    "R4": "192.168.255.4",
    "R5": "192.168.255.5",
}

# loopback IP → router_id (reverse lookup)
LOOPBACK_IP_TO_ROUTER: dict[str, str] = {v: k for k, v in ROUTER_TO_LOOPBACK_IP.items()}

# router_id → loopback /32 prefix
ROUTER_TO_LOOPBACK_PREFIX: dict[str, str] = {
    rid: f"{ip}/32" for rid, ip in ROUTER_TO_LOOPBACK_IP.items()
}

# loopback /32 prefix → router_id
LOOPBACK_PREFIX_TO_ROUTER: dict[str, str] = {
    v: k for k, v in ROUTER_TO_LOOPBACK_PREFIX.items()
}

# All known link interface addresses → router_id that owns the address
LINK_ADDRESS_TO_ROUTER: dict[str, str] = {
    "10.0.12.1": "R1",  # R1 eth1
    "10.0.15.2": "R1",  # R1 eth2
    "10.0.12.2": "R2",  # R2 eth1
    "10.0.23.1": "R2",  # R2 eth2
    "10.0.23.2": "R3",  # R3 eth1
    "10.0.34.1": "R3",  # R3 eth2
    "10.0.34.2": "R4",  # R4 eth1
    "10.0.45.1": "R4",  # R4 eth2
    "10.0.45.2": "R5",  # R5 eth1
    "10.0.15.1": "R5",  # R5 eth2
}

# All valid router IDs in the NEXORA lab
VALID_ROUTER_IDS: frozenset[str] = frozenset(ROUTER_TO_OSPF_ID.keys())

# Link address pair → link_id (module-level for N806 compliance)
_LINK_ADDR_PAIR_TO_LINK: dict[tuple[str, str], str] = {
    ("10.0.12.1", "10.0.12.2"): "L12",
    ("10.0.12.2", "10.0.12.1"): "L12",
    ("10.0.23.1", "10.0.23.2"): "L23",
    ("10.0.23.2", "10.0.23.1"): "L23",
    ("10.0.34.1", "10.0.34.2"): "L34",
    ("10.0.34.2", "10.0.34.1"): "L34",
    ("10.0.45.1", "10.0.45.2"): "L45",
    ("10.0.45.2", "10.0.45.1"): "L45",
    ("10.0.15.1", "10.0.15.2"): "L51",
    ("10.0.15.2", "10.0.15.1"): "L51",
}

# Router pair (frozenset) → link_id (module-level for N806 compliance)
_ROUTER_PAIR_LINK_MAP: dict[frozenset, str] = {
    frozenset(["R1", "R2"]): "L12",
    frozenset(["R2", "R3"]): "L23",
    frozenset(["R3", "R4"]): "L34",
    frozenset(["R4", "R5"]): "L45",
    frozenset(["R5", "R1"]): "L51",
}


# ---------------------------------------------------------------------------
# Identity resolution functions
# ---------------------------------------------------------------------------


def resolve_router_from_ospf_id(ospf_router_id: str) -> str | None:
    """
    Resolve a stable router ID from an OSPF Router-ID string.

    Parameters
    ----------
    ospf_router_id : str
        Dotted-decimal OSPF Router-ID, e.g. '2.2.2.2'.

    Returns
    -------
    str | None
        Stable router ID (e.g. 'R2') or None if not recognized.
    """
    return OSPF_ID_TO_ROUTER.get(ospf_router_id)


def resolve_router_from_loopback(address: str) -> str | None:
    """
    Resolve a stable router ID from a loopback IPv4 address.

    Accepts both '192.168.255.2' and '192.168.255.2/32'.

    Parameters
    ----------
    address : str
        Loopback IP address (with or without /32 prefix).

    Returns
    -------
    str | None
        Stable router ID or None if not a known loopback.
    """
    stripped = address.split("/")[0].strip()
    result = LOOPBACK_IP_TO_ROUTER.get(stripped)
    if result:
        return result
    # Try with /32 suffix
    return LOOPBACK_PREFIX_TO_ROUTER.get(address)


def resolve_router_from_any_address(address: str) -> str | None:
    """
    Attempt to identify a router from any known address type.

    Checks (in order):
    1. OSPF Router-ID (e.g. '2.2.2.2')
    2. Loopback IPv4 address (e.g. '192.168.255.2')
    3. Link interface address (e.g. '10.0.23.1')
    4. Loopback /32 prefix (e.g. '192.168.255.2/32')

    Parameters
    ----------
    address : str
        Any IPv4 address or prefix string.

    Returns
    -------
    str | None
        Stable router ID or None if unresolvable.

    Note
    ----
    Never guesses. If the address is not in any known mapping, returns None.
    """
    stripped = address.split("/")[0].strip()

    # OSPF Router-ID check
    if stripped in OSPF_ID_TO_ROUTER:
        return OSPF_ID_TO_ROUTER[stripped]

    # Loopback IP check
    if stripped in LOOPBACK_IP_TO_ROUTER:
        return LOOPBACK_IP_TO_ROUTER[stripped]

    # Link address check
    if stripped in LINK_ADDRESS_TO_ROUTER:
        return LINK_ADDRESS_TO_ROUTER[stripped]

    # Prefix form
    if "/" in address:
        prefix_no_mask = address.split("/")[0]
        if prefix_no_mask in LOOPBACK_IP_TO_ROUTER:
            return LOOPBACK_IP_TO_ROUTER[prefix_no_mask]

    return None


def is_valid_router_id(router_id: str) -> bool:
    """Return True if router_id is a recognized stable NEXORA router ID."""
    return router_id in VALID_ROUTER_IDS


def get_ospf_id(router_id: str) -> str:
    """
    Return the OSPF Router-ID for a stable router ID.

    Raises
    ------
    KeyError
        If router_id is not a recognized NEXORA router.
    """
    if router_id not in ROUTER_TO_OSPF_ID:
        raise KeyError(f"Unknown router_id {router_id!r}. Valid: {sorted(VALID_ROUTER_IDS)}")
    return ROUTER_TO_OSPF_ID[router_id]


def get_loopback_ip(router_id: str) -> str:
    """
    Return the loopback IPv4 address (no mask) for a stable router ID.

    Raises
    ------
    KeyError
        If router_id is not a recognized NEXORA router.
    """
    if router_id not in ROUTER_TO_LOOPBACK_IP:
        raise KeyError(f"Unknown router_id {router_id!r}. Valid: {sorted(VALID_ROUTER_IDS)}")
    return ROUTER_TO_LOOPBACK_IP[router_id]


def validate_identity_mapping() -> dict[str, dict]:
    """
    Return the complete validated identity mapping table for all routers.

    Used for documentation and test assertion. Confirms:
    - OSPF Router-ID uses N.N.N.N format (N is 1-5 in this lab).
    - Loopback uses 192.168.255.N/32 (N is 1-5).
    - OSPF Router-ID ≠ Loopback IP (they are distinct identifiers).

    Returns
    -------
    dict[str, dict]
        Maps router_id → {ospf_id, loopback_ip, loopback_prefix}.
    """
    result: dict[str, dict] = {}
    for rid in sorted(VALID_ROUTER_IDS):
        ospf_id = ROUTER_TO_OSPF_ID[rid]
        lb_ip = ROUTER_TO_LOOPBACK_IP[rid]
        lb_prefix = ROUTER_TO_LOOPBACK_PREFIX[rid]
        result[rid] = {
            "router_id": rid,
            "ospf_router_id": ospf_id,
            "loopback_ip": lb_ip,
            "loopback_prefix": lb_prefix,
            "ospf_id_ne_loopback": ospf_id != lb_ip,
        }
    return result


def resolve_link_from_address_pair(addr_a: str, addr_b: str) -> str | None:
    """
    Attempt to identify a link_id from two link endpoint addresses.

    Parameters
    ----------
    addr_a : str
        One endpoint address (e.g. '10.0.12.1').
    addr_b : str
        The other endpoint address (e.g. '10.0.12.2').

    Returns
    -------
    str | None
        Link ID (e.g. 'L12') or None if not recognized.
    """
    a = addr_a.split("/")[0].strip()
    b = addr_b.split("/")[0].strip()
    return _LINK_ADDR_PAIR_TO_LINK.get((a, b))


def resolve_link_from_router_pair(router_a: str, router_b: str) -> str | None:
    """
    Return the link_id between two routers, if they are directly connected.

    Parameters
    ----------
    router_a : str
        First router ID (e.g. 'R1').
    router_b : str
        Second router ID (e.g. 'R2').

    Returns
    -------
    str | None
        Link ID or None if routers are not directly connected.
    """
    return _ROUTER_PAIR_LINK_MAP.get(frozenset([router_a, router_b]))


def validate_ospf_id_format(ospf_id: str) -> bool:
    """Return True if ospf_id matches dotted-decimal format x.x.x.x."""
    try:
        ipaddress.IPv4Address(ospf_id)
        return True
    except ValueError:
        return False


def validate_router_id_format(router_id: str) -> bool:
    """Return True if router_id matches the 'R<N>' pattern."""
    return bool(re.match(r"^R[1-9][0-9]*$", router_id))
