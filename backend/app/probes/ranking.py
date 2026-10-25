"""
Deterministic probe ranking and prioritization engine for NEXORA.

Calculates an explainable diagnostic utility score in the range [0.0, 1.0].
DISCLAIMER: This score is a deterministic heuristic ranking metric, NOT a calibrated
probabilistic information gain value.
"""

from __future__ import annotations

from app.schemas.probe import PlannedProbe, ProbeCostEstimate, ProbeType


class ProbeRankingEngine:
    """Ranks proposed diagnostic probes by diagnostic discrimination and efficiency.

    Scoring formula:
        Utility = 0.40 * Discrimination + 0.30 * MissingRequired + 0.15 * Proximity + 0.15 * Cost

    Components:
    - Discrimination (40%): Distinguishes competing fault hypotheses (e.g. F2 ambiguity).
    - MissingRequired (30%): Fulfills missing REQUIRED counterfactual expectations.
    - Proximity (15%): Topological locality to the suspected fault site.
    - Cost (15%): Operational efficiency (lower packet/RTT overhead yields higher score).

    Deterministic tie-breaking:
        (-priority_score, probe_type.value, source_router, target_component, plan_id)
    """

    WEIGHT_DISCRIMINATION = 0.40
    WEIGHT_MISSING_REQUIRED = 0.30
    WEIGHT_PROXIMITY = 0.15
    WEIGHT_COST = 0.15

    def compute_priority(
        self,
        probe_type: ProbeType,
        source_router: str,
        target_component: str,
        cost: ProbeCostEstimate,
        is_ambiguity_resolver: bool = False,
        resolves_missing_required: bool = False,
        resolves_inconclusive: bool = False,
        is_confirmatory_only: bool = False,
        hop_distance: int = 1,
    ) -> tuple[float, str]:
        """Compute the heuristic utility score [0.0, 1.0] and generate an explainable rationale."""
        # 1. Discrimination factor [0.0, 1.0]
        if is_ambiguity_resolver:
            d_score = 1.0
            d_desc = "high discrimination (resolves competing fault hypotheses)"
        elif resolves_missing_required:
            d_score = 0.85
            d_desc = "targeted discrimination (resolves key missing hypothesis evidence)"
        elif resolves_inconclusive:
            d_score = 0.65
            d_desc = "moderate discrimination (resolves ambiguous observation)"
        elif is_confirmatory_only:
            d_score = 0.30
            d_desc = "low discrimination (confirmatory check on supported finding)"
        else:
            d_score = 0.50
            d_desc = "standard diagnostic discrimination"

        # 2. Missing evidence weight [0.0, 1.0]
        if resolves_missing_required:
            m_score = 1.0
            m_desc = "required observation missing"
        elif resolves_inconclusive:
            m_score = 0.70
            m_desc = "inconclusive observation needs clarity"
        elif is_confirmatory_only:
            m_score = 0.20
            m_desc = "evidence already partially observed"
        else:
            m_score = 0.40
            m_desc = "supplementary observation"

        # 3. Topological proximity [0.0, 1.0]
        if hop_distance <= 1:
            t_score = 1.0
            t_desc = "immediate adjacent vantage point (hop <= 1)"
        elif hop_distance == 2:
            t_score = 0.70
            t_desc = "two-hop traversal vantage point"
        else:
            t_score = 0.40
            t_desc = "distant vantage point (hop > 2)"

        # 4. Operational cost factor [0.0, 1.0]
        # relative_cost_score is between 1.0 and 5.0 (capped at 10.0)
        c_score = max(0.0, min(1.0, 1.0 - (cost.relative_cost_score / 10.0)))
        c_desc = f"cost score {cost.relative_cost_score:.1f} ({cost.resource_impact.value} impact)"

        total_score = (
            self.WEIGHT_DISCRIMINATION * d_score
            + self.WEIGHT_MISSING_REQUIRED * m_score
            + self.WEIGHT_PROXIMITY * t_score
            + self.WEIGHT_COST * c_score
        )
        total_score = round(max(0.0, min(1.0, total_score)), 4)

        rationale = (
            f"Utility {total_score:.4f}: {d_desc} [D={d_score:.2f}]; "
            f"{m_desc} [M={m_score:.2f}]; {t_desc} [T={t_score:.2f}]; {c_desc} [C={c_score:.2f}]."
        )
        return total_score, rationale

    def sort_probes(self, probes: list[PlannedProbe]) -> list[PlannedProbe]:
        """Sort planned probes with deterministic multi-level tie-breaking.

        Tie-breaking order:
        1. Priority score (descending)
        2. Probe type name (alphabetical ascending)
        3. Source router ID (alphabetical ascending)
        4. Target component ID (alphabetical ascending)
        5. Plan ID (alphabetical ascending)
        """
        return sorted(
            probes,
            key=lambda p: (
                -p.priority_score,
                p.probe_type.value,
                p.source_router,
                p.target_component,
                p.plan_id,
            ),
        )
