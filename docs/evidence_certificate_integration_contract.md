# NEXORA Evidence Certificate & Explainability Integration Contract (Phase 09)

**Author:** Track A (Core Intelligence)  
**Audience:** Track B (FastAPI Presentation Endpoints & Next.js Dashboard)  
**Schema Version:** `phase09-evidence-certificate-v1.0`  
**Status:** Approved for Integration  

---

## 1. Overview

The **Evidence Certificate** is an operator-facing, cryptographically auditable artifact that consolidates:
1. **Diagnosis Result:** Selected hypothesis, fault location, heuristic rule score, and diagnosis status.
2. **Counterfactual Verification:** Verdict (`SUPPORTED`, `CONTRADICTED`, `INCONCLUSIVE`, `INSUFFICIENT_EVIDENCE`), verified status, and expectations.
3. **Evidence Provenance & References:** Resolved references to raw snapshot observations, separating supporting and contradictory findings.
4. **Active Probe Planning (Phase 08):** Safe next checks (strictly labeled `PROPOSED_NOT_EXECUTED`).
5. **Cryptographic Integrity:** Canonical snapshot SHA-256 digest cross-referenced against capture binding.
6. **Structured Root-Cause Explanation:** Human-readable explanations answering 8 canonical operator questions (WHAT, WHERE, WHY, SUPPORTING, CONTRADICTING, COUNTERFACTUAL, MISSING, SAFE CHECKS).

---

## 2. Pydantic Models & Import Path

All models are defined in Track A:
```python
from app.schemas.certificate import (
    CERTIFICATE_SCHEMA_VERSION,
    AuditableEvidenceCertificate,
    EvidenceReference,
    EvidenceRole,
    IntegrityVerificationResult,
    ProvenanceIntegrityStatus,
    RootCauseExplanation,
)
from app.certificates import (
    CertificateGenerator,
    compute_snapshot_digest,
    verify_snapshot_integrity,
)
```

---

## 3. Schema Fields

### 3.1 `AuditableEvidenceCertificate`

| Field | Type | Required | Description |
|---|---|---|---|
| `certificate_id` | `str` | Yes | Deterministic ID (e.g. `cert-3217b84b98f2fdca`). |
| `schema_version` | `str` | Yes | Fixed string: `"phase09-evidence-certificate-v1.0"`. |
| `created_at` | `datetime` (UTC) | Yes | Time when certificate was issued. |
| `snapshot_id` | `str \| None` | Optional | Identifier of the observation snapshot. |
| `snapshot_digest` | `str \| None` | Optional | Canonical SHA-256 hex digest of the snapshot. |
| `source_run_id` | `str \| None` | Optional | Live capture run ID from binding (e.g. `exp-aab6c8...`). |
| `incident_id` | `str` | Yes | Incident identifier covered by this certificate. |
| `selected_hypothesis_id` | `str \| None` | Optional | ID of top-ranked hypothesis (None if abstained). |
| `fault_type` | `FaultType \| str \| None` | Optional | Fault classification (e.g. `LINK_FAILURE`, `ROUTER_FAILURE`). |
| `fault_location` | `FaultLocation \| str \| None` | Optional | Location component (e.g. link `L12` or router `R3`). |
| `diagnosis_status` | `DiagnosisStatus \| str` | Yes | `DIAGNOSED`, `AMBIGUOUS`, or `INSUFFICIENT_EVIDENCE`. |
| `original_heuristic_score` | `float \| None` | Optional | Heuristic score in `[0.0, 1.0]` (None if abstained). |
| `score_interpretation` | `str` | Yes | Non-probabilistic heuristic score disclaimer. |
| `counterfactual_verdict` | `CounterfactualVerdict \| str \| None` | Optional | `SUPPORTED`, `CONTRADICTED`, `INCONCLUSIVE`, `INSUFFICIENT_EVIDENCE`. |
| `counterfactual_verified` | `bool \| None` | Optional | `True` (SUPPORTED), `False` (CONTRADICTED), or `None`. |
| `supporting_evidence_references` | `list[EvidenceReference]` | Yes | Resolved supporting observation references. |
| `contradictory_evidence_references` | `list[EvidenceReference]` | Yes | Resolved contradictory observation references. |
| `missing_required_observations` | `list[str]` | Yes | Expected observations that were absent. |
| `collector_failures` | `list[str]` | Yes | Collection attempts that failed (`COLLECTION_FAILED`). |
| `evidence_coverage_pct` | `float` | Yes | Percentage of planned points observed (`0.0`–`100.0`). |
| `sufficiency_status` | `str` | Yes | `"SUFFICIENT"`, `"INSUFFICIENT"`, `"ABSTAINED_INSUFFICIENT"`. |
| `safe_probe_recommendations` | `list[PlannedProbe]` | Yes | Proposed read-only checks (`PROPOSED_NOT_EXECUTED`). |
| `explanation` | `RootCauseExplanation` | Yes | Structured 8-question narrative explanation. |
| `limitations` | `list[str]` | Yes | Standard diagnostic and boundary disclaimers. |
| `integrity_result` | `IntegrityVerificationResult` | Yes | Cryptographic digest and reference resolution audit. |

