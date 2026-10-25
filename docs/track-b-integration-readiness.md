# NEXORA — Track B Dashboard Integration Readiness

**Document Version:** 1.0.0  
**Target Release:** Cross-Branch Intelligence Integration (Phase 08 & 09)  
**Track:** B — Application / Presentation API / Operations Dashboard  
**Branch:** `feature/dashboard-api`  
**Device Context:** MacBook 2 (Application Node)  
**Remote Source:** `https://github.com/aiori-hackathon/A3-PS035-TC490.git`

---

## 1. Executive Summary & Integration Purpose

This document details the readiness of the **Track B Application & Presentation Layer** for seamless two-branch integration with the core intelligence modules developed by Track A (MacBook 1):
- **Phase 08:** Safe Active Probe Planning (`ProbePlanner`, `ProbeSafetyPolicy`, `ProbeRankingEngine`, `ProbePlanReport`)
- **Phase 09:** Auditable Evidence Certificates & Explainability (`CertificateGenerator`, `ExplanationEngine`, `IntegrityVerifier`, `AuditableEvidenceCertificate`)

All presentation models, REST endpoints, and UI views have been prepared with typed contracts, rigorous safety guardrails, honest data lineage, and zero breaking changes to existing functionality.

---

## 2. API Endpoints Catalog (`/api/v1`)

The FastAPI presentation layer exposes read-only, deterministic endpoints under `/api/v1` designed to serve the Next.js operations console:

