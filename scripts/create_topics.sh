#!/bin/bash
# Creates all Kafka topics (idempotent). Runs inside the kafka-init container.
set -euo pipefail

BOOTSTRAP="${BOOTSTRAP:-kafka:9092}"
KT=/opt/kafka/bin/kafka-topics.sh

for topic in flights.raw schedules.raw weather.raw \
             flights.cleaned weather.cleaned flights.enriched \
             airport.metrics dead-letter pipeline.health; do
  "$KT" --bootstrap-server "$BOOTSTRAP" --create --if-not-exists \
        --topic "$topic" --partitions 1 --replication-factor 1
done

echo "Topics:"
"$KT" --bootstrap-server "$BOOTSTRAP" --list
