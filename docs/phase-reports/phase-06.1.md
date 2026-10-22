# PHASE: 06.1 — Diagnosis validation and evaluation repair

Date: 2026-10-20. Branch: `feature/phase-06-diagnosis`.

**STATUS:** Offline repairs and validation complete; real fault-time accuracy is
not measurable from the existing recordings. All work remains uncommitted and
unpushed. The worktree already contained the unapproved Phase06 implementation
at the start of this follow-up; it was not reset or treated as clean.
No live fault, container restart, Docker modification, or Phase07 work occurred.

## ROOT CAUSE OF EVALUATION ISSUES

The manifest associated Phase04 observation filenames with Phase03 truth from
different runs. All five snapshots were collected roughly 80 minutes after the
older truth intervals. The snapshots contain no controller run ID or their own
injection/reset/recovery timestamps. F3/F5 targets and F4/F5 parameters also differ
between the two generations. These are not timezone conversion errors.

All five original `lab/reports` experiment records are byte-identical to their
copies under `docs/phase-reports`. Their ground-truth files match their run IDs,
locations and injection/recovery times. Those original truth records remain
unchanged. Scenario/file-name correspondence cannot bind a later capture to them.

All 532 fault-snapshot observations retain base evidence fields only. Typed loss,
RTT, target, route-prefix and next-hop payloads were lost during historical
serialization. Every record has `observed_at == collected_at`; these are polling
timestamps, not independently recorded fault-transition times. No missing value
was reconstructed from a filename, evidence ID, raw command, or injected label.

The previous evaluator exposed temporal mismatch but still counted the same
cases in a 1/5 accuracy denominator. That is now removed. There is no valid 1/5
fault-time result, and no evidence that the correct rate is 0/5 or 5/5 either.

## OSPF L23/L12 DISCREPANCY

- Original Phase03 run `exp-20261019T174322Z-5b7e56` targets **L12 / R1 eth1**, with
  hello 5s / dead 15s. Its own active-state report still has all ten adjacencies FULL.
- Phase04 documentation describes **L23 / R2 eth2**, hello 5s / dead 20s. The later
  raw snapshot contains `OSPF_NEIGHBOUR_DOWN` from R2/eth2, evidence
  `ev-ospf-r2-1792436672457-24ec6b-3-3-3-3`. Snapshot topology maps that port to
  R3/eth1 through **L23**, consistently with the normal topology map.
- Both L12 directions report FULL. The opposite L23 direction, R3→R2, also reports
  FULL (`ev-ospf-r3-1792436672560-ebea07-2-2-2-2`) and is retained as a contradiction.
- Stored Phase05 artifact `cr-20261020T071302Z-4019f3.json` links to this snapshot
  by `snapshot_id`, but incorrectly reports HEALTHY after lossy deserialization
  and anchors its window to next-day processing time. It is a historical artifact,
  not evidence of a healthy capture. Phase06 reruns repaired correlation from the
  actual snapshot rather than trusting this artifact.
- Current inference maps the surviving observations to **OSPF_CONFIGURATION_MISMATCH
  / L23**, heuristic score 0.70. The candidate is plausible, not proof of observed
  timer configuration: typed timer parameters are missing.

Conclusion: **misaligned experiment association**, not a demonstrated L23 topology
mapping error. Neither prediction nor Phase04 prose is sufficient to relabel the
older L12 ground truth. Actual Phase04 fault-time correctness remains unverified.

Sources: `docs/phase-reports/phase-04.md` lines 44–75;
`evaluation/datasets/observations/f3_ospf_mismatch_snapshot.json` lines 215–265,
1431–1440; `docs/phase-reports/ground_truth/gt-exp-20261019T174322Z-5b7e56.json`;
`evaluation/datasets/correlations/cr-20261020T071302Z-4019f3.json`.

## F1–F5 TIMELINES

All times are **UTC on 2026-10-19**. Recovery is the original controller's recorded
post-reset/post-convergence timestamp, not the unknown reset-command execution
time. Injection is recorded after the injection operation returns. See
`lab/fault_injection/controller.py`, `inject_fault`, `reset_fault`, `run_experiment`.