---

### 3.2 `EvidenceReference`

| Field | Type | Description |
|---|---|---|
| `evidence_id` | `str` | Observation record ID. |
| `source_router` | `str` | Router that generated/polled the observation (`R1`–`R5`). |
| `source_interface` | `str \| None` | Interface name if applicable (`eth1`, `eth2`, etc.). |
| `event_type` | `str` | Semantic event label (`INTERFACE_DOWN_OBSERVED`, etc.). |
| `observed_at` | `datetime` (UTC) | Timestamp when event occurred on the device. |
| `role` | `EvidenceRole` | `SUPPORTING`, `CONTRADICTORY`, `COLLECTION_FAILURE`, `NEUTRAL_CONTEXT`. |
| `summary` | `str` | Concise human-readable description of observation. |

---

### 3.3 `IntegrityVerificationResult`

| Field | Type | Description |
|---|---|---|
| `status` | `ProvenanceIntegrityStatus` | Categorical status (see mapping below). |
| `is_authentic` | `bool` | True if snapshot digest matches expected provenance and references resolve. |
| `computed_digest` | `str \| None` | SHA-256 digest computed from snapshot JSON. |
| `expected_digest` | `str \| None` | Expected SHA-256 digest from capture binding. |
| `source_run_id` | `str \| None` | Capture run ID if available. |
| `total_evidence_records_in_snapshot` | `int` | Count of records in snapshot. |
| `total_references_checked` | `int` | Count of evidence IDs verified. |
| `unresolved_reference_ids` | `list[str]` | Any IDs referenced by diagnosis but missing from snapshot. |
| `details` | `str` | Human-readable integrity explanation. |

---

### 3.4 `RootCauseExplanation`

| Field | Type | Description |
|---|---|---|
| `what_happened` | `str` (max 1024) | Summary of detected network defect. |
| `where_located` | `str` (max 512) | Component identifier and type. |
| `why_selected` | `str` (max 2048) | Rationale for hypothesis selection (includes F2 collateral link handling). |
| `supporting_observations_summary` | `str` (max 2048) | Summary of observations supporting the diagnosis. |
| `contradicting_observations_summary` | `str` (max 2048) | Summary of contradictory observations (or "None."). |
| `counterfactual_expectations_summary` | `str` (max 2048) | Summary of expectations evaluated and verdict. |
| `missing_evidence_summary` | `str` (max 2048) | Summary of uncollected expectations or failures. |
| `safe_next_checks_summary` | `str` (max 2048) | Summary of proposed active probes. |
| `full_text` | `str` (max 8192) | Complete narrative combining all 8 sections. |

---

## 4. Categorical Status Mappings for Frontend Display

### 4.1 Provenance Integrity Status (`integrity_result.status`)

| Enum Value | UI Badge Color | Label | Meaning |
|---|---|---|---|
| `VERIFIED_AUTHENTIC` | Green | `CERTIFIED AUTHENTIC` | Cryptographic digest matched binding and all evidence resolved. |
| `VERIFIED_UNBOUND` | Blue | `VERIFIED (UNBOUND)` | Digest computed and evidence resolved; no external binding supplied. |
| `DIGEST_MISMATCH` | Red | `TAMPERED / MISMATCH` | Snapshot payload altered; digest does not match binding. |
| `UNRESOLVED_REFERENCES` | Red | `INVALID EVIDENCE` | Diagnosis references evidence IDs not in the snapshot. |
| `INCOMPLETE_PROVENANCE` | Yellow | `INCOMPLETE` | Snapshot payload is missing or invalid. |

### 4.2 Counterfactual Verdict (`counterfactual_verdict`)

| Enum Value | UI Badge Color | Meaning |
|---|---|---|
| `SUPPORTED` | Green | All required counterfactual expectations matched telemetry. |
| `CONTRADICTED` | Red | One or more counterfactual expectations directly refuted by telemetry. |
| `INCONCLUSIVE` | Amber | Some expectations matched, but key evidence is incomplete without contradiction. |
| `INSUFFICIENT_EVIDENCE` | Grey | Telemetry was missing or uncollected; unable to evaluate expectations. |

---

## 5. UI Presentation Guidelines

1. **PROPOSED / NOT EXECUTED Badge:**
   All entries in `safe_probe_recommendations` MUST display a prominent `PROPOSED / NOT EXECUTED` badge. Do not display probe execution buttons or indicate that probes have been run.

2. **Heuristic Score Disclaimer:**
   Whenever `original_heuristic_score` is displayed, display `score_interpretation` nearby (e.g. tooltip or footnote) clarifying that the score is a deterministic rule weight, NOT a statistical probability.

3. **Collateral Link Handling (F2):**
   When `fault_type == "ROUTER_FAILURE"`, the UI should present adjacent link drops (`L23`, `L34`) as collateral manifestations of the router failure rather than independent faults, following `explanation.why_selected`.

