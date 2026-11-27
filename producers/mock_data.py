"""Synthetic data for development without API keys (MOCK_MODE=true).

Every record is labelled source="mock" so it can never be mistaken for real data, and dashboards
built on it must be described as simulated.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from config.settings import Airport
from producers.kafka_utils import iso_utc


def mock_states(airport: Airport, now: datetime, count: int = 14) -> list[dict]:
    """Aircraft around the airport in different phases. Positions drift with time."""
    rng = random.Random(int(now.timestamp()) // 30)
    out = []
    for i in range(count):
        kind = ["arriving", "departing", "ground", "enroute"][i % 4]
        bearing = rng.uniform(0, 2 * math.pi)
        if kind == "ground":
            dist, alt, vr, v, on_ground = rng.uniform(0, 0.01), 0.0, 0.0, rng.uniform(0, 12), True
        elif kind == "arriving":
            dist, alt, vr, v, on_ground = rng.uniform(0.02, 0.22), rng.uniform(300, 2800), rng.uniform(-8, -2), rng.uniform(60, 90), False
        elif kind == "departing":
            dist, alt, vr, v, on_ground = rng.uniform(0.02, 0.22), rng.uniform(300, 2800), rng.uniform(3, 12), rng.uniform(70, 120), False
        else:
            dist, alt, vr, v, on_ground = rng.uniform(0.3, 0.48), rng.uniform(6000, 11000), rng.uniform(-1, 1), rng.uniform(200, 250), False
        out.append(
            {
                "icao24": f"mock{i:02d}",
                "callsign": f"MCK{100 + i}",
                "origin_country": "India",
                "latitude": round(airport.latitude + dist * math.cos(bearing), 5),
                "longitude": round(airport.longitude + dist * math.sin(bearing), 5),
                "altitude": round(alt, 1),
                "velocity": round(v, 1),
                "heading": round(math.degrees(bearing) % 360, 1),
                "vertical_rate": round(vr, 1),
                "on_ground": on_ground,
                "event_timestamp": iso_utc(now),
                "airport_code": airport.iata,
                "source": "mock",
            }
        )
    return out


def mock_schedules(airport: Airport, now: datetime) -> list[dict]:
    """~24 flights spread over -3h..+6h with a mix of statuses and delays. Stable keys => upserts."""
    rng = random.Random(now.strftime("%Y%m%d%H"))
    cities = [c for c in ("DEL", "BOM", "MAA", "HYD", "CCU", "GOI", "COK") if c != airport.iata]
    airlines = [("IndiGo", "6E"), ("Air India", "AI"), ("Akasa Air", "QP"), ("SpiceJet", "SG")]
    base = now.replace(minute=0, second=0, microsecond=0)
    out = []
    for n in range(24):
        direction = "ARRIVAL" if n % 2 == 0 else "DEPARTURE"
        airline, code = airlines[n % len(airlines)]
        city = cities[n % len(cities)]
        scheduled = base + timedelta(minutes=30 * (n - 6))
        delay = rng.choice([0, 0, 0, 5, 10, 20, 35, 60])
        cancelled = rng.random() < 0.05
        estimated = scheduled + timedelta(minutes=delay)
        happened = estimated < now
        if cancelled:
            status = "cancelled"
        elif happened:
            status = "landed" if direction == "ARRIVAL" else "active"
        else:
            status = "scheduled"
        number = f"{code}{500 + n}"
        rec = {
            "flight_key": f"{number}_{scheduled.date()}_{airport.iata if direction == 'DEPARTURE' else city}",
            "airport_code": airport.iata,
            "direction": direction,
            "flight_number": number,
            "airline": airline,
            "origin_airport": city if direction == "ARRIVAL" else airport.iata,
            "destination_airport": airport.iata if direction == "ARRIVAL" else city,
            "scheduled_departure": None,
            "scheduled_arrival": None,
            "estimated_departure": None,
            "estimated_arrival": None,
            "actual_departure": None,
            "actual_arrival": None,
            "flight_status": status,
            "delay_minutes": None if cancelled else delay,
            "terminal": "T2" if n % 3 else "T1",
            "gate": f"{rng.randint(1, 40)}",
            "source": "mock",
            "event_timestamp": iso_utc(now),
        }
        side = "arrival" if direction == "ARRIVAL" else "departure"
        rec[f"scheduled_{side}"] = iso_utc(scheduled)
        rec[f"estimated_{side}"] = iso_utc(estimated)
        if status in ("landed", "active"):
            rec[f"actual_{side}"] = iso_utc(estimated)
        out.append(rec)
    return out


def mock_weather(airport: Airport, now: datetime) -> dict:
    rng = random.Random(int(now.timestamp()) // 300)
    storm = rng.random() < 0.15
    return {
        "airport_code": airport.iata,
        "temperature": round(rng.uniform(21, 32), 1),
        "wind_speed": round(rng.uniform(25, 60) if storm else rng.uniform(4, 22), 1),
        "wind_gusts": round(rng.uniform(45, 80) if storm else rng.uniform(8, 35), 1),
        "wind_direction": rng.randint(0, 359),
        "visibility": round(rng.uniform(600, 4000) if storm else rng.uniform(6000, 24000)),
        "precipitation": round(rng.uniform(2, 14) if storm else 0.0, 1),
        "cloud_cover": rng.randint(0, 100),
        "weather_code": 95 if storm else rng.choice([0, 1, 2, 3]),
        "weather_timestamp": iso_utc(now.replace(second=0, microsecond=0, minute=now.minute - now.minute % 5)),
        "source": "mock",
    }
