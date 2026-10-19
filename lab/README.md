# NEXORA — Real Five-Router Network Laboratory (Phase 02)

**Team**: A3-PS035-TC490  
**Problem Statement**: PS-035 — Evidence-Based Operator Network Fault Localisation  
**Hackathon**: AIORI Hackathon 3  
**Tagline**: *From Correlation to Verification.*

---

## 1. Overview

The NEXORA network laboratory is a reproducible five-router ring topology running FRRouting (FRR) with OSPFv2 in Area 0 (`0.0.0.0`). The topology matches the Phase 01 architecture specification (`docs/architecture/topology.md`) exactly.

Each router runs in an independent container with dedicated network namespaces, interconnected via Docker bridge networks acting as pure Layer 2 links.

```
       [R1] (1.1.1.1)
      /    \
    L12    L51
    /        \
  [R2]      [R5] (5.5.5.5)
 (2.2.2.2)    |
    \        L45
    L23       |
      \     [R4] (4.4.4.4)
       [R3]--L34
      (3.3.3.3)
```

---

## 2. IP Addressing Plan

### Router Nodes and Loopbacks

| Router | Container Name | Hostname | Router ID | Loopback IP | Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R1** | `nexora-r1` | `r1` | `1.1.1.1` | `192.168.255.1/32` | Core Gateway / Entry Point |
| **R2** | `nexora-r2` | `r2` | `2.2.2.2` | `192.168.255.2/32` | Aggregation Node A |
| **R3** | `nexora-r3` | `r3` | `3.3.3.3` | `192.168.255.3/32` | Aggregation Node B |
| **R4** | `nexora-r4` | `r4` | `4.4.4.4` | `192.168.255.4/32` | Edge Router |
| **R5** | `nexora-r5` | `r5` | `5.5.5.5` | `192.168.255.5/32` | Peer / Transit Node |

### Point-to-Point Links (/30 Subnets)

| Link | Subnet | Side A Router | Interface A | IP A | Side B Router | Interface B | IP B |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **L12** | `10.0.12.0/30` | R1 | `eth1` | `10.0.12.1/30` | R2 | `eth1` | `10.0.12.2/30` |
| **L23** | `10.0.23.0/30` | R2 | `eth2` | `10.0.23.1/30` | R3 | `eth1` | `10.0.23.2/30` |
| **L34** | `10.0.34.0/30` | R3 | `eth2` | `10.0.34.1/30` | R4 | `eth1` | `10.0.34.2/30` |
| **L45** | `10.0.45.0/30` | R4 | `eth2` | `10.0.45.1/30` | R5 | `eth1` | `10.0.45.2/30` |
| **L51** | `10.0.15.0/30` | R5 | `eth2` | `10.0.15.1/30` | R1 | `eth2` | `10.0.15.2/30` |

### Management Network

- **Subnet**: `192.168.100.0/24`
- **Interface**: `eth0` on all routers (`192.168.100.1` to `192.168.100.5`)
- **OSPF Status**: `passive-interface eth0` configured; management subnet is **completely excluded** from OSPF announcements and LSDB.

---

## 3. Architecture & Container Design

### Cross-Project Isolation & L2 Carrier Subnets
On development environments where other Docker projects (such as FaultLens) run concurrently and occupy `10.0.x.x/24` bridge networks, Docker's host IPAM prevents creating conflicting bridge subnets.

NEXORA solves this using a two-tier virtual networking model:
1. **L2 Carrier Subnets**: Docker Compose creates isolated bridge networks (`nexora_net_l12` through `nexora_net_l51`) using non-conflicting IPAM ranges (`172.31.x.x/29`).
2. **Deterministic Interface Normalization**: At container boot, `lab/scripts/configure.sh` detects interface attachments, standardizes naming so `eth0` is always management, `eth1` is Link 1, and `eth2` is Link 2, and assigns the official Phase 01 `10.0.x.x/30` addresses.
3. **Pure L2 Forwarding**: `lab.sh` configures `net.bridge.bridge-nf-call-iptables=0` on the Docker host to allow line-rate bridged packet delivery across containers without host iptables interference.

---

## 4. Operational Commands

Management operations are automated via `lab.sh` (or `make`):

```bash
# Start the lab and wait for OSPF convergence
./lab.sh up
# or: make lab-up

# Check container status and OSPF neighbor tables
./lab.sh status
# or: make lab-status

# Run the automated 7-point validation suite
./lab.sh verify
# or: make lab-verify

# Run the L12 link-failure failover smoke test
./lab.sh failover
# or: make lab-failover

# Show container logs
./lab.sh logs
./lab.sh logs r1

# Teardown the lab (scoped strictly to project=nexora)
./lab.sh down
# or: make lab-down
```

---

## 5. Automated Verification & Testing

### Verification Suite (`lab.sh verify`)
The verification script validates 7 critical operational criteria:
1. **Container Health**: All 5 router containers running and healthy.
2. **Network Topology**: All 5 data-plane networks exist and are connected.
3. **Addressing Verification**: All loopback and data-plane addresses exist on the proper interfaces.
4. **OSPF Adjacencies**: Exactly 10 directional FULL adjacencies (2 per router in ring).
5. **Full Reachability**: All 20 cross-router loopback pings succeed with 0% loss.
6. **FIB Routing Entries**: Every router has >= 4 OSPF routes in its FIB.
7. **Management Isolation**: The `192.168.100.0/24` network never appears in the OSPF LSDB.

### Pytest Integration Suite
Run the automated pytest integration tests from `backend/`:

```bash
cd backend
uv run pytest tests/test_lab_integration.py -v -m lab_integration
```
All 66 tests validate live Docker container health, daemon processes, interface addressing, OSPF adjacency states, and bidirectional reachability.
