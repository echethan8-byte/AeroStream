"""Open-Meteo current weather at the monitored airport -> Kafka topic weather.raw.

Open-Meteo "current" values come from weather models/assimilation for the airport's coordinates,
not from the airport's own METAR sensors, and refresh in 15-minute steps. Repeated polls inside the
same step carry the same weather_timestamp and are de-duplicated downstream.

Units: temperature deg C, wind km/h, visibility metres, precipitation mm.
"""
from __future__ import annotations

import logging

from config.settings import Topics, get_settings
from producers.kafka_utils import (
    KafkaJsonProducer, RateLimited, http_session, parse_args, run_poll_loop, setup_logging, utc_now,
)

log = logging.getLogger("producers.weather")

URL = "https://api.open-meteo.com/v1/forecast"
CURRENT_VARS = "temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,cloud_cover,weather_code,visibility"


def parse_current(body: dict, airport_code: str) -> dict | None:
    cur = body.get("current")
    if not cur or not cur.get("time"):
        return None
    return {
        "airport_code": airport_code,
        "temperature": cur.get("temperature_2m"),
        "wind_speed": cur.get("wind_speed_10m"),
        "wind_gusts": cur.get("wind_gusts_10m"),
        "wind_direction": cur.get("wind_direction_10m"),
        "visibility": cur.get("visibility"),
        "precipitation": cur.get("precipitation"),
        "cloud_cover": cur.get("cloud_cover"),
        "weather_code": cur.get("weather_code"),
        "weather_timestamp": cur["time"][:16] + ":00Z",   # request uses timezone=UTC
        "source": "open_meteo",
    }


def main() -> None:
    args = parse_args(__doc__.splitlines()[0])
    setup_logging()
    cfg = get_settings()
    airports = cfg.airports
    producer = KafkaJsonProducer()
    mock = cfg.mock_mode or args.mock
    session = http_session()

    def poll() -> int:
        now, sent = utc_now(), 0
        for airport in airports:
            if mock:
                from producers.mock_data import mock_weather

                event = mock_weather(airport, now)
            else:
                resp = session.get(
                    URL,
                    params={"latitude": airport.latitude, "longitude": airport.longitude,
                            "current": CURRENT_VARS, "timezone": "UTC", "wind_speed_unit": "kmh"},
                    timeout=20,
                )
                if resp.status_code == 429:
                    raise RateLimited(600, "Open-Meteo 429")
                resp.raise_for_status()
                event = parse_current(resp.json(), airport.iata)
                if event is None:
                    raise RuntimeError(f"Open-Meteo response had no 'current' block for {airport.iata}")
            producer.send(Topics.WEATHER_RAW, event, key=airport.iata)
            sent += 1
        return sent

    run_poll_loop("weather_producer", cfg.weather_poll_seconds, poll, producer, once=args.once)


if __name__ == "__main__":
    main()
