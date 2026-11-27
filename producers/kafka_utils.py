"""Shared helpers for the API producers: Kafka client, HTTP session, polling loop, heartbeats."""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from typing import Callable

from config.settings import Topics, get_settings

log = logging.getLogger("producers")


class RateLimited(Exception):
    """Raised by a poll function when the upstream API asks us to back off."""

    def __init__(self, retry_after_seconds: float, message: str = "rate limited"):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime | None) -> str | None:
    """Format as 2026-11-23T08:30:00Z (the format the Flink JSON sources expect)."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1.0, status_forcelist=(500, 502, 503, 504), allowed_methods=("GET", "POST"))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "realtime-flight-monitoring/1.0 (student project)"
    return session


class KafkaJsonProducer:
    def __init__(self, bootstrap_servers: str | None = None):
        from confluent_kafka import Producer

        servers = bootstrap_servers or get_settings().kafka_bootstrap
        self._producer = Producer({"bootstrap.servers": servers, "linger.ms": 50, "acks": "all"})
        self.errors = 0

    def _on_delivery(self, err, msg) -> None:
        if err is not None:
            self.errors += 1
            log.error("delivery failed for %s: %s", msg.topic(), err)

    def send(self, topic: str, value: dict, key: str | None = None) -> None:
        self._producer.produce(
            topic,
            key=key.encode() if key else None,
            value=json.dumps(value, separators=(",", ":")).encode(),
            on_delivery=self._on_delivery,
        )
        self._producer.poll(0)

    def flush(self, timeout: float = 10.0) -> None:
        self._producer.flush(timeout)


def publish_health(producer: KafkaJsonProducer, component: str, status: str, records: int, message: str | None) -> None:
    producer.send(
        Topics.PIPELINE_HEALTH,
        {
            "component": component,
            "status": status,
            "records_published": records,
            "message": message,
            "event_timestamp": iso_utc(utc_now()),
        },
    )


def run_poll_loop(
    component: str,
    interval_seconds: float,
    poll_fn: Callable[[], int],
    producer: KafkaJsonProducer,
    once: bool = False,
) -> None:
    """Call poll_fn every interval. poll_fn returns the number of records it published.

    Failures never kill the loop: they are logged, reported to pipeline.health, and retried.
    """
    log.info("%s started (interval=%ss, once=%s)", component, interval_seconds, once)
    while True:
        started = time.monotonic()
        wait = None
        try:
            count = poll_fn()
            publish_health(producer, component, "OK", count, None)
            log.info("%s published %d records", component, count)
        except RateLimited as exc:
            wait = exc.retry_after_seconds
            log.warning("%s rate limited, backing off %.0fs", component, wait)
            publish_health(producer, component, "RATE_LIMITED", 0, str(exc))
        except Exception as exc:  # noqa: BLE001 - keep the pipeline alive
            log.exception("%s poll failed", component)
            publish_health(producer, component, "ERROR", 0, str(exc)[:500])
        producer.flush()
        if once:
            return
        sleep_for = wait if wait is not None else max(1.0, interval_seconds - (time.monotonic() - started))
        time.sleep(sleep_for)


def parse_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--once", action="store_true", help="poll a single time and exit")
    parser.add_argument("--mock", action="store_true", help="emit synthetic data (same as MOCK_MODE=true)")
    return parser.parse_args()
