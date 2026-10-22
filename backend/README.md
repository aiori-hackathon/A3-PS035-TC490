# NEXORA Backend

Deterministic, evidence-based network fault localisation backend service.

## Requirements
- Python >= 3.12
- `uv` package manager

## Quickstart
```bash
# Setup virtual environment and install dependencies
uv sync --extra dev

# Run development server
uv run uvicorn app.main:app --reload --port 8000

# Run tests
uv run pytest -v

# Run linting
uv run ruff check .
```

## Phase 06 diagnosis

Use `app.diagnosis.engine.DiagnosisEngine` with a collected, correlated Incident,
or call `diagnose_snapshot_dict(snapshot)` to run the snapshot correlation and
diagnosis pipeline. Scores are deterministic heuristics, not probabilities.

Run the offline recorded-snapshot evaluator from this directory:

```sh
.venv/bin/python -m app.evaluation.phase06
```

Architecture and score definitions: `../docs/architecture/root-cause-diagnosis.md`.
Recorded results and data limitations: `../evaluation/reports/phase06-evaluation.md`.

The Phase 06.1 evaluator excludes unbound or mistimed captures as **NOT EVALUABLE**.
It reports accuracy only for verified fault-active captures and keeps prediction
coverage separate. The five historical pairs currently yield N/A accuracy. See
`../docs/phase-reports/phase-06.1.md` for the timeline audit and recapture requirements.

## Phase 06.2 capture infrastructure

The mock-only rehearsal exercises all five bounded capture plans and creates new
synthetic artifacts. From the **repository root**, use a new output directory:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.capture.dry_run \
  --dry-run --output-dir /tmp/nexora-capture-rehearsal-new
```

This CLI has no live mode. Synthetic cases are excluded from empirical accuracy.
The programmatic `CaptureRunner` reuses the controller and `LabObserver` adapter;
real execution needs separate authorization and supervised environment preflight.
See `../docs/architecture/fault-capture.md` for measurement fidelity, provenance,
execution budgets, retained locks, and the limits of crash recovery.
