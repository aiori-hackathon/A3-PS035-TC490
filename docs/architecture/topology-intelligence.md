# Topology Intelligence Architecture

## Overview

The Topology Intelligence subsystem provides deterministic, graph-theoretic reasoning about the network's structural, physical, and logical relationships. In NEXORA, topology is not merely a static asset inventory; it forms the spatial foundation upon which raw network observations are localized, correlated, and bounded.

## Core Concepts

### Expected vs. Observed Topology

Nexora enforces a strict distinction between **Expected Topology** (grounded engineering truth) and **Observed Topology** (runtime state):

1. **Expected Topology (`TopologyKind.EXPECTED`)**:
   - Represents the intended physical and routing architecture of the network.
   - For the 5-router ring topology:
     - 5 Routers: R1, R2, R3, R4, R5
     - 5 Point-to-Point Physical Links: L12 (R1-eth1 ↔ R2-eth1), L23 (R2-eth2 ↔ R3-eth1), L34 (R3-eth2 ↔ R4-eth1), L45 (R4-eth2 ↔ R5-eth1), L51 (R5-eth2 ↔ R1-eth2)
     - 10 Directional OSPF Adjacency Pairs: (R1 ↔ R2, R2 ↔ R3, R3 ↔ R4, R4 ↔ R5, R5 ↔ R1)
   - Serves as the invariant reference model for missing entity detection.

2. **Observed Topology (`TopologyKind.OBSERVED`)**:
   - Dynamic graph reconstructed directly from normalized runtime evidence snapshots (`EvidenceSnapshot`).
   - Reflects the operational status of interfaces (`UP`, `DOWN`, `ADMIN_DOWN`) and OSPF neighbour state (`FULL`, `2-WAY`, `DOWN`).
   - May exhibit partitioning, missing adjacencies, or unreachable nodes during fault states.

```
       [R1] 1.1.1.1
      /            \
   L12              L51
    /                \
 [R2] 2.2.2.2       [R5] 5.5.5.5
    \                /
   L23              L45
      \            /
       [R3] ─── [R4]
     3.3.3.3   L34   4.4.4.4
```

### OSPF Identity Disambiguation

A common source of confusion in multi-vendor or containerized network telemetry is the divergence between management router names and protocol-specific identifiers:
- **Router Hostname / Name**: `R1`, `R2`, `R3`, `R4`, `R5`
- **OSPF Router ID**: 32-bit dotted quad (e.g., `1.1.1.1`, `2.2.2.2`, `3.3.3.3`, `4.4.4.4`, `5.5.5.5`)
- **Loopback IP / Management IP**: IP assigned to loopback or dummy interface (e.g., `192.168.255.1/32`)
- **Interface IPs**: Point-to-point subnet addresses (e.g., `10.0.12.1/30` on R1-eth1, `10.0.12.2/30` on R2-eth1)

The `IdentityResolver` and `OSPFIdentityMapping` modules in `app/topology/identity.py` provide bidirectional, deterministic mappings between these identifier spaces:
- `resolve_router_from_ospf_id(ospf_id: str) -> str | None`
- `resolve_router_from_ip(ip: str) -> str | None`
- `resolve_link_from_interfaces(r1: str, if1: str, r2: str, if2: str) -> str | None`

## Topology Graph Operations

Implemented in `app/topology/graph.py` using `networkx`:
- **Shortest Path Computation**: Calculates hop distance and alternate routes when primary paths fail.
- **Topology Proximity**: Determines whether two routers are directly adjacent, within 1 hop, or topologically isolated.
- **Adjacency Discrepancy Detection**: Compares observed runtime adjacencies against the expected full-mesh/ring specification. Identifies asymmetric adjacencies (e.g., R1 sees R2 as FULL, but R2 sees R1 as DOWN or missing).
- **Connected Components**: Identifies network partitions and isolated router islands during multi-link or node failures.

## Isolation from Ground-Truth

The topology intelligence layer operates strictly on structural configuration and live observations. It never consumes or exposes fault scenario names, injected parameters, or synthetic labels.
