# PHASE: 06

Date: 2026-10-20. Branch: `feature/phase-06-diagnosis`.
The branch was verified and the working tree was clean before implementation.

## STATUS

Implemented and ready for code review, with recorded-data and default-build
limitations below. No commit or push was made. No live fault was injected, no
Docker configuration changed, and no Phase 07 or frontend feature was implemented.

## IMPLEMENTED

- Concrete Phase 01 `HypothesisGenerator`, `RuleBasedDiagnoser`,
  `EvidenceSufficiencyEvaluator`, `EvidenceCertificateBuilder`, and orchestrating
  `DiagnosisEngine` implementations.
- Candidates for LINK_FAILURE, ROUTER_FAILURE, OSPF_CONFIGURATION_MISMATCH,
  PACKET_LOSS, and HIGH_LATENCY, with actual topology interface/address mapping.
- Traceroute and source-route path constraints, alternative equal-cost paths,
  stable Top-1/Top-3 ordering, and spatial/temporal incident scoping.
- Explicit supporting/contradicting evidence IDs, readable signed rule traces,
  bounded evidence-family scoring, independent-point sufficiency, ambiguity and
  insufficient-evidence abstention, and evidence certificates.
- Phase 05 audit repairs: semantic deduplication; unknown/untyped evidence cannot
  establish health; missing data is not a contradiction; opposing state facts
  retain IDs; temporal context stays within its group; OSPF dependency links
  require the same topology link.
- Strict invalid-typed-data rejection, exact replay handling, conflicting-ID
  rejection, lossless legacy state-tag decoding, and offline evaluation artifacts.

## TOP-1/TOP-3 RESULTS — superseded by Phase 06.1 audit

The original declared-pair 1/5 Top-1 and 1/5 Top-3 calculations are withdrawn as
accuracy claims. They compared different experiment runs and incorrectly counted
invalid captures as hits/misses. See `phase-06.1.md` for the forensic audit.

**Valid Top-1: N/A. Valid Top-3: N/A. All five cases: NOT EVALUABLE.**
Raw inference still accepts LINK_FAILURE/L12 for F1 and
OSPF_CONFIGURATION_MISMATCH/L23 for F3; F2/F4/F5 abstain. These are predictions,
not measured fault-time correctness. The declared baseline has no fault candidate.

The old Phase03 truth records remain unchanged. Phase04 captures have no matching
run binding or injection/reset/recovery times. They all follow the older declared
recovery interval; that does not prove their own faults had recovered. Phase04
also changed F3/F5 targets and F4/F5 parameters. Missing typed metrics remain
missing; no labels or measurements were fabricated.

Current reports: `evaluation/reports/phase06-evaluation.md`,
`evaluation/reports/phase06-results.json`; six neutral inference artifacts are in
`evaluation/reports/phase06-diagnoses/`. The testing section below is the original
Phase06 run; Phase06.1 records newer results separately.

## SCORING SYSTEM

Dimensionless heuristic scores sum bounded signed evidence-family weights,
clamp to `[0,1]`, and round to six decimals. They are not calibrated probabilities.
Repeated observations do not repeat a family weight; downstream route withdrawals
and operational performance context carry zero added weight. Every router's RIB
prefixes share one coverage point, and availability failures share one point.

Defaults: two independent primary observation points, usable represented coverage
≥60%, leading score ≥0.65, and separation ≥0.10. A narrow margin yields AMBIGUOUS;
inadequate evidence/coverage/score yields INSUFFICIENT_EVIDENCE. Both withhold
accepted Top-1. Ties order by fault-type value and component ID without pretending
that lexical ordering resolves uncertainty.

All weights, dependency rules, coverage semantics, APIs and path assumptions are
documented in `docs/architecture/root-cause-diagnosis.md`.

## GROUND-TRUTH ISOLATION

Inference accepts typed evidence/topology or snapshot content only; filenames,
scenario metadata, injected labels and evaluation truth are never features.
Known contamination is rejected. Inference does not import evaluation or lab
control modules. The offline evaluator completes every inference call and writes
neutral results before importing or reading `FaultInjectionRecord` records.
Tests exercise this ordering and the filename/content boundary.

## TEST RESULTS

| Check | Real result |
| --- | --- |
| Backend Ruff (`.venv/bin/ruff check .`) | PASS |
| Full backend Pytest | **378 passed, 0 failed, 92 skipped**, 1 existing dependency deprecation warning |
| Phase 06 diagnosis tests | **108 passed** (included above) |
| Phase 06 evaluation tests | **20 passed** (included above) |
| New Phase 05 regression tests | **21 passed** (included above) |
| Frontend `pnpm run lint` | PASS |
| Frontend `pnpm run typecheck` | PASS |
| Frontend default `pnpm run build` | FAILED: Turbopack worker local port binding denied; elevated retry also failed |
| Frontend `pnpm exec next build --webpack` | PASS after elevated retry allowed existing Google Fonts fetch; static pages generated |
| `git diff --check` | PASS |

The 92 skips comprise 80 tests needing running NEXORA lab containers, six
explicitly gated live collector tests, and six explicitly gated live fault tests.
Live-test flags were unset for the full suite. No skip was counted as a pass.
The initial sandboxed Webpack attempt failed DNS lookup for Google Fonts; its
elevated retry succeeded. No frontend files/configuration were changed to pass.

Reproduce from `backend`:

```sh
.venv/bin/ruff check .
env -u NEXORA_RUN_FAULT_TESTS -u NEXORA_RUN_COLLECTOR_LIVE_TESTS \
  .venv/bin/python -m pytest -q -rs --tb=short
.venv/bin/python -m app.evaluation.phase06
```

## FILES CHANGED

- `backend/app/diagnosis/{engine,evidence,rules}.py`: complete inference pipeline.
- `backend/app/core/config.py`: bounded configurable sufficiency thresholds.
- `backend/app/collectors/normalizer.py`: typed validation and contamination guards.
- `backend/app/correlation/{engine,temporal}.py`: audited correlation repairs.
- `backend/app/evaluation/phase06.py`: isolated offline evaluator and CLI.
- `backend/tests/test_phase05_correlation.py`: corrected invalid/vacuous assertions.
- `backend/tests/test_phase05_regressions.py`: audit regressions.
- `backend/tests/test_phase06_diagnosis.py`: diagnosis and adapter edge cases.
- `backend/tests/test_phase06_evaluation.py`: evaluation/isolation regressions.
- `evaluation/datasets/phase06_manifest.json`: explicit offline truth pairings.
- `evaluation/reports/phase06-results.json`, `phase06-evaluation.md`,
  `phase06-diagnoses/{control,diagnosis-001,diagnosis-002,diagnosis-003,diagnosis-004,diagnosis-005}.json`.
- `backend/README.md`, `docs/architecture/root-cause-diagnosis.md`, and this report.

## KNOWN ISSUES

1. Lossy, temporally unmatched recordings prevent a valid measured accuracy
   benchmark; fresh aligned recordings require separate authorized lab work.
2. Configuration mismatch remains heuristic without observed parameter evidence.
3. When traces are unavailable, source-route remaining hops or topology shortest
   paths are inferred; localisation can remain ambiguous. An unobserved dynamic
   path change cannot be proven from static topology.
4. No collection-plan model exists in Phase 01. Coverage measures represented
   polling attempts and explicit gaps, not completely omitted planned work.
5. The default Turbopack build is blocked by this environment's local port policy.
   The supported Webpack production build passes.

## READY FOR REVIEW

**Yes, with the stated limitations.** All work remains uncommitted and unpushed
for approval. Phase 07, frontend changes and live fault injection remain outside
this implementation.
