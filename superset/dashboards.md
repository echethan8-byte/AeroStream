# Superset dashboards

Run `python scripts/setup_superset.py` to register the database and datasets, then run
`python scripts/create_superset_dashboards.py` to create or update both dashboards and charts.
Both dashboards read the same PostgreSQL tables/views (no second pipeline). Open
http://localhost:8088 (default login admin / admin, change it).

Both dashboards include an **Airport** dropdown at the top. Select BLR, BOM, DEL, or MAA to
filter the dashboard charts for that airport; the default selection is BLR. Flight, weather,
and operations tables include `airport_code` so the selected airport is visible in the results.
The pipeline-health chart is global because it reports producer status across the whole pipeline.
Dashboards refresh every 5 seconds.

## Dashboard 1: Passenger dashboard (auto-refresh 30 s)

| Chart | Type | Dataset | Configuration |
|---|---|---|---|
| Arrivals today / Departures today | Big Number | `v_passenger_kpis` | metric `MAX(arrivals_today)` / `MAX(departures_today)` |
| Arrivals / departures next hour | Big Number | `v_passenger_kpis` | `MAX(arrivals_next_hour)` / `MAX(departures_next_hour)` |
| Delayed / Cancelled | Big Number | `v_passenger_kpis` | `MAX(delayed_flights)` / `MAX(cancelled_flights)` |
| On-time % | Big Number | `v_passenger_kpis` | `MAX(on_time_percentage)` |
| Average delay (min) | Big Number | `v_passenger_kpis` | `MAX(average_delay_min)` |
| **Live flight information** | Table (raw records) | `v_passenger_flights` | columns: flight_number, airline, direction, city_airport, scheduled_local, expected_local, status, terminal, gate; order by `scheduled_local` |
| Status mix | Pie | `v_passenger_flights` | dimension `status`, metric `COUNT(*)` |
| Airport weather | Table | `v_weather_latest` | temperature, wind_speed, visibility, precipitation, observed_local |

An airport filter is already created by the setup script. Add a `direction` filter in Superset
if you also want to narrow the passenger flight table to arrivals or departures.

## Dashboard 2: Airport operations dashboard (auto-refresh 1 min)

| Chart | Type | Dataset | Configuration |
|---|---|---|---|
| Airborne / on ground now | Big Number | `v_aircraft_now` | `MAX(airborne_aircraft)` / `MAX(ground_aircraft)` |
| Arrivals & departures per hour | Time-series bar | `v_hourly_ops` | x `hour_local`, metrics `MAX(arrivals)`, `MAX(departures)` |
| Movements per 5 minutes | Time-series line | `airport_metrics_5min` | x `window_start`, metric `MAX(total_movements)` |
| Congestion | Gauge / Big Number | `v_ops_current` | `MAX(congestion_index)`, show `congestion_level` |
| Average arrival / departure delay by hour | Time-series line | `v_hourly_ops` | `MAX(avg_arrival_delay_min)`, `MAX(avg_departure_delay_min)` |
| Weather risk | Table | `v_ops_current` | window_start, weather_risk |
| Delay vs weather | Scatter / mixed | `v_delay_vs_weather` | x `avg_wind_kmh` or `min_visibility_m`, y `avg_delay_min` |
| Pipeline health | Table | `v_pipeline_status` | component, status, records_published, event_timestamp |

## Not available (and intentionally not faked)

* **Runway traffic / utilisation**: needs runway-level operational data (OpenSky positions alone cannot tell which runway was used).
* **Average turnaround time**: needs aircraft registration/tail linking an arrival to its next departure, which the schedule API does not reliably provide.

## Notes

* Set refresh under the dashboard's `...` menu -> *Set auto-refresh*. Superset queries PostgreSQL, not Kafka.
* To let anonymous users see the passenger dashboard, publish it and grant the `Public` role read access to its datasets. Review this before exposing Superset publicly.
* `superset_config.py` disables CSRF for scripting convenience; re-enable it outside local development.
