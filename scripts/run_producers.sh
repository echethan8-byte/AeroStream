#!/bin/bash
# Runs the three producers on the host in the background. Logs go to ./logs/.
# Stop with: pkill -f "python -m producers"
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
set -a; [ -f .env ] && . ./.env; set +a

for p in flight_producer schedule_producer weather_producer; do
  nohup python -m "producers.${p}" > "logs/${p}.log" 2>&1 &
  echo "started ${p} (pid $!)"
done
