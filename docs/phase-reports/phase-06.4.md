# PHASE: 06.4 — Live F1 Link Failure Evidence Audit & Certification

**DATE:** 2026-10-21 (Execution) / 2026-10-23 (Independent Audit)  
**STATUS:** AUDITED & CERTIFIED; exact match reproduced offline.  
**BRANCH:** `feature/phase-06-diagnosis`  
**RUN ID:** `exp-aab6c8bcaad34acfaa7583d3ea391948`  
**SNAPSHOT ID:** `obs-snap-20261021T113754Z-520097`  
**CANONICAL SHA-256:** `fcf27ee3289d349e0b74ec8d4fa2e790e2c265e4ae9eab0527ab1d87c58e2b82`  

> [!IMPORTANT]
> **This experiment provides one successful live F1 trial, not a general 100% fault-localisation accuracy claim.**

---

## 1. Experiment Purpose

The objective of Phase 06.4 was to transition from the synthetic rehearsal framework validated in Phase 06.2 to a real-world, supervised fault-injection and evidence-capture trial on the running containerized 5-node FRRouting / OSPF network lab.

The trial specifically tested:
1. Controlled, safe fault injection using `FaultController`.
2. High-fidelity telemetry capture by `LabObserver` across interface states, OSPF neighbor tables, routing tables, and active ping probes.
3. Cryptographic provenance binding separating neutral observation snapshots from ground-truth labels.
4. Clean post-experiment network restoration and baseline recovery verification.
5. Deterministic, explainable offline root-cause diagnosis without ground-truth contamination.

---

## 2. Authorized Scope

Execution was strictly restricted to:
- **Scenario:** `F1_LINK_FAILURE`
- **Target:** Topology link `L12` (interconnecting router `R1` interface `eth1` [10.0.12.1/30] and router `R2` interface `eth1` [10.0.12.2/30]).
- **Network Boundaries:** Approved data interfaces only (`eth1` on `nexora-r1`). Host management interfaces, control plane networks, and other routers (`R3`, `R4`, `R5`) were untouched.
- **Trial Count:** Exactly one single supervised run. Scenarios F2, F3, F4, and F5 were **not** authorized and were **not** executed.

---

## 3. Healthy Baseline

Prior to injection, baseline verification was performed by the capture runner at `2026-10-21T11:37:52.400633+00:00`:
- All 5 FRRouting containers (`nexora-r1` through `nexora-r5`) reported healthy and responsive.
- OSPF neighbor adjacencies were verified in state `FULL` across all 5 topology links.
- Routing tables on all routers were fully populated with loopback routes (`192.168.255.1/32` through `192.168.255.5/32`) and transit subnets.
- End-to-end active ping reachability exhibited 0.0% packet loss.

---

## 4. Actual Execution Timeline (UTC)

| Milestone | Timestamp (UTC) | Delta from Injection |
| --- | --- | --- |
| Baseline Verified | `2026-10-21T11:37:52.400633+00:00` | -0.88s |
| Fault Injection Command Start | `2026-10-21T11:37:53.279748+00:00` | 0.00s |
| Fault Injection Command Completed | `2026-10-21T11:37:53.359838+00:00` | +0.08s |
| Evidence Collection Window Start | `2026-10-21T11:37:53.361745+00:00` | +0.08s |
| Earliest Observation Recorded | `2026-10-21T11:37:55.682678+00:00` | +2.40s |
| Latest Observation Recorded | `2026-10-21T11:38:57.998714+00:00` | +64.72s |
| Latest Evidence Polled/Collected | `2026-10-21T11:39:18.152217+00:00` | +84.87s |
| Evidence Collection Window End | `2026-10-21T11:39:18.153395+00:00` | +84.87s |
| Fault Reset Command Started | `2026-10-21T11:39:18.168540+00:00` | +84.89s |
| Fault Reset Command Completed | `2026-10-21T11:39:18.238717+00:00` | +84.96s |
| Baseline Recovery Confirmed Healthy | `2026-10-21T11:39:24.498574+00:00` | +91.22s |

**Chronology Verification:**
- Evidence collection completed at `11:39:18.153395Z`.
- Reset command was issued at `11:39:18.168540Z` (~15.1 ms *after* collection completed).
- All 103 evidence observations fall strictly within the active fault window (`injection_command_end` to `reset_started_at`).
- All 103 records are classified `FAULT_ACTIVE` by `app.evaluation.timing.audit_timing`.

