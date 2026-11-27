#!/bin/bash
# Submits all PyFlink jobs to the running Flink cluster (detached).
# Order matters a little: weather and the Postgres sink first, so the enrichment job's
# JDBC lookup finds a weather_current row as early as possible.
set -euo pipefail
cd "$(dirname "$0")/.."

JOBS=(weather_cleaning flight_cleaning postgres_sink flight_enrichment airport_analytics)

for job in "${JOBS[@]}"; do
  echo ">> submitting ${job}"
  docker compose exec -T flink-jobmanager \
    flink run -d -py "/opt/project/flink_jobs/${job}.py" -pyexec python3 -pyclientexec python3
done

echo "Done. Flink UI: http://localhost:8081"
