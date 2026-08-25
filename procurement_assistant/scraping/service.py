from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from procurement_assistant.models import PriceObservation, ScrapeRun, SupplierOffer
from procurement_assistant.scraping.types import ScrapeAdapter, ScrapeResult, classify_result


class ScrapePersistenceError(RuntimeError):
    """Raised after a failed persistence transaction has been recorded."""


class ScrapeRunService:
    def __init__(self, session_factory: sessionmaker[Session], *, retire_after_misses: int = 3):
        if retire_after_misses < 1:
            raise ValueError("retire_after_misses must be positive")
        self.session_factory = session_factory
        self.retire_after_misses = retire_after_misses

    def execute(
        self,
        *,
        supplier_id: uuid.UUID,
        supplier_location_id: uuid.UUID,
        adapter: ScrapeAdapter,
    ) -> uuid.UUID:
        run_id = self._start_run(supplier_id, supplier_location_id)
        try:
            result = adapter()
        except Exception as exc:
            self._finish_failed(run_id, f"adapter failure: {type(exc).__name__}: {exc}")
            return run_id

        try:
            self._persist_result(run_id, supplier_location_id, result)
        except Exception as exc:
            self._finish_failed(run_id, f"persistence failure: {type(exc).__name__}: {exc}")
            raise ScrapePersistenceError(str(exc)) from exc
        return run_id

    def mark_interrupted(self, *, older_than: timedelta) -> int:
        cutoff = datetime.now(UTC) - older_than
        with self.session_factory.begin() as session:
            runs = session.scalars(
                select(ScrapeRun).where(
                    ScrapeRun.status == "running", ScrapeRun.started_at < cutoff
                )
            ).all()
            now = datetime.now(UTC)
            for run in runs:
                run.status = "interrupted"
                run.finished_at = now
                run.error_summary = "run did not reach a terminal state"
            return len(runs)

    def _start_run(self, supplier_id: uuid.UUID, supplier_location_id: uuid.UUID) -> uuid.UUID:
        with self.session_factory.begin() as session:
            run = ScrapeRun(
                supplier_id=supplier_id,
                supplier_location_id=supplier_location_id,
                status="running",
            )
            session.add(run)
            session.flush()
            return run.id

    def _persist_result(
        self,
        run_id: uuid.UUID,
        supplier_location_id: uuid.UUID,
        result: ScrapeResult,
    ) -> None:
        status = classify_result(result)
        with self.session_factory.begin() as session:
            run = session.get(ScrapeRun, run_id)
            if run is None:
                raise LookupError(f"scrape run {run_id} does not exist")

            seen_offer_ids: set[uuid.UUID] = set()
            for item in result.observations:
                if item.supplier_offer_id in seen_offer_ids:
                    raise ValueError(f"duplicate offer observation: {item.supplier_offer_id}")
                offer = session.get(SupplierOffer, item.supplier_offer_id)
                if offer is None:
                    raise LookupError(f"supplier offer {item.supplier_offer_id} does not exist")
                if offer.supplier_location_id != supplier_location_id:
                    raise ValueError("observation offer belongs to a different supplier location")

                observation = PriceObservation(
                    supplier_offer_id=offer.id,
                    scrape_run_id=run.id,
                    price=item.price,
                    mrp=item.mrp,
                    availability=item.availability,
                    observed_at=item.observed_at,
                    raw_reference=item.raw_reference,
                )
                session.add(observation)
                session.flush()
                offer.current_price = item.price
                offer.current_mrp = item.mrp
                offer.current_availability = item.availability
                offer.last_seen_at = item.observed_at
                offer.current_observation_id = observation.id
                offer.consecutive_misses = 0
                offer.active = True
                seen_offer_ids.add(offer.id)

            if status == "complete":
                unseen = session.scalars(
                    select(SupplierOffer).where(
                        SupplierOffer.supplier_location_id == supplier_location_id,
                        SupplierOffer.active.is_(True),
                        SupplierOffer.id.not_in(seen_offer_ids),
                    )
                ).all()
                for offer in unseen:
                    offer.consecutive_misses += 1
                    if offer.consecutive_misses >= self.retire_after_misses:
                        offer.active = False
                        offer.current_availability = False

            run.status = status
            run.finished_at = datetime.now(UTC)
            run.expected_count = result.expected_count
            run.observed_count = len(result.observations)
            run.failed_page_count = len(result.failed_pages)
            run.warning_count = len(result.warnings)
            run.error_summary = "; ".join(result.failed_pages) or None
            run.run_metadata = {
                **result.metadata,
                "failed_pages": list(result.failed_pages),
                "warnings": list(result.warnings),
                "complete_signal": result.complete_signal,
            }

    def _finish_failed(self, run_id: uuid.UUID, summary: str) -> None:
        with self.session_factory.begin() as session:
            run = session.get(ScrapeRun, run_id)
            if run is None:
                raise LookupError(f"scrape run {run_id} does not exist")
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            run.error_summary = summary[:4000]

