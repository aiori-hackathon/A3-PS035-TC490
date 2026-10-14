# NEXORA — Security Boundaries

**Team**: A3-PS035-TC490 | **PS-035** | AIORI Hackathon 3

---

## 1. Ground-Truth Isolation Boundary

```
┌─────────────────────────────────────────────────────────┐
│            DIAGNOSTIC INFERENCE PIPELINE                │
│                                                         │
│  EvidenceCollector → IncidentCorrelator               │
│    → HypothesisGenerator → RuleBasedDiagnoser         │
│    → CounterfactualVerifier → ActiveProbePlanner       │
│    → EvidenceSufficiencyEvaluator                     │
│    → EvidenceCertificateBuilder                       │
│    → DiagnosisResult                                  │
│                                                         │
│  ✗ NO ACCESS to FaultInjectionRecord                  │
│  ✗ NO ACCESS to seeded_fault_type                     │
│  ✗ NO ACCESS to actual_fault_location_id              │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼ (post inference only)
┌─────────────────────────────────────────────────────────┐
│              OFFLINE EVALUATION SYSTEM                  │
│                                                         │
│  EvaluationEngine reads:                               │
│   - DiagnosisResult (from inference output store)      │
│   - FaultInjectionRecord (from isolated storage)       │
│                                                         │
│  Produces: BenchmarkReport (evaluation/reports/)       │
│                                                         │
│  ✓ ONLY component allowed to access ground truth       │
│  ✗ DOES NOT feed back to inference pipeline            │
└─────────────────────────────────────────────────────────┘
```

---

## 2. API Endpoint Security

| Endpoint | Exposes Ground Truth? |
|----------|-----------------------|
| `GET /health` | No |
| `GET /api/v1/topology` | No |
| `GET /api/v1/incidents` | No |
| `GET /api/v1/diagnosis/{id}` | No |
| `GET /api/v1/evidence/{id}` | No |
| `GET /api/v1/certificates/{id}` | No |
| `POST /api/v1/probes` | No |
| `GET /api/v1/evaluation/reports` | No (aggregate metrics only) |
| *(no endpoint)* | `FaultInjectionRecord` — never exposed via API |

---

## 3. Probe Safety Boundary

The `ProbeRequest` Pydantic model enforces the probe safety boundary at the
data contract level. The following fields do NOT exist in `ProbeRequest`:

- ❌ `command: str` — no arbitrary shell command execution
- ❌ `arguments: list[str]` — no argument injection
- ❌ `script: str` — no script upload or execution
- ❌ `config_change: str` — no router configuration modification
- ❌ `interface_action: str` — no interface state modification

Only the fields defined in the `ProbeRequest` model may be populated.
The `extra="forbid"` Pydantic configuration rejects any unexpected fields.

---

## 4. Evidence Provenance Boundary

EvidenceRecord.raw_reference is an opaque audit pointer.
It MUST NOT be:
- Executed as a shell command
- Parsed as SQL
- Used to construct file paths for dynamic loading
- Passed to `eval()` or equivalent

EvidenceRecord.raw_message (SyslogEvent) is stored as an opaque string.
It MUST NOT be:
- Executed or interpreted as instructions
- Used to construct queries without full sanitisation

---

## 5. No Remediation Boundary

NEXORA is a **diagnostic-only** system. The following actions are **permanently prohibited**:

- Issuing OSPF configuration commands to any router
- Restarting any FRR daemon or container
- Modifying interface state (bringing interfaces up or down)
- Modifying routing tables
- Executing any write operation on the experimental network

These constraints are enforced by:
1. The ProbeRequest schema (no write-operation fields).
2. The diagnostic engine interface contracts (Protocol classes, no mutation outputs).
3. Code review and CI enforcement (no FRR write-command library imports in diagnosis/).

---

## 6. Management Network Isolation

The management network `192.168.100.0/24` is outside the OSPF experiment topology:
- `mgmt0` on all routers is a passive OSPF interface.
- `192.168.100.0/24` is not redistributed into OSPF.
- Diagnostic SSH/API access uses management network exclusively.
- This prevents management traffic from inadvertently becoming a transit path.

---

## 7. Random Forest Isolation

The optional scikit-learn Random Forest model:
- Is trained ONLY on offline evaluation data (FaultInjectionRecord + DiagnosisResult pairs).
- Training data is the held-out evaluation dataset split, not live diagnostic sessions.
- RF predictions are computed offline and stored in evaluation/reports/.
- No RF inference code executes during live incident diagnosis.
- The RF model file is stored in evaluation/ and is never loaded by app/diagnosis/ code.
