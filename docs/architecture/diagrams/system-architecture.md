# NEXORA — System Architecture Diagram

**Team**: A3-PS035-TC490 | **PS-035**

```mermaid
graph TB
    subgraph LAB["Network Laboratory (ARM64 Linux VM)"]
        R1["R1 FRRouting\nOSPFv2"]
        R2["R2 FRRouting\nOSPFv2"]
        R3["R3 FRRouting\nOSPFv2"]
        R4["R4 FRRouting\nOSPFv2"]
        R5["R5 FRRouting\nOSPFv2"]
        LC["Lab Controller\ntc/netem fault injection"]
        LC -. "injects fault" .-> R1
        LC -. "injects fault" .-> R2
        LC -. "injects fault" .-> R3
        LC -. "injects fault" .-> R4
        LC -. "injects fault" .-> R5
    end

    subgraph BACKEND["Backend (FastAPI / Python 3.12)"]
        direction TB
        EC["EvidenceCollector\nsyslog, OSPF poll, ping"]
        IC["IncidentCorrelator"]
        TI["TopologyIntelligence\nNetworkX graph"]
        HG["HypothesisGenerator"]
        RBD["RuleBasedDiagnoser\ndeterministic rules"]
        CV["CounterfactualVerifier\n(optional)"]
        APP["ActiveProbePlanner\n(optional, bounded probes)"]
        ESE["EvidenceSufficiencyEvaluator"]
        ECB["EvidenceCertificateBuilder"]
        DR["DiagnosisResult\n+ EvidenceCertificate"]

        EC --> IC
        IC --> TI
        TI --> HG
        HG --> RBD
        RBD --> CV
        CV --> APP
        APP --> ESE
        ESE --> ECB
        ECB --> DR
    end

    subgraph EVAL["Offline Evaluation (isolated)"]
        FIR["FaultInjectionRecord\nGROUND-TRUTH LABELS"]
        EE["EvaluationEngine"]
        RF["Random Forest\n(optional comparison)"]
        BR["BenchmarkReport"]
        FIR --> EE
        DR --> EE
        EE --> RF
        EE --> BR
    end

    subgraph FRONTEND["Operator Dashboard (Next.js)"]
        UI["Operations Console"]
        API["FastAPI REST Endpoints"]
        API --> UI
    end

    R1 & R2 & R3 & R4 & R5 -->|"syslog / polls"| EC
    LC -->|"FaultInjectionRecord"| FIR
    DR -->|"stored"| API

    style FIR fill:#7f1d1d,color:#fef2f2
    style EVAL fill:#1c1917,color:#e7e5e4
    style FIR stroke:#dc2626,stroke-width:2px
    style DR fill:#064e3b,color:#ecfdf5
```

---

## Component Key

| Symbol | Component |
|--------|-----------|
| `R1–R5` | FRRouting OSPFv2 containers (Containerlab) |
| `Lab Controller` | Fault injection script (`tc/netem`, container stop) |
| `FaultInjectionRecord` | Ground-truth labels (ISOLATED from inference) |
| `EvidenceCollector` | Multi-source observation ingestion |
| `IncidentCorrelator` | Alarm grouping and deduplication |
| `TopologyIntelligence` | NetworkX graph context |
| `HypothesisGenerator` | Candidate fault generation |
| `RuleBasedDiagnoser` | Deterministic scoring |
| `CounterfactualVerifier` | Optional hypothesis validation |
| `ActiveProbePlanner` | Optional bounded read-only probes |
| `EvidenceSufficiencyEvaluator` | Abstention gating |
| `EvidenceCertificateBuilder` | Audit certificate generation |
| `EvaluationEngine` | Offline-only post-inference comparison |
| `Random Forest` | Optional offline comparison model |
