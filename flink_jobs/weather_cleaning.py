"""Job 2: weather.raw -> weather.cleaned (+ dead-letter).

Validates ranges, handles missing observations, de-duplicates repeated polls of the same
Open-Meteo interval and classifies weather risk with the shared thresholds in config/rules.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.rules import DEFAULT_WEATHER, weather_risk_rank_sql, weather_risk_sql  # noqa: E402
from config.settings import Topics  # noqa: E402
from flink_jobs.common import create_table, kafka_with, run_job  # noqa: E402

JOB_NAME = "weather-cleaning"

VALID = (
    "airport_code IS NOT NULL AND weather_timestamp IS NOT NULL "
    "AND (temperature IS NOT NULL OR wind_speed IS NOT NULL) "
    "AND COALESCE(temperature, 0) BETWEEN -60 AND 60 "
    "AND COALESCE(wind_speed, 0) BETWEEN 0 AND 400 "
    "AND COALESCE(visibility, 0) >= 0 AND COALESCE(precipitation, 0) >= 0"
)

RAW_COLUMNS = """  airport_code STRING, temperature DOUBLE, wind_speed DOUBLE, wind_gusts DOUBLE,
  wind_direction DOUBLE, visibility DOUBLE, precipitation DOUBLE, cloud_cover DOUBLE,
  weather_code INT, weather_timestamp TIMESTAMP_LTZ(3), source STRING"""

CLEANED_COLUMNS = (
    "  source_observation_id STRING,\n" + RAW_COLUMNS + ",\n  weather_risk STRING, weather_risk_rank INT"
)


def ddl() -> list[str]:
    return [
        create_table("weather_raw", RAW_COLUMNS + ",\n  proc_time AS PROCTIME()",
                     kafka_with(Topics.WEATHER_RAW, "flink-weather-cleaning")),
        create_table("weather_cleaned", CLEANED_COLUMNS, kafka_with(Topics.WEATHER_CLEANED)),
        create_table(
            "dead_letter",
            "  source_topic STRING, reason STRING, icao24 STRING, callsign STRING,\n"
            "  event_timestamp TIMESTAMP_LTZ(3), failed_at TIMESTAMP_LTZ(3)",
            kafka_with(Topics.DEAD_LETTER),
        ),
    ]


def inserts() -> list[str]:
    risk = weather_risk_sql(DEFAULT_WEATHER)
    cleaned = f"""
INSERT INTO weather_cleaned
SELECT source_observation_id, airport_code, temperature, wind_speed, wind_gusts, wind_direction,
       visibility, precipitation, cloud_cover, weather_code, weather_timestamp, source,
       weather_risk, {weather_risk_rank_sql('weather_risk')} AS weather_risk_rank
FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY source_observation_id ORDER BY proc_time ASC) AS rn
  FROM (
    SELECT CONCAT(airport_code, '_', DATE_FORMAT(CAST(weather_timestamp AS TIMESTAMP(3)), 'yyyyMMddHHmm')) AS source_observation_id,
           airport_code, temperature, wind_speed, wind_gusts, wind_direction, visibility,
           precipitation, cloud_cover, weather_code, weather_timestamp, source,
           {risk} AS weather_risk, proc_time
    FROM weather_raw
    WHERE {VALID}
  )
)
WHERE rn = 1"""
    rejected = f"""
INSERT INTO dead_letter
SELECT 'weather.raw',
       CASE WHEN airport_code IS NULL THEN 'missing_airport_code'
            WHEN weather_timestamp IS NULL THEN 'missing_weather_timestamp'
            WHEN temperature IS NULL AND wind_speed IS NULL THEN 'empty_observation'
            ELSE 'value_out_of_range' END,
       airport_code, CAST(NULL AS STRING), weather_timestamp, CURRENT_TIMESTAMP
FROM weather_raw
WHERE NOT ({VALID})"""
    return [cleaned, rejected]


if __name__ == "__main__":
    run_job(JOB_NAME, ddl(), inserts())
