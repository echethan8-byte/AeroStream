"""OpenSky live aircraft states -> Kafka topic flights.raw.

OpenSky returns tracking data only (position, altitude, speed, on-ground flag). It has no
schedules, gates or delays: those come from the schedule producer.

Units are kept as OpenSky reports them: altitude in metres, velocity in m/s, vertical_rate in m/s.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from config.settings import Topics, get_settings
from producers.kafka_utils import (
    KafkaJsonProducer, RateLimited, http_session, iso_utc, parse_args, run_poll_loop, setup_logging, utc_now,
)

log = logging.getLogger("producers.flight")

TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
STATES_URL = "https://opensky-network.org/api/states/all"


class OpenSkyAuth:
    """OAuth2 client-credentials token with caching. Without credentials, requests are anonymous."""

    def __init__(self, session, client_id: str | None, client_secret: str | None):
        self._session, self._id, self._secret = session, client_id, client_secret
        self._token: str | None = None
        self._expires_at = 0.0

    def headers(self) -> dict:
        if not (self._id and self._secret):
            return {}
        if self._token is None or time.time() >= self._expires_at:
            resp = self._session.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials", "client_id": self._id, "client_secret": self._secret},
                timeout=20,
            )
            resp.raise_for_status()
            body = resp.json()
            self._token = body["access_token"]
            self._expires_at = time.time() + int(body.get("expires_in", 300)) - 30
        return {"Authorization": f"Bearer {self._token}"}


def parse_state(state: list, airport_code: str, api_time: int | None = None) -> dict | None:
    """Convert one OpenSky state vector to our event schema. Returns None if it has no position.

    Index layout: 0 icao24, 1 callsign, 2 origin_country, 3 time_position, 4 last_contact,
    5 longitude, 6 latitude, 7 baro_altitude, 8 on_ground, 9 velocity, 10 true_track,
    11 vertical_rate, 13 geo_altitude.
    """
    if not state or len(state) < 12:
        return None
    lon, lat = state[5], state[6]
    if lon is None or lat is None:
        return None
    ts = state[3] or state[4] or api_time
    if ts is None:
        return None
    altitude = state[7] if state[7] is not None else (state[13] if len(state) > 13 else None)
    return {
        "icao24": state[0],
        "callsign": (state[1] or "").strip() or None,
        "origin_country": state[2],
        "latitude": lat,
        "longitude": lon,
        "altitude": altitude,
        "velocity": state[9],
        "heading": state[10],
        "vertical_rate": state[11],
        "on_ground": bool(state[8]),
        "event_timestamp": iso_utc(datetime.fromtimestamp(ts, tz=timezone.utc)),
        "airport_code": airport_code,
        "source": "opensky",
    }


def parse_response(body: dict, airport_code: str) -> list[dict]:
    events = (parse_state(s, airport_code, body.get("time")) for s in body.get("states") or [])
    return [e for e in events if e is not None]


def fetch_states(session, auth: OpenSkyAuth, bbox: tuple[float, float, float, float]) -> dict:
    lamin, lomin, lamax, lomax = bbox
    resp = session.get(
        STATES_URL,
        params={"lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax},
        headers=auth.headers(),
        timeout=30,
    )
    if resp.status_code == 429:
        retry = float(resp.headers.get("X-Rate-Limit-Retry-After-Seconds", 60))
        raise RateLimited(retry, "OpenSky 429")
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    args = parse_args(__doc__.splitlines()[0])
    setup_logging()
    cfg = get_settings()
    airport = cfg.airport
    producer = KafkaJsonProducer()
    mock = cfg.mock_mode or args.mock

    if mock:
        from producers.mock_data import mock_states

        def poll() -> int:
            events = mock_states(airport, utc_now())
            for e in events:
                producer.send(Topics.FLIGHTS_RAW, e, key=e["icao24"])
            return len(events)
    else:
        session = http_session()
        auth = OpenSkyAuth(session, cfg.opensky_client_id, cfg.opensky_client_secret)
        bbox = airport.bbox(cfg.bbox_radius_deg)
        if not cfg.opensky_client_id:
            log.warning("No OpenSky credentials: anonymous access has very low rate limits")

        def poll() -> int:
            events = parse_response(fetch_states(session, auth, bbox), airport.iata)
            for e in events:
                producer.send(Topics.FLIGHTS_RAW, e, key=e["icao24"])
            return len(events)

    run_poll_loop("flight_producer", cfg.opensky_poll_seconds, poll, producer, once=args.once)


if __name__ == "__main__":
    main()
