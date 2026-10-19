"""
Base collector class and common utilities for NEXORA evidence collection.

Provides:
- Unique evidence ID generation
- Timezone-aware UTC timestamp creation
- Safe error capturing and status representation
- Common collection lifecycle
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import ClassVar

from app.collectors.transport import CollectorTransport
from app.schemas.evidence import EvidenceRecord

DEFAULT_ROUTER_IDS: list[str] = ["R1", "R2", "R3", "R4", "R5"]


class BaseCollector(ABC):
    """Abstract base class for all specialized evidence collectors."""

    COLLECTOR_NAME: ClassVar[str] = "base"

    def __init__(self, transport: CollectorTransport) -> None:
        self.transport = transport

    def now_utc(self) -> datetime:
        """Return the current timezone-aware UTC datetime."""
        return datetime.now(UTC)

    def generate_evidence_id(self, router_id: str, suffix: str = "") -> str:
        """Generate a globally unique, auditable evidence identifier."""
        ts = int(time.time() * 1000)
        short_id = uuid.uuid4().hex[:6]
        base_id = f"ev-{self.COLLECTOR_NAME}-{router_id.lower()}-{ts}-{short_id}"
        if suffix:
            return f"{base_id}-{suffix}"
        return base_id

    @abstractmethod
    def collect(
        self,
        router_ids: list[str] | None = None,
        incident_id: str | None = None,
    ) -> list[EvidenceRecord]:
        """Collect observations for the requested router IDs."""

    def filter_router_ids(self, requested: list[str] | None) -> list[str]:
        """Validate and filter requested router IDs against defaults."""
        if requested is None:
            return list(DEFAULT_ROUTER_IDS)
        return [r.upper() for r in requested if r.upper() in DEFAULT_ROUTER_IDS]
