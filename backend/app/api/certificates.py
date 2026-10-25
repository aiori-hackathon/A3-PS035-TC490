"""
Phase 09 Auditable Evidence Certificate presentation endpoints for NEXORA.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.presentation_adapter import PresentationAdapter
from app.schemas.presentation import AuditableEvidenceCertificateResponse, DetailError

router = APIRouter(prefix="/certificates", tags=["Evidence Certificates"])


@router.get(
    "",
    response_model=list[AuditableEvidenceCertificateResponse],
    status_code=status.HTTP_200_OK,
    summary="List All Auditable Evidence Certificates",
    description=(
        "Returns auditable certificates across all diagnosed incidents adhering to "
        "Phase 09 contract."
    ),
)
async def list_certificates() -> list[AuditableEvidenceCertificateResponse]:
    adapter = PresentationAdapter.get_instance()
    incidents = adapter.list_incidents()
    certs = []
    for inc in incidents:
        cert = adapter.get_evidence_certificate(inc.incident_id)
        if cert:
            certs.append(cert)
    return certs


@router.get(
    "/{incident_id}",
    response_model=AuditableEvidenceCertificateResponse,
    responses={404: {"model": DetailError, "description": "Certificate not found"}},
    status_code=status.HTTP_200_OK,
    summary="Get Certificate by Incident ID",
    description="Returns full Phase 09 auditable evidence certificate for a single incident.",
)
async def get_certificate(incident_id: str) -> AuditableEvidenceCertificateResponse:
    adapter = PresentationAdapter.get_instance()
    cert = adapter.get_evidence_certificate(incident_id)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evidence certificate for incident '{incident_id}' not found.",
        )
    return cert
