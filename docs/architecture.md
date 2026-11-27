# Architecture

One streaming pipeline feeds both dashboards; they differ only in which tables/views they query.

```mermaid
flowchart LR
  OS[OpenSky API<br/>aircraft positions] --> FP[flight_producer]
  AV[Aviationstack API<br/>schedules / status] --> SP[schedule_producer]
  OM[Open-Meteo API<br/>weather] --> WP[weather_producer]

  FP --> K1[(flights.raw)]
  SP --> K2[(schedules.raw)]
  WP --> K3[(weather.raw)]

  K1 --> J1[Job 1: flight cleaning]
  K3 --> J2[Job 2: weather cleaning<br/>+ weather risk]
  J1 --> K4[(flights.cleaned)]
  J2 --> K5[(weather.cleaned)]
  J1 -.invalid.-> DL[(dead-letter)]
  J2 -.invalid.-> DL

  K4 --> J3[Job 3: enrichment<br/>phase + latest weather]
  J3 --> K6[(flights.enriched)]
  K6 --> J4[Job 4: analytics<br/>5-min tumbling, 1-h sliding]
  J4 --> K7[(airport.metrics)]

  K6 --> J5[Job 5: PostgreSQL sink<br/>idempotent upserts]
  K5 --> J5
  K2 --> J5
  K7 --> J5
  FP & SP & WP -.heartbeats.-> K8[(pipeline.health)] --> J5

  J5 --> PG[(PostgreSQL<br/>flight_analytics)]
  PG -.weather_current lookup.-> J3
  PG --> SS[Apache Superset]
  SS --> D1[Passenger dashboard]
  SS --> D2[Operations dashboard]
```

Kafka is the transport layer, Flink does the processing, PostgreSQL stores results, Superset only
queries PostgreSQL.

## Key design choices

| Choice | Reason |
|---|---|
| Separate Kafka topics per stage | each stage can be inspected and replayed independently |
| Dead-letter topic | invalid records are kept with a reason, not silently dropped |
| Event-time windows + watermarks | results follow when events happened, not when they arrived |
| Deterministic keys + JDBC upserts | replays and duplicate API polls cannot create duplicate rows |
| Processing-time JDBC lookup for weather | low latency; trade-off documented in `flink_jobs/flight_enrichment.py` |
| Delay metrics from schedule data in SQL views | positions cannot yield delays; views always reflect the latest flight state |
| Rules shared by Python and Flink SQL (`config/rules.py`) | thresholds are defined once |
| `MOCK_MODE` | develop and demo without API keys; records are labelled `source = "mock"` |

## Ports

Kafka UI 8080 · Flink UI 8081 · Superset 8088 · PostgreSQL 5432 · Kafka (host) 29092
