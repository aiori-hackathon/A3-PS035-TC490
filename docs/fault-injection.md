# NEXORA — Controlled Network Fault Injection Framework (Phase 03)

**Team**: A3-PS035-TC490  
**Problem Statement**: PS-035 — Evidence-Based Operator Network Fault Localisation  
**Hackathon**: AIORI Hackathon 3  
**Tagline**: *From Correlation to Verification.*  

---

## 1. Overview and Architecture

The NEXORA Fault Injection Framework implements safe, deterministic, and reversible fault injection against the five-router FRRouting/OSPFv2 network testbed.

It enables systematic generation of diagnostic evidence across the five primary fault categories specified for PS-035:
1. **F1: LINK_FAILURE** (Data-plane interface down)
2. **F2: ROUTER_FAILURE** (Router container stop)
3. **F3: OSPF_CONFIGURATION_MISMATCH** (Incompatible OSPF hello/dead timers)
4. **F4: PACKET_LOSS** (Bounded Linux `tc/netem` packet loss)
5. **F5: HIGH_LATENCY** (Bounded Linux `tc/netem` packet delay)

```
                       +-----------------------------------+
                       |      NEXORA Fault Controller      |
                       | (lab/fault_injection/controller)  |
                       +-----------------+-----------------+
                                         |
               +-------------------------+-------------------------+
               |                         |                         |
               v                         v                         v
       [Safety Guards]           [Lifecycle Engine]       [Experiment Records]
       - Approved targets only   - Pre-baseline check     - UTC timestamps
       - Concurrency lock        - Atomic inject/hold     - Baseline observations
       - Mgmt interface shield   - Safe restoration       - Fault-state observations
       - Command whitelisting    - Post-verification      - Restoration observations
       - Emergency reset         - Idempotent cleanup     - Ground-truth isolation
```

---

## 2. Safety Invariants & Guardrails

| Invariant | Implementation Mechanism | Enforcement |
| :--- | :--- | :--- |
| **No Concurrent Experiments** | File lock at `lab/.active_fault.json` | Rejects new injection if experiment active |
| **Management Plane Shield** | Rejection of `eth0`, `mgmt`, `mgmt0`, `lo` | `SecurityViolationError` raised immediately |
| **Target Whitelisting** | Approved links: `L12, L23, L34, L45, L51`<br>Approved routers: `R1, R2, R3, R4, R5` | `InvalidTargetError` raised on unrecognized target |
| **No Shell Injection** | `subprocess.run(cmd_list, shell=False)` | Zero shell interpolation or eval |
| **Parameter Bounds** | Loss %: `[1, 100]`, Delay ms: `[1, 2000]` | Strict type & range validation |
| **Always-Restore Guarantee** | `try...finally` block in controller lifecycle | Reverses injected state even if observation fails |
| **Emergency Reset** | Idempotent multi-step recovery | Resets interfaces, qdiscs, timers, containers |

---

## 3. Scenario Specifications

### F1: LINK_FAILURE

- **Purpose**: Emulate a physical or optical link degradation/cut between adjacent routers.
- **Approved Targets**: `L12`, `L23`, `L34`, `L45`, `L51`.
- **Injected Change**: Disables the data-plane interface on side A of the link:
  ```bash
  docker exec nexora-r1 ip link set dev eth1 down
  ```
- **Expected Symptoms**:
  - Immediate loss of carrier/link state on `eth1`.
  - OSPF neighbor adjacency with R2 transitions to Down.
  - LSDB updates via LSA Type 1 (Router LSA) advertisement.
- **Expected Alternative Routing Behavior**:
  - The ring degrades into a linear chain (R1–R5–R4–R3–R2).
  - Traffic from R1 to R2 shifts from direct 1-hop path (`cost 1 via eth1`) to the 4-hop reverse ring path (`cost 4 via eth2 -> R5 -> R4 -> R3 -> R2`).
  - Loopback ping reachability between R1 and R2 is preserved via the alternate path.
- **Reset Procedure**:
  ```bash
  docker exec nexora-r1 ip link set dev eth1 up
  ```
- **Verification Evidence**:
  - Both neighbors on R1 return to `Full/-`.
  - Route cost to R2 returns to 1 via `eth1`.

---

### F2: ROUTER_FAILURE

- **Purpose**: Emulate complete hardware, power, or kernel failure of an entire router node.
- **Approved Targets**: `R1`, `R2`, `R3`, `R4`, `R5`.
- **Injected Change**: Stops the designated router container:
  ```bash
  docker stop nexora-r3
  ```
- **Expected Symptoms**:
  - Container enters `Exited` status.
  - Adjacent routers (R2 and R4) detect dead-interval timeout (40s) or socket reset.
  - Adjacencies with R3 drop.
- **Expected Alternative Routing Behavior**:
  - The ring breaks into two disconnected segments: `[R1, R2]` and `[R4, R5]`.
  - Loopback of R3 becomes completely unreachable from all remaining routers.
  - Intra-segment reachability (e.g. R1 <-> R2, R4 <-> R5) is maintained.
- **Reset Procedure**:
  ```bash
  docker start nexora-r3
  ```
  Followed by 30s wait for interface normalization and OSPF re-convergence.
- **Verification Evidence**:
  - Container health returns to `running`.
  - 10/10 directional OSPF adjacencies return to `Full/-`.
  - 20/20 loopback cross-pings succeed.

