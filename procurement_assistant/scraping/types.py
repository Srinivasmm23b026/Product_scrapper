from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class OfferObservationInput:
    supplier_offer_id: uuid.UUID
    price: Decimal | None
    mrp: Decimal | None
    availability: bool | None
    observed_at: datetime
    raw_reference: str | None = None


@dataclass(frozen=True, slots=True)
class ScrapeResult:
    observations: tuple[OfferObservationInput, ...] = ()
    expected_count: int | None = None
    failed_pages: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    complete_signal: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


ScrapeAdapter = Callable[[], ScrapeResult]


def classify_result(result: ScrapeResult) -> str:
    observed = len(result.observations)
    if observed == 0:
        return "failed" if result.failed_pages else "suspicious_zero"
    if result.failed_pages or not result.complete_signal:
        return "partial"
    if result.expected_count is not None and observed != result.expected_count:
        return "partial"
    return "complete"

