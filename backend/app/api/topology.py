"""
Topology presentation endpoints for NEXORA.

Serves 5-node FRRouting / OSPFv2 topology snapshots, router health, and link states.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.presentation_adapter import PresentationAdapter
from app.schemas.presentation import (
    DetailError,
    LinkDetailResponse,
    RouterDetailResponse,
    TopologyStatusSummary,
)
from app.schemas.topology import Topology

router = APIRouter(prefix="/topology", tags=["Topology"])


@router.get(
    "",
    response_model=Topology,
    status_code=status.HTTP_200_OK,
    summary="Active or Scenario Topology Snapshot",
    description="Five-node topology snapshot for the given scenario or active snapshot.",
)
async def get_topology(
    snapshot_id: str | None = Query(
        default=None,
        description="Optional snapshot ID or scenario key ('baseline', 'f1'..'f5', 'canonical').",
    ),
) -> Topology:
    adapter = PresentationAdapter.get_instance()
    return adapter.get_topology(snapshot_id)


@router.get(
    "/canonical",
    response_model=Topology,
    status_code=status.HTTP_200_OK,
    summary="Canonical Five-Router Baseline Topology",
    description="Returns the reference Phase 01 five-node ring topology specification.",
)
async def get_canonical_topology() -> Topology:
    adapter = PresentationAdapter.get_instance()
    return adapter.get_canonical_topology()


@router.get(
    "/status",
    response_model=TopologyStatusSummary,
    status_code=status.HTTP_200_OK,
    summary="Topology Operational Health Metrics",
    description="Summary counts and status evaluations for all 5 routers and 5 links.",
)
async def get_topology_status(
    snapshot_id: str | None = Query(
        default=None,
        description="Optional scenario key ('baseline', 'f1'..'f5') or snapshot ID.",
    ),
) -> TopologyStatusSummary:
    adapter = PresentationAdapter.get_instance()
    return adapter.get_topology_status(snapshot_id)


@router.get(
    "/routers",
    response_model=list[RouterDetailResponse],
    status_code=status.HTTP_200_OK,
    summary="List All Topology Routers",
    description="Interface configurations, loopback IPs, and OSPF IDs for all routers.",
)
async def list_routers(
    snapshot_id: str | None = Query(
        default=None, description="Optional scenario key or snapshot ID."
    ),
) -> list[RouterDetailResponse]:
    adapter = PresentationAdapter.get_instance()
    return adapter.list_routers(snapshot_id)


@router.get(
    "/routers/{router_id}",
    response_model=RouterDetailResponse,
    responses={404: {"model": DetailError, "description": "Router not found"}},
    status_code=status.HTTP_200_OK,
    summary="Router Details",
    description="Returns full interface, role, and peer details for a single router.",
)
async def get_router(
    router_id: str,
    snapshot_id: str | None = Query(
        default=None, description="Optional scenario key or snapshot ID."
    ),
) -> RouterDetailResponse:
    adapter = PresentationAdapter.get_instance()
    router_detail = adapter.get_router(router_id, snapshot_id)
    if not router_detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Router '{router_id}' not found in topology.",
        )
    return router_detail


@router.get(
    "/links",
    response_model=list[LinkDetailResponse],
    status_code=status.HTTP_200_OK,
    summary="List All Ring Links",
    description="Point-to-point links (L12..L51) with subnets and endpoint health.",
)
async def list_links(
    snapshot_id: str | None = Query(
        default=None, description="Optional scenario key or snapshot ID."
    ),
) -> list[LinkDetailResponse]:
    adapter = PresentationAdapter.get_instance()
    return adapter.list_links(snapshot_id)


@router.get(
    "/links/{link_id}",
    response_model=LinkDetailResponse,
    responses={404: {"model": DetailError, "description": "Link not found"}},
    status_code=status.HTTP_200_OK,
    summary="Link Details",
    description="Returns interface endpoints, subnets, and calculated health for a single link.",
)
async def get_link(
    link_id: str,
    snapshot_id: str | None = Query(
        default=None, description="Optional scenario key or snapshot ID."
    ),
) -> LinkDetailResponse:
    adapter = PresentationAdapter.get_instance()
    link_detail = adapter.get_link(link_id, snapshot_id)
    if not link_detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Link '{link_id}' not found in topology.",
        )
    return link_detail
