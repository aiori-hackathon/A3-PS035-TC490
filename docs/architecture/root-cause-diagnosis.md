# Deterministic root-cause diagnosis — Phase 06

`app.diagnosis.engine.DiagnosisEngine` implements the Phase 01 hypothesis,
ranking, sufficiency and certificate contracts. It accepts collected evidence and
topology, performs no network commands, and leaves optional verification and
active probing unimplemented.

## Entry points and processing order

```python
from app.diagnosis.engine import DiagnosisEngine

engine = DiagnosisEngine()
# An Incident already produced by collection/correlation:
result = engine.diagnose(incident, evidence, topology)
# A saved EvidenceSnapshot dictionary, without its filename:
results = engine.diagnose_snapshot_dict(snapshot)
```

The snapshot adapter validates the payload, decodes surviving collector state
tags, excludes records outside the collection window, partitions explicit
incident bindings, and runs Phase 05 correlation. Each group seeds candidates
from its own symptoms. Healthy evidence in the same time slice supplies context
for contradictions, coverage and path resolution. Different spatial incidents
cannot seed each other's candidates. The public direct entry point expects an
already correlated Incident and enforces its time window and incident binding.

Next, topology context resolves interfaces, neighbours, addresses and paths;
the generator enumerates candidates; bounded rules score and rank them;
sufficiency evaluates the result; the certificate builder records the audit;
and the engine emits a `DiagnosisResult`. No evaluator participates in inference.

## Localisation

- Link candidates use the supplied `NetworkLink` endpoints and interface names.
  Router candidates use unavailable sources, neighbours of physical/protocol
  anomalies, and known unreachable probe targets. Unknown addresses and ports
  cannot create invented locations.
- Complete matching traceroutes within 30 seconds of a probe take precedence.
  All supplied complete paths are retained. A path's evidence ID supports only
  components that it actually contains.
- Otherwise, a present longest-prefix source route constrains the first hop.
  A unique peer endpoint address can resolve a missing egress interface; a supplied
  interface remains a constraint and cannot be overridden by an incompatible
  address. Remaining equal-cost paths are inferred, preserving alternative locations.
- Typed OSPF router ID, source interface and neighbour endpoint address must agree.
  Only an absent address or collector placeholder `0.0.0.0` permits pair-only
  resolution. Malformed and incompatible supplied addresses are excluded.
- Without route/trace evidence, all equal-cost shortest topology paths remain
  possible. A multi-link path generally yields competing hypotheses. Operational
  interface coverage cannot by itself distinguish impairment locations.
- Missing topology observations never become interface DOWN or router failure.
  Topology statuses, roles and expected OSPF configuration are not health evidence.

## Rule weights

Weights below apply once per candidate and evidence family. Signed weights sum,
then clamp to `[0, 1]` and round to six decimal places. They are **heuristic
alignment scores, not calibrated probabilities**.

| Candidate | Supporting families | Contradicting families |
| --- | --- | --- |
| LINK_FAILURE | Interface down `+0.70`, or both endpoints down `+0.80`; non-FULL adjacency `+0.15` with physical evidence, otherwise `+0.35` | Both ports UP `−0.55`; same-port UP/DOWN conflict `−0.40`; FULL adjacency `−0.10` |
| ROUTER_FAILURE | Explicit unavailable source `+0.55`, or generic collection failure `+0.15`; all peers lose adjacency `+0.30` (some peers `+0.10`); all local data ports down `+0.20`; measured complete reachability loss `+0.15` | Successful collection from router `−0.65`; peers still FULL `−0.15` |
| OSPF_CONFIGURATION_MISMATCH | Non-FULL adjacency `+0.40`; with that anomaly, both ports UP `+0.40` (one port `+0.12`) | Physical DOWN `−0.60`; FULL in the same observed direction `−0.40`, otherwise `−0.10` |
| PACKET_LOSS | Typed measured loss `≥5%` and `<100%` on a possible path `+0.65` | Normal probe on every possible path through link `−0.25`; physical DOWN `−0.50` |
| HIGH_LATENCY | Typed measured RTT `≥10 ms` with replies on a possible path `+0.65` | Normal RTT on every possible path through link `−0.25`; physical DOWN `−0.50` |

Operational interface and adjacency observations corroborate performance faults
at zero additional weight. Route withdrawals provide downstream audit context at
zero additional weight. Syslog volume adds no weight. Failed ping execution is
unknown target state; it cannot stand in for observed packet loss. Complete loss
alone cannot establish the partial-loss fault category.

Adjacency loss with UP interfaces is a plausible configuration-mismatch hypothesis,
not proof of a particular area, timer or authentication mismatch. Missing observed
parameters remain explicit even when the heuristic threshold is met.

## Replay, dependency and contradiction safeguards

Exact ID replays collapse; conflicting payloads under one ID raise an error.
Repeated polls and distinct IDs with the same underlying state do not increase
rule weight. Primary sufficiency counts observation points, not alarm counts.
All failed collectors on one router share one availability point. All route
prefixes from one router share one routing-table coverage point. Correlation
relationship counts never become scoring multipliers.

Different states survive deduplication. Supporting and contradicting IDs are
unique, disjoint references to actual input evidence. Missing telemetry remains
missing information. UP physical interfaces support a protocol fault; they are
not contradictions of an OSPF DOWN observation. FULL adjacency conflicts with a
persistent fault but incurs a limited penalty where dead-timer lag is possible.
Conflicting observations in one incident window are retained rather than silently
choosing one as truth.