4. **Evidence Reference Links:**
   `supporting_evidence_references` and `contradictory_evidence_references` contain `evidence_id`, `source_router`, and `summary`. Operators can click evidence references to view the underlying telemetry record.

---

## 6. Example JSON Output

```json
{
  "certificate_id": "cert-3217b84b98f2fdca",
  "schema_version": "phase09-evidence-certificate-v1.0",
  "created_at": "2026-10-25T14:15:10.123456Z",
  "snapshot_id": "obs-snap-20261021T113754Z-520097",
  "snapshot_digest": "fcf27ee3289d349e0b74ec8d4fa2e790e2c265e4ae9eab0527ab1d87c58e2b82",
  "source_run_id": "exp-aab6c8bcaad34acfaa7583d3ea391948",
  "incident_id": "incident-obs-snap-20261021T113754Z-520097",
  "selected_hypothesis_id": "hyp-f1-l12-link",
  "fault_type": "LINK_FAILURE",
  "fault_location": {
    "kind": "LINK",
    "component_id": "L12",
    "affected_routers": ["R1", "R2"]
  },
  "diagnosis_status": "DIAGNOSED",
  "original_heuristic_score": 0.75,
  "score_interpretation": "Rule scores are dimensionless heuristic values in [0.0, 1.0] produced by deterministic rules. They are NOT calibrated statistical probabilities.",
  "counterfactual_verdict": "SUPPORTED",
  "counterfactual_verified": true,
  "supporting_evidence_references": [
    {
      "evidence_id": "ev-interface-r1-1792582675753-4cf4f9-eth1",
      "source_router": "R1",
      "source_interface": "eth1",
      "event_type": "INTERFACE_DOWN_OBSERVED",
      "observed_at": "2026-10-21T11:37:55.682678Z",
      "role": "SUPPORTING",
      "summary": "Interface eth1 status observed as down"
    }
  ],
  "contradictory_evidence_references": [],
  "missing_required_observations": [],
  "collector_failures": [],
  "evidence_coverage_pct": 100.0,
  "sufficiency_status": "SUFFICIENT",
  "safe_probe_recommendations": [
    {
      "plan_id": "plan-a1b2c3d4e5f6",
      "probe_type": "INTERFACE_STATE",
      "source_router": "R1",
      "target_component": "L12",
      "selection_reason": "Verify operational carrier state on R1 eth1",
      "priority_score": 0.95,
      "execution_authorization": "PROPOSED_NOT_EXECUTED"
    }
  ],
  "explanation": {
    "what_happened": "Physical link failure detected on L12. Bidirectional traffic was interrupted with loss of interface carrier and corresponding OSPF adjacency drop.",
    "where_located": "LINK L12",
    "why_selected": "Hypothesis LINK_FAILURE at L12 achieved the highest heuristic rule score (0.75) among candidates. Counterfactual verification yielded verdict: SUPPORTED.",
    "supporting_observations_summary": "[R1:eth1] Interface eth1 status observed as down",
    "contradicting_observations_summary": "None. No contradicting observations were recorded.",
    "counterfactual_expectations_summary": "Verdict: SUPPORTED. Evaluated 3 expectation(s): 3 supported, 0 contradicted, 0 missing/uncollected.",
    "missing_evidence_summary": "None. All expected telemetry was successfully collected.",
    "safe_next_checks_summary": "[INTERFACE_STATE] on R1 targeting L12: Verify operational carrier state on R1 eth1 (Priority: 0.95). Note: All recommendations are strictly PROPOSED / NOT EXECUTED.",
    "full_text": "=== NEXORA ROOT-CAUSE EVIDENCE CERTIFICATE EXPLANATION ===\n\n1. WHAT HAPPENED:\n   Physical link failure detected on L12...\n\n2. WHERE LOCATED:\n   LINK L12..."
  },
  "limitations": [
    "Rule scores are dimensionless heuristic values in [0.0, 1.0] produced by deterministic rules; they are not calibrated statistical probabilities.",
    "All safe probe recommendations are proposed next checks and have NOT been executed (strictly PROPOSED_NOT_EXECUTED)."
  ],
  "integrity_result": {
    "status": "VERIFIED_AUTHENTIC",
    "is_authentic": true,
    "computed_digest": "fcf27ee3289d349e0b74ec8d4fa2e790e2c265e4ae9eab0527ab1d87c58e2b82",
    "expected_digest": "fcf27ee3289d349e0b74ec8d4fa2e790e2c265e4ae9eab0527ab1d87c58e2b82",
    "source_run_id": "exp-aab6c8bcaad34acfaa7583d3ea391948",
    "total_evidence_records_in_snapshot": 109,
    "total_references_checked": 5,
    "unresolved_reference_ids": [],
    "details": "Cryptographic snapshot digest matches certified binding and all referenced observations resolve in the snapshot."
  }
}
```
