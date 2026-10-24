"""
Readiness and operational health endpoints for NEXORA.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.presentation_adapter import PresentationAdapter
from app.schemas.presentation import SystemReadinessResponse

router = APIRouter(tags=["System Readiness"])


@router.get(
    "/readiness",
    response_model=SystemReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Subsystem Readiness Check",
    description=(
        "Returns granular readiness across all diagnostic, verification, and topology subsystems."
    ),
)
async def get_readiness() -> SystemReadinessResponse:
    adapter = PresentationAdapter.get_instance()
    return adapter.get_system_readiness()
