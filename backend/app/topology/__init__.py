"""
NEXORA topology intelligence package.

Provides graph-aware topology context for incident correlation and hypothesis generation.
"""

from app.topology.graph import (
    TopologyGraph,
    TopologyKind,
    build_expected_topology_graph,
    build_observed_topology_graph,
)

__all__ = [
    "TopologyGraph",
    "TopologyKind",
    "build_expected_topology_graph",
    "build_observed_topology_graph",
]
