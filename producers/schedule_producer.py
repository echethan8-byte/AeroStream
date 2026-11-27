"""Aviationstack flight schedules/status -> Kafka topic schedules.raw.

Each cycle requests departures from and arrivals to the monitored airport. Free plans have very
small request quotas (and http only), so the default poll interval is long: see .env.example.

Aviationstack quirk: its timestamps carry a "+00:00" suffix but are expressed in the airport's
LOCAL time. We therefore take the wall-clock part and attach the airport's `timezone` field.
Verify this against a real response for your plan; if your plan returns true UTC, set
TREAT_TIMES_AS_LOCAL = False.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config.settings import Topics, get_settings
from producers.kafka_utils import (
    KafkaJsonProducer, RateLimited, http_session, iso_utc, parse_args, run_poll_loop, setup_logging, utc_now,
)

log = logging.getLogger("producers.schedule")

TREAT_TIMES_AS_LOCAL = True


def parse_av_time(value: str | None, tz_name: str | None) -> datetime | None:
    if not value:
        return None
    try:
        naive = datetime.fromisoformat(value[:19])
    except ValueError:
        return None
    if TREAT_TIMES_AS_LOCAL and tz_name:
        try:
            return naive.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)
        except Exception:  # unknown tz name
            pass
    return naive.replace(tzinfo=timezone.utc)


def _minutes(a: datetime | None, b: datetime | None) -> int | None:
    return None if a is None or b is None else round((a - b).total_seconds() / 60)


def parse_flight(item: dict, direction: str, airport_code: str, fetched_at: datetime) -> dict | None:
    """Convert one Aviationstack flight record to our schedule schema (None if unusable)."""
    dep, arr = item.get("departure") or {}, item.get("arrival") or {}
    flight, airline = item.get("flight") or {}, item.get("airline") or {}
    number = flight.get("iata") or flight.get("icao") or flight.get("number")
    if not number:
        return None

    def times(side: dict) -> tuple[datetime | None, datetime | None, datetime | None]:
        tz = side.get("timezone")
        return (parse_av_time(side.get("scheduled"), tz), parse_av_time(side.get("estimated"), tz),
                parse_av_time(side.get("actual"), tz))

    dep_s, dep_e, dep_a = times(dep)
    arr_s, arr_e, arr_a = times(arr)
    this_side = arr if direction == "ARRIVAL" else dep
    sched, est, act = (arr_s, arr_e, arr_a) if direction == "ARRIVAL" else (dep_s, dep_e, dep_a)
    if sched is None:
        return None

    delay = this_side.get("delay")
    if delay is None:
        delay = _minutes(act or est, sched)
    status = (item.get("flight_status") or "").lower() or None

    return {
        "flight_key": f"{number}_{item.get('flight_date') or sched.date()}_{dep.get('iata') or 'NA'}",
        "airport_code": airport_code,
        "direction": direction,
        "flight_number": number,
        "airline": airline.get("name"),
        "origin_airport": dep.get("iata"),
        "destination_airport": arr.get("iata"),
        "scheduled_departure": iso_utc(dep_s),
        "scheduled_arrival": iso_utc(arr_s),
        "estimated_departure": iso_utc(dep_e),
        "estimated_arrival": iso_utc(arr_e),
        "actual_departure": iso_utc(dep_a),
        "actual_arrival": iso_utc(arr_a),
        "flight_status": status,
        "delay_minutes": int(delay) if delay is not None else None,
        "terminal": this_side.get("terminal"),
        "gate": this_side.get("gate"),
        "source": "aviationstack",
        "event_timestamp": iso_utc(fetched_at),
    }


def fetch_page(session, base_url: str, key: str, params: dict, offset: int) -> dict:
    resp = session.get(f"{base_url}/flights", params={"access_key": key, "limit": 100, "offset": offset, **params}, timeout=30)
    if resp.status_code == 429:
        raise RateLimited(3600, "Aviationstack 429")
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        err = body["error"]
        if err.get("code") in ("rate_limit_reached", "usage_limit_reached"):
            raise RateLimited(6 * 3600, f"Aviationstack: {err.get('code')}")
        raise RuntimeError(f"Aviationstack error: {err}")
    return body


def main() -> None:
    args = parse_args(__doc__.splitlines()[0])
    setup_logging()
    cfg = get_settings()
    airports = cfg.airports
    producer = KafkaJsonProducer()
    mock = cfg.mock_mode or args.mock

    if mock:
        from producers.mock_data import mock_schedules

        def poll() -> int:
            now, sent = utc_now(), 0
            for airport in airports:
                records = mock_schedules(airport, now)
                for r in records:
                    producer.send(Topics.SCHEDULES_RAW, r, key=r["flight_key"])
                sent += len(records)
            return sent
    else:
        if not cfg.aviationstack_key:
            raise SystemExit("AVIATIONSTACK_API_KEY is not set (or run with --mock / MOCK_MODE=true)")
        session = http_session()
        log.warning(
            "Each cycle uses %d API requests; check your Aviationstack quota",
            2 * cfg.aviationstack_max_pages * len(airports),
        )

        def poll() -> int:
            now, sent = utc_now(), 0
            for airport in airports:
                for direction, param in (("DEPARTURE", "dep_iata"), ("ARRIVAL", "arr_iata")):
                    for page in range(cfg.aviationstack_max_pages):
                        body = fetch_page(session, cfg.aviationstack_base_url, cfg.aviationstack_key,
                                          {param: airport.iata}, offset=page * 100)
                        items = body.get("data") or []
                        for item in items:
                            rec = parse_flight(item, direction, airport.iata, now)
                            if rec:
                                producer.send(Topics.SCHEDULES_RAW, rec, key=rec["flight_key"])
                                sent += 1
                        if len(items) < 100:
                            break
            return sent

    run_poll_loop("schedule_producer", cfg.aviationstack_poll_seconds, poll, producer, once=args.once)


if __name__ == "__main__":
    main()
