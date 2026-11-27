from datetime import datetime, timezone

from producers.flight_producer import parse_response, parse_state
from producers.mock_data import mock_schedules, mock_states, mock_weather
from producers.schedule_producer import parse_av_time, parse_flight
from producers.weather_producer import parse_current
from config.settings import AIRPORTS

BLR = AIRPORTS["BLR"]
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)


def _state(**over):
    s = ["80123a", "AIC501  ", "India", 1795000000, 1795000001, 77.7, 13.2, 1200.0, False, 80.0, 180.0, -4.5,
         None, 1250.0, None, False, 0]
    for idx, val in over.items():
        s[int(idx[1:])] = val
    return s


def test_parse_state_maps_fields():
    e = parse_state(_state(), "BLR")
    assert e["icao24"] == "80123a" and e["callsign"] == "AIC501"
    assert e["latitude"] == 13.2 and e["longitude"] == 77.7
    assert e["vertical_rate"] == -4.5 and e["on_ground"] is False
    assert e["event_timestamp"].endswith("Z") and e["source"] == "opensky"


def test_parse_state_edge_cases():
    assert parse_state(_state(i5=None), "BLR") is None            # no position
    assert parse_state(_state(i1=" "), "BLR")["callsign"] is None  # blank callsign
    assert parse_state(_state(i7=None), "BLR")["altitude"] == 1250.0  # falls back to geo altitude
    assert parse_state(_state(i3=None, i4=None), "BLR", api_time=None) is None
    assert parse_response({"time": 1, "states": None}, "BLR") == []


def test_parse_av_time_converts_local_to_utc():
    dt = parse_av_time("2026-11-24T14:30:00+00:00", "Asia/Kolkata")
    assert dt == datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)
    assert parse_av_time(None, "Asia/Kolkata") is None
    assert parse_av_time("garbage", None) is None


def test_parse_flight_departure():
    item = {
        "flight_date": "2026-11-24", "flight_status": "Active",
        "departure": {"iata": "BLR", "timezone": "Asia/Kolkata", "terminal": "2", "gate": "14", "delay": 25,
                      "scheduled": "2026-11-24T14:30:00+00:00", "estimated": "2026-11-24T14:55:00+00:00"},
        "arrival": {"iata": "DEL", "timezone": "Asia/Kolkata", "scheduled": "2026-11-24T17:15:00+00:00"},
        "airline": {"name": "IndiGo"}, "flight": {"iata": "6E234"},
    }
    r = parse_flight(item, "DEPARTURE", "BLR", NOW)
    assert r["flight_key"] == "6E234_2026-11-24_BLR"
    assert r["flight_status"] == "active" and r["delay_minutes"] == 25
    assert r["scheduled_departure"] == "2026-11-24T09:00:00Z"
    assert r["terminal"] == "2" and r["gate"] == "14" and r["airline"] == "IndiGo"


def test_parse_flight_delay_fallback_and_invalid():
    item = {"departure": {"iata": "DEL", "timezone": "Asia/Kolkata", "scheduled": "2026-11-24T10:00:00+00:00"},
            "arrival": {"iata": "BLR", "timezone": "Asia/Kolkata", "scheduled": "2026-11-24T12:00:00+00:00",
                        "estimated": "2026-11-24T12:20:00+00:00"},
            "flight": {"iata": "AI501"}, "flight_status": "scheduled"}
    assert parse_flight(item, "ARRIVAL", "BLR", NOW)["delay_minutes"] == 20
    assert parse_flight({"flight": {}}, "ARRIVAL", "BLR", NOW) is None
    assert parse_flight({"flight": {"iata": "X1"}, "arrival": {}}, "ARRIVAL", "BLR", NOW) is None


def test_parse_weather():
    body = {"current": {"time": "2026-11-24T09:45", "temperature_2m": 24.1, "wind_speed_10m": 12.0,
                        "wind_gusts_10m": 25.0, "wind_direction_10m": 200, "visibility": 24000.0,
                        "precipitation": 0.0, "cloud_cover": 40, "weather_code": 2}}
    e = parse_current(body, "BLR")
    assert e["weather_timestamp"] == "2026-11-24T09:45:00Z" and e["wind_speed"] == 12.0
    assert parse_current({}, "BLR") is None


def test_mock_generators_are_labelled_and_valid():
    states = mock_states(BLR, NOW)
    assert states and all(s["source"] == "mock" for s in states)
    sched = mock_schedules(BLR, NOW)
    assert all(s["source"] == "mock" and s["direction"] in ("ARRIVAL", "DEPARTURE") for s in sched)
    assert len({s["flight_key"] for s in sched}) == len(sched)
    w = mock_weather(BLR, NOW)
    assert w["source"] == "mock" and w["weather_timestamp"].endswith("Z")


def test_mock_multi_airport_ids_do_not_collide():
    bom = AIRPORTS["BOM"]
    blr_states = mock_states(BLR, NOW)
    bom_states = mock_states(bom, NOW)
    assert {s["icao24"] for s in blr_states}.isdisjoint({s["icao24"] for s in bom_states})

    blr_sched = mock_schedules(BLR, NOW)
    bom_sched = mock_schedules(bom, NOW)
    assert {s["flight_key"] for s in blr_sched}.isdisjoint({s["flight_key"] for s in bom_sched})
