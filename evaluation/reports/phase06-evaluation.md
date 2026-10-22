# Phase 06.1 offline evaluation

Engine: phase06-rules-v1.1.
Scores are deterministic heuristics, not calibrated probabilities.

**Valid fault-time results: Top-1 N/A; Top-3 N/A (zero evaluable fault-active cases).**
Raw abstentions: 3/5. Coverage and abstention describe completed inference, independent of truth validity.
NOT EVALUABLE cases receive neither accuracy credit nor penalty; correctness is null.
For eligible cases, Top-1 requires an accepted DIAGNOSED root; AMBIGUOUS may retain tentative Top-3 credit. INSUFFICIENT_EVIDENCE abstains at both ranks.

| Case | Declared type/location | Accepted Top-1 | Evaluation | Declared interval timing | Actual capture timing |
| --- | --- | --- | --- | --- | --- |
| 001 | LINK_FAILURE / L12 | LINK_FAILURE / L12 | NOT EVALUABLE | POST_FAULT_RECOVERY | UNKNOWN_TIMING |
| 002 | ROUTER_FAILURE / R3 | abstained | NOT EVALUABLE | POST_FAULT_RECOVERY | UNKNOWN_TIMING |
| 003 | OSPF_CONFIGURATION_MISMATCH / L12 | OSPF_CONFIGURATION_MISMATCH / L23 | NOT EVALUABLE | POST_FAULT_RECOVERY | UNKNOWN_TIMING |
| 004 | PACKET_LOSS / L12 | abstained | NOT EVALUABLE | POST_FAULT_RECOVERY | UNKNOWN_TIMING |
| 005 | HIGH_LATENCY / L12 | abstained | NOT EVALUABLE | POST_FAULT_RECOVERY | UNKNOWN_TIMING |

Timing relative to an unbound historical truth record is diagnostic audit information, not proof of the state of the snapshot's own experiment. No missing time is invented.

| Case | Injection → recorded recovery (UTC) | Snapshot window (UTC) | All observations / collections (UTC) |
| --- | --- | --- | --- |
| 001 | 2026-10-19T17:41:57.028066+00:00 → 2026-10-19T17:42:25.371909+00:00 | 2026-10-19T19:02:30.600078+00:00 → 2026-10-19T19:02:53.429499+00:00 | 2026-10-19T19:02:31.342453+00:00 → 2026-10-19T19:02:53.374021+00:00 / 2026-10-19T19:02:31.342453+00:00 → 2026-10-19T19:02:53.374021+00:00 |
| 002 | 2026-10-19T17:42:31.297851+00:00 → 2026-10-19T17:43:16.982044+00:00 | 2026-10-19T19:03:07.012477+00:00 → 2026-10-19T19:03:41.721427+00:00 | 2026-10-19T19:03:07.641848+00:00 → 2026-10-19T19:03:37.624131+00:00 / 2026-10-19T19:03:07.641848+00:00 → 2026-10-19T19:03:37.624131+00:00 |
| 003 | 2026-10-19T17:43:22.957189+00:00 → 2026-10-19T17:43:45.611653+00:00 | 2026-10-19T19:04:31.157356+00:00 → 2026-10-19T19:04:33.308318+00:00 | 2026-10-19T19:04:31.940727+00:00 → 2026-10-19T19:04:32.776001+00:00 / 2026-10-19T19:04:31.940727+00:00 → 2026-10-19T19:04:32.776001+00:00 |
| 004 | 2026-10-19T17:43:51.306002+00:00 → 2026-10-19T17:44:13.914922+00:00 | 2026-10-19T19:04:46.515605+00:00 → 2026-10-19T19:05:09.303489+00:00 | 2026-10-19T19:04:47.245777+00:00 → 2026-10-19T19:05:09.242410+00:00 / 2026-10-19T19:04:47.245777+00:00 → 2026-10-19T19:05:09.242410+00:00 |
| 005 | 2026-10-19T17:44:19.743440+00:00 → 2026-10-19T17:44:40.006315+00:00 | 2026-10-19T19:05:36.973133+00:00 → 2026-10-19T19:06:00.084419+00:00 | 2026-10-19T19:05:37.697671+00:00 → 2026-10-19T19:06:00.027933+00:00 / 2026-10-19T19:05:37.697671+00:00 → 2026-10-19T19:06:00.027933+00:00 |

