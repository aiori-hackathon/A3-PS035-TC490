"""
Active diagnostic probe recommendation endpoints for NEXORA.

Read-only presentation endpoints with strict safety boundaries.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.presentation_adapter import PresentationAdapter
from app.schemas.presentation import DetailError, SafeProbePlanResponse

router = APIRouter(prefix="/probes", tags=["Active Probes"])


@router.get(
    "/recommendations",
    response_model=list[SafeProbePlanResponse],
    status_code=status.HTTP_200_OK,
    summary="List Safe Probe Plans",
    description="Returns recommended safe read-only probe plans across all diagnosed incidents.",
)
async def list_probe_plans() -> list[SafeProbePlanResponse]:
    adapter = PresentationAdapter.get_instance()
    incidents = adapter.list_incidents()
    plans = []
    for inc in incidents:
        plans.append(adapter.get_probe_plan(inc.incident_id))
    return plans


@router.get(
    "/recommendations/{incident_id}",
    response_model=SafeProbePlanResponse,
    responses={404: {"model": DetailError, "description": "Incident not found"}},
    status_code=status.HTTP_200_OK,
    summary="Get Safe Probe Plan for Incident",
    description=(
        "Returns read-only recommended next checks, target router/interfaces, and guardrails."
    ),
)
async def get_probe_plan(incident_id: str) -> SafeProbePlanResponse:
    adapter = PresentationAdapter.get_instance()
    inc = adapter.get_incident(incident_id)
    if not inc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )
    return adapter.get_probe_plan(incident_id)
