"""
Read-only transport abstraction for NEXORA network evidence collection.

Provides safe, bounded, read-only command execution against NEXORA router containers.
Strictly prohibits arbitrary shell commands, management interface modification,
and access to non-NEXORA containers.
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from typing import ClassVar


class SecurityViolationError(Exception):
    """Raised when an unauthorized command, target, or parameter is attempted."""


class TransportExecutionError(Exception):
    """Raised when a command fails to execute or times out."""


class CollectorTransport(ABC):
    """Abstract interface for executing read-only observation commands on routers."""

    @abstractmethod
    def execute(
        self,
        router_id: str,
        command: list[str],
        timeout: float = 5.0,
    ) -> tuple[int, str, str]:
        """Execute a validated command on the specified router.

        Returns: (returncode, stdout, stderr)
        """

    @abstractmethod
    def is_router_running(self, router_id: str) -> bool:
        """Check if the router container/process is running."""

    @abstractmethod
    def get_logs(
        self,
        router_id: str,
        tail: int = 100,
        since: str | None = None,
    ) -> list[str]:
        """Retrieve recent timestamped log lines from the router container."""


class DockerTransport(CollectorTransport):
    """Executes read-only commands against NEXORA containers via docker exec."""

    ROUTER_TO_CONTAINER: ClassVar[dict[str, str]] = {
        "R1": "nexora-r1",
        "R2": "nexora-r2",
        "R3": "nexora-r3",
        "R4": "nexora-r4",
        "R5": "nexora-r5",
    }

    # Approved read-only command templates (matching prefix/subcommands)
    ALLOWED_COMMAND_PREFIXES: ClassVar[tuple[tuple[str, ...], ...]] = (
        ("vtysh", "-c", "show ip ospf neighbor json"),
        ("vtysh", "-c", "show ip ospf interface json"),
        ("vtysh", "-c", "show ip route json"),
        ("ip", "-j", "-s", "link", "show"),
        ("ip", "-j", "addr", "show"),
        ("ping", "-c"),
        ("traceroute", "-n"),
        ("tc", "-j", "qdisc", "show", "dev", "eth1"),
        ("tc", "-j", "qdisc", "show", "dev", "eth2"),
    )

    FORBIDDEN_PATTERNS: ClassVar[tuple[str, ...]] = (
        "eth0",
        "mgmt",
        "192.168.100.",
        "rm ",
        "iptables",
        "ip link set",
        "ip route add",
        "ip route del",
        "reboot",
        "shutdown",
        "kill",
        ">",
        "|",
        ";",
        "&",
        "`",
        "$",
    )

    def __init__(self, project_prefix: str = "nexora") -> None:
        self.project_prefix = project_prefix

    def _resolve_container(self, router_id: str) -> str:
        canonical_id = router_id.upper()
        if canonical_id not in self.ROUTER_TO_CONTAINER:
            raise SecurityViolationError(
                f"Unauthorized router target: {router_id!r}. "
                f"Allowed routers are: {list(self.ROUTER_TO_CONTAINER.keys())}"
            )
        return self.ROUTER_TO_CONTAINER[canonical_id]

    def validate_command(self, command: list[str]) -> None:
        """Enforce strict read-only command validation."""
        if not command:
            raise SecurityViolationError("Empty command list is not allowed.")

        cmd_str = " ".join(command)
        for forbidden in self.FORBIDDEN_PATTERNS:
            if forbidden in cmd_str:
                raise SecurityViolationError(
                    f"Command contains forbidden pattern or target {forbidden!r}: {cmd_str!r}"
                )

        if command[0] == "tc" and (
            len(command) != 6 or tuple(command) not in self.ALLOWED_COMMAND_PREFIXES
        ):
            raise SecurityViolationError(
                "Only exact read-only data-interface qdisc queries allowed"
            )

        # Match against allowed prefixes
        matched = False
        for prefix in self.ALLOWED_COMMAND_PREFIXES:
            if len(command) >= len(prefix) and tuple(command[: len(prefix)]) == prefix:
                matched = True
                break

        if not matched:
            raise SecurityViolationError(
                f"Command {command!r} is not on the approved read-only allowlist."
            )

    def execute(
        self,
        router_id: str,
        command: list[str],
        timeout: float = 5.0,
    ) -> tuple[int, str, str]:
        container = self._resolve_container(router_id)
        self.validate_command(command)

        docker_cmd = ["docker", "exec", container] + command
        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            return -1, "", f"Command timed out after {timeout} seconds: {exc}"
        except Exception as exc:
            return -1, "", f"Transport execution failed: {exc}"

    def is_router_running(self, router_id: str) -> bool:
        try:
            container = self._resolve_container(router_id)
        except SecurityViolationError:
            return False

        try:
            proc = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            return proc.returncode == 0 and proc.stdout.strip() == "true"
        except Exception:
            return False

    def get_logs(
        self,
        router_id: str,
        tail: int = 100,
        since: str | None = None,
    ) -> list[str]:
        container = self._resolve_container(router_id)
        docker_cmd = ["docker", "logs", "--timestamps", "--tail", str(tail)]
        if since:
            docker_cmd.extend(["--since", since])
        docker_cmd.append(container)

        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            if proc.returncode != 0:
                return []
            lines = proc.stdout.splitlines() + proc.stderr.splitlines()
            return [line.strip() for line in lines if line.strip()]
        except Exception:
            return []


class MockTransport(CollectorTransport):
    """In-memory mock transport for testing collectors without Docker."""

    def __init__(self) -> None:
        self.responses: dict[tuple[str, tuple[str, ...]], tuple[int, str, str]] = {}
        self.router_status: dict[str, bool] = {
            "R1": True,
            "R2": True,
            "R3": True,
            "R4": True,
            "R5": True,
        }
        self.logs: dict[str, list[str]] = {
            "R1": [],
            "R2": [],
            "R3": [],
            "R4": [],
            "R5": [],
        }

    def set_response(
        self,
        router_id: str,
        command: list[str],
        returncode: int,
        stdout: str,
        stderr: str = "",
    ) -> None:
        self.responses[(router_id.upper(), tuple(command))] = (returncode, stdout, stderr)

    def set_router_running(self, router_id: str, is_running: bool) -> None:
        self.router_status[router_id.upper()] = is_running

    def set_logs(self, router_id: str, lines: list[str]) -> None:
        self.logs[router_id.upper()] = lines

    def execute(
        self,
        router_id: str,
        command: list[str],
        timeout: float = 5.0,
    ) -> tuple[int, str, str]:
        rid = router_id.upper()
        if not self.router_status.get(rid, False):
            return 1, "", f"Error response from daemon: Container {rid} is not running"

        key = (rid, tuple(command))
        if key in self.responses:
            return self.responses[key]

        # Check prefix match
        for (r, cmd_prefix), res in self.responses.items():
            if (
                r == rid
                and len(command) >= len(cmd_prefix)
                and tuple(command[: len(cmd_prefix)]) == cmd_prefix
            ):
                return res

        return 1, "", f"No mock response configured for {rid}: {command}"

    def is_router_running(self, router_id: str) -> bool:
        return self.router_status.get(router_id.upper(), False)

    def get_logs(
        self,
        router_id: str,
        tail: int = 100,
        since: str | None = None,
    ) -> list[str]:
        rid = router_id.upper()
        if not self.router_status.get(rid, False):
            return []
        lines = self.logs.get(rid, [])
        return lines[-tail:]
