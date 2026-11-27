"""Central configuration: airports, Kafka topics and runtime settings (all env-driven)."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Airport:
    iata: str
    icao: str
    name: str
    latitude: float
    longitude: float
    timezone: str

    def bbox(self, radius_deg: float) -> tuple[float, float, float, float]:
        """(lamin, lomin, lamax, lomax) box around the airport (longitude widened by latitude)."""
        d_lon = radius_deg / max(math.cos(math.radians(self.latitude)), 0.01)
        return (
            self.latitude - radius_deg,
            self.longitude - d_lon,
            self.latitude + radius_deg,
            self.longitude + d_lon,
        )


AIRPORTS: dict[str, Airport] = {
    "BLR": Airport("BLR", "VOBL", "Kempegowda International Airport", 13.1986, 77.7066, "Asia/Kolkata"),
    "DEL": Airport("DEL", "VIDP", "Indira Gandhi International Airport", 28.5562, 77.1000, "Asia/Kolkata"),
    "BOM": Airport("BOM", "VABB", "Chhatrapati Shivaji Maharaj International Airport", 19.0887, 72.8679, "Asia/Kolkata"),
    "MAA": Airport("MAA", "VOMM", "Chennai International Airport", 12.9941, 80.1709, "Asia/Kolkata"),
}


class Topics:
    FLIGHTS_RAW = "flights.raw"
    SCHEDULES_RAW = "schedules.raw"
    WEATHER_RAW = "weather.raw"
    FLIGHTS_CLEANED = "flights.cleaned"
    WEATHER_CLEANED = "weather.cleaned"
    FLIGHTS_ENRICHED = "flights.enriched"
    AIRPORT_METRICS = "airport.metrics"
    DEAD_LETTER = "dead-letter"
    PIPELINE_HEALTH = "pipeline.health"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _bool(name: str, default: bool = False) -> bool:
    return str(_env(name, str(default))).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    airport_code: str
    airport_codes: tuple[str, ...]
    kafka_bootstrap: str
    mock_mode: bool

    opensky_client_id: str | None
    opensky_client_secret: str | None
    opensky_poll_seconds: int
    bbox_radius_deg: float
    terminal_radius_deg: float

    aviationstack_key: str | None
    aviationstack_base_url: str
    aviationstack_poll_seconds: int
    aviationstack_max_pages: int

    weather_poll_seconds: int

    on_time_threshold_min: int
    capacity_per_hour: float

    jdbc_url: str
    postgres_user: str
    postgres_password: str

    @property
    def airport(self) -> Airport:
        try:
            return AIRPORTS[self.airport_code]
        except KeyError as exc:
            raise ValueError(
                f"Unknown AIRPORT_CODE {self.airport_code!r}; add it to config/settings.py AIRPORTS "
                f"and database/schema.sql (airport_reference)"
            ) from exc

    @property
    def airports(self) -> list[Airport]:
        out: list[Airport] = []
        for code in self.airport_codes:
            try:
                out.append(AIRPORTS[code])
            except KeyError as exc:
                raise ValueError(
                    f"Unknown airport code {code!r} in AIRPORT_CODES; add it to config/settings.py AIRPORTS "
                    f"and database/schema.sql (airport_reference)"
                ) from exc
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    primary = _env("AIRPORT_CODE", "BLR").upper()
    raw_codes = _env("AIRPORT_CODES")
    if raw_codes:
        codes = tuple(dict.fromkeys(c.strip().upper() for c in raw_codes.split(",") if c.strip()))
    else:
        codes = (primary,)
    return Settings(
        airport_code=primary,
        airport_codes=codes or (primary,),
        kafka_bootstrap=_env("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
        mock_mode=_bool("MOCK_MODE", False),
        opensky_client_id=_env("OPENSKY_CLIENT_ID"),
        opensky_client_secret=_env("OPENSKY_CLIENT_SECRET"),
        opensky_poll_seconds=int(_env("OPENSKY_POLL_SECONDS", "30")),
        bbox_radius_deg=float(_env("BBOX_RADIUS_DEG", "0.5")),
        terminal_radius_deg=float(_env("TERMINAL_RADIUS_DEG", "0.25")),
        aviationstack_key=_env("AVIATIONSTACK_API_KEY"),
        aviationstack_base_url=_env("AVIATIONSTACK_BASE_URL", "http://api.aviationstack.com/v1").rstrip("/"),
        aviationstack_poll_seconds=int(_env("AVIATIONSTACK_POLL_SECONDS", "900")),
        aviationstack_max_pages=int(_env("AVIATIONSTACK_MAX_PAGES", "1")),
        weather_poll_seconds=int(_env("WEATHER_POLL_SECONDS", "300")),
        on_time_threshold_min=int(_env("ON_TIME_THRESHOLD_MIN", "15")),
        capacity_per_hour=float(_env("CAPACITY_MOVEMENTS_PER_HOUR", "40")),
        jdbc_url=_env("POSTGRES_JDBC_URL", "jdbc:postgresql://localhost:5432/flight_analytics"),
        postgres_user=_env("POSTGRES_USER", "flight"),
        postgres_password=_env("POSTGRES_PASSWORD", "flight_pw"),
    )
