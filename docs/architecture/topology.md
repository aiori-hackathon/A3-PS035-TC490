# NEXORA — Five-Node Network Laboratory Topology

**Team**: A3-PS035-TC490 | **Problem Statement**: PS-035

---

## 1. Overview

The NEXORA network laboratory is a five-router ring topology running FRRouting (FRR) with OSPFv2
in a single Area 0 (backbone). The topology is deployed using Containerlab on an ARM64 Linux VM.
Each router is a separate FRR container. Fault injection is applied via Linux `tc/netem` on the
host-side veth interfaces connecting the containers.

The ring provides redundancy: each router has exactly two OSPF neighbours, so a single link or
router failure creates a detectable asymmetry in routing tables and adjacency states.

---

## 2. Router Identifiers

| Router ID | Name   | Role                       | OSPF Router-ID | Loopback Address  |
|-----------|--------|----------------------------|----------------|-------------------|
| R1        | R1     | Core Gateway / Entry Point | 1.1.1.1        | 192.168.255.1/32  |
| R2        | R2     | Aggregation Node A         | 2.2.2.2        | 192.168.255.2/32  |
| R3        | R3     | Aggregation Node B         | 3.3.3.3        | 192.168.255.3/32  |
| R4        | R4     | Edge Router                | 4.4.4.4        | 192.168.255.4/32  |
| R5        | R5     | Peer / Transit Node        | 5.5.5.5        | 192.168.255.5/32  |

All loopbacks are in OSPF Area 0. They are used as stable probe targets for diagnostic reachability
measurements. Loopbacks are never used as transit interfaces.

---

## 3. Point-to-Point Link IP Addressing Plan

Each physical link uses a dedicated /30 subnet. This gives 4 addresses per subnet: network address,
two host addresses (one per router endpoint), and broadcast address.

| Link   | Subnet          | Router A | Interface A | Address A        | Router B | Interface B | Address B        |
|--------|-----------------|----------|-------------|------------------|----------|-------------|------------------|
| L12    | 10.0.12.0/30   | R1       | eth1        | 10.0.12.1/30     | R2       | eth1        | 10.0.12.2/30     |
| L23    | 10.0.23.0/30   | R2       | eth2        | 10.0.23.1/30     | R3       | eth1        | 10.0.23.2/30     |
| L34    | 10.0.34.0/30   | R3       | eth2        | 10.0.34.1/30     | R4       | eth1        | 10.0.34.2/30     |
| L45    | 10.0.45.0/30   | R4       | eth2        | 10.0.45.1/30     | R5       | eth1        | 10.0.45.2/30     |
| L51    | 10.0.15.0/30   | R5       | eth2        | 10.0.15.1/30     | R1       | eth2        | 10.0.15.2/30     |

**Collision Check**: All five /30 subnets are in distinct ranges within 10.0.0.0/8. No subnet
overlaps with any other, and none overlap with the loopback range (192.168.255.0/24) or the
management network (192.168.100.0/24). ✓

---

## 4. Per-Router Interface Summary

### R1
| Interface | Address        | Purpose       | OSPF Area |
|-----------|----------------|---------------|-----------|
| lo        | 192.168.255.1/32 | Loopback     | 0         |
| eth1      | 10.0.12.1/30   | Link to R2   | 0         |
| eth2      | 10.0.15.2/30   | Link to R5   | 0         |
| mgmt0     | 192.168.100.1/24 | Management  | (passive) |

### R2
| Interface | Address        | Purpose       | OSPF Area |
|-----------|----------------|---------------|-----------|
| lo        | 192.168.255.2/32 | Loopback     | 0         |
| eth1      | 10.0.12.2/30   | Link to R1   | 0         |
| eth2      | 10.0.23.1/30   | Link to R3   | 0         |
| mgmt0     | 192.168.100.2/24 | Management  | (passive) |

### R3
| Interface | Address        | Purpose       | OSPF Area |
|-----------|----------------|---------------|-----------|
| lo        | 192.168.255.3/32 | Loopback     | 0         |
| eth1      | 10.0.23.2/30   | Link to R2   | 0         |
| eth2      | 10.0.34.1/30   | Link to R4   | 0         |
| mgmt0     | 192.168.100.3/24 | Management  | (passive) |

### R4
| Interface | Address        | Purpose       | OSPF Area |
|-----------|----------------|---------------|-----------|
| lo        | 192.168.255.4/32 | Loopback     | 0         |
| eth1      | 10.0.34.2/30   | Link to R3   | 0         |
| eth2      | 10.0.45.1/30   | Link to R5   | 0         |
| mgmt0     | 192.168.100.4/24 | Management  | (passive) |

### R5
| Interface | Address        | Purpose       | OSPF Area |
|-----------|----------------|---------------|-----------|
| lo        | 192.168.255.5/32 | Loopback     | 0         |
| eth1      | 10.0.45.2/30   | Link to R4   | 0         |
| eth2      | 10.0.15.1/30   | Link to R1   | 0         |
| mgmt0     | 192.168.100.5/24 | Management  | (passive) |

---

## 5. OSPF Configuration

