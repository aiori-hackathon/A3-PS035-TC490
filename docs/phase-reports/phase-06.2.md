# NEXORA — Phase 06.2 report

**PHASE:** 06.2 — Trustworthy Fault-Capture Infrastructure  
**STATUS:** IMPLEMENTED; non-disruptive validation passed.  
**BRANCH:** `feature/phase-06-diagnosis`

The checkout contained ongoing uncommitted Phase 06/06.1 work when resumed; it was
not a clean tree. Existing work was preserved. Nothing was committed or pushed.
No live fault, container start/stop/restart, host-network change or destructive
cleanup was executed. No Phase 07 or frontend source changes were made.

## CAPTURE INFRASTRUCTURE

Added a sequential dependency-injected capture runner, real collector adapter,
POSIX deadlines, atomic artifact writer, and mock-only CLI for all five approved
plans. Reused existing scenario implementations, controller, snapshot orchestrator,
Phase 01 contracts and Phase 06.1 timing/digest checks.

The audit found late/non-atomic fault reservation, corrupt-lock handling that did
not actually fail closed, premature lock release after reset, lost ECMP egresses,
absent observed OSPF configuration, and ping failures presented as measurements.
These are repaired for the new workflow. Full design and operator handoff:
[Fault-capture architecture](../architecture/fault-capture.md).

## DATA FIDELITY

- Measured sent/received/lost counts, explicit source and target addresses.
- RTT min/avg/max and optional mdev without precision rounding; explicit ms unit.
- Every observed route prefix/next-hop/outgoing-interface tuple, including ECMP.
- OSPF neighbor identity/state and observed interface configuration where available.
- Evidence IDs and aware UTC observation/collection times, with per-router polling
  start and actual collection completion.
- Round-trip validation rejects lost fields, duplicate IDs, inconsistent counts,
  missing required measurements, invalid timestamps, collector errors and legacy
  fallback records in new captures. Optional measurement gaps are reported.
- Failed ping execution has a separate record without invented loss/counts/RTT.
- Completed snapshots are retained as unverified artifacts even if restoration
  fails. Failed runs receive no evaluation binding.

Historical data was neither reconstructed nor overwritten.

## TIMING AND PROVENANCE

Each experiment has an independent controller run ID and neutral snapshot ID.
Separate provenance records baseline verification, injection command start/end,
collection start/end, reset start/end, recovery confirmation and canonical SHA256.
Truth and binding sidecars are outside inference payloads. Successful synthetic
captures pass matched-metadata timing eligibility but are explicitly excluded from
empirical accuracy denominators.

Historical reevaluation: **5 NOT EVALUABLE; 0 eligible cases; Top-1 N/A; Top-3 N/A**.
The Phase 06.1 conclusion is unchanged. No diagnosis weights or thresholds changed.

## SAFETY CONTROLS

- Healthy baseline verification before injection; unknown baseline fails closed.
- Exclusive persistent sequence lease and atomic controller reservation before mutation.
- Canonical NEXORA targets and Compose project/service ownership checks for scenario commands.
- At most 60 seconds manifestation and 90 seconds collection including manifestation.
- 120 seconds maximum active work plus a reserved 60 seconds for reset within the
  180-second budget in a responsive process; recovery verification is separately bounded.
- At most 20 packets per direct-link direction per round and two total rounds;
  manifestation probes are reused and count toward the budget.
- Owned reset in `finally`; partial injection, timeout, errors and catchable
  interruption enter cleanup. Foreign-run reset is refused.
- Stop after any failed experiment. Retain locks when restoration is unverified.

## DRY-RUN TESTS

**86 new non-disruptive test cases passed; 0 failed; 0 skipped.** Covered all five
plans, lossless round trips, precise RTT/ECMP/configuration retention, complete
baseline checks, successful capture, no manifestation, collector/serialization/I/O
failure, timeout, partial injection, reset/recovery failure, retained evidence,
missing/inverted timestamps, run mismatch, atomic lock races, stale leases, ownership
checks, SIGTERM cleanup, real nested deadline expiry, packet budgets, ground-truth
isolation and synthetic timing eligibility/accuracy exclusion.