| Timeline | Original truth type / location | Injection → recorded recovery | Snapshot collection window | All observation AND collection timestamps | Records |
| --- | --- | --- | --- | --- | ---: |
| F1 TIMELINE | LINK_FAILURE / L12 | 17:41:57.028066 → 17:42:25.371909 | 19:02:30.600078 → 19:02:53.429499 | 19:02:31.342453 → 19:02:53.374021 | 109 |
| F2 TIMELINE | ROUTER_FAILURE / R3 | 17:42:31.297851 → 17:43:16.982044 | 19:03:07.012477 → 19:03:41.721427 | 19:03:07.641848 → 19:03:37.624131 | 100 |
| F3 TIMELINE | OSPF_CONFIGURATION_MISMATCH / L12 | 17:43:22.957189 → 17:43:45.611653 | 19:04:31.157356 → 19:04:33.308318 | 19:04:31.940727 → 19:04:32.776001 | 101 |
| F4 TIMELINE | PACKET_LOSS / L12 | 17:43:51.306002 → 17:44:13.914922 | 19:04:46.515605 → 19:05:09.303489 | 19:04:47.245777 → 19:05:09.242410 | 111 |
| F5 TIMELINE | HIGH_LATENCY / L12 | 17:44:19.743440 → 17:44:40.006315 | 19:05:36.973133 → 19:06:00.084419 | 19:05:37.697671 → 19:06:00.027933 | 111 |

Each of the 532 observation times and 532 collection times is **after the older
Phase03 recovery interval**, with none before or during it. Snapshot starts are
4805.228169s, 4790.030433s, 4845.545703s, 4832.600683s and 4856.966818s after those
respective recovery timestamps. Their own Phase04 experiment timing is **UNKNOWN**.
It would be incorrect to claim these are proven post-recovery captures of their
own faults. The earlier evaluation incorrectly compared them as if shared-run
fault-state observations; the repaired evaluator excludes them.

Leading hypothesis evidence (including the insufficient F2 audit candidate):

| Case | Supporting IDs: observed/collected range | Contradictory IDs: observed/collected range |
| --- | --- | --- |
| F1 | 2 IDs, 19:02:31.342453–19:02:31.650954 | 1 ID, 19:02:31.650954 |
| F2 | 12 IDs, 19:03:07.641848–19:03:32.474015 | 2 IDs, 19:03:07.897246 |
| F3 | 3 IDs, 19:04:31.940727–19:04:32.240233 | 1 ID, 19:04:32.240233 |
| F4 | No ranked hypothesis | None |
| F5 | No ranked hypothesis | None |

The generated `evaluation/reports/phase06-results.json` contains each original
evidence ID, both timestamps, declared/actual timing classes, and support/conflict
roles across all ranked hypotheses. Neutral full diagnosis artifacts retain the
individual hypotheses' complete ID lists.

## DIAGNOSIS BUGS FOUND

1. A present route with a usable next-hop address but no egress interface was
   ignored, selecting unconstrained shortest paths. R1→R3 via R5 now constrains
   candidates to L51/L45/L34 instead of L12/L23, retaining the actual route ID.
   A supplied contradictory/unknown interface cannot be overridden by an address.
2. Typed OSPF neighbour router ID and port could map to one link while its address
   identified a different endpoint. The address must now match the peer endpoint;
   prefixed/plain addresses normalize consistently. Missing/0.0.0.0 placeholders
   permit identity fallback; malformed or incompatible supplied addresses do not.

These are general correctness repairs demonstrated on independent synthetic
observation fixtures. They do not change the five historical predictions.
Engine version is `phase06-rules-v1.1`; scoring weights and thresholds are unchanged.

## EVALUATION BUGS FOUND

- Scenario/filename association was treated as usable truth despite no shared run.
- A visible temporal-invalid flag did not remove cases from accuracy denominators.
- Per-record observation/collection timestamps and real referenced IDs were not audited.
- Missing recovery time was implicitly treated as an ongoing fault.
- Type, location, exact-match correctness and prediction coverage were conflated.
- Recovery-after-convergence alone cannot certify pre-reset fault-active collection.

## FIXES IMPLEMENTED

The offline timing module requires matching run ID, snapshot ID, canonical SHA256
and a separately recorded reset-start boundary. It validates all records, the whole
window, ordered aware timestamps, nonempty evidence and real referenced IDs.
Conservative fault-active bounds are injection inclusive and reset exclusive;
the interval from reset start to convergence recovery is uncertain. Missing times
are never inferred. Identical evidence replay is harmless; conflicting payloads
under one ID invalidate the capture.

