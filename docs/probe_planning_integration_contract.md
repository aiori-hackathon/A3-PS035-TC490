# NEXORA — Safe Active Probe Planning Engine Integration Contract (Track B)

**Document Version:** 1.0.0  
**Phase:** 08 — Safe Active Probe Planning  
**Target Audience:** Track B Engineers (MacBook 2 — Dashboard & API Presentation)  
**Track A Owner:** Core Intelligence Engine  

---

## 1. Overview & Purpose

The **Safe Active Probe Planning Engine** answers the key diagnostic question:
> *"What additional read-only observation would best help confirm or distinguish the remaining fault hypotheses?"*

### Critical Architectural Boundary
- **Planning Only:** All generated probe recommendations are strictly **`PROPOSED / NOT EXECUTED`**.
- **No Live Execution:** No active network probes, Docker executions, or router mutations are triggered by this engine.
- **Fail-Closed Safety:** Every recommended probe is verified against the approved topology and safety policy. Probes targeting management interfaces (`eth0`) or outside subnets are rejected.
- **Track B Presentation Mandate:** The dashboard must display these recommendations under the heading **"SAFE NEXT CHECKS"** and must clearly communicate that they are proposed diagnostic steps, not executed actions.

---

## 2. API Data Models & JSON Schemas

All schemas are defined in `app.schemas.probe`.

### 2.1 `ProbePlanReport` (Top-Level Container)

| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `incident_id` | `string` | **Yes** | Identifier of the incident being analyzed. |
| `snapshot_id` | `string \| null` | No | Observation snapshot digest/ID if derived from an archived snapshot. |
| `planned_at` | `string (ISO-8601 UTC)` | **Yes** | Timestamp when the probe plan was computed. |
| `planner_version` | `string` | **Yes** | Engine version (e.g. `"phase08-safe-probe-planner-v1.0"`). |
| `total_probes_evaluated` | `integer` | **Yes** | Count of all candidate probes audited by the planner. |
| `recommended_probes` | `Array<PlannedProbe>` | **Yes** | Ordered list of safe, approved probe recommendations (max 5). |
| `rejected_probes` | `Array<PlannedProbe>` | **Yes** | Probes rejected by safety policy (e.g. management interface target). |
| `unsupported_probes` | `Array<PlannedProbe>` | **Yes** | Probes rejected due to unsupported collector capability. |
| `competing_hypotheses_considered` | `Array<string>` | **Yes** | Hypothesis IDs evaluated for diagnostic discrimination. |
| `ambiguities_addressed` | `Array<string>` | **Yes** | Diagnostic ambiguities analyzed (e.g. F2 Router R3 vs Link L23/L34). |
| `is_abstention` | `boolean` | **Yes** | `true` if no additional safe probe is needed or possible. |
| `abstention_reason` | `string \| null` | No | Explanation when `is_abstention == true`. |
| `summary` | `string` | **Yes** | Plain-language executive summary of the plan. |

---

### 2.2 `PlannedProbe` (Individual Probe Recommendation)

| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `plan_id` | `string` | **Yes** | Deterministic unique plan identifier (e.g. `"plan-a1b2c3d4e5f6"`). |
| `incident_id` | `string` | **Yes** | Incident reference. |
| `probe_request` | `ProbeRequest` | **Yes** | Concrete, validated probe request model. |
| `probe_type` | `string` | **Yes** | `INTERFACE_STATE`, `OSPF_NEIGHBOUR`, `ROUTING_TABLE`, `PING`, `TRACEROUTE`. |
| `source_router` | `string` | **Yes** | Origin router executing the read-only query (`"R1"` - `"R5"`). |
| `target_router` | `string \| null` | No | Target router ID if applicable. |
| `target_address` | `string \| null` | No | Target IPv4 address if applicable (e.g. `"10.0.12.2"`). |
| `target_interface` | `string \| null` | No | Target interface name if applicable (e.g. `"eth1"`, `"eth2"`). |
| `target_prefix` | `string \| null` | No | Destination prefix if applicable (e.g. `"192.168.255.3/32"`). |
| `target_component` | `string` | **Yes** | Topology component ID (`"R3"`, `"L12"`, `"L23"`, etc.). |
| `related_hypothesis_id` | `string \| null` | No | Fault hypothesis ID this probe verifies or refutes. |
| `related_fault_type` | `string \| null` | No | Fault type string (`"ROUTER_FAILURE"`, `"LINK_FAILURE"`, etc.). |
| `selection_reason` | `string` | **Yes** | Human-readable diagnostic reason for selecting this probe. |
| `discriminating_outcomes` | `DiscriminatingOutcomes` | **Yes** | Predicted outcomes and corresponding hypothesis implications. |
| `safety_status` | `string` | **Yes** | `"SAFE"`, `"UNSAFE"`, `"POLICY_VIOLATION"`, `"UNSUPPORTED_CAPABILITY"`. |
| `safety_rationale` | `string` | **Yes** | Audit explanation of safety compliance. |
| `cost` | `ProbeCostEstimate` | **Yes** | Packet count, timeout, RTT overhead, and relative cost score. |
| `priority_score` | `number` | **Yes** | Heuristic utility score `[0.0, 1.0]` representing diagnostic value. |
| `ranking_rationale` | `string` | **Yes** | Transparent explanation of the utility score components. |
| `execution_authorization` | `string` | **Yes** | Always `"PROPOSED_NOT_EXECUTED"`. |

