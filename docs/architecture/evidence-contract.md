# NEXORA — Evidence Contract

**Team**: A3-PS035-TC490 | **PS-035** | AIORI Hackathon 3

---

## 1. Purpose

This document defines the contractual rules that govern all evidence data in NEXORA.
Every component that produces, consumes, or stores evidence must comply with these rules.

---

## 2. Evidence Taxonomy

| Evidence Type | Model | Source | Primary / Secondary |
|---------------|-------|--------|---------------------|
| Syslog alarm | `SyslogEvent` | FRR syslog UDP | Primary |
| Interface state | `InterfaceObservation` | FRR interface poll | Primary |
| OSPF adjacency | `OSPFObservation` | FRR OSPF API | Primary |
| Ping result | `PingMeasurement` | Active ICMP probe | Secondary |
| Route observation | `RouteObservation` | FRR routing table | Secondary |

---

## 3. Mandatory Evidence Fields

Every `EvidenceRecord` MUST carry:

| Field | Constraint |
|-------|-----------|
| `evidence_id` | Globally unique, non-empty |
| `source_router` | Must match a router in the current Topology snapshot |
| `event_type` | Non-empty string label |
| `observed_at` | Timezone-aware UTC datetime |
| `collected_at` | Timezone-aware UTC datetime |
| `source_type` | One of the `EvidenceSourceType` enum values |
| `collection_method` | One of the `CollectionMethod` enum values |
| `collection_status` | One of the `ObservationStatus` enum values |

---

## 4. Observation Status Semantics

```
OBSERVED         — Data was collected successfully.
UNKNOWN          — Collection was attempted; result is ambiguous or partial.
NOT_COLLECTED    — Collection was not attempted (out of scope or window).
COLLECTION_FAILED — Collection was attempted and failed with a specific error.
```

**Critical rule**: `NOT_COLLECTED ≠ FAILED ≠ observed failure of the component`.
A router's absence from syslog does not mean it has failed. Missing data is
explicitly represented, never silently treated as negative evidence.

---

## 5. Timestamp Rules

- All timestamps MUST be timezone-aware (UTC, `tzinfo` must not be `None`).
- `observed_at` reflects the device clock, normalised to UTC at collection time.
- `collected_at` reflects the collector's ingestion timestamp.
- Clock skew between device and collector must be documented and bounded.

---

## 6. Raw Data Handling

- `raw_reference` is an opaque audit pointer (e.g. `syslog://R2:514/line-4812`).
- Raw log text stored in `SyslogEvent.raw_message` is opaque string data.
- Raw log text MUST NEVER be parsed as a command, executed, or used to construct
  database queries or shell commands without sanitisation.
- Evidence records never contain ground-truth fault injection labels.

---

## 7. Ping Measurement Contract

`PingMeasurement` carries validated numeric constraints:
- `packet_loss_pct` ∈ [0.0, 100.0] — enforced by Pydantic validator.
- `packets_received` ≤ `packets_sent` — enforced by Pydantic validator.
- `packet_loss_pct` must be consistent with `packets_sent` / `packets_received` (±1% tolerance).
- `rtt_*` fields must be ≥ 0.0 and may be `None` if all packets were lost.

A 100% packet-loss probe result does NOT, by itself, imply a router or link failure.
Corroborating primary evidence (OSPF adjacency loss, interface DOWN syslog) is required.

---

## 8. Double-Counting Risk

A single physical fault (e.g. link R1–R2 fails) generates multiple alarms:
- R1 logs OSPF neighbour-down for R2.
- R2 logs OSPF neighbour-down for R1.
- Syslog events from both routers appear.
- Routing table changes on R1, R2, R3, R4, R5.

The `IncidentCorrelator` MUST group all co-incident alarms into a single `Incident`.
The `RuleBasedDiagnoser` MUST weight these as one fault event, not independent failures.
Counting the same physical fault twice as independent evidence inflates rule_score
and produces spuriously high confidence — this is a documented anti-pattern.

---

## 9. Evidence-to-Hypothesis Linkage

Each `FaultHypothesis` carries:
- `supporting_evidence_ids` — evidence consistent with the hypothesis.
- `contradictory_evidence_ids` — evidence that contradicts the hypothesis.
- A single evidence ID MUST appear in at most one of these lists (enforced by validator).
- Evidence that is irrelevant to a hypothesis is simply omitted from both lists.

---

## 10. Evidence Certificate Auditability

The `EvidenceCertificate` attached to every `DiagnosisResult` documents:
- `total_evidence_count`: how many records were considered.
- `supporting_evidence_count` / `contradictory_evidence_count` for the top-1 hypothesis.
- `collection_coverage_pct`: percentage of planned collection points that were observed.
- `missing_evidence_descriptions`: plain-language descriptions of absent data.
- `score_interpretation`: mandatory disclaimer that `rule_score` is not a probability.
- `reasoning_summary`: human-readable explanation of the key diagnostic steps.
