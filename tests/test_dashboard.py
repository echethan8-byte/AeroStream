"""Tests for the custom FastAPI live dashboard."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.db import json_safe

client = TestClient(app)


def test_json_safe_converts_datetime_and_decimal():
    dt = datetime(2026, 11, 27, 2, 30, tzinfo=timezone.utc)
    payload = {"ts": dt, "pct": Decimal("83.3"), "nested": [{"v": Decimal("1.5")}]}
    assert json_safe(payload) == {
        "ts": "2026-11-27T02:30:00+00:00",
        "pct": 83.3,
        "nested": [{"v": 1.5}],
    }


def test_health_and_index():
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    assert res_health.json() == {"status": "ok"}

    res_index = client.get("/")
    assert res_index.status_code == 200
    assert "SkyPulse Control Tower" in res_index.text


def test_dashboard_endpoint_returns_payload():
    sample = {
        "server_time_utc": "2026-11-27T02:30:00+00:00",
        "airport_code": "BLR",
        "terminal_radius_deg": 0.25,
        "airports": [{"airport_code": "BLR", "airport_name": "Kempegowda International Airport"}],
        "selected_airport": {"airport_code": "BLR", "latitude": 13.1986, "longitude": 77.7066},
        "passenger_kpis": {"arrivals_today": 10},
        "passenger_flights": [],
        "weather": None,
        "aircraft_now": {"airborne_aircraft": 8, "ground_aircraft": 6},
        "aircraft": [],
        "ops_current": None,
        "metrics_5min": [],
        "hourly_ops": [],
        "delay_vs_weather": [],
        "pipeline_status": [],
    }
    with patch("dashboard.app.fetch_dashboard_state", return_value=sample) as mock_fetch:
        res = client.get("/api/dashboard?airport=BLR&direction=ARRIVAL")
        assert res.status_code == 200
        assert res.json()["airport_code"] == "BLR"
        mock_fetch.assert_called_once_with(airport_code="BLR", direction="ARRIVAL")


def test_dashboard_endpoint_returns_503_on_db_error():
    with patch("dashboard.app.fetch_dashboard_state", side_effect=RuntimeError("db down")):
        res = client.get("/api/dashboard")
        assert res.status_code == 503
        assert "Database unavailable" in res.json()["detail"]