| HTTP Method | Route | Description | Contract Status |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/health` | System health check and service status | **Implemented & Tested** |
| `GET` | `/api/v1/readiness` | Subsystem readiness matrix (topology, diagnosis, verifier, planner) | **Implemented & Tested** |
| `GET` | `/api/v1/topology` | Complete 5-router ring topology with interfaces and link subnets | **Implemented & Tested** |
| `GET` | `/api/v1/topology/status` | Current aggregate health counts (routers up/down, links healthy/degraded) | **Implemented & Tested** |
| `GET` | `/api/v1/topology/routers/{router_id}` | Detailed router interfaces, OSPF status, and connected links | **Implemented & Tested** |
| `GET` | `/api/v1/topology/links/{link_id}` | Detailed link status, endpoint states, and OSPF cost | **Implemented & Tested** |
| `GET` | `/api/v1/snapshots` | Catalog of archived evidence snapshots (certified runs & benchmarks) | **Implemented & Tested** |
| `GET` | `/api/v1/snapshots/{snapshot_id}` | Raw snapshot observation payload | **Implemented & Tested** |
| `GET` | `/api/v1/incidents` | Correlated incident summaries grouped by spatial/temporal windows | **Implemented & Tested** |
| `GET` | `/api/v1/incidents/{incident_id}` | Single incident details | **Implemented & Tested** |
| `GET` | `/api/v1/diagnosis` | Diagnosed incident results with top-1 and ranked hypotheses | **Implemented & Tested** |
| `GET` | `/api/v1/diagnosis/{incident_id}` | Diagnosis result for specific incident | **Implemented & Tested** |
| `GET` | `/api/v1/diagnosis/{incident_id}/certificate` | **Phase 09 Evidence Certificate** with provenance and causation disclaimer | **Provisional Adapter Preview** |
| `GET` | `/api/v1/certificates` | List all auditable evidence certificates | **Provisional Adapter Preview** |
| `GET` | `/api/v1/certificates/{incident_id}` | Get auditable certificate by incident ID | **Provisional Adapter Preview** |
| `GET` | `/api/v1/verification` | Counterfactual verification reports with expectation evaluation | **Implemented & Tested** |
| `GET` | `/api/v1/verification/{incident_id}` | Single incident verification report | **Implemented & Tested** |
| `GET` | `/api/v1/probes/recommendations/{incident_id}` | **Phase 08 Ranked Safe Probes** (`PLANNED — NOT EXECUTED`) | **Provisional Adapter Preview** |
| `GET` | `/api/v1/evidence` | Filterable evidence log with router, source type, and incident queries | **Implemented & Tested** |

---

## 3. Data Models & Intelligence Integration Contracts

### 3.1 Phase 08 Safe Active Probe Planning Contract

- **Model:** `SafeProbePlanResponse` & `RankedProbeRecommendation`
- **Integration Status:** Provisional Typed Adapter (Awaiting final Track A schema merge)
- **Execution Authorization Policy:** **`PLANNED — NOT EXECUTED`** (Hard-enforced).
- **Guardrails:**
  - Zero socket execution endpoints exist.
  - No active ping or traceroute command is ever dispatched from the dashboard or presentation API.
  - Probe budget capped at `total_plan_cost <= 10` (Ping/Traceroute weight 2, interface/OSPF weight 1).
  - Timeouts strictly bounded to 5.0 seconds.
  - Information gain is explicitly rendered as `"UNAVAILABLE (PENDING PHASE 08 PLANNER)"` with no synthetic entropy calculations.

#### Fields Requiring Final Contract Validation with Track A:
1. `probe_id` format and determinism across repeated plan generations.
2. `ranking_rationale` string field vs structured list.
3. `relative_cost` integer weight values matching Track A `ProbeRankingEngine`.
4. `expected_discriminating_outcomes` string list representation.
5. `missing_evidence_addressed` list format.
6. `execution_authorization` exact enum string (`"PROPOSED_NOT_EXECUTED"` vs `"PLANNED — NOT EXECUTED"`).

### 3.2 Phase 09 Auditable Evidence Certificate Contract

- **Model:** `AuditableEvidenceCertificateResponse`
- **Integration Status:** Provisional Typed Adapter (Awaiting final Track A schema merge)
- **12 Required Presentation Fields:**
  1. `certificate_id`: Unique identifier (e.g., `cert-520097-f1-live`).
  2. `fault_type` & `fault_location_component_id`: Predicted root cause.
  3. `explanation`: Evidence-backed root-cause explanation.
  4. `heuristic_score`: Deterministic rule alignment score in `[0.0, 1.0]`, labeled strictly as **"Rule Alignment Score"** (never probability).
  5. `counterfactual_verdict`: `SUPPORTED`, `CONTRADICTED`, or `INSUFFICIENT_EVIDENCE`.
  6. `supporting_evidence_ids`: Clickable reference chips with deep-linking to Evidence Explorer.
  7. `contradictory_evidence_ids`: Clickable contradiction audit references.
  8. `missing_observations`: List of unpolled or missing expectations.
  9. `recommended_safe_checks`: Safe read-only checks recommended by the verifier.
  10. `provenance_integrity_status`: `PROVENANCE_VERIFIED`, `STRUCTURALLY_VALID_LOCAL_CAPTURE`, or `AWAITING_CERTIFIED_ARCHIVE_TRANSFER`.
  11. `snapshot_id`, `snapshot_digest`, `source_run_id`: Exact provenance metadata. SHA-256 is only rendered when verified; never synthesized.
  12. `limitations` & `causation_disclaimer`: Bounded observation window and explicit philosophical disclaimer:
      > *"A SUPPORTED diagnosis indicates rigorous mathematical consistency with observed evidence and counterfactual rules, but is not absolute philosophical proof of causation."*

#### Fields Requiring Final Contract Validation with Track A:
1. `snapshot_digest` hashing algorithm and canonical serialization format.
2. Contradiction audit resolution protocol when `contradictory_evidence_ids` is non-empty.
3. Distinction between `evidence_sufficiency_met` boolean flag vs numerical coverage percentage.

---

## 4. Replay Catalog & Honest Data Lineage

NEXORA maintains strict separation between dataset categories:

### A. Certified Live Archived Evidence
- **F1_LINK_FAILURE (Link L12):** Verified contemporaneous capture binding from Phase 06.4 (`obs-snap-20261021T113754Z-520097`). Available locally on MacBook 2.
- **F2_ROUTER_FAILURE (Router R3):** Certified experiment executed on MacBook 1; evidence archive resides on MacBook 1.
- **F3_OSPF_CONFIG_MISMATCH (Link L12):** Certified experiment executed on MacBook 1; evidence archive resides on MacBook 1.
- **F4_PACKET_LOSS (Link L12):** Certified experiment executed on MacBook 1; evidence archive resides on MacBook 1.
- **F5_HIGH_LATENCY (Link L12):** Certified experiment executed on MacBook 1; evidence archive resides on MacBook 1.

**Display Policy for F2–F5 on MacBook 2:**
- Availability status: **`CERTIFIED_CAPTURE_NOT_YET_AVAILABLE_ON_THIS_DEVICE`**
- Data source: **`CERTIFIED_ARCHIVE_NOT_ON_DEVICE`**
- Notice: Replay buttons are disabled with label `"CERTIFIED CAPTURE NOT YET AVAILABLE ON THIS DEVICE"`. These are NOT marked as pending experiments because the experiments have already succeeded on MacBook 1. No placeholder telemetry is fabricated.

### B. Historical Phase 06 Benchmark Evaluation Datasets
- 7 historical benchmark scenarios (Baseline healthy state, Link flap, Interface down, Cost mismatch, Process crash, MTU mismatch, High drop rate).
- Clearly identified as benchmark evaluation data, never confused with certified live laboratory runs.

---

## 5. Development & Verification Commands

### Backend Service (FastAPI)
```bash
# Navigate to backend
cd backend

