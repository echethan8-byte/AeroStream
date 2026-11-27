"""Job 4: flights.enriched -> airport.metrics (event-time windows).

  * 5-minute TUMBLE windows  -> granularity '5MIN'
  * 1-hour HOP windows sliding every 5 minutes (rolling last hour) -> granularity '1HOUR'

Event time + a 30-second watermark delay means late-arriving events (e.g. an event stamped 10:00:00
that reaches Kafka at 10:00:08) land in the correct window. Aircraft counts are DISTINCT icao24
per window; arrivals/departures are aircraft classified ARRIVING/DEPARTING inside the window.
These are position-based approximations (see docs/metrics.md).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.rules import congestion_index_sql, congestion_level_sql  # noqa: E402
from config.settings import Topics, get_settings  # noqa: E402
from flink_jobs.common import create_table, kafka_with, run_job  # noqa: E402

JOB_NAME = "airport-analytics"

ENRICHED_COLUMNS = """  icao24 STRING, on_ground BOOLEAN, phase STRING, airport_code STRING,
  weather_risk_rank INT, event_timestamp TIMESTAMP_LTZ(3),
  WATERMARK FOR event_timestamp AS event_timestamp - INTERVAL '30' SECOND"""

METRICS_COLUMNS = """  airport_code STRING, granularity STRING,
  window_start TIMESTAMP(3), window_end TIMESTAMP(3),
  airborne_aircraft BIGINT, ground_aircraft BIGINT, arrivals BIGINT, departures BIGINT,
  total_movements BIGINT, congestion_index DOUBLE, congestion_level STRING, weather_risk STRING"""


def ddl() -> list[str]:
    return [
        create_table("flights_enriched", ENRICHED_COLUMNS,
                     kafka_with(Topics.FLIGHTS_ENRICHED, "flink-airport-analytics")),
        create_table("airport_metrics", METRICS_COLUMNS, kafka_with(Topics.AIRPORT_METRICS)),
    ]


def window_query(granularity: str, tvf: str, window_minutes: int, capacity_per_hour: float) -> str:
    index = congestion_index_sql("total_movements", window_minutes, capacity_per_hour)
    return f"""
INSERT INTO airport_metrics
SELECT airport_code, '{granularity}', window_start, window_end,
       airborne_aircraft, ground_aircraft, arrivals, departures, total_movements,
       congestion_index, {congestion_level_sql('congestion_index')}, weather_risk
FROM (
  SELECT airport_code, window_start, window_end, airborne_aircraft, ground_aircraft,
         arrivals, departures, total_movements, {index} AS congestion_index, weather_risk
  FROM (
    SELECT airport_code, window_start, window_end,
           COUNT(DISTINCT CASE WHEN NOT on_ground THEN icao24 END) AS airborne_aircraft,
           COUNT(DISTINCT CASE WHEN on_ground THEN icao24 END)     AS ground_aircraft,
           COUNT(DISTINCT CASE WHEN phase = 'ARRIVING'  THEN icao24 END) AS arrivals,
           COUNT(DISTINCT CASE WHEN phase = 'DEPARTING' THEN icao24 END) AS departures,
           COUNT(DISTINCT CASE WHEN phase IN ('ARRIVING', 'DEPARTING') THEN icao24 END) AS total_movements,
           CASE MAX(weather_risk_rank) WHEN 2 THEN 'HIGH_RISK' WHEN 1 THEN 'CAUTION'
                                       WHEN 0 THEN 'NORMAL' ELSE 'UNKNOWN' END AS weather_risk
    FROM TABLE({tvf})
    GROUP BY airport_code, window_start, window_end
  )
)"""


def inserts() -> list[str]:
    capacity = get_settings().capacity_per_hour
    return [
        window_query("5MIN", "TUMBLE(TABLE flights_enriched, DESCRIPTOR(event_timestamp), INTERVAL '5' MINUTE)",
                     5, capacity),
        window_query("1HOUR",
                     "HOP(TABLE flights_enriched, DESCRIPTOR(event_timestamp), INTERVAL '5' MINUTE, INTERVAL '1' HOUR)",
                     60, capacity),
    ]


if __name__ == "__main__":
    run_job(JOB_NAME, ddl(), inserts())
