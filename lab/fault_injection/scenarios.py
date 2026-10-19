"""
NEXORA Fault Scenarios
Team: A3-PS035-TC490 | Problem Statement: PS-035

Concrete implementations of the five fault injection scenarios:
  F1: LINK_FAILURE
  F2: ROUTER_FAILURE
  F3: OSPF_CONFIGURATION_MISMATCH
  F4: PACKET_LOSS
  F5: HIGH_LATENCY
"""

from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod
from typing import Any

from app.schemas.hypothesis import FaultLocation, FaultLocationKind, FaultType
from lab.fault_injection.models import (
    APPROVED_DATA_INTERFACES,
    APPROVED_LINKS,
    APPROVED_ROUTER_CONTAINERS,
    APPROVED_ROUTERS,
    FORBIDDEN_INTERFACES,
    LINK_ENDPOINTS,
    ROUTER_TO_CONTAINER,
    ScenarioID,
)

logger = logging.getLogger("nexora.fault_injection.scenarios")


class SecurityViolationError(Exception):
    """Raised when an attempt is made to target a forbidden component (e.g. mgmt interface)."""


class InvalidTargetError(Exception):
    """Raised when an invalid router, link, or interface is specified."""


def _run_docker(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    """Execute a safe Docker command with timeout (no shell=True)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return -1, f"Command timed out after {timeout}s: {' '.join(cmd)}"


class BaseScenario(ABC):
    """Abstract base class for all NEXORA fault scenarios."""

    scenario_id: ScenarioID
    fault_type: FaultType

    @abstractmethod
    def validate_target(self, target: str, **params: Any) -> None:
        """Validate target identifier and parameters."""

    @abstractmethod
    def inject(self, target: str, **params: Any) -> dict[str, Any]:
        """Inject fault into the lab. Returns dictionary of injected details for restoration."""

    @abstractmethod
    def restore(self, target: str, injected_details: dict[str, Any]) -> None:
        """Safely restore the component to its baseline state."""

    @abstractmethod
    def get_fault_location(self, target: str) -> FaultLocation:
        """Return typed FaultLocation for this scenario and target."""

    @abstractmethod
    def get_affected_components(self, target: str) -> list[str]:
        """Return list of routers, links, or interfaces affected."""


# ---------------------------------------------------------------------------
# F1: LINK FAILURE
# ---------------------------------------------------------------------------


class LinkFailureScenario(BaseScenario):
    """F1: Temporarily disable an approved data-plane interface."""

    scenario_id = ScenarioID.F1_LINK_FAILURE
    fault_type = FaultType.LINK_FAILURE

    def validate_target(self, target: str, **params: Any) -> None:
        if target.lower() in [i.lower() for i in FORBIDDEN_INTERFACES]:
            raise SecurityViolationError(f"Targeting management or loopback interface '{target}' is strictly forbidden!")
        if target.upper() not in APPROVED_LINKS:
            raise InvalidTargetError(f"Target '{target}' is not an approved link. Must be one of {sorted(APPROVED_LINKS)}")

    def inject(self, target: str, **params: Any) -> dict[str, Any]:
        target = target.upper()
        self.validate_target(target)
        endpoint = LINK_ENDPOINTS[target]
        router_a = endpoint["router_a"]
        interface_a = endpoint["interface_a"]

        logger.info("Injecting LINK_FAILURE on %s (%s dev %s down)", target, router_a, interface_a)
        cmd = ["docker", "exec", router_a, "ip", "link", "set", "dev", interface_a, "down"]
        rc, out = _run_docker(cmd)
        if rc != 0:
            raise RuntimeError(f"Failed to disable {interface_a} on {router_a}: {out}")

        return {
            "link_id": target,
            "router": router_a,
            "interface": interface_a,
            "action": "ip link set dev down",
        }

    def restore(self, target: str, injected_details: dict[str, Any]) -> None:
        router = injected_details.get("router", LINK_ENDPOINTS[target.upper()]["router_a"])
        interface = injected_details.get("interface", LINK_ENDPOINTS[target.upper()]["interface_a"])

        logger.info("Restoring LINK_FAILURE on %s (%s dev %s up)", target, router, interface)
        cmd = ["docker", "exec", router, "ip", "link", "set", "dev", interface, "up"]
        rc, out = _run_docker(cmd)
        if rc != 0:
            raise RuntimeError(f"Failed to enable {interface} on {router}: {out}")

    def get_fault_location(self, target: str) -> FaultLocation:
        target = target.upper()
        endpoint = LINK_ENDPOINTS[target]
        r_a = APPROVED_ROUTER_CONTAINERS[endpoint["router_a"]]
        r_b = APPROVED_ROUTER_CONTAINERS[endpoint["router_b"]]
        return FaultLocation(
            kind=FaultLocationKind.LINK,
            component_id=target,
            affected_routers=[r_a, r_b],
        )

    def get_affected_components(self, target: str) -> list[str]:
        target = target.upper()
        endpoint = LINK_ENDPOINTS[target]
        return [target, endpoint["router_a"], endpoint["router_b"]]


# ---------------------------------------------------------------------------
# F2: ROUTER FAILURE
# ---------------------------------------------------------------------------


class RouterFailureScenario(BaseScenario):
    """F2: Stop only the selected NEXORA router container."""

    scenario_id = ScenarioID.F2_ROUTER_FAILURE
    fault_type = FaultType.ROUTER_FAILURE

    def _normalize_router(self, target: str) -> tuple[str, str]:
        t = target.strip()
        if t.upper() in APPROVED_ROUTERS:
            r_name = t.upper()
            ctr = ROUTER_TO_CONTAINER[r_name]
            return r_name, ctr
        elif t.lower() in APPROVED_ROUTER_CONTAINERS:
            ctr = t.lower()
            r_name = APPROVED_ROUTER_CONTAINERS[ctr]
            return r_name, ctr
        raise InvalidTargetError(f"Target '{target}' is not an approved router. Must be one of {sorted(APPROVED_ROUTERS)}")

    def validate_target(self, target: str, **params: Any) -> None:
        self._normalize_router(target)

    def inject(self, target: str, **params: Any) -> dict[str, Any]:
        r_name, ctr = self._normalize_router(target)
        logger.info("Injecting ROUTER_FAILURE on %s (%s: docker stop)", r_name, ctr)

        cmd = ["docker", "stop", ctr]
        rc, out = _run_docker(cmd, timeout=30)
        if rc != 0:
            raise RuntimeError(f"Failed to stop container {ctr}: {out}")

        return {
            "router_id": r_name,
            "container": ctr,
            "action": "docker stop",
        }

    def restore(self, target: str, injected_details: dict[str, Any]) -> None:
        ctr = injected_details.get("container")
        if not ctr:
            _, ctr = self._normalize_router(target)

        logger.info("Restoring ROUTER_FAILURE on %s (%s: docker start)", target, ctr)
        cmd = ["docker", "start", ctr]
        rc, out = _run_docker(cmd, timeout=30)
        if rc != 0:
            raise RuntimeError(f"Failed to start container {ctr}: {out}")

    def get_fault_location(self, target: str) -> FaultLocation:
        r_name, _ = self._normalize_router(target)
        return FaultLocation(
            kind=FaultLocationKind.ROUTER,
            component_id=r_name,
            affected_routers=[r_name],
        )

    def get_affected_components(self, target: str) -> list[str]:
        r_name, ctr = self._normalize_router(target)
        return [r_name, ctr]


# ---------------------------------------------------------------------------
# F3: OSPF CONFIGURATION MISMATCH
# ---------------------------------------------------------------------------


class OSPFConfigMismatchScenario(BaseScenario):
    """F3: Safely apply a temporary incompatible OSPF parameter on an approved adjacency."""

    scenario_id = ScenarioID.F3_OSPF_CONFIG_MISMATCH
    fault_type = FaultType.OSPF_CONFIGURATION_MISMATCH

    def _resolve_link(self, target: str) -> tuple[str, str, str]:
        t = target.upper()
        if t in APPROVED_LINKS:
            endpoint = LINK_ENDPOINTS[t]
            return t, endpoint["router_a"], endpoint["interface_a"]
        raise InvalidTargetError(f"Target '{target}' is not an approved link for OSPF config mismatch. Must be in {sorted(APPROVED_LINKS)}")

    def validate_target(self, target: str, **params: Any) -> None:
        if target.lower() in [i.lower() for i in FORBIDDEN_INTERFACES]:
            raise SecurityViolationError(f"Targeting management interface '{target}' is strictly forbidden!")
        self._resolve_link(target)

    def inject(self, target: str, **params: Any) -> dict[str, Any]:
        link_id, router, interface = self._resolve_link(target)
        mismatch_hello = int(params.get("hello_interval", 5))
        mismatch_dead = int(params.get("dead_interval", 15))

        logger.info("Injecting OSPF_CONFIG_MISMATCH on %s (%s %s: hello=%ds dead=%ds)", link_id, router, interface, mismatch_hello, mismatch_dead)
        cmd = [
            "docker", "exec", router, "vtysh",
            "-c", "configure terminal",
            "-c", f"interface {interface}",
            "-c", f"ip ospf hello-interval {mismatch_hello}",
            "-c", f"ip ospf dead-interval {mismatch_dead}",
        ]
        rc, out = _run_docker(cmd)
        if rc != 0:
            raise RuntimeError(f"Failed to configure OSPF mismatch on {router} {interface}: {out}")

        return {
            "link_id": link_id,
            "router": router,
            "interface": interface,
            "original_hello": 10,
            "original_dead": 40,
            "injected_hello": mismatch_hello,
            "injected_dead": mismatch_dead,
        }

    def restore(self, target: str, injected_details: dict[str, Any]) -> None:
        link_id, default_router, default_iface = self._resolve_link(target)
        router = injected_details.get("router", default_router)
        interface = injected_details.get("interface", default_iface)
        orig_hello = injected_details.get("original_hello", 10)
        orig_dead = injected_details.get("original_dead", 40)

        logger.info("Restoring OSPF_CONFIG_MISMATCH on %s (%s %s: hello=%ds dead=%ds)", link_id, router, interface, orig_hello, orig_dead)
        cmd = [
            "docker", "exec", router, "vtysh",
            "-c", "configure terminal",
            "-c", f"interface {interface}",
            "-c", f"ip ospf hello-interval {orig_hello}",
            "-c", f"ip ospf dead-interval {orig_dead}",
            "-c", "ip ospf network point-to-point",
        ]
        rc, out = _run_docker(cmd)
        if rc != 0:
            raise RuntimeError(f"Failed to restore OSPF configuration on {router} {interface}: {out}")

    def get_fault_location(self, target: str) -> FaultLocation:
        link_id, _, _ = self._resolve_link(target)
        endpoint = LINK_ENDPOINTS[link_id]
        r_a = APPROVED_ROUTER_CONTAINERS[endpoint["router_a"]]
        r_b = APPROVED_ROUTER_CONTAINERS[endpoint["router_b"]]
        return FaultLocation(
            kind=FaultLocationKind.LINK,
            component_id=link_id,
            affected_routers=[r_a, r_b],
        )

    def get_affected_components(self, target: str) -> list[str]:
        link_id, router, interface = self._resolve_link(target)
        endpoint = LINK_ENDPOINTS[link_id]
        return [link_id, router, interface, endpoint["router_b"]]


# ---------------------------------------------------------------------------
# F4: PACKET LOSS
# ---------------------------------------------------------------------------


class PacketLossScenario(BaseScenario):
    """F4: Use bounded Linux tc/netem rules to inject packet loss on an approved interface."""

    scenario_id = ScenarioID.F4_PACKET_LOSS
    fault_type = FaultType.PACKET_LOSS

    def _resolve_target(self, target: str, interface: str | None = None) -> tuple[str, str, str]:
        t = target.upper()
        if t in APPROVED_LINKS:
            endpoint = LINK_ENDPOINTS[t]
            return t, endpoint["router_a"], endpoint["interface_a"]
        elif t in APPROVED_ROUTERS or target.lower() in APPROVED_ROUTER_CONTAINERS:
            ctr = ROUTER_TO_CONTAINER.get(t, target.lower())
            if not interface or interface not in APPROVED_DATA_INTERFACES:
                raise InvalidTargetError(f"Router target requires an approved data-plane interface ({APPROVED_DATA_INTERFACES})")
            return t, ctr, interface
        raise InvalidTargetError(f"Target '{target}' is not an approved link or router.")

    def validate_target(self, target: str, **params: Any) -> None:
        if target.lower() in [i.lower() for i in FORBIDDEN_INTERFACES]:
            raise SecurityViolationError(f"Targeting management interface '{target}' is strictly forbidden!")
        if "interface" in params and params["interface"] in FORBIDDEN_INTERFACES:
            raise SecurityViolationError(f"Interface '{params['interface']}' is a management/forbidden interface!")
        self._resolve_target(target, params.get("interface"))
        loss_pct = params.get("loss_pct", 30)
        if not isinstance(loss_pct, int) or not (1 <= loss_pct <= 100):
            raise ValueError(f"loss_pct must be an integer between 1 and 100, got {loss_pct}")

    def inject(self, target: str, **params: Any) -> dict[str, Any]:
        comp_id, router, interface = self._resolve_target(target, params.get("interface"))
        loss_pct = int(params.get("loss_pct", 30))
        self.validate_target(target, loss_pct=loss_pct, interface=interface)

        logger.info("Injecting PACKET_LOSS on %s (%s dev %s: netem loss %d%%)", comp_id, router, interface, loss_pct)
        # Clear any existing root qdisc safely first
        _run_docker(["docker", "exec", router, "tc", "qdisc", "del", "dev", interface, "root"])

        cmd = ["docker", "exec", router, "tc", "qdisc", "add", "dev", interface, "root", "netem", "loss", f"{loss_pct}%"]
        rc, out = _run_docker(cmd)
        if rc != 0:
            raise RuntimeError(f"Failed to add tc netem loss on {router} {interface}: {out}")

        return {
            "target": target,
            "router": router,
            "interface": interface,
            "loss_pct": loss_pct,
            "action": f"tc netem loss {loss_pct}%",
        }

    def restore(self, target: str, injected_details: dict[str, Any]) -> None:
        router = injected_details.get("router")
        interface = injected_details.get("interface")
        if not router or not interface:
            _, router, interface = self._resolve_target(target)

        logger.info("Restoring PACKET_LOSS on %s (%s dev %s: tc qdisc del)", target, router, interface)
        cmd = ["docker", "exec", router, "tc", "qdisc", "del", "dev", interface, "root"]
        _run_docker(cmd)

    def get_fault_location(self, target: str) -> FaultLocation:
        comp_id, router, _ = self._resolve_target(target)
        if comp_id in APPROVED_LINKS:
            endpoint = LINK_ENDPOINTS[comp_id]
            r_a = APPROVED_ROUTER_CONTAINERS[endpoint["router_a"]]
            r_b = APPROVED_ROUTER_CONTAINERS[endpoint["router_b"]]
            return FaultLocation(kind=FaultLocationKind.LINK, component_id=comp_id, affected_routers=[r_a, r_b])
        else:
            r_name = APPROVED_ROUTER_CONTAINERS[router]
            return FaultLocation(kind=FaultLocationKind.ROUTER, component_id=r_name, affected_routers=[r_name])

    def get_affected_components(self, target: str) -> list[str]:
        comp_id, router, interface = self._resolve_target(target)
        return [comp_id, router, interface]


# ---------------------------------------------------------------------------
# F5: HIGH LATENCY
# ---------------------------------------------------------------------------


class HighLatencyScenario(BaseScenario):
    """F5: Use bounded tc/netem delay on an approved interface."""

    scenario_id = ScenarioID.F5_HIGH_LATENCY
    fault_type = FaultType.HIGH_LATENCY

    def _resolve_target(self, target: str, interface: str | None = None) -> tuple[str, str, str]:
        t = target.upper()
        if t in APPROVED_LINKS:
            endpoint = LINK_ENDPOINTS[t]
            return t, endpoint["router_a"], endpoint["interface_a"]
        elif t in APPROVED_ROUTERS or target.lower() in APPROVED_ROUTER_CONTAINERS:
            ctr = ROUTER_TO_CONTAINER.get(t, target.lower())
            if not interface or interface not in APPROVED_DATA_INTERFACES:
                raise InvalidTargetError(f"Router target requires an approved data-plane interface ({APPROVED_DATA_INTERFACES})")
            return t, ctr, interface
        raise InvalidTargetError(f"Target '{target}' is not an approved link or router.")

    def validate_target(self, target: str, **params: Any) -> None:
        if target.lower() in [i.lower() for i in FORBIDDEN_INTERFACES]:
            raise SecurityViolationError(f"Targeting management interface '{target}' is strictly forbidden!")
        if "interface" in params and params["interface"] in FORBIDDEN_INTERFACES:
            raise SecurityViolationError(f"Interface '{params['interface']}' is a management/forbidden interface!")
        self._resolve_target(target, params.get("interface"))
        delay_ms = params.get("delay_ms", 100)
        if not isinstance(delay_ms, int) or not (1 <= delay_ms <= 2000):
            raise ValueError(f"delay_ms must be an integer between 1 and 2000, got {delay_ms}")

    def inject(self, target: str, **params: Any) -> dict[str, Any]:
        comp_id, router, interface = self._resolve_target(target, params.get("interface"))
        delay_ms = int(params.get("delay_ms", 100))
        self.validate_target(target, delay_ms=delay_ms, interface=interface)

        logger.info("Injecting HIGH_LATENCY on %s (%s dev %s: netem delay %dms)", comp_id, router, interface, delay_ms)
        # Clear any existing root qdisc safely first
        _run_docker(["docker", "exec", router, "tc", "qdisc", "del", "dev", interface, "root"])

        cmd = ["docker", "exec", router, "tc", "qdisc", "add", "dev", interface, "root", "netem", "delay", f"{delay_ms}ms"]
        rc, out = _run_docker(cmd)
        if rc != 0:
            raise RuntimeError(f"Failed to add tc netem delay on {router} {interface}: {out}")

        return {
            "target": target,
            "router": router,
            "interface": interface,
            "delay_ms": delay_ms,
            "action": f"tc netem delay {delay_ms}ms",
        }

    def restore(self, target: str, injected_details: dict[str, Any]) -> None:
        router = injected_details.get("router")
        interface = injected_details.get("interface")
        if not router or not interface:
            _, router, interface = self._resolve_target(target)

        logger.info("Restoring HIGH_LATENCY on %s (%s dev %s: tc qdisc del)", target, router, interface)
        cmd = ["docker", "exec", router, "tc", "qdisc", "del", "dev", interface, "root"]
        _run_docker(cmd)

    def get_fault_location(self, target: str) -> FaultLocation:
        comp_id, router, _ = self._resolve_target(target)
        if comp_id in APPROVED_LINKS:
            endpoint = LINK_ENDPOINTS[comp_id]
            r_a = APPROVED_ROUTER_CONTAINERS[endpoint["router_a"]]
            r_b = APPROVED_ROUTER_CONTAINERS[endpoint["router_b"]]
            return FaultLocation(kind=FaultLocationKind.LINK, component_id=comp_id, affected_routers=[r_a, r_b])
        else:
            r_name = APPROVED_ROUTER_CONTAINERS[router]
            return FaultLocation(kind=FaultLocationKind.ROUTER, component_id=r_name, affected_routers=[r_name])

    def get_affected_components(self, target: str) -> list[str]:
        comp_id, router, interface = self._resolve_target(target)
        return [comp_id, router, interface]


# Scenario Registry
SCENARIOS: dict[ScenarioID, BaseScenario] = {
    ScenarioID.F1_LINK_FAILURE: LinkFailureScenario(),
    ScenarioID.F2_ROUTER_FAILURE: RouterFailureScenario(),
    ScenarioID.F3_OSPF_CONFIG_MISMATCH: OSPFConfigMismatchScenario(),
    ScenarioID.F4_PACKET_LOSS: PacketLossScenario(),
    ScenarioID.F5_HIGH_LATENCY: HighLatencyScenario(),
}


def get_scenario(scenario_id: str | ScenarioID) -> BaseScenario:
    """Retrieve scenario implementation by ID with strict validation."""
    if isinstance(scenario_id, str):
        # Allow case-insensitive or short match
        clean_id = scenario_id.strip().upper()
        # Map common aliases (e.g. F1 -> F1_LINK_FAILURE)
        alias_map = {
            "F1": ScenarioID.F1_LINK_FAILURE,
            "F2": ScenarioID.F2_ROUTER_FAILURE,
            "F3": ScenarioID.F3_OSPF_CONFIG_MISMATCH,
            "F4": ScenarioID.F4_PACKET_LOSS,
            "F5": ScenarioID.F5_HIGH_LATENCY,
        }
        if clean_id in alias_map:
            clean_id = alias_map[clean_id]
        try:
            scenario_id = ScenarioID(clean_id)
        except ValueError:
            raise InvalidTargetError(f"Invalid scenario ID '{scenario_id}'. Must be one of {[s.value for s in ScenarioID]}")

    if scenario_id not in SCENARIOS:
        raise InvalidTargetError(f"Scenario '{scenario_id}' is not implemented.")
    return SCENARIOS[scenario_id]