Declared healthy baseline: 1 diagnosis results; any fault candidate: False; accepted fault: False.
The baseline is a separately declared control, excluded from fault accuracy denominators.

Every inference call and neutral diagnosis artifact write completed before truth or capture bindings were read. No metadata is used to filter or rerun inference.

Exact Top-1/Top-3 correctness requires type AND location in the same hypothesis. The JSON reports type and location correctness separately, plus eligible-case and all-case coverage, timestamp validity, and each real evidence ID's timestamps/roles.

## Limitations

- The original recorded snapshot serialisation retained base evidence fields but dropped typed ping/RTT/OSPF metrics. Event names are not substitutes for missing measurement values; valid abstentions are expected.
- These are unverified historical scenario associations, not shared-run capture bindings: Phase03 truth precedes every Phase04 snapshot by about 80 minutes. Actual Phase04 injection/reset/recovery timestamps are missing. All five cases are NOT EVALUABLE.
- Phase04 documentation describes different targets/parameters for F3 (L23, hello5/dead20), F4 (25% loss), and F5 (L23, 150ms delay) than the older Phase03 records. The original truth is preserved, not relabelled to match predictions.
- The Phase03 recovery timestamp follows reset and convergence polling; it is not the reset-command timestamp. A future capture binding must record reset_started_at separately. No historical binding or missing timestamp has been fabricated.
- 5/5 cases are NOT EVALUABLE. Fault accuracy excludes them; additional aligned, lossless recordings with contemporaneous capture/run bindings are required.

## Per-snapshot reasoning

### Case 001

Top-3: LINK_FAILURE / L12 (0.750).

- DIAGNOSED using 109 evidence records; represented collection coverage 66.67%: DIAGNOSED. Leading candidate LINK_FAILURE at L12, heuristic score 0.75. +0.70: Direct physical interface down family; repeated polls add no weight. Evidence: [ev-interface-r1-1792436551406-969e5a-eth1]. +0.15: Adjacency-loss family; dependent on physical state when present. Evidence: [ev-ospf-r1-1792436551755-416549-2-2-2-2]. -0.10: FULL adjacency conflicts with persistent link loss; dead-timer lag possible. Evidence: [ev-ospf-r2-1792436551863-64d429-1-1-1-1]. Scores are heuristic alignment values, not calibrated probabilities.
- Missing or mismatched capture binding (run ID, snapshot ID, canonical SHA256); scenario names and filenames do not establish a shared experiment.
- A valid reset_started_at boundary is required to exclude restoration polling.
- Collection window is POST_FAULT_RECOVERY relative to declared truth.
- Not all observation and collection timestamps are fault-active.
- Actual capture timing is UNKNOWN_TIMING; fault-active evidence is unverified.

### Case 002

Top-3: no sufficient ranking.

- INSUFFICIENT_EVIDENCE using 100 evidence records; represented collection coverage 64.00%: INSUFFICIENT_EVIDENCE. Leading candidate ROUTER_FAILURE at R3, heuristic score 0.40. +0.55: Router availability family (all collector failures capped together). Evidence: [ev-interface-r3-1792436587781-57860c-eth1, ev-interface-r3-1792436587781-70d330-eth2, ev-interface-r3-1792436587781-fa32ce-lo, ev-ospf-r3-1792436588128-4fd10c-2-2-2-2, ev-ospf-r3-1792436588128-db12dc-4-4-4-4, ev-ping-r3-1792436597972-6d6fa0-to-192-168-255-4, ev-routing-r3-1792436588601-010cea-192-168-255-5-32, ev-routing-r3-1792436588601-041cf4-192-168-255-1-32, … (12 IDs total)]. -0.15: Peers still report FULL; may reflect dead-timer lag, but conflicts remain. Evidence: [ev-ospf-r2-1792436588105-6c80a9-3-3-3-3, ev-ospf-r4-1792436588252-ded1aa-3-3-3-3]. Scores are heuristic alignment values, not calibrated probabilities.
  Missing: Independent peer adjacency or reachability loss corroboration.; Leading rule score below 0.65.; Too few independent primary observation points: 1/2.
