from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Protocol

from procurement_assistant.models import ScrapeRun
from procurement_assistant.settings import Settings

LOGGER = logging.getLogger("procurement.events")


def log_event(event: str, **fields) -> None:
    LOGGER.info(
        json.dumps(
            {"event": event, "timestamp": datetime.now(UTC).isoformat(), **fields},
            default=str,
            separators=(",", ":"),
        )
    )


class MetricsSink(Protocol):
    def record_scrape_run(self, source: str, run: ScrapeRun, duration_seconds: float) -> None: ...


class LogMetricsSink:
    def record_scrape_run(self, source: str, run: ScrapeRun, duration_seconds: float) -> None:
        log_event(
            "scrape_run_finished",
            supplier=source,
            supplier_location=str(run.supplier_location_id),
            scrape_run_id=str(run.id),
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            duration_seconds=round(duration_seconds, 3),
            expected_count=run.expected_count,
            observed_count=run.observed_count,
            failed_pages=run.failed_page_count,
            warnings=run.warning_count,
            error=run.error_summary,
        )


class CloudWatchMetricsSink(LogMetricsSink):
    def __init__(self, *, namespace: str, region: str):
        import boto3

        self.namespace = namespace
        self.client = boto3.client("cloudwatch", region_name=region)

    def record_scrape_run(self, source: str, run: ScrapeRun, duration_seconds: float) -> None:
        super().record_scrape_run(source, run, duration_seconds)
        dimensions = [{"Name": "Supplier", "Value": source}]
        self.client.put_metric_data(
            Namespace=self.namespace,
            MetricData=[
                {
                    "MetricName": "RunComplete",
                    "Dimensions": dimensions,
                    "Value": 1 if run.status == "complete" else 0,
                },
                {
                    "MetricName": "ObservedProducts",
                    "Dimensions": dimensions,
                    "Value": run.observed_count,
                },
                {
                    "MetricName": "RunFailure",
                    "Dimensions": dimensions,
                    "Value": 0 if run.status == "complete" else 1,
                },
                {
                    "MetricName": "DurationSeconds",
                    "Dimensions": dimensions,
                    "Value": duration_seconds,
                },
            ],
        )


def configure_metrics(settings: Settings) -> MetricsSink:
    if settings.metrics_provider == "cloudwatch":
        if not settings.cloudwatch_namespace:
            raise ValueError("CloudWatch metrics require CLOUDWATCH_NAMESPACE")
        return CloudWatchMetricsSink(
            namespace=settings.cloudwatch_namespace, region=settings.aws_region
        )
    return LogMetricsSink()
