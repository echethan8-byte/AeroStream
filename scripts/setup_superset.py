"""Registers the PostgreSQL database and the dashboard datasets (views) in Superset via its REST API.

Charts and dashboards are then built in the UI following superset/dashboards.md.
Usage:  python scripts/setup_superset.py   (Superset must be up at http://localhost:8088)
"""
import os
import sys

import requests

BASE = os.getenv("SUPERSET_URL", "http://localhost:8088")
USER = os.getenv("SUPERSET_ADMIN_USER", "admin")
PASSWORD = os.getenv("SUPERSET_ADMIN_PASSWORD", "admin")
PG_USER = os.getenv("POSTGRES_USER", "flight")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "flight_pw")
PG_DB = os.getenv("POSTGRES_DB", "flight_analytics")

DATASETS = [
    "v_passenger_flights", "v_passenger_kpis", "v_weather_latest",
    "v_ops_current", "v_aircraft_now", "v_hourly_ops", "v_delay_vs_weather", "v_pipeline_status",
    "airport_metrics_5min", "weather_observations", "flights_current",
]


def main() -> None:
    s = requests.Session()
    resp = s.post(f"{BASE}/api/v1/security/login",
                  json={"username": USER, "password": PASSWORD, "provider": "db", "refresh": True}, timeout=30)
    resp.raise_for_status()
    s.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"

    uri = f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@postgres:5432/{PG_DB}"
    existing = s.get(f"{BASE}/api/v1/database/", timeout=30).json().get("result", [])
    db = next((d for d in existing if d["database_name"] == "flight_analytics"), None)
    if db is None:
        r = s.post(f"{BASE}/api/v1/database/",
                   json={"database_name": "flight_analytics", "sqlalchemy_uri": uri, "expose_in_sqllab": True},
                   timeout=30)
        r.raise_for_status()
        db_id = r.json()["id"]
        print(f"created database connection (id={db_id})")
    else:
        db_id = db["id"]
        print(f"database connection exists (id={db_id})")

    for table in DATASETS:
        r = s.post(f"{BASE}/api/v1/dataset/",
                   json={"database": db_id, "schema": "public", "table_name": table}, timeout=30)
        if r.status_code in (200, 201):
            print(f"  dataset created: {table}")
        elif r.status_code == 422:
            print(f"  dataset exists or invalid: {table}")
        else:
            print(f"  FAILED {table}: {r.status_code} {r.text[:200]}", file=sys.stderr)


if __name__ == "__main__":
    main()