- Missing or mismatched capture binding (run ID, snapshot ID, canonical SHA256); scenario names and filenames do not establish a shared experiment.
- A valid reset_started_at boundary is required to exclude restoration polling.
- Collection window is POST_FAULT_RECOVERY relative to declared truth.
- Not all observation and collection timestamps are fault-active.
- Actual capture timing is UNKNOWN_TIMING; fault-active evidence is unverified.

### Case 003

Top-3: OSPF_CONFIGURATION_MISMATCH / L23 (0.700).

- DIAGNOSED using 101 evidence records; represented collection coverage 80.00%: DIAGNOSED. Leading candidate OSPF_CONFIGURATION_MISMATCH at L23, heuristic score 0.70. +0.40: Non-FULL OSPF adjacency on this topology link. Evidence: [ev-ospf-r2-1792436672457-24ec6b-3-3-3-3]. +0.40: Physical state family: UP endpoints distinguish protocol from link fault. Evidence: [ev-interface-r2-1792436672059-c958e5-eth2, ev-interface-r3-1792436672119-e12407-eth1]. -0.10: FULL observation conflicts with persistent adjacency mismatch. Evidence: [ev-ospf-r3-1792436672560-ebea07-2-2-2-2]. Scores are heuristic alignment values, not calibrated probabilities.
  Missing: Observed OSPF area/hello/dead/authentication parameters to confirm mismatch; UP plus adjacency loss is a heuristic explanation, not parameter verification.
- Missing or mismatched capture binding (run ID, snapshot ID, canonical SHA256); scenario names and filenames do not establish a shared experiment.
- A valid reset_started_at boundary is required to exclude restoration polling.
- Collection window is POST_FAULT_RECOVERY relative to declared truth.
- Not all observation and collection timestamps are fault-active.
- Actual capture timing is UNKNOWN_TIMING; fault-active evidence is unverified.

### Case 004

Top-3: no sufficient ranking.

- INSUFFICIENT_EVIDENCE using 111 evidence records; represented collection coverage 66.67%: INSUFFICIENT_EVIDENCE. No evidence-supported fault candidate was generated. Scores are heuristic alignment values, not calibrated probabilities.
  Missing: No supported fault candidate. Healthy observations do not imply a fault; untyped measurements or absent data cannot establish network health.
- Missing or mismatched capture binding (run ID, snapshot ID, canonical SHA256); scenario names and filenames do not establish a shared experiment.
- A valid reset_started_at boundary is required to exclude restoration polling.
- Collection window is POST_FAULT_RECOVERY relative to declared truth.
- Not all observation and collection timestamps are fault-active.
- Actual capture timing is UNKNOWN_TIMING; fault-active evidence is unverified.

### Case 005

Top-3: no sufficient ranking.

- INSUFFICIENT_EVIDENCE using 111 evidence records; represented collection coverage 66.67%: INSUFFICIENT_EVIDENCE. No evidence-supported fault candidate was generated. Scores are heuristic alignment values, not calibrated probabilities.
  Missing: No supported fault candidate. Healthy observations do not imply a fault; untyped measurements or absent data cannot establish network health.
- Missing or mismatched capture binding (run ID, snapshot ID, canonical SHA256); scenario names and filenames do not establish a shared experiment.
- A valid reset_started_at boundary is required to exclude restoration polling.
- Collection window is POST_FAULT_RECOVERY relative to declared truth.
- Not all observation and collection timestamps are fault-active.
- Actual capture timing is UNKNOWN_TIMING; fault-active evidence is unverified.

