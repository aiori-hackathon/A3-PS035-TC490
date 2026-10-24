"""
Evidence explorer presentation endpoints for NEXORA.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.presentation_adapter import PresentationAdapter
from app.schemas.evidence import EvidenceRecord
from app.schemas.presentation import DetailError, EvidenceQueryResponse

router = APIRouter(prefix="/evidence", tags=["Evidence Explorer"])


@router.get(
    "",
    response_model=EvidenceQueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Query and Filter Evidence",
    description="Filter evidence records by router, collector source, event type, or snapshot.",
)
async def query_evidence(
    router_id: str | None = Query(
        default=None, description="Filter by source router ID (e.g. 'R1')."
    ),
    source_type: str | None = Query(
        default=None, description="Filter by source type (e.g. 'OSPF_API')."
    ),
    event_type: str | None = Query(
        default=None, description="Filter by event type (e.g. 'OSPF_NEIGHBOUR_DOWN')."
    ),
    incident_id: str | None = Query(default=None, description="Filter by associated incident ID."),
    snapshot_id: str | None = Query(
        default=None, description="Scenario key ('f1'..'f5', 'baseline') or snapshot ID."
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Page limit."),
    offset: int = Query(default=0, ge=0, description="Page offset."),
) -> EvidenceQueryResponse:
    adapter = PresentationAdapter.get_instance()
    items = adapter.query_evidence(
        router_id=router_id,
        source_type=source_type,
        event_type=event_type,
        incident_id=incident_id,
        snapshot_id=snapshot_id,
        limit=limit,
        offset=offset,
    )
    total = adapter.count_evidence(
        router_id=router_id,
        source_type=source_type,
        event_type=event_type,
        incident_id=incident_id,
        snapshot_id=snapshot_id,
    )
    applied = {
        "router_id": router_id,
        "source_type": source_type,
        "event_type": event_type,
        "incident_id": incident_id,
        "snapshot_id": snapshot_id,
    }
    return EvidenceQueryResponse(
        total_count=total,
        limit=limit,
        offset=offset,
        items=items,
        applied_filters={k: v for k, v in applied.items() if v is not None},
    )


@router.get(
    "/{evidence_id}",
    response_model=EvidenceRecord,
    responses={404: {"model": DetailError, "description": "Evidence record not found"}},
    status_code=status.HTTP_200_OK,
    summary="Get Evidence Record Details",
    description="Returns single EvidenceRecord by unique evidence identifier.",
)
async def get_evidence(evidence_id: str) -> EvidenceRecord:
    adapter = PresentationAdapter.get_instance()
    rec = adapter.get_evidence(evidence_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evidence record '{evidence_id}' not found.",
        )
    return rec
