# NEXORA — System Architecture

**Team**: A3-PS035-TC490 | **PS-035** | AIORI Hackathon 3

---

## 1. Architectural Philosophy

NEXORA replaces purely correlative network-alarm management with a deterministic, evidence-based diagnostic pipeline. The design principle is: **every diagnostic conclusion must be traceable to specific, citable network observations collected before the conclusion was formed**.

The system is a **modular monolith** — all components run in the same Python process and communicate via typed function calls and Pydantic models. No message brokers, microservices, or plugin frameworks are introduced in Phase 01–04.

---

## 2. Mandatory PS-035 Requirements Mapping

| PS-035 Requirement | NEXORA Component / Phase |
|--------------------|--------------------------|
| 5 instrumented network routers | Network Lab (Containerlab/FRR) — Phase 01 |
| 5 reproducible seeded faults | Lab Controller + FaultInjectionRecord — Phase 01 |
| Topology, syslog, ping collection | EvidenceCollector — Phase 02 |
| Rule-based diagnostic baseline | RuleBasedDiagnoser — Phase 02 |
| Ranked Top-1 / Top-3 predictions | DiagnosisResult — Phase 02 |
| Supporting + contradictory evidence | FaultHypothesis — Phase 02 |
| Counterfactual hypothesis verification | CounterfactualVerifier — Phase 03 |
| Bounded read-only probing | ActiveProbePlanner + ProbeRequest — Phase 03 |
| Evidence sufficiency / abstention | EvidenceSufficiencyEvaluator — Phase 03 |
| Held-out diagnostic evaluation | EvaluationEngine — Phase 04 |
| Optional ML comparison | Random Forest (offline only) — Phase 04 |
| Operator-facing dashboard | Next.js frontend — Phase 00 onwards |

---

## 3. Module Responsibilities

### 3.1 Network Lab (`lab/`)
- Five FRRouting containers running OSPFv2, managed by Containerlab.
- Linux `tc/netem` fault injection on host-side veth interfaces.
- Lab Controller scripts inject faults and record FaultInjectionRecords.
- Management plane is isolated on a separate bridge (`192.168.100.0/24`).

### 3.2 Evidence Collector (`app/collectors/`)
- Polls all five routers for OSPF adjacency state, interface state, and routing tables.
- Ingests syslog from an in-process UDP receiver.
- Executes passive collection only during normal operation.
- Records collection status (OBSERVED / NOT_COLLECTED / COLLECTION_FAILED) for every planned observation.

### 3.3 Incident Correlator (`app/correlation/`)
- Groups temporally co-incident alarms from multiple routers into unified Incidents.
- Avoids creating one Incident per alarm when a single fault generates many alarms.
- Identifies potentially affected components (routers, links) from initial signals.

### 3.4 Topology Intelligence (`app/topology/`)
- Maintains the current topology snapshot (Topology model with Routers, Links, Adjacencies).
- Provides graph-theoretic neighbour maps and reachability matrices to hypothesis generation.
- Detects adjacency anomalies by comparing expected vs. observed adjacency state.

### 3.5 Hypothesis Generator (`app/diagnosis/`)
- Uses topology graph + incident evidence to enumerate candidate fault locations.
- Produces FaultHypothesis objects for all five supported FaultTypes.
- Attaches initial evidence references and identifies missing evidence.

### 3.6 Rule-Based Diagnoser (`app/diagnosis/`)
- Applies deterministic, hand-crafted diagnostic rules (Phase 02).
- Assigns rule_score ∈ [0.0, 1.0] to each hypothesis.
- Records reasoning_trace for full auditability.
- Does NOT label scores as probabilities.

### 3.7 Counterfactual Verifier (`app/diagnosis/`)
- Optional. Tests whether the predicted network state under a hypothesis is consistent with observations.
- Updates FaultHypothesis.counterfactual_verified.

### 3.8 Active Probe Planner (`app/probes/`)
- Optional. Plans bounded, read-only additional probes when evidence is insufficient.
- Generates ProbeRequest objects for approved ProbeType values only.
- No arbitrary command execution.

### 3.9 Evidence Sufficiency Evaluator (`app/diagnosis/`)
- Determines DiagnosisStatus: DIAGNOSED, AMBIGUOUS, or INSUFFICIENT_EVIDENCE.
- Abstaining is always valid and preferred over a low-confidence guess.

### 3.10 Evidence Certificate Builder (`app/diagnosis/`)
- Produces EvidenceCertificate: a complete audit record of the diagnostic run.

### 3.11 Evaluation Engine (`app/evaluation/`) — OFFLINE ONLY
- Post-inference comparison of DiagnosisResult against FaultInjectionRecord.
- Computes Top-1 / Top-3 accuracy, abstention rate, and coverage.
- Optional Random Forest comparison uses only training-split FaultInjectionRecords.
- Never feeds ground-truth into live inference.

### 3.12 FastAPI Backend (`app/api/`, `app/main.py`)
- REST API exposing topology snapshots, incident status, diagnosis results, and certificates.
- No API endpoint exposes FaultInjectionRecord labels.
- CORS restricted to configured local frontend origins.

### 3.13 Next.js Frontend (`frontend/`)
- Operator-facing dashboard with topology view, incident list, diagnosis results.
- Displays evidence certificate and reasoning trace.
- Shows "Network lab not configured" when lab is not running.

---

## 4. Data Provenance Model

Every EvidenceRecord carries:
- `source_router`: which router reported it.
- `source_type`: syslog / SNMP / OSPF API / active ping / routing table.
- `collection_method`: passive / periodic poll / triggered probe / manual.
- `collection_status`: OBSERVED / UNKNOWN / NOT_COLLECTED / COLLECTION_FAILED.
- `observed_at` and `collected_at`: both timezone-aware UTC datetimes.
- `raw_reference`: opaque pointer to raw log line (audit only, never executed).

This ensures every diagnostic step can cite the precise observation that contributed to the conclusion.

---

## 5. Primary vs. Secondary Observations

**Primary observations** are direct, first-order network state readings:
- Interface operational status (polled from device).
- OSPF adjacency state (polled from FRR daemon).
- Syslog events from FRR processes.

**Secondary observations** are derived or inferred:
- Routing-table changes inferred from OSPF LSDB diffs.
- Reachability inferred from ping probe results.

Secondary observations are weighted lower in rule scoring because they may reflect consequences rather than root causes. The rule engine must not treat an absent secondary observation as equivalent to an observed failure.

---

## 6. No Automated Remediation

NEXORA produces **diagnostic output only**. The system:
- MUST NOT issue configuration change commands to any router.
- MUST NOT modify OSPF process state.
- MUST NOT restart any network container.
- MUST NOT perform any write operation on the experimental network.

Active probes are strictly read-only (ICMP ping, OSPF show, route table read). This constraint is enforced at the ProbeRequest contract level (no command/script fields exist in the model).

---

## 7. Optional Random Forest Component

A scikit-learn Random Forest (RF) classifier is an **optional, offline-only** comparison model:
- Trained exclusively on historical FaultInjectionRecord + DiagnosisResult pairs.
- Training data is drawn from held-out evaluation datasets only.
- The RF model does NOT participate in live inference.
- RF predictions are compared against rule-based results in evaluation/reports/.
- RF never replaces the mandatory rule-based baseline.
