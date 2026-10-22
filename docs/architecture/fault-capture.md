# Phase 06.2 — trustworthy fault capture

This workflow prepares future controlled NEXORA experiments. Only synthetic execution
has been validated in Phase 06.2. It does not establish diagnostic accuracy or repair
the five historical captures. Diagnosis scoring and thresholds are unchanged.

## Audit and minimum changes

| Existing module | Finding | Change |
| --- | --- | --- |
| Evidence snapshot / normalizer | Snapshot dictionaries already preserve subclass fields; legacy deserialization can accept incomplete records | Reuse snapshot contract; add strict validation for **new** captures; keep legacy replay separate |
| Ping collector | Execution failure could become invented transmitted counts/100% loss; source address absent; RTT precision reduced | Explicit failed-attempt record, observed counts including lost packets, source binding, full min/avg/max/mdev precision and millisecond unit |
| Routing collector | Only first ECMP next hop retained | Preserve each observed prefix/next-hop/interface tuple with its own evidence ID |
| OSPF collector | Neighbor state retained, interface configuration discarded | Preserve observed interface JSON and its collection timestamp; missing configuration stays explicitly unavailable |
| Collector timestamps | Some collection timestamps copied the observation start | Stamp each router's observation start and actual record collection completion; reject naive evidence timestamps |
| Fault controller | Lock reserved after mutation; corrupt lock could appear absent; reset could clear a lock without verified recovery | Atomic reservation before mutation, fail-closed corrupt locks, independent run ID, command timing, owned reset and explicit recovery completion |
| Scenario commands | Container names allowed, ownership not checked | Require approved container and NEXORA Compose project/service labels before scenario mutations |
| Phase 06.1 evaluation | Requires matching run/snapshot/digest and fault-active timestamps | Emit a separate binding compatible with those gates; exclude synthetic cases from empirical metrics |

The existing Phase 01 evidence subclasses gain additive optional measurement fields.
No historical files are rewritten and no missing historical measurements are inferred.
A `PingAttemptFailure` contains requested packet count and addresses, but **no measured
sent/received/lost counts or RTT**. Successful command statistics with zero replies
are measured loss, distinct from command execution without statistics.

## Components and artifacts

- `app.capture.workflow.CaptureRunner`: sequential state machine; explicit controller
  and observer dependencies; constructing it never performs Docker operations.
- `app.capture.observer.LabObserver`: existing collectors and snapshot orchestrator,
  scoped direct-link probes, manifestation and recovery observations.
- `app.capture.safety`: POSIX main-thread deadlines, catchable SIGTERM handling,
  atomic JSON file replacement.
- `app.capture.dry_run`: synthetic controller, fixtures and mock transport. Its CLI
  has **no live execution option**, including when `--dry-run` is omitted.
- `app.collectors.fidelity.validate_capture`: strict new-capture validation and
  explicit reporting of unavailable optional measurements.

Each new output directory contains an index and neutral UUID subdirectories. A
successful subdirectory contains:

| File | Contents | Inference input? |
| --- | --- | --- |
| `snapshot.json` | Typed observation dictionaries, topology, evidence IDs, UTC times, counts | Yes |
| `provenance.json` | Controller run ID, plan, injection/collection/reset/recovery times, snapshot ID and hash, errors, synthetic flag, final status | No |
| `truth.json` | Actual experiment label/location and controller run ID | No |
| `binding.json` | Run ID, snapshot ID, canonical SHA256, reset-start boundary, synthetic flag | No |

The lossless snapshot is first persisted as `unverified-snapshot.json` within the
capture budget, so completed evidence survives later reset/recovery failure. Keep
it for audit; it has no evaluation binding unless the entire workflow succeeds.
An interrupted collector may still lose its unfinished in-memory observations.

Use only artifacts whose provenance has final `CAPTURED` status. Files are each
written with flush/fsync and atomic replacement; the entire directory is not an
atomic transaction. A failed publication may leave incomplete artifacts and never
certifies them. The SHA256 binds exact canonical JSON contents, independent of
filenames/whitespace; it does not authenticate an operator or prevent malicious
metadata replacement.

The controller run ID is generated independently from the snapshot ID. Success
requires aware, ordered times:

`baseline ≤ injection start ≤ injection end ≤ collection start ≤ collection end < reset start ≤ reset end ≤ recovery confirmation`

Every evidence observation/collection time must fall within the collection window.
The Phase 06.1 timing validator additionally checks binding identity and all record
and snapshot times against the fault-active interval. The reset-start boundary
excludes recovery/convergence observations. Missing, unordered or unmatched metadata
cannot become eligible. Artifact filenames and fault labels never enter inference.
Synthetic bindings produce `SYNTHETIC_VALIDATION_ONLY`, null accuracy outcomes and
zero empirical denominator contribution, even when their timing eligibility passes.

