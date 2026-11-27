# Real-Time Flight Monitoring & Airport Analytics Platform

Kafka -> PyFlink -> PostgreSQL -> Superset, monitoring one airport (default **BLR**) with two
dashboards (passenger, airport operations) on a single shared pipeline.

Data sources: OpenSky (aircraft positions), Aviationstack (schedules/status), Open-Meteo (weather).
See `docs/architecture.md` for the diagram and `docs/metrics.md` for every metric definition.

## Quick start

```bash
cp .env.example .env            # add API keys, or set MOCK_MODE=true to run without them
docker compose up -d --build    # Kafka (KRaft), Kafka UI, PostgreSQL, Flink, Superset (first build takes a while)

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

./scripts/run_producers.sh      # flight, schedule and weather producers (logs in ./logs)
./scripts/submit_flink_jobs.sh  # submits the 5 PyFlink jobs to the cluster
python scripts/setup_superset.py
```

Then build the charts following `superset/dashboards.md`.

| Service | URL |
|---|---|
| Control Tower Dashboard | http://localhost:8050 |
| Kafka UI | http://localhost:8080 |
| Flink UI | http://localhost:8081 |
| Superset | http://localhost:8088 (admin / admin) |
| PostgreSQL | localhost:5432, db `flight_analytics` |

Producers can also run in containers: `docker compose --profile producers up -d --build`.

## Verify each stage

1. **Kafka**: in Kafka UI open `flights.raw`, `weather.raw`, `schedules.raw` and see messages arriving.
2. **Flink**: jobs `flight-cleaning`, `weather-cleaning`, `postgres-sink`, `flight-enrichment`, `airport-analytics` are RUNNING; `flights.cleaned`, `flights.enriched` and `airport.metrics` fill up.
3. **PostgreSQL**:
   ```bash
   docker compose exec postgres psql -U flight -d flight_analytics \
     -c "SELECT COUNT(*) FROM flight_events;" \
     -c "SELECT * FROM v_ops_current;" \
     -c "SELECT * FROM v_passenger_kpis;"
   ```
   5-minute metrics appear after the first window closes (about 5-6 minutes after data starts).
4. **Superset**: dashboards auto-refresh from PostgreSQL.

## Layout

```
config/        settings (env), airports, shared metric rules
dashboard/     FastAPI + Leaflet/Chart.js real-time Control Tower & FIDS UI
producers/     OpenSky, Aviationstack, Open-Meteo -> Kafka (+ mock data)
flink_jobs/    the 5 PyFlink SQL jobs
database/      schema.sql (tables, indexes, dashboard views)
superset/      Superset image/config and dashboard build guide
scripts/       topic creation, job submission, producers launcher, Superset setup
tests/         unit tests (rules, parsers, generated SQL)
docs/          architecture, metric definitions
```

## Tests

```bash
pytest -q
```

Unit tests cover the metric rules, API response parsers and the generated Flink SQL. The full
Docker pipeline is not covered by automated tests: run the verification steps above.

## Notes and limits

* Aviationstack free plans have tiny quotas and are http-only; the default schedule poll is 15 minutes. Check your plan.
* Runway traffic and turnaround time are not computed (data not available); see `docs/metrics.md`.
* Start with `MOCK_MODE=true` to validate the whole pipeline, then switch to real APIs. Mock records carry `source = "mock"`; do not present them as real flight data.
* Superset ships with development defaults (admin/admin, CSRF off): change them before exposing it.