Fault-active, before-fault, post-recovery, mixed and unknown-timing data are separated
from the declared healthy baseline. Unverified cases are **NOT EVALUABLE**, with
null correctness values. Eligible Top-1/Top-3 exact, type-only and location-only
metrics have explicit denominators. Coverage/abstention are reported for all and
eligible cases separately. Different Top3 hypotheses cannot combine their separate
type/location matches into one exact hit.

All six inference calls and neutral artifact writes precede truth-model loading,
truth-file reads and capture-binding reads. Only observation content enters
inference. Evaluation never re-runs or filters inference using labels. Historical
truth, observations, Phase05 artifacts and lab controller files are unchanged.
No retrospective capture sidecars were invented. Manifest associations are marked
UNVERIFIED_CROSS_RUN; previous misleading Phase06 accuracy prose is superseded.

## ABSTENTIONS EXPLAINED

- **F2:** Twelve failed R3 collections depend on one availability point, not twelve
  independent failures. Both peers still report FULL, preserved as contradictions.
  Score is 0.55 − 0.15 = **0.40**, with **1/2** required primary points and **64%**
  represented coverage. A surviving lost-ping tag lacks typed target/count/loss
  fields; its opaque ID/raw reference cannot provide independent reachability proof.
- **F4:** All ten data ports are UP and all ten OSPF directions FULL, but no saved
  typed loss/target/probe counts survive. A successful ping tag does not establish
  zero loss or quantify partial loss. Coverage **66.67%**, no supported impairment.
- **F5:** Same operational evidence and coverage as F4; no saved typed RTT or
  target/path measurements. No supported latency candidate can be generated.

All three are appropriate abstentions on the supplied payload. The route bug
would discard usable structured data in other inputs, but that data is absent
from these old F4/F5 snapshots. No weights or sufficiency requirements were relaxed.
F1 still accepts LINK_FAILURE/L12 at 0.75; F3 accepts OSPF mismatch/L23 at 0.70.
The declared baseline produces no fault candidate.

## VALID TOP-1 RESULTS

**N/A — zero evaluable fault-active cases.** Raw accepted-prediction coverage is
2/5; abstention is 3/5. These rates are not correctness rates.

## VALID TOP-3 RESULTS

**N/A — zero evaluable fault-active cases.** Tentative/accepted rankings remain in
the audit artifacts but receive no accuracy credit or penalty for invalid cases.

## NOT EVALUABLE CASES

**F1, F2, F3, F4, F5.** No run bindings; their actual injection/reset/recovery
intervals are unknown. Every timestamp is also outside the unrelated declared
Phase03 interval. Synthetic regression tests are explicitly unit fixtures, never
substituted into this benchmark.

## TESTS PASSED

- Backend Ruff: **PASS**.
- Full backend Pytest: **453 passed, 0 failed**, one existing Starlette/httpx
  deprecation warning. Includes **123 diagnosis**, **25 evaluation**, and **55
  timing-audit** cases, plus Phase05 and pre-existing regressions.
- Offline evaluator: all six original snapshots processed; five fault cases
  excluded; no baseline fault candidate.
- `git diff --check`: **PASS**.

Regressions cover timing boundaries, reset/convergence overlap, unknown/naive/
missing timestamps, timezone offsets, mixed captures, hash/run/snapshot mismatches,
post-recovery exclusion, exact versus partial location/type correctness, valid and
invalid abstentions, contradictory/missing evidence, duplicates, dependency caps,
route/OSPF identity mapping, leakage isolation, and stable rankings.

## TESTS SKIPPED

**92**: 80 tests require running NEXORA lab containers; six live collector tests
and six live fault tests are explicitly gated. Both live-test flags were unset.
No skipped test is reported as passed.

Frontend checks were not repeated for this backend/evaluation-only follow-up.
Prior Phase06 results remain: lint PASS, typecheck PASS, Webpack production build
PASS after permitted font fetching. **Default Turbopack build FAILED**, including
its elevated retry. The panic trace goes through the CSS webpack-loader worker
and fails when spawning a process that binds a local port (`Operation not permitted`).
That is an environment restriction; no source-syntax defect was established.
Webpack success does not establish Turbopack success. No frontend changes were made.

## FILES CHANGED

Phase06.1 changes, in addition to the already-uncommitted Phase06 work:

