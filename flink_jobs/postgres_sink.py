"""Job 5: processed Kafka topics -> PostgreSQL.

Idempotent upserts keyed on deterministic IDs, so replays and duplicates never create duplicate rows:
  flights.enriched  -> flight_events (source_event_id), flights_current (icao24)
  weather.cleaned   -> weather_observations (source_observation_id), weather_current (airport_code)
  schedules.raw     -> flight_schedules (flight_key)
  airport.metrics   -> airport_metrics_5min / airport_metrics_hourly (airport_code, window_start)
  pipeline.health   -> pipeline_health (append)

Note: flights_current is last-write-wins per aircraft; with a single partition per topic that is
event order, but a multi-partition deployment could briefly show an older position.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import Topics  # noqa: E402
from flink_jobs.common import create_table, jdbc_with, kafka_with, run_job  # noqa: E402

JOB_NAME = "postgres-sink"

TS = "TIMESTAMP(3)"


def ddl() -> list[str]:
    statements = []

    # ---------------- sources
    statements.append(create_table(
        "src_flights",
        """  source_event_id STRING, icao24 STRING, callsign STRING, origin_country STRING,
  latitude DOUBLE, longitude DOUBLE, altitude DOUBLE, velocity DOUBLE, heading DOUBLE,
  vertical_rate DOUBLE, on_ground BOOLEAN, event_timestamp TIMESTAMP_LTZ(3), airport_code STRING,
  phase STRING, wind_speed DOUBLE, visibility DOUBLE, weather_risk STRING""",
        kafka_with(Topics.FLIGHTS_ENRICHED, "flink-pg-flights")))
    statements.append(create_table(
        "src_weather",
        """  source_observation_id STRING, airport_code STRING, temperature DOUBLE, wind_speed DOUBLE,
  wind_gusts DOUBLE, wind_direction DOUBLE, visibility DOUBLE, precipitation DOUBLE,
  cloud_cover DOUBLE, weather_code INT, weather_timestamp TIMESTAMP_LTZ(3),
  weather_risk STRING, weather_risk_rank INT""",
        kafka_with(Topics.WEATHER_CLEANED, "flink-pg-weather")))
    statements.append(create_table(
        "src_schedules",
        """  flight_key STRING, airport_code STRING, direction STRING, flight_number STRING, airline STRING,
  origin_airport STRING, destination_airport STRING,
  scheduled_departure TIMESTAMP_LTZ(3), scheduled_arrival TIMESTAMP_LTZ(3),
  estimated_departure TIMESTAMP_LTZ(3), estimated_arrival TIMESTAMP_LTZ(3),
  actual_departure TIMESTAMP_LTZ(3), actual_arrival TIMESTAMP_LTZ(3),
  flight_status STRING, delay_minutes INT, terminal STRING, gate STRING, source STRING,
  event_timestamp TIMESTAMP_LTZ(3)""",
        kafka_with(Topics.SCHEDULES_RAW, "flink-pg-schedules")))
    statements.append(create_table(
        "src_metrics",
        """  airport_code STRING, granularity STRING, window_start TIMESTAMP(3), window_end TIMESTAMP(3),
  airborne_aircraft BIGINT, ground_aircraft BIGINT, arrivals BIGINT, departures BIGINT,
  total_movements BIGINT, congestion_index DOUBLE, congestion_level STRING, weather_risk STRING""",
        kafka_with(Topics.AIRPORT_METRICS, "flink-pg-metrics")))
    statements.append(create_table(
        "src_health",
        "  component STRING, status STRING, records_published INT, message STRING, event_timestamp TIMESTAMP_LTZ(3)",
        kafka_with(Topics.PIPELINE_HEALTH, "flink-pg-health")))

    # ---------------- sinks
    statements.append(create_table(
        "pg_flight_events",
        f"""  source_event_id STRING, icao24 STRING, callsign STRING, latitude DOUBLE, longitude DOUBLE,
  altitude DOUBLE, velocity DOUBLE, heading DOUBLE, vertical_rate DOUBLE, on_ground BOOLEAN,
  phase STRING, airport_code STRING, weather_risk STRING, wind_speed DOUBLE, visibility DOUBLE,
  event_timestamp {TS},
  PRIMARY KEY (source_event_id) NOT ENFORCED""",
        jdbc_with("flight_events")))
    statements.append(create_table(
        "pg_flights_current",
        f"""  icao24 STRING, callsign STRING, origin_country STRING, latitude DOUBLE, longitude DOUBLE,
  altitude DOUBLE, velocity DOUBLE, heading DOUBLE, vertical_rate DOUBLE, on_ground BOOLEAN,
  phase STRING, airport_code STRING, weather_risk STRING, event_timestamp {TS},
  PRIMARY KEY (icao24) NOT ENFORCED""",
        jdbc_with("flights_current")))
    statements.append(create_table(
        "pg_weather_obs",
        f"""  source_observation_id STRING, airport_code STRING, temperature DOUBLE, wind_speed DOUBLE,
  wind_gusts DOUBLE, wind_direction DOUBLE, visibility DOUBLE, precipitation DOUBLE,
  cloud_cover DOUBLE, weather_code INT, weather_risk STRING, weather_timestamp {TS},
  PRIMARY KEY (source_observation_id) NOT ENFORCED""",
        jdbc_with("weather_observations")))
    statements.append(create_table(
        "pg_weather_current",
        f"""  airport_code STRING, temperature DOUBLE, wind_speed DOUBLE, wind_gusts DOUBLE,
  wind_direction DOUBLE, visibility DOUBLE, precipitation DOUBLE, cloud_cover DOUBLE,
  weather_code INT, weather_risk STRING, weather_risk_rank INT, weather_timestamp {TS},
  PRIMARY KEY (airport_code) NOT ENFORCED""",
        jdbc_with("weather_current")))
    statements.append(create_table(
        "pg_schedules",
        f"""  flight_key STRING, airport_code STRING, direction STRING, flight_number STRING, airline STRING,
  origin_airport STRING, destination_airport STRING,
  scheduled_departure {TS}, scheduled_arrival {TS}, estimated_departure {TS}, estimated_arrival {TS},
  actual_departure {TS}, actual_arrival {TS},
  flight_status STRING, delay_minutes INT, terminal STRING, gate STRING, source STRING,
  last_updated {TS},
  PRIMARY KEY (flight_key) NOT ENFORCED""",
        jdbc_with("flight_schedules")))
    for name, table in (("pg_metrics_5min", "airport_metrics_5min"), ("pg_metrics_hourly", "airport_metrics_hourly")):
        statements.append(create_table(
            name,
            """  airport_code STRING, window_start TIMESTAMP(3), window_end TIMESTAMP(3),
  airborne_aircraft INT, ground_aircraft INT, arrivals INT, departures INT, total_movements INT,
  congestion_index DOUBLE, congestion_level STRING, weather_risk STRING,
  PRIMARY KEY (airport_code, window_start) NOT ENFORCED""",
            jdbc_with(table)))
    statements.append(create_table(
        "pg_health",
        f"  component STRING, status STRING, records_published INT, message STRING, event_timestamp {TS}",
        jdbc_with("pipeline_health")))
    return statements


def _metrics_insert(sink: str, granularity: str) -> str:
    return f"""
