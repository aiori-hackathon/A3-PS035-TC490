"""
Counterfactual verification presentation endpoints for NEXORA.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.presentation_adapter import PresentationAdapter
from app.schemas.counterfactual import VerificationReport
from app.schemas.presentation import DetailError

router = APIRouter(prefix="/verification", tags=["Counterfactual Verification"])


@router.get(
    "",
    response_model=list[VerificationReport],
    status_code=status.HTTP_200_OK,
    summary="List Verification Reports",
    description="Returns counterfactual verification reports across all diagnosed incidents.",
)
async def list_verifications() -> list[VerificationReport]:
    adapter = PresentationAdapter.get_instance()
    return adapter.list_verifications()


@router.get(
    "/{incident_id}",
    response_model=VerificationReport,
    responses={404: {"model": DetailError, "description": "Verification report not found"}},
    status_code=status.HTTP_200_OK,
    summary="Get Verification Report for Incident",
    description=(
        "Returns expected vs observed expectations, supporting/contradicting evidence, and verdict."
    ),
)
async def get_verification(incident_id: str) -> VerificationReport:
    adapter = PresentationAdapter.get_instance()
    rep = adapter.get_verification(incident_id)
    if not rep:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification report for incident '{incident_id}' not found.",
        )
    return rep
