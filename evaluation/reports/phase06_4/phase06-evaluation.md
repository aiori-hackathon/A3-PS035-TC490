# Phase 06.1 offline evaluation

Engine: phase06-rules-v1.1.
Scores are deterministic heuristics, not calibrated probabilities.

**Valid fault-time results: Top-1 1/1; Top-3 1/1.**
Raw abstentions: 0/1. Coverage and abstention describe completed inference, independent of truth validity.
NOT EVALUABLE cases receive neither accuracy credit nor penalty; correctness is null.
For eligible cases, Top-1 requires an accepted DIAGNOSED root; AMBIGUOUS may retain tentative Top-3 credit. INSUFFICIENT_EVIDENCE abstains at both ranks.

| Case | Declared type/location | Accepted Top-1 | Evaluation | Declared interval timing | Actual capture timing |
| --- | --- | --- | --- | --- | --- |
| f1live001 | LINK_FAILURE / L12 | LINK_FAILURE / L12 | EVALUABLE | FAULT_ACTIVE | FAULT_ACTIVE |

Timing relative to an unbound historical truth record is diagnostic audit information, not proof of the state of the snapshot's own experiment. No missing time is invented.

| Case | Injection → recorded recovery (UTC) | Snapshot window (UTC) | All observations / collections (UTC) |
| --- | --- | --- | --- |
| f1live001 | 2026-10-21T11:37:53.359838+00:00 → 2026-10-21T11:39:24.498574+00:00 | 2026-10-21T11:37:53.361745+00:00 → 2026-10-21T11:39:18.153395+00:00 | 2026-10-21T11:37:55.682678+00:00 → 2026-10-21T11:38:57.998714+00:00 / 2026-10-21T11:37:55.753828+00:00 → 2026-10-21T11:39:18.152217+00:00 |

Declared healthy baseline: 1 diagnosis results; any fault candidate: False; accepted fault: False.
The baseline is a separately declared control, excluded from fault accuracy denominators.

Every inference call and neutral diagnosis artifact write completed before truth or capture bindings were read. No metadata is used to filter or rerun inference.

Exact Top-1/Top-3 correctness requires type AND location in the same hypothesis. The JSON reports type and location correctness separately, plus eligible-case and all-case coverage, timestamp validity, and each real evidence ID's timestamps/roles.

## Limitations

- Supervised single-trial live F1 validation on link L12. Not a claim of 100% multi-fault accuracy.
- Contemporaneous capture binding binds snapshot obs-snap-20261021T113754Z-520097 to controller run exp-aab6c8bcaad34acfaa7583d3ea391948.
- Reset began after observation window completed; recovery was confirmed healthy.

## Per-snapshot reasoning

### Case f1live001

Top-3: LINK_FAILURE / L12 (0.750).

- DIAGNOSED using 103 evidence records; represented collection coverage 100.00%: DIAGNOSED. Leading candidate LINK_FAILURE at L12, heuristic score 0.75. +0.70: Direct physical interface down family; repeated polls add no weight. Evidence: [ev-interface-r1-1792582675753-3ac931-eth1]. +0.15: Adjacency-loss family; dependent on physical state when present. Evidence: [ev-ospf-r1-1792582676207-4e1b54-2-2-2-2]. -0.10: FULL adjacency conflicts with persistent link loss; dead-timer lag possible. Evidence: [ev-ospf-r2-1792582676407-f541c7-1-1-1-1]. Scores are heuristic alignment values, not calibrated probabilities.