---

### F3: OSPF_CONFIGURATION_MISMATCH

- **Purpose**: Emulate operator error during interface provisioning leading to OSPF parameter mismatch.
- **Approved Targets**: `L12`, `L23`, `L34`, `L45`, `L51`.
- **Injected Change**: Changes OSPF hello and dead intervals on one endpoint via `vtysh`:
  ```bash
  docker exec nexora-r1 vtysh -c "configure terminal" \
    -c "interface eth1" \
    -c "ip ospf hello-interval 5" \
    -c "ip ospf dead-interval 15"
  ```
- **Expected Symptoms**:
  - Hello packets transmitted with non-standard `HelloInterval` (5s vs expected 10s).
  - RFC 2328 Section 10.5 compliance: peer router discards mismatched Hellos.
  - Syslog logs `Hello interval mismatch` warning.
  - Adjacency collapses upon dead-timer expiry.
- **Expected Alternative Routing Behavior**:
  - Traffic diverts across the alternate ring path similar to link failure, but the underlying Layer 2 link remains UP.
- **Reset Procedure**:
  ```bash
  docker exec nexora-r1 vtysh -c "configure terminal" \
    -c "interface eth1" \
    -c "ip ospf hello-interval 10" \
    -c "ip ospf dead-interval 40" \
    -c "ip ospf network point-to-point"
  ```
- **Verification Evidence**:
  - Adjacency re-converges to `Full/-`.
  - Both hello and dead timers match baseline on both peers.

---

### F4: PACKET_LOSS

- **Purpose**: Emulate intermittent physical layer errors, CRC drops, or link congestion.
- **Approved Targets**: `L12`, `L23`, `L34`, `L45`, `L51`.
- **Parameters**: `loss_pct` (bounded integer between 1% and 100%, default 30%).
- **Injected Change**: Attaches a netem qdisc to the data-plane egress interface:
  ```bash
  docker exec nexora-r1 tc qdisc add dev eth1 root netem loss 30%
  ```
- **Expected Symptoms**:
  - Packets traversing `eth1` experience drop rate proportional to configured percentage.
  - ICMP ping probes show measurable packet loss.
  - OSPF hellos may experience intermittent drops; if loss is high enough, retransmissions increase.
- **Expected Alternative Routing Behavior**:
  - If loss is below threshold, OSPF adjacency remains UP but data-plane path quality degrades.
  - If loss causes dead-timer drop, traffic reroutes around the ring.
- **Reset Procedure**:
  ```bash
  docker exec nexora-r1 tc qdisc del dev eth1 root
  ```
- **Verification Evidence**:
  - Root qdisc returns to default `noqueue`.
  - Ping probe between link endpoints returns to 0% packet loss.

---

### F5: HIGH_LATENCY

- **Purpose**: Emulate routing congestion, bufferbloat, or asymmetric propagation delay.
- **Approved Targets**: `L12`, `L23`, `L34`, `L45`, `L51`.
- **Parameters**: `delay_ms` (bounded integer between 1ms and 2000ms, default 100ms).
- **Injected Change**: Attaches netem delay qdisc:
  ```bash
  docker exec nexora-r1 tc qdisc add dev eth1 root netem delay 100ms
  ```
- **Expected Symptoms**:
  - Round-trip time (RTT) on the targeted link increases by the injected delay.
  - Ping RTT transitions from sub-millisecond (~0.3ms) to ~100ms+.
- **Reset Procedure**:
  ```bash
  docker exec nexora-r1 tc qdisc del dev eth1 root
  ```
- **Verification Evidence**:
  - Root qdisc returns to `noqueue`.
  - Ping RTT returns to sub-millisecond baseline.

---

## 4. Operator CLI & Makefile Usage

```bash
# 1. List scenarios
make fault-list
# or: ./lab.sh fault-list

# 2. Check baseline readiness
./lab.sh fault-observe

# 3. Inject a single fault
./lab.sh fault-inject F1 --target L12
./lab.sh fault-inject F4 --target L12 --loss-pct 25
./lab.sh fault-inject F5 --target L12 --delay-ms 150

# 4. Inspect active experiment
make fault-status
# or: ./lab.sh fault-status

# 5. Reset active fault
make fault-reset
# or: ./lab.sh fault-reset

# 6. Execute complete automated experiment run (with report generation)
./lab.sh fault-run F1 --target L12 --hold-sec 15
./lab.sh fault-run F4 --target L12 --loss-pct 30

# 7. Emergency Reset (clears all faults across all routers unconditionally)
make fault-emergency-reset
# or: ./lab.sh fault-emergency-reset
```

---

## 5. Ground-Truth Isolation

All experiment runs generate two distinct output artifacts:
1. **Experiment Report**: Stored in `docs/phase-reports/fault-<run_id>-<scenario>.json`. Contains raw telemetry observations, timestamps, and outcome.
2. **Ground-Truth Label**: Stored in `docs/phase-reports/ground_truth/gt-<run_id>.json`. Encapsulates `FaultInjectionRecord` with exact seeded fault type and location.

> **CRITICAL SECURITY BOUNDARY**:
> In accordance with PS-035 architecture contracts, `FaultInjectionRecord` instances and ground-truth files are strictly isolated from the live diagnostic engine. Live collectors and hypothesis evaluators never have access to ground-truth labels during inference.
