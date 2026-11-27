-- flight_analytics schema
-- Refinements vs. the starting schema in the project plan:
--   * natural keys (flight_key, source_event_id, source_observation_id) so Flink JDBC upserts are idempotent
--   * flight_schedules carries direction/terminal/gate/delay_minutes
--   * weather_current holds the latest row per airport (used by Flink's JDBC lookup join)
--   * delay metrics are computed in SQL views from schedule data (positions cannot give delays),
--     so airport_metrics_* only hold position-derived movement metrics
-- All timestamps are stored as TIMESTAMPTZ (UTC); views convert to the airport's local time.

-- ------------------------------------------------------------------ reference data
CREATE TABLE IF NOT EXISTS airport_reference (
    airport_code  VARCHAR(10) PRIMARY KEY,
    airport_name  VARCHAR(150),
    icao_code     VARCHAR(10),
    latitude      DOUBLE PRECISION,
    longitude     DOUBLE PRECISION,
    timezone      VARCHAR(50) NOT NULL
);

INSERT INTO airport_reference VALUES
  ('BLR', 'Kempegowda International Airport', 'VOBL', 13.1986, 77.7066, 'Asia/Kolkata'),
  ('DEL', 'Indira Gandhi International Airport', 'VIDP', 28.5562, 77.1000, 'Asia/Kolkata'),
  ('BOM', 'Chhatrapati Shivaji Maharaj International Airport', 'VABB', 19.0887, 72.8679, 'Asia/Kolkata'),
  ('MAA', 'Chennai International Airport', 'VOMM', 12.9941, 80.1709, 'Asia/Kolkata')
ON CONFLICT (airport_code) DO NOTHING;

-- ------------------------------------------------------------------ flights
CREATE TABLE IF NOT EXISTS flight_schedules (
    flight_key           VARCHAR(120) PRIMARY KEY,         -- <flight_iata>_<flight_date>_<dep_iata>
    airport_code         VARCHAR(10) NOT NULL REFERENCES airport_reference(airport_code),
    direction            VARCHAR(10) NOT NULL CHECK (direction IN ('ARRIVAL', 'DEPARTURE')),
    flight_number        VARCHAR(30),
    airline              VARCHAR(100),
    origin_airport       VARCHAR(10),
    destination_airport  VARCHAR(10),
    scheduled_departure  TIMESTAMPTZ,
    scheduled_arrival    TIMESTAMPTZ,
    estimated_departure  TIMESTAMPTZ,
    estimated_arrival    TIMESTAMPTZ,
    actual_departure     TIMESTAMPTZ,
    actual_arrival       TIMESTAMPTZ,
    flight_status        VARCHAR(30),
    delay_minutes        INTEGER,
    terminal             VARCHAR(20),
    gate                 VARCHAR(20),
    source               VARCHAR(30),
    last_updated         TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS flight_events (
    event_id         BIGSERIAL PRIMARY KEY,
    source_event_id  VARCHAR(150) UNIQUE NOT NULL,         -- <icao24>_<yyyyMMddHHmmss>
    icao24           VARCHAR(10),
    callsign         VARCHAR(30),
    latitude         DOUBLE PRECISION,
    longitude        DOUBLE PRECISION,
    altitude         DOUBLE PRECISION,                     -- metres
    velocity         DOUBLE PRECISION,                     -- m/s
    heading          DOUBLE PRECISION,
    vertical_rate    DOUBLE PRECISION,                     -- m/s
    on_ground        BOOLEAN,
    phase            VARCHAR(20),
    airport_code     VARCHAR(10),
    weather_risk     VARCHAR(20),
    wind_speed       DOUBLE PRECISION,
    visibility       DOUBLE PRECISION,
    event_timestamp  TIMESTAMPTZ,
    ingested_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS flights_current (
    icao24           VARCHAR(10) PRIMARY KEY,
    callsign         VARCHAR(30),
    origin_country   VARCHAR(80),
    latitude         DOUBLE PRECISION,
    longitude        DOUBLE PRECISION,
    altitude         DOUBLE PRECISION,
    velocity         DOUBLE PRECISION,
    heading          DOUBLE PRECISION,
    vertical_rate    DOUBLE PRECISION,
    on_ground        BOOLEAN,
    phase            VARCHAR(20),
    airport_code     VARCHAR(10),
    weather_risk     VARCHAR(20),
    event_timestamp  TIMESTAMPTZ
);

-- ------------------------------------------------------------------ weather
CREATE TABLE IF NOT EXISTS weather_observations (
    observation_id         BIGSERIAL PRIMARY KEY,
    source_observation_id  VARCHAR(100) UNIQUE NOT NULL,   -- <airport>_<yyyyMMddHHmm>
    airport_code           VARCHAR(10),
    temperature            DOUBLE PRECISION,               -- deg C
    wind_speed             DOUBLE PRECISION,               -- km/h
    wind_gusts             DOUBLE PRECISION,               -- km/h
    wind_direction         DOUBLE PRECISION,
    visibility             DOUBLE PRECISION,               -- metres
    precipitation          DOUBLE PRECISION,               -- mm
    cloud_cover            DOUBLE PRECISION,               -- %
    weather_code           INTEGER,                        -- WMO code
    weather_risk           VARCHAR(20),
    weather_timestamp      TIMESTAMPTZ,
    ingested_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS weather_current (
    airport_code       VARCHAR(10) PRIMARY KEY,
    temperature        DOUBLE PRECISION,
    wind_speed         DOUBLE PRECISION,
    wind_gusts         DOUBLE PRECISION,
    wind_direction     DOUBLE PRECISION,
    visibility         DOUBLE PRECISION,
    precipitation      DOUBLE PRECISION,
    cloud_cover        DOUBLE PRECISION,
    weather_code       INTEGER,
    weather_risk       VARCHAR(20),
    weather_risk_rank  INTEGER,
    weather_timestamp  TIMESTAMPTZ
);

-- ------------------------------------------------------------------ analytics results
CREATE TABLE IF NOT EXISTS airport_metrics_5min (
    metric_id         BIGSERIAL PRIMARY KEY,
    airport_code      VARCHAR(10),
    window_start      TIMESTAMPTZ,
    window_end        TIMESTAMPTZ,
    airborne_aircraft INTEGER,
    ground_aircraft   INTEGER,
    arrivals          INTEGER,
    departures        INTEGER,
    total_movements   INTEGER,
    congestion_index  DOUBLE PRECISION,
    congestion_level  VARCHAR(20),
    weather_risk      VARCHAR(20),
    UNIQUE (airport_code, window_start)
);

-- Rolling one-hour windows that slide every 5 minutes (HOP). Dashboards filter to clock-aligned rows.
CREATE TABLE IF NOT EXISTS airport_metrics_hourly (
    metric_id         BIGSERIAL PRIMARY KEY,
    airport_code      VARCHAR(10),
    window_start      TIMESTAMPTZ,
    window_end        TIMESTAMPTZ,
    airborne_aircraft INTEGER,
    ground_aircraft   INTEGER,
    arrivals          INTEGER,
    departures        INTEGER,
    total_movements   INTEGER,
    congestion_index  DOUBLE PRECISION,
    congestion_level  VARCHAR(20),
    weather_risk      VARCHAR(20),
    UNIQUE (airport_code, window_start)
);

CREATE TABLE IF NOT EXISTS pipeline_health (
    health_id          BIGSERIAL PRIMARY KEY,
    component          VARCHAR(50),
    status             VARCHAR(20),
    records_published  INTEGER,
    message            VARCHAR(600),
    event_timestamp    TIMESTAMPTZ,
    ingested_at        TIMESTAMPTZ DEFAULT NOW()
);

-- ------------------------------------------------------------------ indexes
CREATE INDEX IF NOT EXISTS idx_flight_events_ts        ON flight_events (event_timestamp);
CREATE INDEX IF NOT EXISTS idx_flight_events_icao24    ON flight_events (icao24);
CREATE INDEX IF NOT EXISTS idx_flight_schedules_number ON flight_schedules (flight_number);
CREATE INDEX IF NOT EXISTS idx_flight_schedules_dep    ON flight_schedules (scheduled_departure);
CREATE INDEX IF NOT EXISTS idx_flight_schedules_arr    ON flight_schedules (scheduled_arrival);
CREATE INDEX IF NOT EXISTS idx_weather_obs_airport_ts  ON weather_observations (airport_code, weather_timestamp);
CREATE INDEX IF NOT EXISTS idx_metrics_5min_start      ON airport_metrics_5min (window_start);
CREATE INDEX IF NOT EXISTS idx_metrics_hourly_start    ON airport_metrics_hourly (window_start);
CREATE INDEX IF NOT EXISTS idx_pipeline_health_ts      ON pipeline_health (event_timestamp);

-- ------------------------------------------------------------------ views for Superset
-- On-time threshold is 15 minutes (see docs/metrics.md). Change it here and in .env together.

CREATE OR REPLACE VIEW v_schedule_base AS
SELECT s.*,
       a.timezone AS airport_tz,
       CASE WHEN s.direction = 'ARRIVAL' THEN s.scheduled_arrival ELSE s.scheduled_departure END AS scheduled_time,
       CASE WHEN s.direction = 'ARRIVAL'
            THEN COALESCE(s.actual_arrival, s.estimated_arrival, s.scheduled_arrival)
            ELSE COALESCE(s.actual_departure, s.estimated_departure, s.scheduled_departure) END AS expected_time,
       CASE WHEN s.direction = 'ARRIVAL' THEN s.origin_airport ELSE s.destination_airport END AS other_airport
FROM flight_schedules s
JOIN airport_reference a ON a.airport_code = s.airport_code;

-- Live flight information table (passenger dashboard)
CREATE OR REPLACE VIEW v_passenger_flights AS
SELECT flight_key,
       airport_code,
       direction,
       flight_number,
       airline,
       other_airport                              AS city_airport,
       scheduled_time AT TIME ZONE airport_tz     AS scheduled_local,
       expected_time  AT TIME ZONE airport_tz     AS expected_local,
       delay_minutes,
       terminal,
       gate,
       CASE
         WHEN LOWER(flight_status) = 'cancelled' THEN 'Cancelled'
         WHEN LOWER(flight_status) = 'landed'    THEN 'Landed'
         WHEN LOWER(flight_status) = 'diverted'  THEN 'Diverted'
         WHEN LOWER(flight_status) = 'incident'  THEN 'Incident'
         WHEN delay_minutes > 15                 THEN 'Delayed'
         WHEN LOWER(flight_status) = 'active'    THEN 'In air'
         ELSE 'Scheduled'
       END AS status
FROM v_schedule_base
WHERE scheduled_time BETWEEN NOW() - INTERVAL '3 hours' AND NOW() + INTERVAL '12 hours';

-- Passenger KPI row per airport. "Today" = the airport's local calendar day.
CREATE OR REPLACE VIEW v_passenger_kpis AS
SELECT airport_code,
       COUNT(*) FILTER (WHERE direction = 'ARRIVAL'
             AND (scheduled_time AT TIME ZONE airport_tz)::date = (NOW() AT TIME ZONE airport_tz)::date)   AS arrivals_today,
       COUNT(*) FILTER (WHERE direction = 'DEPARTURE'
             AND (scheduled_time AT TIME ZONE airport_tz)::date = (NOW() AT TIME ZONE airport_tz)::date)   AS departures_today,
       COUNT(*) FILTER (WHERE direction = 'ARRIVAL'
             AND scheduled_time BETWEEN NOW() AND NOW() + INTERVAL '1 hour')                                AS arrivals_next_hour,
       COUNT(*) FILTER (WHERE direction = 'DEPARTURE'
             AND scheduled_time BETWEEN NOW() AND NOW() + INTERVAL '1 hour')                                AS departures_next_hour,
       COUNT(*) FILTER (WHERE delay_minutes > 15 AND LOWER(flight_status) <> 'cancelled'
             AND (scheduled_time AT TIME ZONE airport_tz)::date = (NOW() AT TIME ZONE airport_tz)::date)   AS delayed_flights,
       COUNT(*) FILTER (WHERE LOWER(flight_status) = 'cancelled'
             AND (scheduled_time AT TIME ZONE airport_tz)::date = (NOW() AT TIME ZONE airport_tz)::date)   AS cancelled_flights,
       ROUND(100.0 * COUNT(*) FILTER (WHERE delay_minutes <= 15 AND LOWER(flight_status) <> 'cancelled'
             AND (scheduled_time AT TIME ZONE airport_tz)::date = (NOW() AT TIME ZONE airport_tz)::date)
             / NULLIF(COUNT(*) FILTER (WHERE delay_minutes IS NOT NULL AND LOWER(flight_status) <> 'cancelled'
             AND (scheduled_time AT TIME ZONE airport_tz)::date = (NOW() AT TIME ZONE airport_tz)::date), 0), 1) AS on_time_percentage,
       ROUND(AVG(GREATEST(delay_minutes, 0)) FILTER (WHERE delay_minutes IS NOT NULL
             AND LOWER(flight_status) <> 'cancelled'
             AND (scheduled_time AT TIME ZONE airport_tz)::date = (NOW() AT TIME ZONE airport_tz)::date)::numeric, 1) AS average_delay_min
FROM v_schedule_base
GROUP BY airport_code;

CREATE OR REPLACE VIEW v_weather_latest AS
SELECT w.airport_code,
       w.temperature, w.wind_speed, w.wind_gusts, w.wind_direction,
       w.visibility, w.precipitation, w.cloud_cover, w.weather_code, w.weather_risk,
       w.weather_timestamp AT TIME ZONE a.timezone AS observed_local
FROM weather_current w
JOIN airport_reference a ON a.airport_code = w.airport_code;

-- Latest completed 5-minute window per airport
CREATE OR REPLACE VIEW v_ops_current AS
SELECT DISTINCT ON (m.airport_code)
       m.airport_code, m.window_start, m.window_end,
       m.arrivals, m.departures, m.total_movements,
       m.congestion_index, m.congestion_level, m.weather_risk
FROM airport_metrics_5min m
ORDER BY m.airport_code, m.window_start DESC;

-- Aircraft seen in the last 5 minutes (state of the monitored area right now)
CREATE OR REPLACE VIEW v_aircraft_now AS
SELECT airport_code,
       COUNT(*) FILTER (WHERE NOT on_ground) AS airborne_aircraft,
       COUNT(*) FILTER (WHERE on_ground)     AS ground_aircraft,
       COUNT(*)                              AS tracked_aircraft
FROM flights_current
WHERE event_timestamp > NOW() - INTERVAL '5 minutes'
GROUP BY airport_code;

-- Arrivals/departures per hour: clock-aligned (airport local time) rolling windows + schedule delays
CREATE OR REPLACE VIEW v_hourly_ops AS
WITH sched AS (
    SELECT airport_code,
           DATE_TRUNC('hour', scheduled_time AT TIME ZONE airport_tz) AS hour_local,
           ROUND(AVG(GREATEST(delay_minutes, 0)) FILTER (WHERE direction = 'ARRIVAL'
                 AND LOWER(flight_status) <> 'cancelled')::numeric, 1)   AS avg_arrival_delay_min,
           ROUND(AVG(GREATEST(delay_minutes, 0)) FILTER (WHERE direction = 'DEPARTURE'
                 AND LOWER(flight_status) <> 'cancelled')::numeric, 1)   AS avg_departure_delay_min,
           ROUND(100.0 * COUNT(*) FILTER (WHERE delay_minutes <= 15 AND LOWER(flight_status) <> 'cancelled')
                 / NULLIF(COUNT(*) FILTER (WHERE delay_minutes IS NOT NULL AND LOWER(flight_status) <> 'cancelled'), 0), 1)
                                                                          AS on_time_percentage
    FROM v_schedule_base
    GROUP BY 1, 2
)
SELECT m.airport_code,
       m.window_start AT TIME ZONE a.timezone AS hour_local,
       m.arrivals, m.departures, m.total_movements,
       m.congestion_index, m.congestion_level, m.weather_risk,
       s.avg_arrival_delay_min, s.avg_departure_delay_min, s.on_time_percentage
FROM airport_metrics_hourly m
JOIN airport_reference a ON a.airport_code = m.airport_code
LEFT JOIN sched s ON s.airport_code = m.airport_code
                 AND s.hour_local = DATE_TRUNC('hour', m.window_start AT TIME ZONE a.timezone)
WHERE EXTRACT(MINUTE FROM (m.window_start AT TIME ZONE a.timezone)) = 0;

-- How weather conditions relate to delays, per local hour
CREATE OR REPLACE VIEW v_delay_vs_weather AS
SELECT b.airport_code,
       DATE_TRUNC('hour', b.scheduled_time AT TIME ZONE b.airport_tz)        AS hour_local,
       ROUND(AVG(GREATEST(b.delay_minutes, 0))::numeric, 1)                 AS avg_delay_min,
       COUNT(*)                                                              AS flights,
       ROUND(AVG(w.wind_speed)::numeric, 1)                                 AS avg_wind_kmh,
       ROUND(MIN(w.visibility)::numeric, 0)                                 AS min_visibility_m,
       ROUND(SUM(w.precipitation)::numeric, 1)                              AS precipitation_mm,
       MAX(CASE w.weather_risk WHEN 'HIGH_RISK' THEN 2 WHEN 'CAUTION' THEN 1 ELSE 0 END) AS max_risk_rank
FROM v_schedule_base b
LEFT JOIN weather_observations w
       ON w.airport_code = b.airport_code
      AND DATE_TRUNC('hour', w.weather_timestamp AT TIME ZONE b.airport_tz)
          = DATE_TRUNC('hour', b.scheduled_time AT TIME ZONE b.airport_tz)
WHERE b.delay_minutes IS NOT NULL AND LOWER(b.flight_status) <> 'cancelled'
GROUP BY 1, 2;

-- Latest heartbeat per pipeline component
CREATE OR REPLACE VIEW v_pipeline_status AS
SELECT DISTINCT ON (component)
       component, status, records_published, message, event_timestamp
FROM pipeline_health
ORDER BY component, event_timestamp DESC;
