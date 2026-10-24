"""
Incident presentation endpoints for NEXORA.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.presentation_adapter import PresentationAdapter
from app.schemas.presentation import DetailError, IncidentSummary

router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.get(
    "",
    response_model=list[IncidentSummary],
    status_code=status.HTTP_200_OK,
    summary="List Correlated Incidents",
    description="Summaries of all incidents formed across archived scenarios or for a snapshot.",
)
async def list_incidents(
    snapshot_id: str | None = Query(
        default=None, description="Optional scenario key or snapshot ID filter."
    ),
) -> list[IncidentSummary]:
    adapter = PresentationAdapter.get_instance()
    return adapter.list_incidents(snapshot_id)


@router.get(
    "/{incident_id}",
    response_model=IncidentSummary,
    responses={404: {"model": DetailError, "description": "Incident not found"}},
    status_code=status.HTTP_200_OK,
    summary="Get Incident Summary",
    description="Affected components, evidence count, and correlation explanation for an incident.",
)
async def get_incident(incident_id: str) -> IncidentSummary:
    adapter = PresentationAdapter.get_instance()
    inc = adapter.get_incident(incident_id)
    if not inc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )
    return inc
