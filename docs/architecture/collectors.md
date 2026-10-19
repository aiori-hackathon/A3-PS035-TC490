# NEXORA — Network Evidence Collectors Architecture

**Team**: A3-PS035-TC490 | **PS-035** | Phase 04

---

## 1. Purpose

The NEXORA Evidence Collection Engine provides a production-grade, read-only observation pipeline for the five-router FRRouting / OSPFv2 experimental laboratory (`nexora-r1` through `nexora-r5`). It retrieves live data-plane and control-plane metrics and translates them into Phase 01 Pydantic evidence schemas.

In strict compliance with PS-035:
- **Zero Fabrication**: All measurements originate from actual network queries.
- **Evidence-Only Scope**: The collection engine produces observations; it does not perform fault localisation, diagnosis, or hypothesis generation.
- **Strict Ground-Truth Isolation**: Seeds, injected parameters, and ground-truth scenario IDs are strictly excluded from diagnosis-facing evidence outputs.

---

## 2. Collector Modules

The collector subsystem is located in `backend/app/collectors/` and organized into modular components:

| Module | Class | Responsibility | Primary Data Source | Produced Contract |
|---|---|---|---|---|
| `transport.py` | `CollectorTransport`, `DockerTransport`, `MockTransport` | Safe read-only execution abstraction | `docker exec` (or mock) | `tuple[int, str, str]` |
| `base.py` | `BaseCollector` | ID generation, UTC timestamps, common lifecycle | Python standard library | Base contracts |
| `topology_collector.py` | `TopologyCollector` | Discovers live topology, compares vs baseline | `ip -j addr show`, `vtysh neighbor` | `Topology`, `TopologyComparison` |
| `interface_collector.py` | `InterfaceCollector` | Polls interface state and error counters | `ip -j -s link show` | `InterfaceObservation` |
| `ospf_collector.py` | `OSPFCollector` | OSPF neighbour states, dead timers, missing neighbours | `vtysh -c 'show ip ospf neighbor json'` | `OSPFObservation` |
| `routing_collector.py` | `RoutingCollector` | RIB entries, next hops, missing route detection | `vtysh -c 'show ip route json'` | `RouteObservation` |
| `ping_collector.py` | `PingCollector` | Bounded ICMP probes, packet loss, RTT | Linux `ping -c -W` | `PingMeasurement` |
| `traceroute_collector.py` | `TracerouteCollector` | Bounded forwarding path and hop discovery | Linux `traceroute -n -w -m` | `TracerouteObservation` |
| `syslog_collector.py` | `SyslogCollector` | Ingests FRR daemon and container logs | `docker logs --timestamps` | `SyslogEvent` |
| `normalizer.py` | `EvidenceNormalizer` | Schema validation, UTC enforcement, GT isolation | Pydantic models | Normalized records |
| `orchestrator.py` | `CollectionOrchestrator` | Coordinates runs, handles partial failure, saves snapshots | All collectors | `EvidenceSnapshot` |

---

## 3. Approved Command Interfaces

To prevent command injection and ensure read-only safety, all commands executed by `DockerTransport` must match explicit prefix allowlists:

```python
ALLOWED_COMMAND_PREFIXES = (
    ("vtysh", "-c", "show ip ospf neighbor json"),
    ("vtysh", "-c", "show ip ospf interface json"),
    ("vtysh", "-c", "show ip route json"),
    ("ip", "-j", "-s", "link", "show"),
    ("ip", "-j", "addr", "show"),
    ("ping", "-c"),
    ("traceroute", "-n"),
)
```

### Security Boundaries
1. **Subprocess Arrays Only**: Dynamic commands are never passed to a shell (`shell=False`).
2. **Container Target Whitelist**: Target containers are strictly limited to `nexora-r1` through `nexora-r5`.
3. **Management Interface Shield**: Any command containing `eth0`, `mgmt`, or `192.168.100.*` raises `SecurityViolationError`.
4. **Bounded Timeouts**: All transport calls enforce bounded timeouts (typically 3–5s) to prevent hangs.

---

## 4. Handling Missing Data and Failures

In accordance with Phase 01 design invariants:
- A missing observation is **not** an assumed failure:
  - `OBSERVED`: Successfully queried and parsed.
  - `UNKNOWN`: Partial or ambiguous data.
  - `NOT_COLLECTED`: Not attempted during this collection window.
  - `COLLECTION_FAILED`: Attempted, but command failed or device was unreachable.
- When a router container is stopped (e.g. Scenario F2):
  - The collector emits explicit records with `collection_status = COLLECTION_FAILED` and `event_type = ROUTER_UNAVAILABLE`.
  - The router is represented in `Topology` with `RouterStatus.DOWN`.
  - Other running routers continue to be collected normally.

---

## 5. How to Collect an Evidence Snapshot

### Via Python API
```python
from app.collectors import CollectionOrchestrator, DockerTransport

orchestrator = CollectionOrchestrator(transport=DockerTransport())
snapshot = orchestrator.collect_snapshot(
    include_probes=True,
    include_logs=True,
    log_tail=50,
)

# Persist to evaluation/datasets/observations/
saved_file = orchestrator.save_snapshot(snapshot)
print(f"Snapshot saved to: {saved_file}")
```

### Via CLI Script
```bash
cd backend
uv run python -c "
from app.collectors import CollectionOrchestrator
orch = CollectionOrchestrator()
snap = orch.collect_snapshot()
path = orch.save_snapshot(snap)
print(f'Snapshot {snap.snapshot_id} saved: {snap.total_records} records')
"
```