## Ranking and sufficiency

Positive supported candidates sort by descending score, then fault-type value,
then component ID. Ranks are sequential and Top-3 is the exact first three
candidates (fewer is valid). Stable tie-breaking never resolves ambiguity.

Defaults in `app/core/config.py` require at least two independent primary points,
60% usable represented collection coverage, score `≥0.65`, and margin `≥0.10`.
Below evidence/coverage/score thresholds: `INSUFFICIENT_EVIDENCE`. With adequate
evidence but insufficient margin: `AMBIGUOUS`. Both abstain from accepted Top-1;
tentative candidates remain available for audit. Healthy evidence generates no
fault candidate. The Phase 01 status enum has no HEALTHY diagnosis status, so a
fault-free input abstains with an explicit explanation.

Coverage is usable polling points divided by represented attempted/explicitly
missing points, excluding passive logs and optional traces. The Phase 01 models
carry no complete collection plan, so completely omitted attempts cannot be
measured. No claim of full network collection coverage is made.

## Legacy records and offline evaluation

The original recordings dropped typed evidence fields. Only exact surviving
interface UP/DOWN and OSPF FULL/DOWN collector tags can be decoded, preserving
the original evidence IDs and using topology only for identity resolution.
Legacy loopback DOWN tags are excluded from data-link localisation. Ping success
tags do not encode loss percentage or RTT; no measurements are reconstructed from
IDs, filenames, raw command references, topology health or scenario metadata.
Invalid supplied typed measurements fail validation; only missing legacy fields
may use the base-record fallback.

Run offline evaluation from `backend`:

```sh
.venv/bin/python -m app.evaluation.phase06
```

The offline manifest identifies candidate snapshot/truth associations; filenames
and scenario names never establish experiment identity. All inference calls and
neutral diagnosis artifact writes finish before truth or capture-binding files
are read. The evaluator never filters or reruns inference using truth.

Phase 06.1 output schema 2.0 replaces the misleading declared-pair accuracy field:

- `valid_fault_metrics`: exact Top-1/Top-3 correctness and separate type/location
  correctness, using only eligible fault-active captures. Zero eligible cases
  means `null` accuracy (N/A), not 0% or 100%.
- `coverage`: accepted Top-1, abstention, ambiguity and sufficiency counts/rates for
  both all captures and eligible captures. Each diagnosis retains its represented
  collection coverage, which is different from prediction coverage.
- `timestamp_validity`: eligibility and timing category counts.
- `cases[].timing`: snapshot window, injection/recovery/reset boundaries, every
  real evidence ID's observation/collection times and supporting/contradicting
  roles. All context is audited, including records not referenced in rankings.
- `baseline`: separately declared HEALTHY_BASELINE control, excluded from fault
  accuracy denominators. Its label is not independently proved by the evaluator.

An eligible capture requires a contemporaneously recorded offline sidecar. The
manifest's optional `capture_binding_path` points to this JSON contract:

```json
{
  "run_id": "the actual controller run ID",
  "snapshot_id": "the exact captured snapshot ID",
  "snapshot_sha256": "canonical SHA256 from app.evaluation.timing.snapshot_digest",
  "reset_started_at": "timezone-aware timestamp immediately before reset begins"
}
```

The sidecar stays outside the inference payload. It must be produced by the
capture workflow, never fabricated retrospectively from a scenario filename.
Digest matching detects mismatched content; it is not cryptographic proof of the
truthfulness or contemporaneity of operator-supplied metadata.

The evaluator requires aware ordered timestamps, a matching run/snapshot/content
binding, and nonempty observations with `window_start <= observed_at <=
collected_at <= window_end`. The whole window and every record must be inside
`[injection_timestamp, reset_started_at)`, with reset no later than recorded
recovery. The older controller records recovery only after convergence polling;
`[reset_started_at, recovery_timestamp)` is therefore UNKNOWN_TIMING, not confirmed
fault-active or healthy. Missing recovery/reset times do not imply an ongoing fault.
Invalid chronology, missing referenced IDs and conflicting payloads under one ID
also exclude a capture. Exact replay records remain harmless to eligibility.

Unbound, before-fault, post-recovery, mixed and unknown-timing captures are **NOT
EVALUABLE**. Their predictions remain visible, but every correctness field is
null. Declared-interval timing and actual-capture timing are separate: a snapshot
being after an unrelated old recovery is not proof that its own experiment had
recovered. Per-record roles refer to the union across ranked hypotheses; one ID
may support one hypothesis and contradict another.

For eligible cases, exact fault type **and** component ID must match in the same
hypothesis. Insufficient evidence counts as a miss at both ranks; ambiguous Top-3
remains tentative. Accepted incident roots within 0.10 of each other cause
snapshot-level Top-1 abstention. Weights and sufficiency thresholds were unchanged
by Phase 06.1; the five labels were not used for tuning.

See `evaluation/reports/phase06-evaluation.md` and
`docs/phase-reports/phase-06.1.md`. All five historical pairs lack a shared run
binding and their own injection/reset times. Valid Top-1 and Top-3 are N/A.
Fresh aligned, lossless recordings require separately authorized lab work.