- **Protocol**: OSPFv2 (RFC 2328)
- **Area**: 0.0.0.0 (backbone, single area)
- **Process ID**: 1 (consistent across all routers)
- **Router-ID**: Statically configured (see table in Section 2)
- **Interface network type**: Point-to-point on all eth1/eth2 interfaces (eliminates DR/BDR election)
- **Hello interval**: 10 seconds (FRR default)
- **Dead interval**: 40 seconds (4× hello)
- **Reference bandwidth**: 100 Mbps (consistent cost calculation baseline)
- **Passive interface**: `mgmt0` on all routers (management plane excluded from OSPF flooding)

### OSPF Link Costs (default, reference-bandwidth based)

All containerlab links are 10 Gbps virtual, so default cost = 1 for all links unless overridden
during fault injection scenarios. Documented assumed cost = 1 for all experimental links.

---

## 6. Expected OSPF Neighbour Relationships (Normal State)

| Router | Neighbour | Via Interface | Via Link | State    |
|--------|-----------|---------------|----------|----------|
| R1     | R2        | eth1          | L12      | FULL     |
| R1     | R5        | eth2          | L51      | FULL     |
| R2     | R1        | eth1          | L12      | FULL     |
| R2     | R3        | eth2          | L23      | FULL     |
| R3     | R2        | eth1          | L23      | FULL     |
| R3     | R4        | eth2          | L34      | FULL     |
| R4     | R3        | eth1          | L34      | FULL     |
| R4     | R5        | eth2          | L45      | FULL     |
| R5     | R4        | eth1          | L45      | FULL     |
| R5     | R1        | eth2          | L51      | FULL     |

Total expected adjacencies in normal state: **10** (5 links × 2 directional adjacencies).

---

## 7. Normal-State Routing Behaviour

In the fault-free state:
- Every router has full LSDB visibility of all 5 routers and 5 links.
- Shortest-path routing: All paths have cost 2 (via one intermediate hop on a ring of 5).
- For any source–destination pair with multiple equal-cost paths, OSPF ECMP applies.
- Loopback prefixes (/32) of all 5 routers are reachable from all other routers.

**Example (R1 → R3)**: Two equal-cost paths exist:
- R1 → R2 → R3 (cost 2)
- R1 → R5 → R4 → R3 (cost 3)

OSPF will prefer the 2-hop path. The 3-hop path serves as the failover route.

---

## 8. Failure-State Alternative Path Behaviour

When a single link fails, the ring degrades to a chain. Routing reconverges:

| Failed Link | Alternative Path (all traffic) |
|-------------|-------------------------------|
| L12 (R1–R2) | R1 → R5 → R4 → R3 → R2       |
| L23 (R2–R3) | R2 → R1 → R5 → R4 → R3       |
| L34 (R3–R4) | R3 → R2 → R1 → R5 → R4       |
| L45 (R4–R5) | R4 → R3 → R2 → R1 → R5       |
| L51 (R5–R1) | R5 → R4 → R3 → R2 → R1       |

When a single router fails, that router's two links are effectively removed, creating two
separate chain segments. Connectivity between the two segments is lost.

---

## 9. Management Network Isolation

The management network `192.168.100.0/24` is **not** part of the OSPF experiment topology.

**Isolation rules**:
1. `mgmt0` is declared as a **passive interface** in FRR OSPF configuration on all routers.
   This means OSPF hellos are never sent or received on mgmt0.
2. The 192.168.100.0/24 prefix is **not redistributed** into OSPF. It is not visible in the
   experimental OSPF LSDB.
3. The Containerlab management network uses a separate Linux bridge and is routed by the
   host kernel, not by FRR.
4. Diagnostic SSH/API access from the ARM64 host uses the management network exclusively.

**Risk mitigation**: If a management address were accidentally included in an OSPF network
statement, it could become a transit path for experimental traffic. To prevent this, all FRR
configs include explicit `passive-interface mgmt0` and `no network 192.168.100.0/24 area 0`.

---

## 10. Addressing Assumptions and Constraints

1. All subnet assignments are within the RFC 1918 private address space.
2. No NAT or public routing is required for the experimental topology.
3. The /30 subnets were chosen to minimise wasted address space on point-to-point links.
4. Interface names (`eth1`, `eth2`, `mgmt0`) follow Linux kernel naming conventions in
   FRR containers. Containerlab assigns these deterministically.
5. Loopback addresses (/32) are used as stable diagnostic ping targets for Phase 03 active probes.
6. Routing costs are uniform (cost=1 per link) in the fault-free baseline to maintain
   symmetric, predictable ECMP paths.
7. The OSPF process will be restarted (not live-reconfigured) between scenario runs to
   guarantee clean LSDB state.

---

## 11. Fault Scenario Taxonomy (Labels Only — Deployment Phase 02+)

Five reproducible seeded fault categories supported by the topology:

| Scenario ID | Fault Type                  | Injected On       | Method                |
|-------------|-----------------------------|--------------------|------------------------|
| SCEN-01     | Link Failure                | Any of 5 links     | `ip link set down`    |
| SCEN-02     | Router Failure              | Any of 5 routers   | Container stop        |
| SCEN-03     | OSPF Config Mismatch        | Selected router    | FRR config change     |
| SCEN-04     | Packet Loss                 | Any of 5 links     | `tc netem loss`       |
| SCEN-05     | High Latency                | Any of 5 links     | `tc netem delay`      |

Ground-truth labels for injected faults are managed exclusively by the evaluation module
and are **never exposed to the diagnostic pipeline** during inference. See
`security-boundaries.md` for the isolation contract.