- `backend/app/diagnosis/evidence.py`: next-hop and OSPF endpoint identity fixes.
- `backend/app/diagnosis/engine.py`: inference version increment.
- `backend/app/evaluation/phase06.py`: eligibility-gated metrics, reports and CLI.
- `backend/app/evaluation/timing.py`: new offline provenance/timestamp audit.
- `backend/tests/test_phase06_diagnosis.py`: localisation regressions and valid fixtures.
- `backend/tests/test_phase06_evaluation.py`: denominator/isolation/location regressions.
- `backend/tests/test_phase061_timing.py`: new adversarial timing tests.
- `evaluation/datasets/phase06_manifest.json`: explicit unverified historical associations.
- `evaluation/reports/phase06-results.json`, `phase06-evaluation.md`, and six neutral
  `phase06-diagnoses/*.json` artifacts: regenerated.
- `backend/README.md`, `docs/architecture/root-cause-diagnosis.md`,
  `docs/phase-reports/phase-06.md`, and this report.

## KNOWN LIMITATIONS

No valid measured fault-time accuracy can be claimed. Original typed metrics and
Phase04 injection/reset times cannot be recovered from the available files.
The Phase04 prose is useful forensic context, not substitute measurement truth.
A canonical hash detects changed content, not fabricated operator metadata;
capture sidecars must be created contemporaneously by a trusted capture workflow.
The original controller stores neither injection command-start nor reset-start;
future capture instrumentation must record them separately without changing Phase01
inference contracts. Static/inferred paths and incomplete collection-plan coverage
remain limitations documented in the architecture. OSPF configuration mismatch
remains a hypothesis without observed timer/area/authentication parameters.

## LIVE RECAPTURE REQUIRED: YES

Further empirical validation stops here until explicit authorization for bounded
NEXORA-only experiments. The following is a proposed procedure, not executed work.

Capture one separately labelled healthy baseline and five **sequential** fault runs,
restoring and verifying the full baseline between every run. Use new neutral
snapshot names and independent actual run IDs; retain existing historical data.

| Run | Exact fault proposal | Observable manifestation before capture |
| --- | --- | --- |
| F1 | L12, R1 eth1 administratively down | Direct DOWN state plus peer adjacency loss after its dead timer |
| F2 | R3 unavailable using existing safe scenario | Source unavailable plus R2 and R4 peer losses; typed probes to R3 |
| F3 | L12, R1 eth1 hello 5s/dead 15s against 10s/40s peer | Both ports UP; affected adjacency non-FULL; retain observed timer config |
| F4 | L12, 30% netem loss on approved data interface | Typed direct-link probes show partial loss; both interfaces/OSPF remain operational |
| F5 | L12, 100ms netem delay on approved data interface | Typed direct-link probes show increased RTT; record normal baseline RTT |

For each authorized run:

1. Verify five healthy routers, ten FULL OSPF directions, data interfaces UP,
   expected routes and bounded zero-loss baseline probes. Stop if unhealthy.
2. Record UTC injection-command start/end and the controller's actual run ID in
   isolated offline metadata. Do not include injected labels in observations.
3. Poll for manifestation for **at most 60 seconds**, including the actual peer
   dead timer. If manifestation is absent, reset immediately and mark that attempt
   inconclusive; do not prolong the fault to chase a diagnosis.
4. Collect all-router interfaces, OSPF, routes and typed probes while the fault is
   active, with an overall capture deadline of **90 seconds**. Use at most 20
   packets per direct-link probe in each direction, at most two probe rounds;
   retain typed packet counts, target/source, RTT, timestamps and bounded path
   evidence. Reject lossy serialization via offline round-trip validation.
5. Use a **180-second maximum active-fault deadline** enforced by the authorized
   capture wrapper, including injection and collection; timeout or exceptions
   must enter the existing safe reset path. Never kill cleanup or strand a fault.
6. Immediately before calling `reset_fault`, record `reset_started_at`. Capture
   must be fully closed before this boundary. Reset in `finally`, record reset
   completion and baseline-confirmed recovery separately, and perform the existing
   bounded recovery checks (up to 60 seconds). If restoration fails, stop the run
   sequence and report; never proceed to the next fault or restart unrelated projects.
7. Persist truth and a capture sidecar containing run ID, snapshot ID, canonical
   digest and reset-start time outside inference. Store pre/active/post windows
   separately. Diagnose all neutral snapshots before opening these sidecars/labels.

The proposed capture wrapper/deadline instrumentation is not implemented or run in
this repair. Review it before any authorized experiment. F2's intentional router
availability action requires that same explicit live-fault authorization. Five
successful captures would validate these bounded cases only, not calibrated
probabilities or general accuracy across unseen topologies.
