# NEXORA — Evidence Normalization and Schema Contracts

**Team**: A3-PS035-TC490 | **PS-035** | Phase 04

---

## 1. Overview

Evidence normalization standardizes raw observation telemetry gathered from diverse sources (FRR vtysh JSON, Linux kernel netlink/iproute2, ICMP probes, Docker logs) into strictly validated Pydantic models.

The normalizer ensures:
1. Complete conformance with Phase 01 evidence schemas (`backend/app/schemas/evidence.py`).
2. Absolute timestamp integrity (timezone-aware UTC).
3. Full provenance tracking (`source_type`, `collection_method`, `raw_reference`).
4. Strict ground-truth isolation.

---

## 2. Schema Mappings

| Observation Stream | Raw Source Format | Normalized Pydantic Model | Key Fields Normalized |
|---|---|---|---|
| Interface States | `ip -j -s link show` | `InterfaceObservation` | `observed_status`, `error_count`, `speed_mbps` |
| OSPF Adjacencies | `vtysh -c 'show ip ospf neighbor json'` | `OSPFObservation` | `neighbour_router_id`, `adjacency_state`, `dead_timer_remaining_s` |
| Routing Table | `vtysh -c 'show ip route json'` | `RouteObservation` | `destination_prefix`, `next_hop_address`, `next_hop_interface`, `route_type`, `metric`, `is_present` |
| Ping Measurements | Linux `ping -c <N> -W <T>` stdout | `PingMeasurement` | `packets_sent`, `packets_received`, `packet_loss_pct`, `rtt_min_ms`, `rtt_avg_ms`, `rtt_max_ms` |
| Traceroute Probes | Linux `traceroute -n` stdout | `TracerouteObservation` | `hops` (`TracerouteHop`), `total_hops`, `destination_reached` |
| Syslog Events | `docker logs --timestamps` | `SyslogEvent` | `severity`, `process_name`, `raw_message` |

---

## 3. Timestamp Invariants

- Every record contains:
  - `observed_at`: When the event occurred on the router or device clock.
  - `collected_at`: When the collector ingested the record.
- Both datetimes must be timezone-aware with `tzinfo == timezone.utc`.
- Naive datetimes are rejected or automatically normalized to UTC.

---

## 4. Ground-Truth Isolation Verification

To prevent circular reasoning in automated diagnostic benchmarks, the diagnostic engine (Phase 05) must never see ground truth in its evidence stream.

`EvidenceNormalizer.assert_no_ground_truth_leakage()` scans all record payloads for forbidden tokens:
- `fault_type`
- `f1_link_failure`
- `f2_router_failure`
- `f3_ospf_config_mismatch`
- `f4_packet_loss`
- `f5_high_latency`
- `seeded_fault`
- `injected_loss`
- `injected_delay`

If any token is detected in diagnosis-facing evidence, `GroundTruthLeakageError` is raised immediately.

---

## 5. Auditing and Provenance

Every normalized record contains:
- `evidence_id`: Globally unique identifier (`ev-<collector>-<router>-<timestamp>-<short_uuid>`).
- `raw_reference`: Opaque audit pointer indicating the exact command or file source (e.g. `vtysh:show ip ospf neighbor json`, `docker://nexora-r1/logs/line-12`).
- Raw log strings in `SyslogEvent.raw_message` are stored strictly as opaque text and are never parsed as commands.