The test module blocks real subprocess execution. Ownership tests substitute a
recording fake; signal tests address only the test process itself.

Mock CLI: **5/5 capture workflows completed**, including execution with `--dry-run`
and with that optional flag omitted. Both modes are always synthetic. Latest
artifacts were written outside the repository to:

`/private/tmp/nexora-phase062-capture-retention-20261020`

Historical evaluation output was written separately to:

`/private/tmp/nexora-phase062-historical-20261020`

Synthetic output is not included in historical datasets or empirical benchmarks.

## BACKEND TEST RESULTS

| Check | Result |
| --- | --- |
| Full backend Pytest | **539 passed, 0 failed, 92 skipped** |
| Phase 06.2 tests (included in full total) | **86 passed** |
| Backend Ruff | PASS |
| Ruff on changed lab controller/models/scenarios, using backend config | PASS |
| `git diff --check` | PASS |
| Frontend lint | PASS |
| Frontend typecheck | PASS |
| Mock CLI | 5/5 successful, synthetic only |
| Historical evaluator | 5 NOT EVALUABLE, accuracy N/A |

One existing Starlette/httpx deprecation warning remains. Skips comprise 80 tests
requiring running NEXORA containers and 12 explicitly gated live collector/fault
tests. Both live-test flags were unset for the final run. Skips are not passes.

The frontend production build was not repeated for this backend-only phase. Prior
Phase 06 results remain: Webpack build passed, default Turbopack build failed on an
environmental local-port permission restriction, including its elevated retry.
No new production-build success is claimed.

## FILES CHANGED

Phase 06.2 additions:

- `backend/app/capture/__init__.py`
- `backend/app/capture/workflow.py`
- `backend/app/capture/observer.py`
- `backend/app/capture/safety.py`
- `backend/app/capture/dry_run.py`
- `backend/app/collectors/fidelity.py`
- `backend/tests/test_phase062_capture.py`
- `docs/architecture/fault-capture.md`
- `docs/phase-reports/phase-06.2.md`

Phase 06.2 updates (some already contained earlier uncommitted work):

- `backend/app/schemas/evidence.py`
- `backend/app/collectors/normalizer.py`
- `backend/app/collectors/interface_collector.py`
- `backend/app/collectors/ping_collector.py`
- `backend/app/collectors/ospf_collector.py`
- `backend/app/collectors/routing_collector.py`
- `backend/app/collectors/transport.py`
- `backend/app/evaluation/phase06.py` — synthetic case exclusion only in this phase.
- `lab/fault_injection/controller.py`
- `lab/fault_injection/models.py`
- `lab/fault_injection/scenarios.py`
- `backend/README.md`

The lab files also received Ruff formatting/import cleanup. Other pending Phase
06/06.1 diagnosis, correlation, evaluation and report files predate this work.

## KNOWN RISKS

Python `finally` cannot guarantee cleanup after SIGKILL, process/host crash, power
loss, a second termination during cleanup, blocked native/filesystem operations or
Docker daemon failure. There is no independent watchdog. The timing budgets cannot
guarantee physical fault removal under those conditions. Persistent locks stop new
experiments but do not repair the network. Authorized manual inspection, scoped
restoration and verified baseline are required before stale locks are released.

The lab was unavailable to integration tests. Live FRR JSON shapes, `tc -j` support,
Compose labels, source-bound probe behavior and real capture duration remain
unverified. The adapter fails closed on unsupported baseline data. Incomplete
in-memory observations can be lost if collection itself is interrupted. Atomic
per-file writes are not an atomic multi-file transaction or a host-crash durability
guarantee. All controller users must share one lock directory. Netem random seed
is unspecified (the existing required truth field uses 0 with an explanatory note).

## READY FOR CONTROLLED LIVE VALIDATION: YES

Ready for **supervised validation after explicit approval and read-only lab
preflight**, not unattended experiments. The available CLI is synthetic-only;
real orchestration requires explicit controller/observer wiring by the authorized
operator. No live accuracy or crash-proof restoration is claimed.
