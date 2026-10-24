"""
Archived evidence snapshots catalog endpoints for NEXORA.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.presentation_adapter import PresentationAdapter
from app.schemas.presentation import DetailError, SnapshotSummary

router = APIRouter(prefix="/snapshots", tags=["Evidence Snapshots"])


@router.get(
    "",
    response_model=list[SnapshotSummary],
    status_code=status.HTTP_200_OK,
    summary="List Archived Evidence Snapshots",
    description=(
        "Catalog of available scenario snapshots (baseline, F1..F5) with capture times and counts."
    ),
)
async def list_snapshots() -> list[SnapshotSummary]:
    adapter = PresentationAdapter.get_instance()
    return adapter.list_snapshots()


@router.get(
    "/{snapshot_id}",
    response_model=dict[str, Any],
    responses={404: {"model": DetailError, "description": "Snapshot not found"}},
    status_code=status.HTTP_200_OK,
    summary="Get Full Evidence Snapshot",
    description="Returns raw snapshot payload including topology and complete evidence records.",
)
async def get_snapshot(snapshot_id: str) -> dict[str, Any]:
    adapter = PresentationAdapter.get_instance()
    snap = adapter.get_snapshot(snapshot_id)
    if not snap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot '{snapshot_id}' not found in catalog.",
        )
    return snap
