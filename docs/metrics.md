# Metric definitions

Times are stored in UTC and shown in the airport's local timezone. Thresholds live in
`config/rules.py` (and `.env`), and the Flink SQL is generated from the same values.

## Passenger dashboard (source: Aviationstack schedules -> `flight_schedules`)

| Metric | Definition |
|---|---|
| Arrivals / departures today | Flights whose scheduled time falls on the airport's local calendar day |
| Arrivals / departures next hour | Scheduled time within the next 60 minutes |
| Delayed flights | `delay_minutes > 15` and not cancelled |
| Cancelled flights | `flight_status = cancelled` |
| On-time % | flights with `delay_minutes <= 15` / eligible flights x 100. Eligible = not cancelled and delay known |
| Average delay | mean of `max(delay_minutes, 0)` over eligible flights (early flights count as 0) |
| Status | Cancelled, Landed, Diverted, Incident, Delayed (>15 min), In air, Scheduled |
| Delay | provider `delay` if given, else (actual or estimated) minus scheduled |

## Operations dashboard (source: OpenSky positions + Open-Meteo -> Flink)

| Metric | Definition |
|---|---|
| Airborne / ground aircraft | distinct `icao24` with `on_ground = false/true` per window; "now" view uses the last 5 minutes |
| Phase | `GROUND`; inside the terminal area (default +/-0.25 deg) and below 3000 m: `ARRIVING` if vertical rate <= -1 m/s, `DEPARTING` if >= +1 m/s, else `LOW_LEVEL`; otherwise `ENROUTE` |
| Arrivals / departures | distinct aircraft classified `ARRIVING` / `DEPARTING` per window |
| Total movements | arrivals + departures |
| 5-min windows | event-time tumbling windows, 30 s watermark delay |
| Hourly windows | event-time sliding windows (1 hour, slide 5 min); dashboards use rows aligned to the local hour |
| Congestion index | `movements x (60 / window_minutes) / capacity_per_hour`; capacity is configurable (default 40) |
| Congestion level | LOW < 0.5, MODERATE < 0.8, HIGH < 1.0, else SEVERE |
| Weather risk | worst of: wind >= 30/50 km/h, gusts >= 45/65 km/h, visibility < 3000/1000 m, precipitation >= 2.5/10 mm (CAUTION / HIGH_RISK); UNKNOWN if no inputs |

Weather risk, phase and congestion are project-defined indicators, **not** official aviation
safety or air-traffic classifications.

## Known limitations

* Arrival/departure counts from positions are an approximation: they depend on ADS-B receiver
  coverage near the airport, and one aircraft can be seen in several windows.
* **Runway traffic** and **average turnaround time** are not computed: they need runway-level or
  tail-number data that neither API provides. They are deliberately left out rather than faked.
* Open-Meteo "current" weather is model-based for the airport coordinates, not an airport sensor reading.
* Aviationstack free plans have small quotas and may not include gate/terminal for every flight.