INSERT INTO {sink}
SELECT airport_code, window_start, window_end,
       CAST(airborne_aircraft AS INT), CAST(ground_aircraft AS INT), CAST(arrivals AS INT),
       CAST(departures AS INT), CAST(total_movements AS INT),
       congestion_index, congestion_level, weather_risk
FROM src_metrics
WHERE granularity = '{granularity}'"""


def inserts() -> list[str]:
    ts = "CAST({} AS TIMESTAMP(3))".format
    return [
        f"""
INSERT INTO pg_flight_events
SELECT source_event_id, icao24, callsign, latitude, longitude, altitude, velocity, heading,
       vertical_rate, on_ground, phase, airport_code, weather_risk, wind_speed, visibility,
       {ts('event_timestamp')}
FROM src_flights""",
        f"""
INSERT INTO pg_flights_current
SELECT icao24, callsign, origin_country, latitude, longitude, altitude, velocity, heading,
       vertical_rate, on_ground, phase, airport_code, weather_risk, {ts('event_timestamp')}
FROM src_flights""",
        f"""
INSERT INTO pg_weather_obs
SELECT source_observation_id, airport_code, temperature, wind_speed, wind_gusts, wind_direction,
       visibility, precipitation, cloud_cover, weather_code, weather_risk, {ts('weather_timestamp')}
FROM src_weather""",
        f"""
INSERT INTO pg_weather_current
SELECT airport_code, temperature, wind_speed, wind_gusts, wind_direction, visibility, precipitation,
       cloud_cover, weather_code, weather_risk, weather_risk_rank, {ts('weather_timestamp')}
FROM src_weather""",
        f"""
INSERT INTO pg_schedules
SELECT flight_key, airport_code, direction, flight_number, airline, origin_airport, destination_airport,
       {ts('scheduled_departure')}, {ts('scheduled_arrival')}, {ts('estimated_departure')},
       {ts('estimated_arrival')}, {ts('actual_departure')}, {ts('actual_arrival')},
       flight_status, delay_minutes, terminal, gate, source, {ts('event_timestamp')}
FROM src_schedules
WHERE flight_key IS NOT NULL AND airport_code IS NOT NULL AND direction IN ('ARRIVAL', 'DEPARTURE')""",
        _metrics_insert("pg_metrics_5min", "5MIN"),
        _metrics_insert("pg_metrics_hourly", "1HOUR"),
        f"""
INSERT INTO pg_health
SELECT component, status, records_published, message, {ts('event_timestamp')}
FROM src_health""",
    ]


if __name__ == "__main__":
    run_job(JOB_NAME, ddl(), inserts())
