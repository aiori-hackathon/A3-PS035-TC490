# NEXORA — Diagnostic Contract

**Team**: A3-PS035-TC490 | **PS-035** | AIORI Hackathon 3

---

## 1. Purpose

This document defines the contractual rules for the diagnostic pipeline output:
`DiagnosisResult`, `EvidenceCertificate`, `RankedHypothesis`, and `FaultHypothesis`.

---

## 2. Mandatory Processing Order

The diagnostic pipeline MUST execute in this exact order:

```
1. Collect evidence         (EvidenceCollector)
2. Correlate alarms         (IncidentCorrelator)
3. Build topology context   (TopologyIntelligence)
4. Generate hypotheses      (HypothesisGenerator)
5. Score and rank           (RuleBasedDiagnoser)
   [Optional: CounterfactualVerifier]
   [Optional: ActiveProbePlanner → re-collect → re-score]
6. Evaluate sufficiency     (EvidenceSufficiencyEvaluator)
7. Build certificate        (EvidenceCertificateBuilder)
8. Produce DiagnosisResult  (pipeline output)
```

No step may skip evidence collection and proceed directly to diagnosis.
No step may access ground-truth labels.

---

## 3. Fault Type Taxonomy

| FaultType | Description |
|-----------|-------------|
| `LINK_FAILURE` | Physical or virtual link is down; OSPF adjacency lost on both endpoints |
| `ROUTER_FAILURE` | Router container/process is unresponsive; all its adjacencies lost |
| `OSPF_CONFIGURATION_MISMATCH` | OSPFv2 parameter mismatch (area, timers) blocking adjacency formation |
| `PACKET_LOSS` | Partial packet loss on a link (tc/netem loss injection) |
| `HIGH_LATENCY` | Elevated RTT on a link (tc/netem delay injection) |

---

## 4. Rule Score Semantics

`FaultHypothesis.rule_score` ∈ [0.0, 1.0]:
- Produced by the deterministic rule-based engine.
- Higher values indicate stronger alignment between evidence and hypothesis.
- **NOT a calibrated statistical probability.**
- Must not be presented to operators as "87% confident".
- `EvidenceCertificate.score_interpretation` embeds this disclaimer.

---

## 5. Ranked Hypothesis Contract

`DiagnosisResult.ranked_hypotheses`:
- Ordered by descending `rule_score`.
- `rank` values are sequential integers starting at 1.
- No duplicate ranks.
- `top1_hypothesis` = ranked_hypotheses[rank=1].hypothesis (or None if abstaining).
- `top3_hypotheses` ⊆ ranked_hypotheses (IDs must match).

---

## 6. Diagnosis Status Contract

| Status | Condition | top1_hypothesis |
|--------|-----------|-----------------|
| `DIAGNOSED` | Top hypothesis score exceeds sufficiency threshold; strong supporting evidence | set |
| `AMBIGUOUS` | Top-2 hypotheses scores are within a narrow band; insufficient separation | None or set |
| `INSUFFICIENT_EVIDENCE` | Evidence coverage below minimum threshold; system abstains | MUST be None |

Abstaining (`INSUFFICIENT_EVIDENCE`) is **correct and expected** behaviour when evidence is
incomplete. The system MUST NOT fabricate a diagnosis to avoid abstention.

---

## 7. Counterfactual Verification Contract

For hypothesis H with suspected fault location F:
1. Predict: "If F were faulty, what OSPF/interface state would we expect to observe?"
2. Compare: Does the predicted state match the observed `EvidenceRecord` collection?
3. Set: `H.counterfactual_verified = True` if prediction matches; `False` if it contradicts.

A hypothesis that passes counterfactual verification receives a scoring bonus.
A hypothesis that fails counterfactual verification should be demoted in ranking.

The verifier MUST NOT assume a hypothesis is correct simply because some predicted
observations match — other hypotheses may produce the same predictions.

---

## 8. Active Probe Constraints

During active probing (Phase 03):
- Maximum probes per diagnostic session: **10** (configurable, bounded).
- Maximum probe timeout: **30 seconds** (enforced in ProbeRequest.timeout_s).
- Allowed probe types: PING, INTERFACE_STATE, OSPF_NEIGHBOUR, ROUTING_TABLE, TRACEROUTE.
- Source must be a known topology router.
- Target must be a known topology address or component.
- Probes MUST NOT modify any router state.

---

## 9. Evidence Sufficiency Threshold

The `EvidenceSufficiencyEvaluator` checks:
1. At least N primary evidence records have been collected (N configurable).
2. Collection coverage ≥ X% of planned polling points (X configurable).
3. The top hypothesis score exceeds the DIAGNOSED threshold by at least Δ above the second hypothesis score.

If any of these conditions fails, status is either `AMBIGUOUS` or `INSUFFICIENT_EVIDENCE`.
Specific threshold values are defined in `app/core/config.py` (Phase 02).

---

## 10. Evidence Certificate Requirements

Every `DiagnosisResult` MUST carry an `EvidenceCertificate`.
The certificate MUST be produced by `EvidenceCertificateBuilder`.
The certificate MUST include:
- `total_evidence_count` ≥ 0 (zero is valid and means INSUFFICIENT_EVIDENCE).
- `score_interpretation` with the disclaimer string.
- `evidence_sufficiency_met` = True only if status is DIAGNOSED or AMBIGUOUS with evidence.
- `reasoning_summary` ≥ 1 character.