---

## 5. Fault Manifestation

Fault injection executed `ip link set eth1 down` on `nexora-r1`:
1. **Interface State:** `nexora-r1` interface `eth1` immediately entered state `DOWN`.
2. **OSPF Adjacency:** `nexora-r1` lost neighbor adjacency `2.2.2.2` over `eth1`.
3. **Data Plane:** Bidirectional pings across `10.0.12.1 <-> 10.0.12.2` experienced 100% packet loss.
4. **Transient Asymmetry:** Router `nexora-r2` still reported neighbor `1.1.1.1` as `FULL` during early polling passes because the OSPF dead timer (40s) had not yet expired on the remote peer.

---

## 6. Evidence Collection

A total of **103 evidence records** were captured with 103 unique identifiers:
- **`INTERFACE_POLL` (15 records):** Interface status from all 5 routers (including down state on `R1`'s `eth1`).
- **`OSPF_API` (10 records):** Neighbor states and neighbor IP associations.
- **`ROUTING_TABLE` (74 records):** Forwarding tables across all nodes.
- **`ACTIVE_PING` (4 records):** Explicit probing between endpoint subnets.

**Errors:** 0 collector errors.  
**Missing Measurements:** 1 optional field (`ev-ospf-r1-1792582676207-4e1b54-2-2-2-2: observed OSPF interface configuration unavailable`), correctly documented in provenance without invalidating the run.

---

## 7. Recovery Verification

Following the reset command (`ip link set eth1 up` on `nexora-r1`):
- Convergence polling waited for OSPF adjacencies to reform.
- Post-recovery audit confirmed all 5 links operational, all 5 router IDs active, loopback routes reconverged, and ping packet loss returned to 0.0%.
- Active fault lock was released cleanly (`lab/.active_fault.json` removed).

---

## 8. Snapshot Provenance & Integrity

- **Run ID:** `exp-aab6c8bcaad34acfaa7583d3ea391948`
- **Snapshot ID:** `obs-snap-20261021T113754Z-520097`
- **Canonical SHA-256 Digest:** `fcf27ee3289d349e0b74ec8d4fa2e790e2c265e4ae9eab0527ab1d87c58e2b82`
- **File SHA-256 on Disk:** `e1db683fb316ad9e0fac57302f87ce415a5a9d91635ea2b1e38183e90e446d13`
- **Persistent Archive:** `/Users/azriel/Nexora-backups/live-evidence/f1-exp-aab6c8bcaad34acfaa7583d3ea391948/`
- **Repo-Local Portable Artifacts:**
  - Neutral Telemetry: `evaluation/datasets/observations/live/f1_link_failure_snapshot.json`
  - Evaluation Sidecars: `evaluation/datasets/sidecars/f1-exp-aab6c8bcaad34acfaa7583d3ea391948/{truth,binding,provenance,capture-index}.json`

All digests match byte-for-byte across live run output, persistent backup, and repo-local datasets.

---

## 9. Ground-Truth Isolation

Strict architectural isolation was maintained:
1. `snapshot.json` contains no ground-truth labels, scenario IDs, or expected fault types.
2. Injected truth was serialized to a separate `truth.json` file.
3. The evaluation engine (`backend/app/evaluation/phase06.py`) executes `DiagnosisEngine().diagnose_snapshot_dict(snapshot)` first, completing all inferences before reading `truth.json` or `binding.json`.
4. Ground truth is imported only for scoring accuracy in evaluation sidecars.

---

## 10. Offline Diagnosis Result

Re-diagnosis executed offline using the neutral snapshot dictionary:
- **Status:** `DIAGNOSED`
- **Incident ID:** `incident-8fe433c66ab293e2`
- **Evidence Sufficiency Met:** `True` (103 records examined)
- **Abstention:** `False`
- **Top-1 Hypothesis:**
  - Hypothesis ID: `h-link_failure-l12`
  - Predicted Fault Type: `LINK_FAILURE`
  - Predicted Component: `L12`
  - Affected Routers: `["R1", "R2"]`
  - Final Heuristic Rule Score: `0.75`
- **Evaluation Verdict:** **EXACT MATCH** (Expected: `LINK_FAILURE` at `L12` | Predicted: `LINK_FAILURE` at `L12`).

---

## 11. Full Scoring Breakdown

In accordance with `backend/app/diagnosis/rules.py` (lines 122–143):

$$\text{Final Score} = +0.70 + 0.15 - 0.10 = 0.75$$

| Contribution | Rule Logic | Evidence ID | Explanation |
| :---: | :--- | :--- | :--- |
| **+0.70** | Direct physical interface down family (`0.70` for single endpoint down) | `ev-interface-r1-1792582675753-3ac931-eth1` | Router R1 reported `eth1` state `DOWN`. Repeated polls add no extra weight. |
| **+0.15** | Adjacency-loss family (`0.15` when interface down is present) | `ev-ospf-r1-1792582676207-4e1b54-2-2-2-2` | Non-FULL OSPF adjacency on R1 toward neighbor 2.2.2.2. |
| **-0.10** | Contradictory evidence penalty | `ev-ospf-r2-1792582676407-f541c7-1-1-1-1` | Router R2 still reported adjacency to 1.1.1.1 as `FULL` during initial polling pass due to OSPF dead-timer lag. |

This penalty demonstrates the diagnostic engine's resilience: instead of failing or producing an uncalibrated probability, it deterministically penalizes transient conflicting state while still correctly ranking the true fault location at Top-1.

---

## 12. Supporting and Contradictory Evidence

### Supporting Evidence (2 items)
1. `ev-interface-r1-1792582675753-3ac931-eth1`: Interface `eth1` on `R1` confirmed in `down` state.
2. `ev-ospf-r1-1792582676207-4e1b54-2-2-2-2`: OSPF neighbor `2.2.2.2` unreachable from `R1`.

### Contradictory Evidence (1 item)
1. `ev-ospf-r2-1792582676407-f541c7-1-1-1-1`: OSPF neighbor `1.1.1.1` on `R2` reported `FULL` during early collection window.

---

## 13. Limitations

1. **Single Sample:** This trial confirms one live scenario (F1) on one topology link (L12). It does not validate performance across all fault categories.
2. **Scenarios Pending:** F2 (router crash), F3 (timer mismatch), F4 (packet loss), and F5 (latency) have been validated under synthetic rehearsal (Phase 06.2) but not yet under live supervised execution.
3. **Dead-Timer Asymmetry:** Fast interface down detection on the fault-originating node precedes remote dead-timer expiration on peer routers.
4. **Historical Datasets Untouched:** The five Phase 04 historical captures remain categorized as `NOT EVALUABLE` due to mismatched timestamps.

---

## 14. Reproduction Instructions

To reproduce the audit offline from the repository root:

```bash
# 1. Verify canonical SHA256 digest of neutral snapshot
python3 -c "
import json, hashlib
with open('evaluation/datasets/observations/live/f1_link_failure_snapshot.json') as f:
    snap = json.load(f)
canon = json.dumps(snap, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
print('Canonical SHA256:', hashlib.sha256(canon.encode()).hexdigest())
"

# 2. Run offline evaluation against Phase 06.4 manifest
cd backend
uv run python -m app.evaluation.phase06 \
  --manifest-path ../evaluation/datasets/phase06_4_manifest.json \
  --output-dir ../evaluation/reports/phase06_4

# 3. Run full non-disruptive test suite
uv run pytest -q
```

---

## 15. Final Audit Verdict

| Audit Item | Expected | Verified | Status |
| --- | --- | --- | :---: |
| Run ID | `exp-aab6c8bcaad34acfaa7583d3ea391948` | `exp-aab6c8bcaad34acfaa7583d3ea391948` | PASS |
| Snapshot ID | `obs-snap-20261021T113754Z-520097` | `obs-snap-20261021T113754Z-520097` | PASS |
| Canonical Digest | `fcf27ee3289d349e...` | `fcf27ee3289d349e...` | PASS |
| Evidence Count | 103 records | 103 records (103 unique IDs) | PASS |
| Timing Eligibility | Collection completed before reset | Valid (ended 15.1ms before reset) | PASS |
| Ground-Truth Isolation | Zero truth fields in snapshot | Verified zero label leakage | PASS |
| Top-1 Prediction | `LINK_FAILURE` at `L12` | `LINK_FAILURE` at `L12` | PASS |
| Heuristic Score | 0.75 (+0.70, +0.15, -0.10) | 0.75 (+0.70, +0.15, -0.10) | PASS |
| Baseline Recovery | Full health restoration | Confirmed at 11:39:24 UTC | PASS |

**FINAL AUDIT VERDICT: ACCEPTED & CERTIFIED.**
