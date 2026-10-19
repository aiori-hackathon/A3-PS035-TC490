# NEXORA — Phase 04 Completion Report: Real Network Evidence Collection Engine

**Phase**: 04  
**Project**: NEXORA (PS-035: Evidence-Based Operator Network Fault Localisation)  
**Team**: A3-PS035-TC490  
**Status**: COMPLETED  
**Date**: October 2026  

---

## 1. Executive Summary

Phase 04 implemented a modular, read-only network evidence collection and normalization engine for the five-router FRRouting laboratory (`nexora-r1` through `nexora-r5`). The engine retrieves real control-plane, data-plane, and telemetry metrics and transforms them into Phase 01 Pydantic contracts.

All measurements were taken from the live network. No measurements were fabricated or simulated.

---

## 2. Implemented Collectors

1. **`TopologyCollector`**: Live discovery of router status, interface IP assignments, and directional OSPF adjacencies. Provides structured comparison between expected baseline topology and observed state.
2. **`InterfaceCollector`**: Polls interface operational states (`UP`, `DOWN`, `ADMIN_DOWN`) and hardware/software error and drop counters via Linux `ip -j -s link show`.
3. **`OSPFCollector`**: Ingests structured JSON neighbor tables via `vtysh -c 'show ip ospf neighbor json'`, dead timer countdowns, and explicitly reports missing expected neighbors.
4. **`RoutingCollector`**: Reads kernel and FRR RIB entries via `vtysh -c 'show ip route json'`, tracking destination prefixes, next hops, outgoing interfaces, and detects missing expected routes.
5. **`PingCollector`**: Executes safe, bounded ICMP echo probes against whitelisted loopback and interface targets, strictly verifying packet loss percentage and RTT statistics.
6. **`TracerouteCollector`**: Discovers hop-by-hop forwarding paths and per-hop latencies.
7. **`SyslogCollector`**: Ingests and standardizes container/FRR daemon log lines with timezone-aware timestamps and inferred RFC 5424 severity.
8. **`EvidenceNormalizer`**: Validates schema contracts, guarantees UTC timezone awareness, and enforces ground-truth isolation.
9. **`CollectionOrchestrator`**: Coordinates multi-collector runs, manages partial failures without crashing, and serializes auditable evidence snapshots to `evaluation/datasets/observations/`.

---

## 3. Real Fault Observation Validation

Real evidence snapshots were captured under baseline conditions and while each of the five Phase 03 fault scenarios was active:

### Baseline Snapshot (`baseline_snapshot.json`)
- **Routers**: 5/5 UP
- **OSPF Adjacencies**: 10/10 FULL
- **Cross-Router Pings**: 0.0% packet loss across all loopback pairs (avg RTT < 0.5ms)
- **Routing**: Full OSPF loopback routes present on all routers
- **Total Records**: 80+ evidence observations

### F1: Link Failure Observation (`f1_link_failure_snapshot.json`)
- **Injected Target**: Link L12 (`nexora-r1` eth1 down)
- **Observed Evidence**:
  - `InterfaceObservation`: `nexora-r1` eth1 observed as `down` / `admin-down`.
  - `OSPFObservation`: Neighbor 2.2.2.2 on R1 eth1 transitioned to `Down`.
  - `RouteObservation`: Route to 192.168.255.2 re-routed via `eth2` (transit through R5).

### F2: Router Failure Observation (`f2_router_failure_snapshot.json`)
- **Injected Target**: Router R3 container stopped
- **Observed Evidence**:
  - `Topology`: R3 operational status observed as `RouterStatus.DOWN`.
  - `PingMeasurement`: Probes to R3 loopback (192.168.255.3) recorded 100.0% packet loss.
  - `OSPFObservation`: R2 and R4 adjacencies facing R3 dropped to `Down`.

### F3: OSPF Configuration Mismatch Observation (`f3_ospf_mismatch_snapshot.json`)
- **Injected Target**: Link L23 (R2 eth2: hello=5s, dead=20s vs baseline 10s/40s)
- **Observed Evidence**:
  - `InterfaceObservation`: R2 eth2 interface observed as `up`.
  - `OSPFObservation`: Adjacency R2-R3 dropped from `Full` to `Down` after dead-timer expiration.
  - Key distinction: Interface state remains operational while routing adjacency fails.

### F4: Packet Loss Observation (`f4_packet_loss_snapshot.json`)
- **Injected Target**: Link L12 (25.0% loss via Linux `tc netem`)
- **Observed Evidence**:
  - `InterfaceObservation`: Interface eth1 observed as `up`.
  - `PingMeasurement`: Active probes from R1 to R2 cross-link IP measured ~25% packet loss (0% -> 25.0%).

### F5: High Latency Observation (`f5_high_latency_snapshot.json`)
- **Injected Target**: Link L23 (150ms delay via Linux `tc netem`)
- **Observed Evidence**:
  - `InterfaceObservation`: Interface eth2 observed as `up`.
  - `PingMeasurement`: Active probes across L23 measured RTT increase from <1ms baseline to 152.8ms avg.

---

## 4. Ground-Truth Isolation

All generated snapshots in `evaluation/datasets/observations/` were scanned for forbidden tokens (`seeded_fault_type`, `actual_fault_location`, `injected_loss`, scenario IDs). Zero tokens were present. The diagnostic engine in Phase 05 receives purely observable evidence.

---

## 5. Test Suite Verification

- **Backend Unit Tests**: 138/138 passed (including 22 collector unit tests).
- **Backend Live Integration Tests**: 6/6 passed (`test_evidence_collection_live.py`).
- **Lab Integration Tests**: 80/80 passed (`test_lab_integration.py`).
- **Ruff Linter**: 0 errors, all checks passed.
- **Frontend Checks**: ESLint, TypeScript typecheck, and Next.js build all passed with 0 errors.
- **Lab Operational Verification**: `./lab.sh verify` 7/7 checks passed.

---

## 6. Readiness for Phase 05

With verified, real network evidence collection and ground-truth isolation complete, NEXORA is fully prepared for Phase 05 (Diagnostic Engine and Evidence Correlator).
