# NEXORA — Certified Evidence Transfer Manifest & Offline Synchronization Guide

**Author:** Track A (Core Intelligence)  
**Target Device:** MacBook 2 (Track B: Dashboard & API Presentation)  
**Status:** Approved for Secure Offline Transfer  
**Public Repository Notice:** The GitHub repository [https://github.com/aiori-hackathon/A3-PS035-TC490.git](https://github.com/aiori-hackathon/A3-PS035-TC490.git) is **PUBLIC**. **DO NOT** commit raw live evidence archives, capture bindings, machine-local metadata, or `truth.json` sidecars to the Git repository.

---

## 1. Executive Summary

Track B (MacBook 2) currently possesses the committed benchmark fixtures in `evaluation/datasets/observations/` but lacks the certified live F1–F5 neutral evidence archives captured and validated on MacBook 1.

This document defines the cryptographic manifest for offline peer-to-peer transfer (via AirDrop, encrypted USB, or secure scp on local network) from MacBook 1 to MacBook 2 to enable Track B to execute the full Certified Live Replay suite locally.

---

## 2. Certified Live Evidence Manifest

Each scenario directory contains two files required for offline live replay and provenance auditing:
1. `snapshot.json`: The neutral, ground-truth-isolated evidence snapshot containing topology and all collected telemetry records.
2. `binding.json`: The cryptographic provenance binding linking the capture run ID, canonical SHA-256 digest, and execution parameters.

| Scenario | Run ID | Snapshot ID | Canonical SHA-256 Digest | Records | Primary Diagnostic Outcome |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **F1 (Link Failure)** | `exp-aab6c8bcaad34acfaa7583d3ea391948` | `obs-snap-20261021T113754Z-520097` | `fcf27ee3289d349e0b74ec8d4fa2e790e2c265e4ae9eab0527ab1d87c58e2b82` | 103 | `LINK_FAILURE` on `L12` (Score: 0.7500, `SUPPORTED`) |
| **F2 (Router Failure)** | `exp-5acb69cba29d4b0497f4de2b3b97f1b6` | `obs-snap-20261023T043320Z-ce2b18` | `de21d913f6804eb0d921e9d01d61a3b0f4ce2c4c28c5d676f95640cf7dd2719e` | 100 | `ROUTER_FAILURE` on `R3` (Score: 1.0000, `SUPPORTED`) |
| **F3 (OSPF Mismatch)** | `exp-3d67ba780db64eff83471cacc1a80ea4` | `obs-snap-20261023T063936Z-94f9cb` | `aeb28a1ffb7ed4c888ed2c3ec64c68091dbdf8c8edff6a2b6ac4b98b717ec0da` | 108 | `OSPF_CONFIGURATION_MISMATCH` on `L12` (Score: 0.8000, `SUPPORTED`) |
| **F4 (Packet Loss)** | `exp-1e5e22df3c124d21a58e50884cc54b82` | `obs-snap-20261023T084659Z-579a0c` | `04c8c9d9a2378656b454a11d057f865610c0cb5fc3e6f102da6a091e704a7194` | 112 | `PACKET_LOSS` on `L12` (Score: 0.6500, `SUPPORTED`) |
| **F5 (High Latency)** | `exp-46f8c718e43a494ba628eb7f724325b4` | `obs-snap-20261023T090900Z-211953` | `2fbfe11e0c70ea7340f182278d5db092b8edfe4b4be7f93575b77a64da817466` | 112 | `HIGH_LATENCY` on `L12` (Score: 0.6500, `SUPPORTED`) |

---

## 3. Source Archive Locations on MacBook 1

```
/Users/azriel/Nexora-backups/live-evidence/
├── f1-exp-aab6c8bcaad34acfaa7583d3ea391948/
│   ├── snapshot.json
│   └── binding.json
├── f2-exp-5acb69cba29d4b0497f4de2b3b97f1b6/
│   └── 67bc39cd97744d9d92848847ad6c3945/
│       ├── snapshot.json
│       └── binding.json
├── f3-exp-3d67ba780db64eff83471cacc1a80ea4/
│   ├── snapshot.json
│   └── binding.json
├── f4-exp-1e5e22df3c124d21a58e50884cc54b82/
│   ├── snapshot.json
│   └── binding.json
└── f5-exp-46f8c718e43a494ba628eb7f724325b4/
    ├── snapshot.json
    └── binding.json
```

---

## 4. Setup Instructions for MacBook 2

1. **Create Destination Directory:**
   ```bash
   mkdir -p ~/Nexora-backups/live-evidence
   ```
2. **Transfer Archives Offline:**
   Transfer the 5 scenario directories above into `~/Nexora-backups/live-evidence/` via AirDrop or secure local transfer.
3. **Configure Environment Variable:**
   ```bash
   export NEXORA_LIVE_EVIDENCE_DIR="$HOME/Nexora-backups/live-evidence"
   ```
   Add this line to your `~/.zshrc` on MacBook 2 for persistent access.
4. **Verify Integrity on MacBook 2:**
   Run the full test suite with the environment variable set:
   ```bash
   uv run pytest backend/tests/test_phase07_counterfactual.py backend/tests/test_phase09_evidence_certificates.py -v
   ```
   All certified live replay tests will transition from `SKIPPED` to `PASSED` with verified cryptographic digest matches.

---

## 5. Security & Isolation Invariants

1. **Public Repository Isolation:**
   - The `.gitignore` file must continue to exclude any local backup directories and capture runtime dumps.
   - Never stage `~/Nexora-backups/` or any file named `truth.json`.
2. **Ground-Truth Isolation:**
   - `snapshot.json` files contain zero ground truth labels. Telemetry records contain only neutral observable facts (interface status, OSPF neighbor state, ping RTT/loss).
   - If a `ground_truth` token or section is accidentally present, `EvidenceNormalizer.assert_no_ground_truth_leakage()` will immediately reject it with `GroundTruthLeakageError`.
3. **No Dynamic Execution:**
   - Replaying these snapshots executes purely offline analytical verification, probe planning, and certificate compilation. No network packets or Docker commands are executed.
