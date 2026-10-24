from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.diagnosis import router as diagnosis_router
from app.api.evidence import router as evidence_router
from app.api.health import router as health_router
from app.api.incidents import router as incidents_router
from app.api.probes import router as probes_router
from app.api.readiness import router as readiness_router
from app.api.snapshots import router as snapshots_router
from app.api.topology import router as topology_router
from app.api.verification import router as verification_router
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Lifespan context for startup and shutdown routines
    yield


def create_application() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="NEXORA - Evidence-Based Operator Network Fault Localisation System",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Configure CORS explicitly for configured origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Health & Readiness root routes
    app.include_router(health_router)
    app.include_router(readiness_router)

    # Versioned API routes (/api/v1)
    app.include_router(health_router, prefix=settings.API_V1_PREFIX)
    app.include_router(readiness_router, prefix=settings.API_V1_PREFIX)
    app.include_router(topology_router, prefix=settings.API_V1_PREFIX)
    app.include_router(snapshots_router, prefix=settings.API_V1_PREFIX)
    app.include_router(incidents_router, prefix=settings.API_V1_PREFIX)
    app.include_router(diagnosis_router, prefix=settings.API_V1_PREFIX)
    app.include_router(verification_router, prefix=settings.API_V1_PREFIX)
    app.include_router(probes_router, prefix=settings.API_V1_PREFIX)
    app.include_router(evidence_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_application()
