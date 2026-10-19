"""
NEXORA evidence collectors package.

Provides modular, read-only network evidence collectors for the five-router FRRouting lab:
- Topology discovery and expectation comparison
- Interface operational state and error counter polling
- OSPF adjacency and timer monitoring
- Routing table (RIB) observation and missing route detection
- Active bounded ICMP ping probes
- Active bounded traceroute path discovery
- Syslog and daemon event log extraction
- Normalization, validation, and ground-truth isolation
- Orchestrated evidence snapshot persistence
"""

from app.collectors.base import DEFAULT_ROUTER_IDS, BaseCollector
from app.collectors.interface_collector import InterfaceCollector
from app.collectors.normalizer import EvidenceNormalizer, GroundTruthLeakageError
from app.collectors.orchestrator import CollectionOrchestrator, EvidenceSnapshot
from app.collectors.ospf_collector import OSPFCollector
from app.collectors.ping_collector import APPROVED_PING_TARGETS, PingCollector
from app.collectors.routing_collector import RoutingCollector
from app.collectors.syslog_collector import SyslogCollector
from app.collectors.topology_collector import TopologyCollector, TopologyComparison
from app.collectors.traceroute_collector import TracerouteCollector
from app.collectors.transport import (
    CollectorTransport,
    DockerTransport,
    MockTransport,
    SecurityViolationError,
    TransportExecutionError,
)

__all__ = [
    "APPROVED_PING_TARGETS",
    "BaseCollector",
    "CollectionOrchestrator",
    "CollectorTransport",
    "DEFAULT_ROUTER_IDS",
    "DockerTransport",
    "EvidenceNormalizer",
    "EvidenceSnapshot",
    "GroundTruthLeakageError",
    "InterfaceCollector",
    "MockTransport",
    "OSPFCollector",
    "PingCollector",
    "RoutingCollector",
    "SecurityViolationError",
    "SyslogCollector",
    "TopologyCollector",
    "TopologyComparison",
    "TracerouteCollector",
    "TransportExecutionError",
]
