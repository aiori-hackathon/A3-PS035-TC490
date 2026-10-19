"""
NEXORA Phase 02 — Lab Integration Tests
Team: A3-PS035-TC490 | PS-035

These tests verify the live NEXORA Docker Compose lab is correctly deployed
and matches the Phase 01 topology specification.

Prerequisites:
  - NEXORA lab must be running: `cd lab && ./lab.sh up`
  - Docker must be accessible from the test environment

Run with:
  cd backend && uv run pytest tests/test_lab_integration.py -v --timeout=120

Skip in CI (no Docker): pytest mark `lab_integration`
"""

import json
import subprocess
import time
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Constants matching Phase 01 topology spec
# ---------------------------------------------------------------------------

CONTAINERS = ["nexora-r1", "nexora-r2", "nexora-r3", "nexora-r4", "nexora-r5"]

EXPECTED_LOOPBACKS = {
    "nexora-r1": "192.168.255.1",
    "nexora-r2": "192.168.255.2",
    "nexora-r3": "192.168.255.3",
    "nexora-r4": "192.168.255.4",
    "nexora-r5": "192.168.255.5",
}

EXPECTED_ETH1_IPS = {
    "nexora-r1": "10.0.12.1",
    "nexora-r2": "10.0.12.2",
    "nexora-r3": "10.0.23.2",
    "nexora-r4": "10.0.34.2",
    "nexora-r5": "10.0.45.2",
}

EXPECTED_ETH2_IPS = {
    "nexora-r1": "10.0.15.2",
    "nexora-r2": "10.0.23.1",
    "nexora-r3": "10.0.34.1",
    "nexora-r4": "10.0.45.1",
    "nexora-r5": "10.0.15.1",
}

# OSPF Router-IDs
EXPECTED_ROUTER_IDS = {
    "nexora-r1": "1.1.1.1",
    "nexora-r2": "2.2.2.2",
    "nexora-r3": "3.3.3.3",
    "nexora-r4": "4.4.4.4",
    "nexora-r5": "5.5.5.5",
}

# Expected OSPF adjacency pairs (undirected)
EXPECTED_ADJACENCIES = {
    ("nexora-r1", "nexora-r2"),
    ("nexora-r2", "nexora-r3"),
    ("nexora-r3", "nexora-r4"),
    ("nexora-r4", "nexora-r5"),
    ("nexora-r5", "nexora-r1"),
}

