from config.rules import (
    PhaseRules, WeatherThresholds, average_delay, classify_phase, classify_weather_risk, congestion_index,
    congestion_level, congestion_index_sql, on_time_percentage, phase_sql, weather_risk_sql,
)
from config.settings import AIRPORTS

BLR = AIRPORTS["BLR"]


def test_weather_risk_levels():
    assert classify_weather_risk(10, 20, 10000, 0) == "NORMAL"
    assert classify_weather_risk(32, 20, 10000, 0) == "CAUTION"
    assert classify_weather_risk(10, 20, 2500, 0) == "CAUTION"
    assert classify_weather_risk(55, 20, 10000, 0) == "HIGH_RISK"
    assert classify_weather_risk(10, 20, 800, 0) == "HIGH_RISK"
    assert classify_weather_risk(10, 20, 10000, 12) == "HIGH_RISK"


def test_weather_risk_unknown_and_partial():
    assert classify_weather_risk() == "UNKNOWN"
    assert classify_weather_risk(wind_speed=5) == "NORMAL"


def test_weather_risk_sql_uses_thresholds():
    t = WeatherThresholds(wind_caution_kmh=11, wind_severe_kmh=22)
    sql = weather_risk_sql(t)
    assert "wind_speed >= 22" in sql and "wind_speed >= 11" in sql
    assert "'UNKNOWN'" in sql and "'HIGH_RISK'" in sql


def test_phase_classification():
    lat, lon = BLR.latitude, BLR.longitude
    assert classify_phase(lat, lon, True, 0, 0, BLR) == "GROUND"
    assert classify_phase(lat + 0.05, lon, False, 1500, -5, BLR) == "ARRIVING"
    assert classify_phase(lat + 0.05, lon, False, 1500, 6, BLR) == "DEPARTING"
    assert classify_phase(lat + 0.05, lon, False, 1500, 0.2, BLR) == "LOW_LEVEL"
    assert classify_phase(lat + 0.05, lon, False, 10000, -5, BLR) == "ENROUTE"
    assert classify_phase(lat + 0.4, lon, False, 1500, -5, BLR) == "ENROUTE"
    assert classify_phase(lat, lon, False, None, None, BLR) == "UNKNOWN"


def test_phase_sql_mirrors_rules():
    sql = phase_sql(BLR, PhaseRules(), prefix="f.")
    for fragment in ("f.on_ground", "f.altitude <= 3000.0", "f.vertical_rate <= -1.0", "'ARRIVING'", "'DEPARTING'"):
        assert fragment in sql


def test_congestion():
    assert congestion_index(2, 5, 40) == 0.6
    assert congestion_level(0.3) == "LOW"
    assert congestion_level(0.6) == "MODERATE"
    assert congestion_level(0.9) == "HIGH"
    assert congestion_level(1.2) == "SEVERE"
    assert "12.0" in congestion_index_sql("total_movements", 5, 40)


def test_delay_metrics():
    assert on_time_percentage([0, 10, 15, 30, None]) == 75.0
    assert on_time_percentage([None]) is None
    assert average_delay([-10, 10, 20, None]) == 10.0
    assert average_delay([]) is None
