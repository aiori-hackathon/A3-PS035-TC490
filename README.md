# NEXORA

> **From Correlation to Verification**  
> Evidence-Based Operator Network Fault Localisation System  
> **Team**: A3-PS035-TC490 | **Problem Statement**: PS-035 (AIORI Hackathon 3)

---

## 1. Project Overview

NEXORA is an evidence-based network fault localisation and diagnostic system. It replaces purely correlative network alerting with deterministic diagnostic reasoning, counterfactual hypothesis verification, safe read-only active probes, and mathematically auditable evidence certificates.

### Core Architecture Highlights
- **Real Network Emulation**: 5-node FRRouting / OSPFv2 network lab using Containerlab and Linux `tc/netem`.
- **Deterministic Diagnostic Reasoning**: Rule-based baseline augmented by counterfactual verification and active diagnostic probes.
- **Auditable Evidence Certificates**: Cryptographically verifiable and traceable diagnostic trails with explicit sufficiency bounds.
- **Operator Dashboard**: Dark-mode operations-center interface built with Next.js, React Flow, Recharts, and shadcn/ui.

---

## 2. Directory Structure

```
Nexora/
├── backend/                   # FastAPI backend (Modular Monolith)
│   ├── app/
│   │   ├── api/               # API route handlers (REST endpoints)
│   │   ├── core/              # Configuration, settings, security
│   │   ├── schemas/           # Pydantic v2 schemas and validation
│   │   ├── collectors/        # Syslog, telemetry, and SNMP collectors
│   │   ├── topology/          # NetworkX topology models & graph algorithms
│   │   ├── correlation/       # Temporal and spatial alarm correlation
│   │   ├── diagnosis/         # Deterministic diagnostic engine & counterfactuals
│   │   ├── probes/            # Safe bounded read-only active probing
│   │   ├── evaluation/        # Diagnostic evaluation metrics & benchmarking
│   │   └── database/          # SQLAlchemy 2 models and SQLite storage
│   └── tests/                 # Pytest test suite
├── frontend/                  # Next.js App Router frontend
│   ├── src/
│   │   ├── app/               # Next.js routes and pages
│   │   ├── components/        # Reusable UI & operational dashboard components
│   │   ├── lib/               # Typed API client, utilities, and types
│   │   └── styles/            # Tailwind CSS styling and theme
├── lab/                       # Five-node containerized network laboratory
│   ├── configs/               # Router FRRouting & interface configurations
│   ├── scenarios/             # Reproducible fault injection scenario definitions
│   └── scripts/               # Automation scripts for lab lifecycle
├── evaluation/                # Evaluation datasets and benchmark reports
│   ├── datasets/              # Held-out diagnostic evaluation datasets
│   └── reports/               # Experiment logs and verification metrics
├── docs/                      # Architectural and technical documentation
│   ├── architecture/          # Architecture blueprints and sequence diagrams
│   ├── research/              # Theoretical foundations and literature
│   └── presentation/          # Slides, pitch decks, and walkthroughs
├── scripts/                   # Workspace utility scripts
└── .github/workflows/         # Continuous Integration (CI) pipelines
```

---

## 3. Prerequisites

- **macOS (Apple Silicon)** or Linux (Ubuntu 22.04+)
- **Python**: `>= 3.12`
- **uv**: `>= 0.11` (Python dependency and environment manager)
- **Node.js**: `>= 20.x`
- **pnpm**: `>= 10.x`
- **Docker / Containerlab**: (Required for Phase 01 network lab execution)

---

## 4. Development Setup & Installation

### 4.1 Backend Setup

```bash
# Navigate to backend directory
cd backend

# Copy environment template
cp .env.example .env

# Create virtual environment and install dependencies using uv
uv sync --extra dev
```

### 4.2 Frontend Setup

```bash
# Navigate to frontend directory
cd frontend

# Copy environment template
cp .env.example .env.local

# Install dependencies using pnpm
pnpm install
```

---

## 5. Running the Application

### 5.1 Start Backend Server

```bash
cd backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
- API Base URL: `http://localhost:8000`
- Interactive OpenAPI Docs: `http://localhost:8000/docs`
- Health Endpoint: `http://localhost:8000/health`

**Expected Health Output**:
```json
{
  "status": "healthy",
  "service": "nexora-backend"
}
```

### 5.2 Start Frontend Application

```bash
cd frontend
pnpm run dev
```
- Frontend UI: `http://localhost:3000`

---

## 6. Testing & Quality Verification

### 6.1 Backend Verification

```bash
cd backend

# Run Ruff linter
uv run ruff check .

# Run Pytest suite
uv run pytest -v
```

### 6.2 Frontend Verification

```bash
cd frontend

# Run ESLint
pnpm run lint

# Run TypeScript type check
pnpm run typecheck

# Run Next.js production build
pnpm run build
```

---

## 7. Security & Isolation Guidelines

- Ground-truth injection labels remain isolated from live diagnostic inference.
- Active diagnostic probing is bounded, read-only, and non-destructive.
- No automated remediation or unrestricted agent execution is permitted.
- Never commit credentials, `.env` files, or cryptographic private keys to version control.
