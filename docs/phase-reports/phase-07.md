# PHASE: 07 — COUNTERFACTUAL VERIFICATION ENGINE

Date: 2026-10-24. Branch: `feature/phase-06-diagnosis`.
Base commit: `88e6af9`.

## STATUS

Phase 07 implementation is COMPLETE.
All 16 new Phase 07 tests pass (100%).
All 580 backend offline regression tests pass (100%).
Ruff check passes cleanly on all Phase 07 schemas, engines, and tests.
Zero regressions in previous diagnostic behavior or scoring.
Zero live network mutations or fault injections executed.
Read-only lab safety maintained throughout.

---

## 1. ARCHITECTURE

The Counterfactual Verification Engine fulfills the question:
> *"If this hypothesis were true, what network observations should we expect? Which expectations are supported, contradicted, missing or ambiguous?"*

### Component Hierarchy
- **`app.schemas.counterfactual`**: Domain models defining `CounterfactualVerdict`, `ExpectationCategory`, `Criticality`, `ObservationMatch`, `ExpectedObservation`, `EvaluatedExpectation`, `CounterfactualVerificationResult`, and `VerificationReport`.
- **`app.verification.expectations.ExpectationGenerator`**: Topology-aware generator that constructs falsifiable, dynamic expectation sets for candidate hypotheses based on router connectivity, incident links, and loopback addresses.
- **`app.verification.engine.CounterfactualVerificationEngine`**: Implements the `CounterfactualVerifier` protocol. Compares expected observations against neutral evidence snapshots without ground-truth contamination, separates verification verdicts from Phase 06 heuristic rule scores, and evaluates both top-ranked candidates and competing hypotheses.
- **`app.verification`**: Public API exporting the engine, generator, and schemas.

---

## 2. COUNTERFACTUAL EXPECTATION RULES

For each fault class, dynamic, topology-aware expectations are defined:

### A. LINK_FAILURE (Target: Link)
1. **Physical Interface State** (`REQUIRED`): Physical carrier on the affected endpoint interface observed DOWN. Carrier persistence on the remote veth peer is recorded as an asymmetric observation, not a contradiction.
2. **OSPF Adjacency Loss** (`REQUIRED`): OSPF adjacency non-FULL on at least one endpoint. A peer remaining Full during dead-timer lag (~40s) is handled as protocol lag, not contradiction.
3. **Reachability Failure** (`CONFIRMATORY`): Direct IP ping reachability across the link fails (100% packet loss).

### B. ROUTER_FAILURE (Target: Router)
1. **Router Unavailability** (`REQUIRED`): Router is unresponsive to management/telemetry polling (`ROUTER_UNAVAILABLE` or collection failures).
2. **Incident Peer OSPF Loss** (`REQUIRED`): All incident neighbor routers lose OSPF adjacencies to the failed router (either explicitly reporting Down or dropping the neighbor from the OSPF table after dead-timer expiry).
3. **Loopback Reachability Failure** (`CONFIRMATORY`): Ping probes to the router's loopback address fail (100% packet loss).

### C. OSPF_CONFIGURATION_MISMATCH (Target: Link)
1. **Physical Interfaces UP** (`REQUIRED`): Physical carrier observed UP on both endpoint interfaces (control plane failure, not physical sever).
2. **OSPF Adjacency Non-FULL** (`REQUIRED`): OSPF adjacency state machine does not converge to FULL (Down, Init, 2-Way, or missing).
3. **Data Plane Reachable** (`CONFIRMATORY`): Direct IP ping reachability succeeds (packet loss < 100%).
4. **Parameter Incompatibility** (`CONFIRMATORY`): Direct timer or area configuration disagreement (or behavioral inference when raw config files are absent).

### D. PACKET_LOSS (Target: Link)
1. **Physical Interfaces UP** (`REQUIRED`): Both endpoint interfaces observed UP.
2. **Partial Packet Loss** (`REQUIRED`): Measured packet loss on traversing pings is partial (5.0% <= loss < 100.0%).
3. **Normal RTT** (`CONFIRMATORY`): Average RTT on successfully received packets remains within normal bounds (< 10.0ms).
4. **OSPF Adjacency FULL** (`CONFIRMATORY`): OSPF adjacency remains FULL because periodic hellos survive moderate packet dropping.

### E. HIGH_LATENCY (Target: Link)
1. **Physical Interfaces UP** (`REQUIRED`): Both endpoint interfaces observed UP.
2. **Elevated RTT** (`REQUIRED`): Measured average round-trip time is elevated (RTT >= 10.0ms, netem queueing delay).
3. **Negligible Packet Loss** (`CONFIRMATORY`): Measured packet loss remains negligible (< 5.0%).
4. **OSPF Adjacency FULL** (`CONFIRMATORY`): OSPF adjacency remains FULL (sub-second artificial delay does not exceed the 40s dead timer).

---

## 3. VERIFICATION VERDICT SEMANTICS

- **`SUPPORTED`**: All `REQUIRED` counterfactual expectations matched observed evidence with zero contradictions (`counterfactual_verified = True`).
- **`CONTRADICTED`**: One or more key expectations directly refuted by observed evidence (`counterfactual_verified = False`).
- **`INSUFFICIENT_EVIDENCE`**: Required observations are absent or failed collection without a clear contradiction (`counterfactual_verified = None`). Safe, bounded probe recommendations (`ProbeRequest`) are generated.
- **`INCONCLUSIVE`**: Observations are ambiguous, mixed, or non-overlapping in time (`counterfactual_verified = None`).

