"""Project-defined metric rules.

Every rule exists twice on purpose:
  * a pure-Python function (unit-tested, used by mock data and docs), and
  * a *_sql generator that emits the equivalent Flink SQL expression, built from the same
    thresholds, so the pipeline and the documentation cannot drift apart.

All classifications are project-defined analytical indicators, NOT official aviation
safety or air-traffic classifications.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from config.settings import Airport

# --------------------------------------------------------------------------- weather risk


@dataclass(frozen=True)
class WeatherThresholds:
    wind_caution_kmh: float = 30.0
    wind_severe_kmh: float = 50.0
    gust_caution_kmh: float = 45.0
    gust_severe_kmh: float = 65.0
    visibility_caution_m: float = 3000.0   # visibility BELOW this is a hit
    visibility_severe_m: float = 1000.0
    precip_caution_mm: float = 2.5
    precip_severe_mm: float = 10.0


DEFAULT_WEATHER = WeatherThresholds()
RISK_RANK = {"NORMAL": 0, "CAUTION": 1, "HIGH_RISK": 2}


def classify_weather_risk(
    wind_speed: float | None = None,
    wind_gusts: float | None = None,
    visibility: float | None = None,
    precipitation: float | None = None,
    t: WeatherThresholds = DEFAULT_WEATHER,
) -> str:
    """NORMAL / CAUTION / HIGH_RISK, or UNKNOWN when no input is available."""
    if all(v is None for v in (wind_speed, wind_gusts, visibility, precipitation)):
        return "UNKNOWN"

    def at_least(v: float | None, limit: float) -> bool:
        return v is not None and v >= limit

    def below(v: float | None, limit: float) -> bool:
        return v is not None and v < limit

    if (
        at_least(wind_speed, t.wind_severe_kmh)
        or at_least(wind_gusts, t.gust_severe_kmh)
        or below(visibility, t.visibility_severe_m)
        or at_least(precipitation, t.precip_severe_mm)
    ):
        return "HIGH_RISK"
    if (
        at_least(wind_speed, t.wind_caution_kmh)
        or at_least(wind_gusts, t.gust_caution_kmh)
        or below(visibility, t.visibility_caution_m)
        or at_least(precipitation, t.precip_caution_mm)
    ):
        return "CAUTION"
    return "NORMAL"


def weather_risk_sql(
    t: WeatherThresholds = DEFAULT_WEATHER,
    wind: str = "wind_speed",
    gust: str = "wind_gusts",
    vis: str = "visibility",
    precip: str = "precipitation",
) -> str:
    return (
        "CASE "
        f"WHEN {wind} IS NULL AND {gust} IS NULL AND {vis} IS NULL AND {precip} IS NULL THEN 'UNKNOWN' "
        f"WHEN {wind} >= {t.wind_severe_kmh} OR {gust} >= {t.gust_severe_kmh} "
        f"OR {vis} < {t.visibility_severe_m} OR {precip} >= {t.precip_severe_mm} THEN 'HIGH_RISK' "
        f"WHEN {wind} >= {t.wind_caution_kmh} OR {gust} >= {t.gust_caution_kmh} "
        f"OR {vis} < {t.visibility_caution_m} OR {precip} >= {t.precip_caution_mm} THEN 'CAUTION' "
        "ELSE 'NORMAL' END"
    )


def weather_risk_rank_sql(risk_expr: str) -> str:
    return f"CASE {risk_expr} WHEN 'HIGH_RISK' THEN 2 WHEN 'CAUTION' THEN 1 WHEN 'NORMAL' THEN 0 ELSE -1 END"


# --------------------------------------------------------------------------- movement phase


@dataclass(frozen=True)
class PhaseRules:
    max_altitude_m: float = 3000.0      # "low level" ceiling for arrival/departure classification
    min_vertical_rate_ms: float = 1.0   # |vertical rate| needed to call it a climb/descent
    terminal_radius_deg: float = 0.25   # latitude half-width of the terminal area (~28 km)

    def lon_radius(self, airport: Airport) -> float:
        return self.terminal_radius_deg / max(math.cos(math.radians(airport.latitude)), 0.01)


def classify_phase(
    latitude: float,
    longitude: float,
    on_ground: bool,
    altitude: float | None,
    vertical_rate: float | None,
    airport: Airport,
    rules: PhaseRules = PhaseRules(),
) -> str:
    """GROUND / ARRIVING / DEPARTING / LOW_LEVEL / ENROUTE / UNKNOWN.

    A position-only heuristic: an aircraft low, near the airport and descending is treated as
    arriving; low, near and climbing as departing. It cannot see runways or flight numbers.
    """
    if on_ground:
        return "GROUND"
    near = (
        abs(latitude - airport.latitude) <= rules.terminal_radius_deg
        and abs(longitude - airport.longitude) <= rules.lon_radius(airport)
    )
    if not near:
        return "ENROUTE"
    if altitude is None:
        return "UNKNOWN"
    if altitude <= rules.max_altitude_m:
        if vertical_rate is not None and vertical_rate <= -rules.min_vertical_rate_ms:
            return "ARRIVING"
        if vertical_rate is not None and vertical_rate >= rules.min_vertical_rate_ms:
            return "DEPARTING"
        return "LOW_LEVEL"
    return "ENROUTE"


def phase_sql(
    airport: Airport,
    rules: PhaseRules = PhaseRules(),
    prefix: str = "",
) -> str:
    lat, lon = f"{prefix}latitude", f"{prefix}longitude"
    alt, vr, gnd = f"{prefix}altitude", f"{prefix}vertical_rate", f"{prefix}on_ground"
    near = (
        f"ABS({lat} - {airport.latitude}) <= {rules.terminal_radius_deg} "
        f"AND ABS({lon} - {airport.longitude}) <= {round(rules.lon_radius(airport), 6)}"
    )
    return (
        "CASE "
        f"WHEN {gnd} THEN 'GROUND' "
        f"WHEN NOT ({near}) THEN 'ENROUTE' "
        f"WHEN {alt} IS NULL THEN 'UNKNOWN' "
        f"WHEN {alt} <= {rules.max_altitude_m} AND {vr} <= -{rules.min_vertical_rate_ms} THEN 'ARRIVING' "
        f"WHEN {alt} <= {rules.max_altitude_m} AND {vr} >= {rules.min_vertical_rate_ms} THEN 'DEPARTING' "
        f"WHEN {alt} <= {rules.max_altitude_m} THEN 'LOW_LEVEL' "
        "ELSE 'ENROUTE' END"
    )


def multi_airport_phase_sql(
    airports: list[Airport],
    default_airport: Airport,
    rules: PhaseRules = PhaseRules(),
    prefix: str = "",
) -> str:
    """Emit a CASE dispatch over airport_code so one Flink job handles multiple airports."""
    branches = "\n".join(
        f"WHEN '{ap.iata}' THEN {phase_sql(ap, rules, prefix=prefix)}"
        for ap in airports
    )
    return f"CASE {prefix}airport_code\n{branches}\nELSE {phase_sql(default_airport, rules, prefix=prefix)}\nEND"


# --------------------------------------------------------------------------- congestion


def congestion_index(movements: float, window_minutes: float, capacity_per_hour: float) -> float:
    """Movements scaled to an hourly rate, divided by the configured hourly capacity."""
    return movements * (60.0 / window_minutes) / capacity_per_hour


def congestion_level(index: float) -> str:
    if index < 0.5:
        return "LOW"
    if index < 0.8:
        return "MODERATE"
    if index < 1.0:
        return "HIGH"
    return "SEVERE"


def congestion_index_sql(total_expr: str, window_minutes: float, capacity_per_hour: float) -> str:
    return f"CAST({total_expr} AS DOUBLE) * {60.0 / window_minutes} / {capacity_per_hour}"


def congestion_level_sql(index_expr: str) -> str:
    return (
        f"CASE WHEN {index_expr} < 0.5 THEN 'LOW' WHEN {index_expr} < 0.8 THEN 'MODERATE' "
        f"WHEN {index_expr} < 1.0 THEN 'HIGH' ELSE 'SEVERE' END"
    )


# --------------------------------------------------------------------------- delay


def is_on_time(delay_minutes: float, threshold_min: float = 15.0) -> bool:
    """On time = no more than `threshold_min` minutes late (early counts as on time)."""
    return delay_minutes <= threshold_min


def on_time_percentage(delays: list[float | None], threshold_min: float = 15.0) -> float | None:
    """On-time flights / eligible flights x 100. Eligible = flights with a known delay."""
    eligible = [d for d in delays if d is not None]
    if not eligible:
        return None
    return 100.0 * sum(is_on_time(d, threshold_min) for d in eligible) / len(eligible)


def average_delay(delays: list[float | None]) -> float | None:
    """Mean delay in minutes over eligible flights; early departures count as 0 delay."""
    eligible = [max(d, 0.0) for d in delays if d is not None]
    return sum(eligible) / len(eligible) if eligible else None