---

### 2.3 `DiscriminatingOutcomes` (Hypothesis Resolution Mapping)

| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `observation_if_true` | `string` | **Yes** | Observation expected if the candidate hypothesis is true. |
| `observation_if_false` | `string` | **Yes** | Observation expected if the candidate hypothesis is false. |
| `hypotheses_supported_if_true` | `Array<string>` | **Yes** | Hypotheses supported if `observation_if_true` occurs. |
| `hypotheses_contradicted_if_true` | `Array<string>` | **Yes** | Hypotheses refuted if `observation_if_true` occurs. |
| `hypotheses_supported_if_false` | `Array<string>` | **Yes** | Hypotheses supported if `observation_if_false` occurs. |
| `hypotheses_contradicted_if_false` | `Array<string>` | **Yes** | Hypotheses refuted if `observation_if_false` occurs. |

---

## 3. UI Display Guidelines for Dashboard (Track B)

1. **Header & Badge:**
   - Display title: **Safe Next Checks**
   - Badge: `PROPOSED / NOT EXECUTED` (Neutral or Blue outline, never Green/Executed).
2. **Priority Ordering:**
   - Probes in `recommended_probes` are already ordered by `priority_score` descending. Display them in the provided sequence.
3. **Discriminating Chips:**
   - For each recommended probe, render two outcome scenarios:
     - **If Observed:** Supports *X*, Contradicts *Y*
     - **If Not Observed:** Supports *Y*, Contradicts *X*
4. **Safety & Cost Indicators:**
   - Show cost badge: e.g. `Low Impact (1.0)` or `Medium Impact (3.0)`.
   - Tooltip displaying `ranking_rationale` and `safety_rationale`.
5. **Abstention State:**
   - When `is_abstention === true`, display:
     - Info Banner: *"No Additional Safe Probes Needed"*
     - Text: `abstention_reason` (e.g. *"All counterfactual expectations are verified; no diagnostic ambiguity remains."*)

---

## 4. Example JSON Response Fixture

```json
{
  "incident_id": "incident-18d4c4764899409f",
  "snapshot_id": "obs-snap-20261019T190307Z-2b4c8c",
  "planned_at": "2026-10-24T15:30:00Z",
  "planner_version": "phase08-safe-probe-planner-v1.0",
  "total_probes_evaluated": 5,
  "recommended_probes": [
    {
      "plan_id": "plan-3b9e4a1f2c8d",
      "incident_id": "incident-18d4c4764899409f",
      "snapshot_id": "obs-snap-20261019T190307Z-2b4c8c",
      "probe_request": {
        "probe_id": "req-9c8b7a6d",
        "incident_id": "incident-18d4c4764899409f",
        "probe_type": "INTERFACE_STATE",
        "source_router": "R2",
        "target_router": null,
        "target_address": null,
        "target_interface": "eth2",
        "target_prefix": null,
        "selection_reason": "Check carrier state of R2 interface eth2 facing R3 to distinguish R3 router failure from physical link cut",
        "timeout_s": 2,
        "requested_at": "2026-10-24T15:30:00Z"
      },
      "probe_type": "INTERFACE_STATE",
      "source_router": "R2",
      "target_router": null,
      "target_address": null,
      "target_interface": "eth2",
      "target_prefix": null,
      "target_component": "L23",
      "related_hypothesis_id": "h-r3",
      "related_fault_type": "ROUTER_FAILURE",
      "selection_reason": "Check carrier state of R2 interface eth2 facing R3 to distinguish R3 router failure from physical link cut",
      "discriminating_outcomes": {
        "observation_if_true": "Peer interface R2 eth2 is UP with carrier present",
        "observation_if_false": "Peer interface R2 eth2 is DOWN with loss of carrier",
        "hypotheses_supported_if_true": ["ROUTER_FAILURE at R3"],
        "hypotheses_contradicted_if_true": ["Physical link cut on L23"],
        "hypotheses_supported_if_false": ["LINK_FAILURE on L23"],
        "hypotheses_contradicted_if_false": ["Pure isolated node outage at R3"]
      },
      "safety_status": "SAFE",
      "safety_rationale": "Read-only diagnostic query within approved topology bounds; fail-closed verified",
      "cost": {
        "packet_count": 1,
        "timeout_s": 2,
        "estimated_rtt_overhead_ms": 5.0,
        "resource_impact": "LOW",
        "relative_cost_score": 1.0
      },
      "priority_score": 0.9850,
      "ranking_rationale": "Utility 0.9850: high discrimination (resolves competing fault hypotheses) [D=1.00]; required observation missing [M=1.00]; immediate adjacent vantage point (hop <= 1) [T=1.00]; cost score 1.0 (LOW impact) [C=0.90].",
      "execution_authorization": "PROPOSED_NOT_EXECUTED"
    }
  ],
  "rejected_probes": [],
  "unsupported_probes": [],
  "competing_hypotheses_considered": ["h-l23", "h-l34", "h-r3"],
  "ambiguities_addressed": [
    "Router-vs-Link ambiguity at R3: Candidate ROUTER_FAILURE(R3) has adjacent links (L23, L34) as competing hypotheses"
  ],
  "is_abstention": false,
  "abstention_reason": null,
  "summary": "Probe planner recommended 5 safe read-only probe(s) to discriminate candidates for ROUTER_FAILURE @ R3. Total relative cost: 7.5 / 20.0."
}
```