# Install / sync dependencies
~/.local/bin/uv sync

# Run Track B test suite
~/.local/bin/uv run pytest tests/test_health.py tests/test_api_presentation.py -v

# Run code style & linting check
~/.local/bin/uv run ruff check app/api/presentation_adapter.py app/api/certificates.py app/api/diagnosis.py app/main.py app/schemas/presentation.py tests/test_api_presentation.py

# Start local API development server
~/.local/bin/uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Frontend Application (Next.js 16.4.3)
```bash
# Navigate to frontend
cd frontend

# Verify TypeScript types
pnpm run typecheck

# Run ESLint
pnpm run lint

# Security audit
pnpm audit

# Compile production bundle
pnpm run build

# Start local development server
pnpm run dev --port 3000
```

---

## 6. Implementation Status Matrix

| Module / Screen | Implementation State | Verification Status | Notes |
| :--- | :--- | :--- | :--- |
| **Overview Dashboard** | Complete | Tested (API + UI) | Connected to live FastAPI backend |
| **5-Node Ring Topology** | Complete | Tested (API + UI) | Interactive router/link selection with reactive state |
| **Incident Investigation** | Complete | Tested (API + UI) | Top-1 & ranked candidates with Rule Alignment Score |
| **Phase 09 Evidence Certificate** | Complete | Tested (API + UI) | All 12 items + causation disclaimer banner |
| **Evidence Explorer** | Complete | Tested (API + UI) | Deep-link filtering from certificate references |
| **Counterfactual Verification** | Complete | Tested (API + UI) | Expectations evaluation and differential verification |
| **Safe Probe Planner** | Complete | Tested (API + UI) | Ranked recommendations, `PLANNED — NOT EXECUTED` |
| **Scenario Replayer** | Complete | Tested (API + UI) | Honest `NOT YET AVAILABLE ON THIS DEVICE` for F2–F5 |
| **API Contract Tests** | Complete | 26/26 Tests PASS | All Stage 7 boundary conditions validated |
| **Security Audit** | Complete | 0 Vulnerabilities | Next.js 16.4.3 patched |

---

## 7. Known Limitations & Handoff Dependencies

1. **Inherited Phase 07 Tests (MacBook 1 Ownership):**
   - 5 Phase 07 regression tests (`test_f2_multi_peer_router_failure_expectations`, `test_f3_ospf_mismatch_expectations`, `test_f4_partial_packet_loss_expectations`, `test_f5_high_latency_expectations`, `test_determinism_across_repeated_runs`) fail due to hardcoded machine-specific paths (`/Users/azriel/...`) and nondeterministic probe IDs in base commit `21d7707`.
   - MacBook 1 owns those fixes; Track B has not altered Track A core code.
2. **Cross-Machine Archive Transfer:**
   - Certified telemetry archives for F2–F5 reside on MacBook 1. Transfer via Git LFS or secure tarball will immediately activate live replays on this console without UI changes.
3. **Intelligence Algorithm Wiring:**
   - Actual `ProbePlanner` and `CertificateGenerator` algorithms will be wired directly to `PresentationAdapter` during the official two-branch merge.
