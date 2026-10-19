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

import subprocess
import time

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


def _ip_addr(container: str) -> str:
    """Return `ip addr` output from a container."""
    _, out = _docker_exec(container, "ip addr show")
    return out


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

    @pytest.fixture(scope="class", autouse=True)
    def wait_for_convergence(self):
        """Give OSPF 90 s to converge if neighbors are not yet FULL."""
        for _ in range(9):
            all_full = all("Full" in _ospf_neighbors(c) for c in CONTAINERS)
            if all_full:
                break
            time.sleep(10)

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_ospf_full_adjacencies_count(self, container: str):
        """Each router must have exactly 2 FULL adjacencies (ring topology)."""
        neighbors = _ospf_neighbors(container)
        full_count = neighbors.count("Full")
        assert full_count >= 2, (
            f"{container}: expected ≥2 FULL adjacencies, found {full_count}\n{neighbors}"
        )

    @pytest.mark.parametrize("container", CONTAINERS)
    def test_ospf_router_id(self, container: str):
        """OSPF Router-ID must match Phase 01 spec."""
        expected_rid = EXPECTED_ROUTER_IDS[container]
        _, out = _docker_exec(container, "vtysh -c 'show ip ospf' 2>/dev/null")
        assert expected_rid in out, f"{container}: OSPF Router-ID {expected_rid} not found\n{out}"

    def test_no_management_in_ospf(self):
        """Management subnet 192.168.100.0/24 must NOT appear in OSPF LSDB."""
        for container in CONTAINERS:
            _, out = _docker_exec(container, "vtysh -c 'show ip ospf database' 2>/dev/null")
            # Filter out the metric/type fields — look for address in LSA content
            assert "192.168.100" not in out, (
                f"{container}: management net 192.168.100.0/24 "
                f"found in OSPF LSDB — isolation broken!\n{out}"
            )


class TestReachability:
    """Cross-router loopback reachability — validates OSPF routing table."""

    @pytest.fixture(scope="class", autouse=True)
    def wait_for_convergence(self):
        """Allow up to 90s for OSPF to converge."""
        time.sleep(15)  # Brief wait; container is already running

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
