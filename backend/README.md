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
