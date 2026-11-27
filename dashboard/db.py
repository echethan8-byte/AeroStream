"""PostgreSQL query layer for the real-time flight monitoring dashboard."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from config.settings import get_settings


def _load_dotenv_if_needed() -> None:
    """Populate missing env vars from project .env so local runs work without shell sourcing."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def get_connection():
    _load_dotenv_if_needed()
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "flight_analytics"),
        user=os.getenv("POSTGRES_USER", "flight"),
        password=os.getenv("POSTGRES_PASSWORD", "flight_pw"),
        connect_timeout=5,
    )


def json_safe(value: Any) -> Any:
    """Convert Postgres/Python types (datetime, Decimal) into JSON-serializable primitives."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


def _query_all(cur, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cur.execute(sql, params)
    return [json_safe(dict(row)) for row in cur.fetchall()]


def _query_one(cur, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    cur.execute(sql, params)
    row = cur.fetchone()
    return json_safe(dict(row)) if row else None


def fetch_dashboard_state(airport_code: str | None = None, direction: str | None = None) -> dict[str, Any]:
    """Fetch all live views and recent time-series for the dashboard in one snapshot."""
    cfg = get_settings()
    code = (airport_code or cfg.airport_code or "BLR").upper()
    dir_filter = direction.upper() if direction and direction.upper() in ("ARRIVAL", "DEPARTURE") else None

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            airports = _query_all(
                cur,
                "SELECT airport_code, airport_name, icao_code, latitude, longitude, timezone "
                "FROM airport_reference ORDER BY airport_code",
            )
            selected_airport = next((a for a in airports if a["airport_code"] == code), None)
            if selected_airport is None and airports:
                selected_airport = airports[0]
                code = selected_airport["airport_code"]

            kpis = _query_one(
                cur,
                "SELECT * FROM v_passenger_kpis WHERE airport_code = %s",
                (code,),
            ) or {
                "airport_code": code,
                "arrivals_today": 0,
                "departures_today": 0,
                "arrivals_next_hour": 0,
                "departures_next_hour": 0,
                "delayed_flights": 0,
                "cancelled_flights": 0,
                "on_time_percentage": None,
                "average_delay_min": None,
            }

            if dir_filter:
                flights = _query_all(
                    cur,
                    "SELECT * FROM v_passenger_flights "
                    "WHERE airport_code = %s AND direction = %s "
                    "ORDER BY scheduled_local ASC",
                    (code, dir_filter),
                )
            else:
                flights = _query_all(
                    cur,
                    "SELECT * FROM v_passenger_flights "
                    "WHERE airport_code = %s "
                    "ORDER BY scheduled_local ASC",
                    (code,),
                )

            weather = _query_one(
                cur,
                "SELECT * FROM v_weather_latest WHERE airport_code = %s",
                (code,),
            )

            aircraft_now = _query_one(
                cur,
                "SELECT * FROM v_aircraft_now WHERE airport_code = %s",
                (code,),
            ) or {
                "airport_code": code,
                "airborne_aircraft": 0,
                "ground_aircraft": 0,
                "tracked_aircraft": 0,
            }

            aircraft = _query_all(
                cur,
                "SELECT icao24, callsign, origin_country, latitude, longitude, altitude, "
                "velocity, heading, vertical_rate, on_ground, phase, weather_risk, event_timestamp "
                "FROM flights_current "
                "WHERE airport_code = %s "
                "ORDER BY event_timestamp DESC, callsign ASC NULLS LAST",
                (code,),
            )

            ops_current = _query_one(
                cur,
                "SELECT * FROM v_ops_current WHERE airport_code = %s",
                (code,),
            )

            metrics_5min = list(
                reversed(
                    _query_all(
                        cur,
                        "SELECT window_start, window_end, airborne_aircraft, ground_aircraft, "
                        "arrivals, departures, total_movements, congestion_index, congestion_level, weather_risk "
                        "FROM airport_metrics_5min "
                        "WHERE airport_code = %s "
                        "ORDER BY window_start DESC LIMIT 36",
                        (code,),
                    )
                )
            )

            hourly_ops = list(
                reversed(
                    _query_all(
                        cur,
                        "SELECT hour_local, arrivals, departures, total_movements, congestion_index, "
                        "congestion_level, weather_risk, avg_arrival_delay_min, avg_departure_delay_min, on_time_percentage "
                        "FROM v_hourly_ops "
                        "WHERE airport_code = %s "
                        "ORDER BY hour_local DESC LIMIT 24",
                        (code,),
                    )
                )
            )

            delay_vs_weather = list(
                reversed(
                    _query_all(
                        cur,
                        "SELECT hour_local, avg_delay_min, flights, avg_wind_kmh, min_visibility_m, "
                        "precipitation_mm, max_risk_rank "
                        "FROM v_delay_vs_weather "
                        "WHERE airport_code = %s "
                        "ORDER BY hour_local DESC LIMIT 24",
                        (code,),
                    )
                )
            )

            pipeline_status = _query_all(
                cur,
                "SELECT component, status, records_published, message, event_timestamp "
                "FROM v_pipeline_status ORDER BY component",
            )

    return {
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
        "airport_code": code,
        "monitored_airport": cfg.airport_code.upper(),
        "terminal_radius_deg": cfg.terminal_radius_deg,
        "airports": airports,
        "selected_airport": selected_airport,
        "passenger_kpis": kpis,
        "passenger_flights": flights,
        "weather": weather,
        "aircraft_now": aircraft_now,
        "aircraft": aircraft,
        "ops_current": ops_current,
        "metrics_5min": metrics_5min,
        "hourly_ops": hourly_ops,
        "delay_vs_weather": delay_vs_weather,
        "pipeline_status": pipeline_status,
    }