## Bounds and restoration

The five default plans use existing scenarios: F1/L12, F2/R3, F3/L12 with hello/dead
5/15, F4/L12 with 30% configured loss, and F5/L12 with 100 ms configured delay.
These parameters are orchestration metadata, not evidence or diagnosis hints.

1. Validate canonical NEXORA target and bounded plan parameters.
2. Reserve a common `.capture-sequence.lock` beside the controller's active lock.
   Different output paths cannot bypass the sequence lease. Every participant must
   use the same controller lock directory.
3. Verify baseline within 60 seconds: existing controller checks, ten observed data
   interfaces UP, ten FULL OSPF observations with observed 10/40-second timers,
   all 25 router/loopback route pairs, and approved unshaped qdiscs on data ports.
   Missing/unknown configuration fails closed. No baseline active probes are sent.
4. Atomically reserve the controller lock before injection. Scenario commands
   verify NEXORA Compose ownership and approved containers/interfaces.
5. Allow at most 60 seconds for manifestation and at most 90 seconds total active
   collection, **including** manifestation observations reused in the snapshot.
   Injection plus collection has a 120-second deadline, reserving up to 60 seconds
   for reset within the requested 180-second active-fault budget.
6. Direct-link probes use an explicit source address, at most 20 packets per
   direction per round, and at most two rounds. F2 probes each of the router's
   two incident links. The performance manifestation round counts toward that
   same budget. Repeated manifestation checks do not send additional rounds.
   Standard orchestrator pings, traceroutes and historical log collection are
   disabled for this capture path.
7. In `finally`, attempt reset of the owned run on success, error, timeout or
   catchable interruption. A run-ID mismatch refuses a foreign reset. The
   controller retains RESTORING state until independent baseline checks pass.
8. Allow reset commands up to 60 seconds and subsequent recovery verification up
   to 60 seconds. Recovery polling is outside the evidence window. No later plan
   runs after any failure, even if restoration succeeds. Failed/unverified recovery
   retains the active lock and sequence lease.

Manifestation is an observation gate, not a diagnosis: F1 requires interface down
plus adjacency loss, F2 requires unavailable router plus two neighboring losses,
F3 requires adjacency loss while both link interfaces remain up, and performance
plans require measured loss or elevated RTT. These checks do not alter diagnosis
rules or scoring thresholds. The stochastic loss plan may legitimately fail to
manifest in its bounded sample; it is not retried beyond the packet budget.

## Process crash and physical safety limits

Python `finally` is **not crash-proof cleanup**. Main-thread SIGTERM, KeyboardInterrupt
and ordinary exceptions trigger best-effort owned reset. A second termination during
cleanup can interrupt it. SIGKILL, interpreter/host crash, power loss, stuck native
code, filesystem stalls or Docker daemon failures may prevent reset or leave the
fault active past the deadline. Killing a Docker CLI also does not prove that a
submitted daemon/container command has stopped.

The 120+60-second budgets bound execution in a responsive process; they are not an
external guarantee that a physical fault is removed within 180 seconds. There is no
independent watchdog in this phase. Retained locks block subsequent experiments;
they do not restore networking. After a crash or unverified recovery, an authorized
operator must inspect the exact NEXORA run/target, perform scoped restoration, verify
baseline, and review stale leases before explicitly permitting another sequence.
Do not blindly delete locks or run broad Docker cleanup. The legacy emergency-reset
command is not invoked by this capture workflow.

Live FRR configuration JSON, `tc -j` support, Compose ownership labels and real
collection duration remain unvalidated in this environment. The baseline parser
recognizes `timerMsecs` hello/dead values or `helloInterval`/`deadInterval` seconds;
unknown formats refuse injection. Probe source binding must also be verified in the
actual lab. Default controller lock paths must be shared by every operator/process.
The existing required truth seed is stored as 0 with an explicit “unspecified” note;
netem randomness is not controlled and no reproducibility claim is made.

## Non-disruptive rehearsal

From the repository root, select a new output path:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.capture.dry_run \
  --dry-run --output-dir /tmp/nexora-capture-rehearsal-new
```

This creates synthetic artifacts and a sibling `-control` directory, calls no
Docker subprocesses, and reports no empirical accuracy. It exercises all five
plans, serialization, persistent ownership, timestamps, digest and timing eligibility.
It is not an end-to-end live FRR/Docker rehearsal.

```sh
cd backend
env -u NEXORA_RUN_FAULT_TESTS -u NEXORA_RUN_COLLECTOR_LIVE_TESTS \
  .venv/bin/python -m pytest -q -ra
.venv/bin/ruff check .
```

Live capture requires explicit separate authorization and a supervised operator
handoff after environment preflight. No live command was executed to implement or
validate this phase. No default live CLI or automatic experiment schedule is added.