Missing telemetry is NEVER interpreted as proof that a predicted fault did not occur.

---

## 4. EVIDENCE HANDLING & GROUND TRUTH ISOLATION

- **Distinction of OBSERVED vs COLLECTION_FAILED**: Records with `COLLECTION_FAILED` are isolated into failures/unavailability metrics and are never used to prove healthy interface state or operational adjacency.
- **Incident Window Filtering**: Stale observations outside the `(collection_window_start, collection_window_end)` window are excluded from hypothesis matching.
- **Zero Ground-Truth Leakage**: Snapshots are validated through `EvidenceNormalizer.assert_no_ground_truth_leakage()`. Ground-truth files (`truth.json`) are never loaded or referenced during inference or verification.

---

## 5. CERTIFIED RESULTS ON LIVE SCENARIOS (F1–F5)

Evaluated directly against immutable certified live evidence snapshots:

| Scenario | Candidate Hypothesis | Score | Verdict | Counterfactual Verified | Supporting Records | Contradicting Records | Competing Hypotheses Verdicts |
|---|---|---|---|---|---|---|---|
| **F1** | `LINK_FAILURE @ L12` | 0.75 | **SUPPORTED** | **True** | 4 | 0 | `OSPF_CONFIGURATION_MISMATCH (CONTRADICTED)`<br>`PACKET_LOSS (CONTRADICTED)`<br>`HIGH_LATENCY (CONTRADICTED)` |
| **F2** | `ROUTER_FAILURE @ R3` | 1.00 | **SUPPORTED** | **True** | 16 | 0 | `OSPF_CONFIGURATION_MISMATCH @ L23 (CONTRADICTED)`<br>`OSPF_CONFIGURATION_MISMATCH @ L34 (CONTRADICTED)`<br>`LINK_FAILURE @ L23 (SUPPORTED locally)`<br>`LINK_FAILURE @ L34 (SUPPORTED locally)` |
| **F3** | `OSPF_CONFIG_MISMATCH @ L12` | 0.80 | **SUPPORTED** | **True** | 8 | 0 | `LINK_FAILURE (CONTRADICTED)`<br>`PACKET_LOSS (CONTRADICTED)`<br>`HIGH_LATENCY (CONTRADICTED)` |
| **F4** | `PACKET_LOSS @ L12` | 0.65 | **SUPPORTED** | **True** | 8 | 0 | `LINK_FAILURE (CONTRADICTED)`<br>`OSPF_CONFIG_MISMATCH (CONTRADICTED)`<br>`HIGH_LATENCY (CONTRADICTED)` |
| **F5** | `HIGH_LATENCY @ L12` | 0.65 | **SUPPORTED** | **True** | 8 | 0 | `LINK_FAILURE (CONTRADICTED)`<br>`OSPF_CONFIG_MISMATCH (CONTRADICTED)`<br>`PACKET_LOSS (CONTRADICTED)` |

---

## 6. COMPETING HYPOTHESIS & NEGATIVE TEST CASES

- **Competing Alternatives Disproven**: For F1, F3, F4, and F5, all 3 competing alternative fault types on link L12 are deterministically refuted (`CONTRADICTED`), demonstrating clear differentiation between plausible hypotheses and well-supported diagnoses.
- **Multi-Failure Subsumption in F2**: In F2, isolated link failures on L23 and L34 are individually supported on a single-link basis, but router failure at R3 unifies and explains both peer adjacency drops, router unresponsiveness, and lack of carrier.
- **Negative Cases**:
  - Healthy interfaces/FULL adjacencies directly contradict `LINK_FAILURE`.
  - Missing telemetry produces `INSUFFICIENT_EVIDENCE` and outputs safe, bounded probe requests.
  - Asymmetric carrier persistence and dead-timer lag are correctly recognized as protocol lag without falsely contradicting physical link failures.
  - Stale evidence outside the collection window is safely pruned.

---

## 7. TEST SUITE & VALIDATION SUMMARY

- **Phase 07 Unit Tests**: 16/16 passed (`backend/tests/test_phase07_counterfactual.py`)
- **Phase 05 Correlation Tests**: 113/113 passed (`backend/tests/test_phase05_correlation.py`)
- **Phase 06 Diagnosis Tests**: 123/123 passed (`backend/tests/test_phase06_diagnosis.py`)
- **F2 Hardening Tests**: 10/10 passed (`backend/tests/test_f2_manifestation_hardening.py`)
- **Total Offline Backend Suite**: 580/580 passed.
- **Ruff Linting**: Clean across all Phase 07 modules.

---

## 8. KNOWN LIMITATIONS

1. **FRR Interface Configuration Telemetry**: Direct inspection of FRR configuration parameters (e.g. `ip ospf hello-interval`) relies on behavioral inference when explicit running-config command records are not polled.
2. **Read-Only Telemetry**: Active probe generation outputs structured `ProbeRequest` objects but does not automatically execute network mutations against live lab containers (by design in Phase 07).
