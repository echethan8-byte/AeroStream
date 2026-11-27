"""Job 3: flights.cleaned (+ latest weather) -> flights.enriched.

Adds the movement phase (ARRIVING / DEPARTING / GROUND / ...) and the latest airport weather.

Design note: weather is attached with a processing-time JDBC lookup join against the
weather_current table (latest row per airport), i.e. "the latest available weather observation",
as described in the plan. This keeps flight latency low: an event-time temporal join would hold
every flight until the next weather observation arrived. The trade-off is that a replayed flight
gets the weather that is current at replay time, not at event time.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.rules import PhaseRules, multi_airport_phase_sql  # noqa: E402
from config.settings import AIRPORTS, Topics, get_settings  # noqa: E402
from flink_jobs.common import create_table, jdbc_with, kafka_with, run_job  # noqa: E402

JOB_NAME = "flight-enrichment"

FLIGHT_COLUMNS = """  source_event_id STRING, icao24 STRING, callsign STRING, origin_country STRING,
  latitude DOUBLE, longitude DOUBLE, altitude DOUBLE, velocity DOUBLE, heading DOUBLE,
  vertical_rate DOUBLE, on_ground BOOLEAN,
  event_timestamp TIMESTAMP_LTZ(3), airport_code STRING, source STRING"""

ENRICHED_COLUMNS = (
    FLIGHT_COLUMNS
    + """,
  phase STRING, temperature DOUBLE, wind_speed DOUBLE, wind_gusts DOUBLE, visibility DOUBLE,
  precipitation DOUBLE, weather_risk STRING, weather_risk_rank INT, weather_observed_at TIMESTAMP(3)"""
)

WEATHER_LOOKUP_COLUMNS = """  airport_code STRING, temperature DOUBLE, wind_speed DOUBLE, wind_gusts DOUBLE,
  wind_direction DOUBLE, visibility DOUBLE, precipitation DOUBLE, weather_risk STRING,
  weather_risk_rank INT, weather_timestamp TIMESTAMP(3),
  PRIMARY KEY (airport_code) NOT ENFORCED"""


def ddl() -> list[str]:
    return [
        create_table("flights_cleaned", FLIGHT_COLUMNS + ",\n  proc_time AS PROCTIME()",
                     kafka_with(Topics.FLIGHTS_CLEANED, "flink-flight-enrichment")),
        create_table("weather_lookup", WEATHER_LOOKUP_COLUMNS,
                     jdbc_with("weather_current", sink=False, lookup=True)),
        create_table("flights_enriched", ENRICHED_COLUMNS, kafka_with(Topics.FLIGHTS_ENRICHED)),
    ]


def inserts() -> list[str]:
    cfg = get_settings()
    phase = multi_airport_phase_sql(
        list(AIRPORTS.values()),
        cfg.airport,
        PhaseRules(terminal_radius_deg=cfg.terminal_radius_deg),
        prefix="f.",
    )
    return [
        f"""
INSERT INTO flights_enriched
SELECT f.source_event_id, f.icao24, f.callsign, f.origin_country, f.latitude, f.longitude,
       f.altitude, f.velocity, f.heading, f.vertical_rate, f.on_ground,
       f.event_timestamp, f.airport_code, f.source,
       {phase} AS phase,
       w.temperature, w.wind_speed, w.wind_gusts, w.visibility, w.precipitation,
       COALESCE(w.weather_risk, 'UNKNOWN') AS weather_risk,
       COALESCE(w.weather_risk_rank, -1) AS weather_risk_rank,
       w.weather_timestamp AS weather_observed_at
FROM flights_cleaned AS f
LEFT JOIN weather_lookup FOR SYSTEM_TIME AS OF f.proc_time AS w
  ON f.airport_code = w.airport_code"""
    ]


if __name__ == "__main__":
    run_job(JOB_NAME, ddl(), inserts())
