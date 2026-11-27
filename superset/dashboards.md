# Building the two dashboards in Superset

Run `python scripts/setup_superset.py` first to register the PostgreSQL database and datasets, then run `python scripts/create_superset_dashboards.py` to auto-create/update both airport-wise dashboards.
Both dashboards read the same PostgreSQL tables/views (no second pipeline).
Open http://localhost:8088 (default login admin / admin, change it).

## Dashboard 1: Passenger dashboard (auto-refresh 10 s)

Includes multi-select native filters for **Airport** (`airport_code`: `BLR`, `BOM`, `DEL`, `MAA`) and **Direction** (`ARRIVAL` / `DEPARTURE`). When no airport filter is selected, totals/averages aggregate across all monitored airports while the comparison charts and tables show every airport side-by-side.

| Chart | Type | Dataset | Configuration |
|---|---|---|---|
| Arrivals Today / Departures Today | Big Number | `v_passenger_kpis` | `SUM(arrivals_today)` / `SUM(departures_today)` |
| Arrivals / Departures Next Hour | Big Number | `v_passenger_kpis` | `SUM(arrivals_next_hour)` / `SUM(departures_next_hour)` |
| Delayed and Cancelled | Big Number | `v_passenger_kpis` | `SUM(delayed_flights)` |
| On-Time Percentage / Average Delay | Big Number | `v_passenger_kpis` | `AVG(on_time_percentage)` / `AVG(average_delay_min)` |
| Airport-Wise Passenger KPIs | Table | `v_passenger_kpis` | All KPI columns ordered by `airport_code` |
| Arrivals & Departures by Airport | Bar | `v_passenger_kpis` | x `airport_code`, `MAX(arrivals_today)`, `MAX(departures_today)` |
| On-Time % & Avg Delay by Airport | Bar | `v_passenger_kpis` | x `airport_code`, `MAX(on_time_percentage)`, `MAX(average_delay_min)` |
| Airport Weather | Table | `v_weather_latest` | `airport_code`, temperature, wind_speed, visibility, precipitation, weather_risk, observed_local |
| **Live Flight Information** | Table | `v_passenger_flights` | `airport_code`, flight_number, airline, direction, city_airport, scheduled_local, expected_local, delay_minutes, status, terminal, gate |
| Passenger Status Mix | Pie | `v_passenger_flights` | dimension `status`, metric `COUNT(*)` |

## Dashboard 2: Airport operations dashboard (auto-refresh 10 s)

Includes a multi-select native filter for **Airport** (`airport_code`) and breaks out every chart by `airport_code`.

| Chart | Type | Dataset | Configuration |
|---|---|---|---|
| Airborne / Ground Aircraft Now | Big Number | `v_aircraft_now` | `SUM(airborne_aircraft)` / `SUM(ground_aircraft)` |
| Live Airspace by Airport | Table | `v_aircraft_now` | `airport_code`, airborne_aircraft, ground_aircraft, tracked_aircraft |
| Current Operations by Airport | Table | `v_ops_current` | `airport_code`, arrivals, departures, total_movements, congestion_index, congestion_level, weather_risk, window_start |
| Airborne vs Ground by Airport | Bar | `v_aircraft_now` | x `airport_code`, `MAX(airborne_aircraft)`, `MAX(ground_aircraft)` |
| Congestion Index by Airport | Bar | `v_ops_current` | x `airport_code`, `MAX(congestion_index)` |
| Movements per 5 Minutes | Time-series line | `airport_metrics_5min` | x `window_start`, grouped by `airport_code`, `MAX(total_movements)` |
| Arrivals & Departures per Hour | Time-series bar | `v_hourly_ops` | x `hour_local`, grouped by `airport_code`, `MAX(arrivals)`, `MAX(departures)` |
| Average Delay by Hour | Time-series line | `v_hourly_ops` | x `hour_local`, grouped by `airport_code`, `MAX(avg_arrival_delay_min)`, `MAX(avg_departure_delay_min)` |
| Delay vs Wind | Scatter | `v_delay_vs_weather` | x `avg_wind_kmh`, grouped by `airport_code`, `MAX(avg_delay_min)` |
| Weather Risk | Table | `v_ops_current` | `airport_code`, window_start, congestion_level, weather_risk |
| Pipeline Health | Table | `v_pipeline_status` | component, status, records_published, event_timestamp |

## Not available (and intentionally not faked)

* **Runway traffic / utilisation**: needs runway-level operational data (OpenSky positions alone cannot tell which runway was used).
* **Average turnaround time**: needs aircraft registration/tail linking an arrival to its next departure, which the schedule API does not reliably provide.

## Notes

* Set refresh under the dashboard's `...` menu -> *Set auto-refresh*. Superset queries PostgreSQL, not Kafka.
* To let anonymous users see the passenger dashboard, publish it and grant the `Public` role read access to its datasets. Review this before exposing Superset publicly.
* `superset_config.py` disables CSRF for scripting convenience; re-enable it outside local development.
