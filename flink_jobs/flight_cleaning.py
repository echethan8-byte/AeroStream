"""Job 1: flights.raw -> flights.cleaned (+ dead-letter).

Validates coordinates, normalises callsigns/ICAO24, builds a deterministic event key and removes
duplicates. Invalid records go to the dead-letter topic with a reason instead of being dropped silently.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import Topics  # noqa: E402
from flink_jobs.common import create_table, kafka_with, run_job  # noqa: E402

JOB_NAME = "flight-cleaning"

VALID = (
    "icao24 IS NOT NULL AND event_timestamp IS NOT NULL "
    "AND latitude IS NOT NULL AND longitude IS NOT NULL "
    "AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180"
)

RAW_COLUMNS = """  icao24 STRING, callsign STRING, origin_country STRING,
  latitude DOUBLE, longitude DOUBLE, altitude DOUBLE, velocity DOUBLE, heading DOUBLE,
  vertical_rate DOUBLE, on_ground BOOLEAN,
  event_timestamp TIMESTAMP_LTZ(3), airport_code STRING, source STRING"""

CLEANED_COLUMNS = "  source_event_id STRING,\n" + RAW_COLUMNS


def ddl() -> list[str]:
    return [
        create_table("flights_raw", RAW_COLUMNS + ",\n  proc_time AS PROCTIME()",
                     kafka_with(Topics.FLIGHTS_RAW, "flink-flight-cleaning")),
        create_table("flights_cleaned", CLEANED_COLUMNS, kafka_with(Topics.FLIGHTS_CLEANED)),
        create_table(
            "dead_letter",
            "  source_topic STRING, reason STRING, icao24 STRING, callsign STRING,\n"
            "  event_timestamp TIMESTAMP_LTZ(3), failed_at TIMESTAMP_LTZ(3)",
            kafka_with(Topics.DEAD_LETTER),
        ),
    ]


def inserts() -> list[str]:
    cleaned = f"""
INSERT INTO flights_cleaned
SELECT source_event_id, icao24, callsign, origin_country, latitude, longitude, altitude, velocity,
       heading, vertical_rate, on_ground, event_timestamp, airport_code, source
FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY icao24, event_timestamp ORDER BY proc_time ASC) AS rn
  FROM (
    SELECT CONCAT(LOWER(TRIM(icao24)), '_', DATE_FORMAT(CAST(event_timestamp AS TIMESTAMP(3)), 'yyyyMMddHHmmss')) AS source_event_id,
           LOWER(TRIM(icao24)) AS icao24,
           NULLIF(UPPER(TRIM(callsign)), '') AS callsign,
           origin_country, latitude, longitude, altitude, velocity, heading, vertical_rate,
           COALESCE(on_ground, FALSE) AS on_ground,
           event_timestamp, airport_code, source, proc_time
    FROM flights_raw
    WHERE {VALID}
  )
)
WHERE rn = 1"""
    rejected = f"""
INSERT INTO dead_letter
SELECT 'flights.raw',
       CASE WHEN icao24 IS NULL THEN 'missing_icao24'
            WHEN event_timestamp IS NULL THEN 'missing_event_timestamp'
            WHEN latitude IS NULL OR longitude IS NULL THEN 'missing_coordinates'
            ELSE 'coordinates_out_of_range' END,
       icao24, callsign, event_timestamp, CURRENT_TIMESTAMP
FROM flights_raw
WHERE NOT ({VALID})"""
    return [cleaned, rejected]


if __name__ == "__main__":
    run_job(JOB_NAME, ddl(), inserts())