# Expected OSPF neighbor router IDs per router (exact ring topology)
EXPECTED_NEIGHBOR_RIDS = {
    "nexora-r1": {"2.2.2.2", "5.5.5.5"},
    "nexora-r2": {"1.1.1.1", "3.3.3.3"},
    "nexora-r3": {"2.2.2.2", "4.4.4.4"},
    "nexora-r4": {"3.3.3.3", "5.5.5.5"},
    "nexora-r5": {"4.4.4.4", "1.1.1.1"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _docker_exec(container: str, cmd: str) -> tuple[int, str]:
    """Run a command in a container. Returns (returncode, stdout+stderr)."""
    result = subprocess.run(
        ["docker", "exec", container, "sh", "-c", cmd],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.returncode, result.stdout + result.stderr


def _docker_running(container: str) -> bool:
    """Return True if the container is running."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.returncode == 0 and "true" in result.stdout.lower()


def _ospf_neighbors(container: str) -> str:
    """Return raw OSPF neighbor table from a container."""
    _, out = _docker_exec(container, "vtysh -c 'show ip ospf neighbor' 2>/dev/null")
    return out


def _ospf_neighbors_json(container: str) -> dict[str, Any]:
    """Return parsed JSON dict of OSPF neighbors from a container."""
    rc, out = _docker_exec(container, "vtysh -c 'show ip ospf neighbor json' 2>/dev/null")
    if rc != 0 or not out.strip():
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def _ospf_routes_json(container: str) -> dict[str, Any]:
    """Return parsed JSON dict of OSPF routes from a container."""
    rc, out = _docker_exec(container, "vtysh -c 'show ip ospf route json' 2>/dev/null")
    if rc != 0 or not out.strip():
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def _ip_route_json(container: str) -> dict[str, Any]:
    """Return parsed JSON dict of kernel routing table from zebra."""
    rc, out = _docker_exec(container, "vtysh -c 'show ip route json' 2>/dev/null")
    if rc != 0 or not out.strip():
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def _ospf_database_router_json(container: str, router_id: str) -> dict[str, Any]:
    """Return parsed JSON dict of router LSA from OSPF LSDB."""
    rc, out = _docker_exec(
        container, f"vtysh -c 'show ip ospf database router {router_id} json' 2>/dev/null"
    )
    if rc != 0 or not out.strip():
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def _ip_addr(container: str) -> str:
    """Return `ip addr` output from a container."""
    _, out = _docker_exec(container, "ip addr show")
    return out


# ---------------------------------------------------------------------------
# Reusable Fault-State Assertion Helpers
# ---------------------------------------------------------------------------


def assert_ospf_neighbor_state(
    container: str, expected_neighbor_rid: str, expected_state: str = "Full"
) -> None:
    """Assert a specific neighbor is present and in the expected convergence state."""
    data = _ospf_neighbors_json(container)
    neighbors = data.get("neighbors", {})
    assert expected_neighbor_rid in neighbors, (
        f"{container}: neighbor {expected_neighbor_rid} not found in neighbors: {list(neighbors.keys())}"
    )
    entries = neighbors[expected_neighbor_rid]
    matching = [
        e
        for e in entries
        if e.get("converged") == expected_state or expected_state in e.get("state", "")
    ]
    assert matching, (
        f"{container}: neighbor {expected_neighbor_rid} found, but none in state '{expected_state}': {entries}"
    )


def assert_ospf_neighbor_absent_or_down(container: str, neighbor_rid: str) -> None:
    """Assert a specific neighbor is either absent or not in FULL state (for fault verification)."""
    data = _ospf_neighbors_json(container)
    neighbors = data.get("neighbors", {})
    if neighbor_rid not in neighbors:
        return
    entries = neighbors[neighbor_rid]
    full_entries = [
        e
        for e in entries
        if e.get("converged") == "Full" or "Full" in e.get("state", "")
    ]
    assert not full_entries, (
        f"{container}: neighbor {neighbor_rid} was expected to be down/absent, but is FULL: {full_entries}"
    )


def assert_ospf_route_prefix(
    container: str,
    prefix: str,
    expected_cost: int | None = None,
    expected_via_iface: str | None = None,
) -> None:
    """Assert an OSPF prefix exists with specific cost and optional interface."""
    routes = _ospf_routes_json(container)
    assert prefix in routes, f"{container}: prefix {prefix} not in OSPF routes: {list(routes.keys())}"
    route_info = routes[prefix]
    if expected_cost is not None:
        actual_cost = route_info.get("cost")
        assert actual_cost == expected_cost, (
            f"{container}: prefix {prefix} expected cost {expected_cost}, got {actual_cost}"
        )
    if expected_via_iface is not None:
        nexthops = route_info.get("nexthops", [])
        via_ifaces = [
            nh.get("via") or nh.get("directlyAttachedTo") or nh.get("directly attached to")
            for nh in nexthops
        ]
        assert expected_via_iface in via_ifaces, (
            f"{container}: prefix {prefix} expected via interface {expected_via_iface}, got {via_ifaces}"
        )


def assert_topology_baseline(containers: list[str] = CONTAINERS) -> None:
    """Verify healthy topology baseline across all five routers."""
    for c in containers:
        nbrs = _ospf_neighbors_json(c)
        active_rids = set(nbrs.get("neighbors", {}).keys())
        expected_rids = EXPECTED_NEIGHBOR_RIDS[c]
        assert active_rids == expected_rids, (
            f"{c}: expected neighbors {expected_rids}, got {active_rids}"
        )
        routes = _ospf_routes_json(c)
        assert len(routes) == 10, f"{c}: expected 10 OSPF routes, got {len(routes)}"


# ---------------------------------------------------------------------------
# Pytest markers and fixtures
# ---------------------------------------------------------------------------


pytestmark = pytest.mark.lab_integration


@pytest.fixture(scope="module", autouse=True)
def require_lab_running():
    """Skip entire module if lab containers are not running."""
    running = [c for c in CONTAINERS if _docker_running(c)]
    if not running:
        pytest.skip("NEXORA lab containers not running — start with: cd lab && ./lab.sh up")
    missing = set(CONTAINERS) - set(running)
    if missing:
        pytest.skip(f"Missing containers: {missing}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContainerHealth:
    """Check all five containers are running and healthy."""

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_container_running(self, container: str):
        assert _docker_running(container), f"{container} is not running"

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_ospfd_process_running(self, container: str):
        rc, out = _docker_exec(container, "pgrep ospfd")
        assert rc == 0, f"ospfd not running in {container}: {out}"

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_zebra_process_running(self, container: str):
        rc, out = _docker_exec(container, "pgrep zebra")
        assert rc == 0, f"zebra not running in {container}: {out}"


class TestInterfaceAddressing:
    """Verify Phase 01 IP addressing on all interfaces."""

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_loopback_address(self, container: str):
        expected_ip = EXPECTED_LOOPBACKS[container]
        ip_info = _ip_addr(container)
        assert expected_ip in ip_info, (
            f"{container}: loopback {expected_ip}/32 not found in ip addr output"
        )

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_eth1_data_plane_address(self, container: str):
        expected_ip = EXPECTED_ETH1_IPS[container]
        ip_info = _ip_addr(container)
        assert expected_ip in ip_info, (
            f"{container}: eth1 IP {expected_ip}/30 not found in ip addr output"
        )

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_eth2_data_plane_address(self, container: str):
        expected_ip = EXPECTED_ETH2_IPS[container]
        ip_info = _ip_addr(container)
        assert expected_ip in ip_info, (
            f"{container}: eth2 IP {expected_ip}/30 not found in ip addr output"
        )


class TestOSPFAdjacencies:
    """Verify OSPF neighbors converge to FULL state on all five links."""

    @classmethod
    @pytest.fixture(scope="class", autouse=True)
    def wait_for_convergence(cls):
        """Give OSPF 90 s to converge if neighbors are not yet FULL."""
        for _ in range(9):
            all_full = all("Full" in _ospf_neighbors(c) for c in CONTAINERS)
            if all_full:
                break
            time.sleep(10)

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_ospf_full_adjacencies_count(self, container: str):
        """Each router must have EXACTLY 2 FULL adjacencies (ring topology invariant)."""
        # 1. Text table check
        neighbors_raw = _ospf_neighbors(container)
        full_count = neighbors_raw.count("Full")
        assert full_count == 2, (
            f"{container}: expected exactly 2 FULL adjacencies, found {full_count}\n{neighbors_raw}"
        )

        # 2. Structured JSON check: ensure total neighbors is exactly 2 (detects spurious non-FULL neighbors)
        nbr_data = _ospf_neighbors_json(container)
        nbr_dict = nbr_data.get("neighbors", {})
        assert len(nbr_dict) == 2, (
            f"{container}: expected exactly 2 total neighbors, but found {len(nbr_dict)}: {list(nbr_dict.keys())}"
        )

        # 3. Exact Router-ID matching: ensure neighbor RIDs match ring topology exactly
        expected_rids = EXPECTED_NEIGHBOR_RIDS[container]
        actual_rids = set(nbr_dict.keys())
        assert actual_rids == expected_rids, (
            f"{container}: neighbor Router-IDs mismatch! Expected {expected_rids}, found {actual_rids}"
        )

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_ospf_router_id(self, container: str):
        """OSPF Router-ID must match Phase 01 spec."""
        expected_rid = EXPECTED_ROUTER_IDS[container]
        _, out = _docker_exec(container, "vtysh -c 'show ip ospf' 2>/dev/null")
        assert expected_rid in out, f"{container}: OSPF Router-ID {expected_rid} not found\n{out}"

    def test_no_management_in_ospf(self):
        """Management subnet 192.168.100.0/24 must NOT appear in OSPF LSDB or OSPF FIB."""
        for container in CONTAINERS:
            # 1. Check parsed OSPF routes: 192.168.100.0/24 must not be in OSPF route table
            ospf_routes = _ospf_routes_json(container)
            mgmt_ospf = [pfx for pfx in ospf_routes if pfx.startswith("192.168.100.")]
            assert not mgmt_ospf, (
                f"{container}: management prefix found in OSPF route table: {mgmt_ospf}"
            )

            # 2. Check parsed zebra FIB: 192.168.100.0/24 must be protocol connected, NEVER ospf
            fib_routes = _ip_route_json(container)
            mgmt_entry = fib_routes.get("192.168.100.0/24", [])
            for route_obj in mgmt_entry:
                assert route_obj.get("protocol") != "ospf", (
                    f"{container}: management net 192.168.100.0/24 has OSPF protocol in FIB: {route_obj}"
                )

            # 3. Check parsed router LSA links in LSDB: no stub network in 192.168.100.0/24
            rid = EXPECTED_ROUTER_IDS[container]
            lsa_data = _ospf_database_router_json(container, rid)
            router_areas = lsa_data.get("routerLinkStates", {}).get("areas", {})
            for area_id, lsa_list in router_areas.items():
                for lsa in lsa_list:
                    links = lsa.get("routerLinks", {})
                    for link_key, link_info in links.items():
                        net_addr = link_info.get("networkAddress", "")
                        assert not net_addr.startswith("192.168.100."), (
                            f"{container}: management network {net_addr} advertised in router LSA {link_key} in area {area_id}"
                        )


class TestReachability:
    """Cross-router loopback reachability — validates OSPF routing table."""

    @classmethod
    @pytest.fixture(scope="class", autouse=True)
    def wait_for_convergence(cls):
        """Allow up to 90s for OSPF to converge."""
        time.sleep(5)

    @pytest.mark.parametrize(
        "src,dst",
        [(src, dst) for src in CONTAINERS for dst in CONTAINERS if src != dst],
    )
    def test_loopback_reachability(self, src: str, dst: str):
        """Every router must reach every other router's loopback."""
        dst_ip = EXPECTED_LOOPBACKS[dst]
        rc, out = _docker_exec(src, f"ping -c 2 -W 3 {dst_ip}")
        assert rc == 0, f"{src} cannot reach {dst} loopback {dst_ip}\nOutput: {out}"

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_ospf_routes_in_fib(self, container: str):
        """Each router must have ≥4 OSPF routes (all other loopbacks)."""
        _, out = _docker_exec(container, "vtysh -c 'show ip route ospf' 2>/dev/null")
        ospf_count = out.count("\nO")
        assert ospf_count >= 4, f"{container}: expected ≥4 OSPF routes, found {ospf_count}\n{out}"


class TestFaultStatePreparation:
    """Verify reusable fault-state test helpers and assertions operate correctly on the live lab."""

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_helper_neighbor_json_parsing(self, container: str):
        """Verify structured parsing of neighbor tables returns valid dict with expected RIDs."""
        data = _ospf_neighbors_json(container)
        neighbors = data.get("neighbors", {})
        assert len(neighbors) == 2, f"{container}: expected 2 neighbors, got {len(neighbors)}"
        expected_rids = EXPECTED_NEIGHBOR_RIDS[container]
        assert set(neighbors.keys()) == expected_rids

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_helper_route_json_parsing(self, container: str):
        """Verify structured parsing of OSPF routes returns 10 routes with valid costs."""
        routes = _ospf_routes_json(container)
        assert len(routes) == 10, f"{container}: expected 10 OSPF routes, got {len(routes)}"
        for pfx, info in routes.items():
            assert "cost" in info, f"{container}: route {pfx} missing cost"
            assert isinstance(info["cost"], int)

    def test_helper_assert_topology_baseline(self):
        """Verify the reusable topology baseline assertion succeeds on the healthy lab."""
        assert_topology_baseline(CONTAINERS)

    def test_helper_assert_neighbor_state_baseline(self):
        """Verify assert_ospf_neighbor_state accurately validates known FULL neighbors."""
        for container, expected_rids in EXPECTED_NEIGHBOR_RIDS.items():
            for rid in expected_rids:
                assert_ospf_neighbor_state(container, rid, expected_state="Full")

    def test_helper_assert_route_prefix_baseline(self):
        """Verify assert_ospf_route_prefix validates loopback routes and expected path metrics."""
        # On R1: R2 loopback (192.168.255.2/32) is cost 1 via eth1
        assert_ospf_route_prefix("nexora-r1", "192.168.255.2/32", expected_cost=1, expected_via_iface="eth1")
        # On R1: R5 loopback (192.168.255.5/32) is cost 1 via eth2
        assert_ospf_route_prefix("nexora-r1", "192.168.255.5/32", expected_cost=1, expected_via_iface="eth2")
        # On R1: R3 loopback (192.168.255.3/32) is cost 2 via eth1
        assert_ospf_route_prefix("nexora-r1", "192.168.255.3/32", expected_cost=2, expected_via_iface="eth1")
        # On R1: R4 loopback (192.168.255.4/32) is cost 2 via eth2
        assert_ospf_route_prefix("nexora-r1", "192.168.255.4/32", expected_cost=2, expected_via_iface="eth2")

    def test_helper_assert_neighbor_absent_validation(self):
        """Verify assert_ospf_neighbor_absent_or_down behaves as expected for an absent neighbor."""
        # RID 99.99.99.99 does not exist in any router's neighbor table
        assert_ospf_neighbor_absent_or_down("nexora-r1", "99.99.99.99")
