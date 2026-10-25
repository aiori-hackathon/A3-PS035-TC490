"""
Diagnosis results presentation endpoints for NEXORA.

Serves deterministic diagnosis outcomes, ranked hypotheses, and auditable evidence certificates.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.presentation_adapter import PresentationAdapter
from app.schemas.diagnosis import DiagnosisResult, RankedHypothesis
from app.schemas.presentation import (
    AuditableEvidenceCertificateResponse,
    DetailError,
)

router = APIRouter(prefix="/diagnosis", tags=["Diagnosis"])


@router.get(
    "",
    response_model=list[DiagnosisResult],
    status_code=status.HTTP_200_OK,
    summary="List All Incident Diagnoses",
    description="Diagnosis results with ranked hypotheses and certificates for all incidents.",
)
async def list_diagnoses() -> list[DiagnosisResult]:
    adapter = PresentationAdapter.get_instance()
    return adapter.list_diagnoses()


@router.get(
    "/{incident_id}",
    response_model=DiagnosisResult,
    responses={404: {"model": DetailError, "description": "Diagnosis not found"}},
    status_code=status.HTTP_200_OK,
    summary="Get Diagnosis for Incident",
    description="Deterministic diagnosis result, Top-1/Top-3 hypotheses, and evidence certificate.",
)
async def get_diagnosis(incident_id: str) -> DiagnosisResult:
    adapter = PresentationAdapter.get_instance()
    diag = adapter.get_diagnosis(incident_id)
    if not diag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Diagnosis result for incident '{incident_id}' not found.",
        )
    return diag


@router.get(
    "/{incident_id}/hypotheses",
    response_model=list[RankedHypothesis],
    responses={404: {"model": DetailError, "description": "Hypotheses not found"}},
    status_code=status.HTTP_200_OK,
    summary="Ranked Candidate Hypotheses",
    description="Returns ranked fault hypotheses with heuristic rule scores and reasoning traces.",
)
async def get_hypotheses(incident_id: str) -> list[RankedHypothesis]:
    adapter = PresentationAdapter.get_instance()
    hyps = adapter.get_hypotheses(incident_id)
    if not hyps and adapter.get_diagnosis(incident_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hypotheses for incident '{incident_id}' not found.",
        )
    return hyps


@router.get(
    "/{incident_id}/certificate",
    response_model=AuditableEvidenceCertificateResponse,
    responses={404: {"model": DetailError, "description": "Certificate not found"}},
    status_code=status.HTTP_200_OK,
    summary="Get Auditable Evidence Certificate for Incident",
    description=(
        "Returns full Phase 09 auditable evidence certificate with provenance and "
        "causation disclaimer."
    ),
)
async def get_evidence_certificate(incident_id: str) -> AuditableEvidenceCertificateResponse:
    adapter = PresentationAdapter.get_instance()
    cert = adapter.get_evidence_certificate(incident_id)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evidence certificate for incident '{incident_id}' not found.",
        )
    return cert
