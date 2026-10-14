"""
Diagnostic engine interface contracts for NEXORA.

This module defines the input/output specifications for each component in the
mandatory diagnostic processing pipeline. Algorithms are NOT implemented here.

Pipeline order (mandatory, from PS-035 requirements):
  1. EvidenceCollector      — Collect network evidence
  2. IncidentCorrelator     — Normalize and correlate observations
  3. TopologyIntelligence   — Graph-aware topology context
  4. HypothesisGenerator    — Generate topology-aware fault hypotheses
  5. RuleBasedDiagnoser     — Apply deterministic rule-based scoring
  6. (Rank hypotheses)
  7. CounterfactualVerifier — Optionally verify hypotheses
  8. ActiveProbePlanner     — Optionally execute safe probes
  9. EvidenceSufficiencyEvaluator — Assess sufficiency / abstention
  10. EvidenceCertificateBuilder  — Build auditable certificate
  11. EvaluationEngine       — Offline benchmark only

Each component specifies its inputs and outputs as typed Pydantic models.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.diagnosis import DiagnosisResult, EvidenceCertificate, RankedHypothesis
from app.schemas.evidence import EvidenceRecord
from app.schemas.hypothesis import FaultHypothesis
from app.schemas.incident import Incident
from app.schemas.probe import ProbeRequest, ProbeResult
from app.schemas.topology import Topology

# ---------------------------------------------------------------------------
# Component interface contracts (Protocol classes)
# ---------------------------------------------------------------------------


@runtime_checkable
class TopologyIntelligence(Protocol):
    """Provides graph-aware topology context to other pipeline components.

    Responsibilities:
    - Maintain the current topology snapshot (or retrieve the latest).
    - Identify which routers and links are adjacent to alarmed components.
    - Compute graph-theoretic neighbour sets used by hypothesis generation.
    - Detect topological anomalies (missing adjacencies, unexpected paths).

    Inputs:
    - topology_snapshot_id: str — ID of the topology snapshot to analyse.

    Outputs:
    - Topology — current topology model.
    - neighbour_map: dict[str, list[str]] — router_id → [adjacent router_ids].
    - Reachability matrix and path information (as needed by HypothesisGenerator).
    """

    def get_topology(self, snapshot_id: str) -> Topology: ...

    def get_neighbours(self, router_id: str, topology: Topology) -> list[str]: ...


@runtime_checkable
class EvidenceCollector(Protocol):
    """Collects and normalises network observations for a given incident.

    Responsibilities:
    - Poll FRR OSPF state (adjacencies, LSDB).
    - Ingest syslog events from the collection window.
    - Poll interface operational states.
    - Read routing tables from all accessible routers.
    - Record collection status (OBSERVED / NOT_COLLECTED / COLLECTION_FAILED).
    - Attach evidence to the incident.

    Inputs:
    - incident: Incident — incident defining the collection scope and window.
    - topology: Topology — current topology for address resolution.

    Outputs:
    - list[EvidenceRecord] — all collected evidence records (including failures).

    MUST NOT:
    - Use ground-truth labels to guide collection.
    - Execute arbitrary commands on routers.
    """

    def collect(self, incident: Incident, topology: Topology) -> list[EvidenceRecord]: ...


@runtime_checkable
class IncidentCorrelator(Protocol):
    """Groups and correlates raw evidence records into coherent incidents.

    Responsibilities:
    - Deduplicate redundant alarms from the same root cause.
    - Group temporally co-incident alarms into a single Incident.
    - Mark potentially affected components from initial alarm signals.
    - Avoid creating one Incident per alarm when all alarms share a root.

    Inputs:
    - raw_evidence: list[EvidenceRecord]

    Outputs:
    - list[Incident] — one or more correlated incidents.
    """

    def correlate(self, raw_evidence: list[EvidenceRecord]) -> list[Incident]: ...


@runtime_checkable
class HypothesisGenerator(Protocol):
    """Generates topology-aware fault hypotheses from incident evidence.

    Responsibilities:
    - Use topology graph structure to identify candidate fault locations.
    - Generate FaultHypothesis objects for each plausible fault type/location pair.
    - Attach initial supporting/contradictory evidence references.
    - Enumerate missing evidence for each hypothesis.

    Inputs:
    - incident: Incident
    - evidence: list[EvidenceRecord]
    - topology: Topology

    Outputs:
    - list[FaultHypothesis] — all plausible hypotheses before scoring.

    MUST NOT:
    - Access ground-truth labels.
    - Assign final diagnosis without scoring.
    """

    def generate(
        self,
        incident: Incident,
        evidence: list[EvidenceRecord],
        topology: Topology,
    ) -> list[FaultHypothesis]: ...


@runtime_checkable
class RuleBasedDiagnoser(Protocol):
    """Applies deterministic rules to score and rank fault hypotheses.

    Responsibilities:
    - Apply predefined diagnostic rules (e.g. 'if OSPF neighbour DOWN on both
      endpoints of a link, LINK_FAILURE score += 0.8').
    - Assign rule_score to each FaultHypothesis.
    - Record the reasoning_trace for each hypothesis.
    - Produce a ranked list of hypotheses.

    Inputs:
    - hypotheses: list[FaultHypothesis]
    - evidence: list[EvidenceRecord]
    - topology: Topology

    Outputs:
    - list[RankedHypothesis] — scored and ranked hypotheses.

    MUST NOT:
    - Label rule_score as a probability.
    - Access ground-truth labels.
    """

    def score_and_rank(
        self,
        hypotheses: list[FaultHypothesis],
        evidence: list[EvidenceRecord],
        topology: Topology,
    ) -> list[RankedHypothesis]: ...


@runtime_checkable
class CounterfactualVerifier(Protocol):
    """Optionally verifies a hypothesis by testing counterfactual predictions.

    Responsibilities:
    - For a top candidate hypothesis, predict what the network state WOULD look
      like if that fault were active (e.g. R2–R3 link failure → R2 loses R3 adj.).
    - Compare predicted state against observed evidence.
    - Update hypothesis.counterfactual_verified accordingly.

    Inputs:
    - hypothesis: FaultHypothesis
    - evidence: list[EvidenceRecord]
    - topology: Topology

    Outputs:
    - FaultHypothesis — same hypothesis with counterfactual_verified populated.

    This component is OPTIONAL. The pipeline proceeds to sufficiency evaluation
    even if counterfactual verification is skipped or unavailable.
    """

    def verify(
        self,
        hypothesis: FaultHypothesis,
        evidence: list[EvidenceRecord],
        topology: Topology,
    ) -> FaultHypothesis: ...


@runtime_checkable
class ActiveProbePlanner(Protocol):
    """Plans and requests safe, bounded diagnostic probes.

    Responsibilities:
    - Given the current top hypotheses and missing evidence, determine which
      additional bounded probes would most reduce diagnostic uncertainty.
    - Generate ProbeRequest objects for approved probe types only.
    - Ensure source and destination are known topology components.

    Inputs:
    - ranked_hypotheses: list[RankedHypothesis]
    - incident: Incident
    - topology: Topology

    Outputs:
    - list[ProbeRequest] — probe requests for execution.

    MUST NOT:
    - Generate probes targeting addresses outside the known topology.
    - Generate probes that modify router state.
    - Generate more than a bounded number of probes per diagnostic session.
    """

    def plan_probes(
        self,
        ranked_hypotheses: list[RankedHypothesis],
        incident: Incident,
        topology: Topology,
    ) -> list[ProbeRequest]: ...

    def record_results(
        self,
        probe_results: list[ProbeResult],
        incident: Incident,
    ) -> list[EvidenceRecord]: ...


@runtime_checkable
class EvidenceSufficiencyEvaluator(Protocol):
    """Determines whether collected evidence is sufficient for a diagnosis.

    Responsibilities:
    - Assess whether the top-ranked hypothesis has adequate supporting evidence.
    - Detect if multiple hypotheses are too close in score to distinguish.
    - Return DIAGNOSED, AMBIGUOUS, or INSUFFICIENT_EVIDENCE.

    Inputs:
    - ranked_hypotheses: list[RankedHypothesis]
    - evidence: list[EvidenceRecord]

    Outputs:
    - DiagnosisStatus — overall outcome.
    - missing_information: list[str] — descriptions of absent evidence.
    - evidence_sufficiency_met: bool
    - collection_coverage_pct: float

    MUST allow abstention. Abstaining is correct behaviour, not a fallback.
    """

    def evaluate(
        self,
        ranked_hypotheses: list[RankedHypothesis],
        evidence: list[EvidenceRecord],
    ) -> tuple[bool, float, list[str]]: ...


@runtime_checkable
class EvidenceCertificateBuilder(Protocol):
    """Builds an auditable EvidenceCertificate from a completed diagnosis run.

    Responsibilities:
    - Count total, supporting, and contradictory evidence.
    - Document missing evidence.
    - Embed the score_interpretation disclaimer.
    - Set collection_coverage_pct.
    - Generate a unique certificate_id.

    Inputs:
    - incident: Incident
    - evidence: list[EvidenceRecord]
    - ranked_hypotheses: list[RankedHypothesis]
    - sufficiency_met: bool
    - coverage_pct: float
    - missing_info: list[str]
    - reasoning_summary: str

    Outputs:
    - EvidenceCertificate
    """

    def build(
        self,
        incident: Incident,
        evidence: list[EvidenceRecord],
        ranked_hypotheses: list[RankedHypothesis],
        sufficiency_met: bool,
        coverage_pct: float,
        missing_info: list[str],
        reasoning_summary: str,
    ) -> EvidenceCertificate: ...


@runtime_checkable
class EvaluationEngine(Protocol):
    """Offline-only evaluation of diagnostic results against ground truth.

    ISOLATED: This component runs entirely post-inference, after DiagnosisResult
    has been produced. It is the ONLY component that accesses FaultInjectionRecord.

    Responsibilities:
    - Match DiagnosisResult instances against FaultInjectionRecord ground truth.
    - Compute Top-1 and Top-3 accuracy, abstention rate, and evidence sufficiency.
    - Compare rule-based engine against optional Random Forest (offline only).
    - Produce benchmark reports in evaluation/reports/.

    Inputs:
    - diagnosis_results: list[DiagnosisResult]
    - ground_truth_records: list[FaultInjectionRecord] (from evaluation module only)

    Outputs:
    - BenchmarkReport (defined in Phase 04)

    MUST NOT:
    - Feed ground-truth labels back to the diagnostic inference pipeline.
    - Expose ground-truth labels via any API endpoint.
    """

    def evaluate(
        self,
        diagnosis_results: list[DiagnosisResult],
        # ground_truth_records type uses string to avoid import of ground_truth
        # module in live inference code paths; import lazily in implementation.
        ground_truth_records: list,  # list[FaultInjectionRecord]
    ) -> dict: ...  # dict is a placeholder; BenchmarkReport defined in Phase 04
