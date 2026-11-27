"""Static checks on the generated Flink SQL (no Flink needed)."""
import importlib

import pytest

JOBS = ["flight_cleaning", "weather_cleaning", "flight_enrichment", "airport_analytics", "postgres_sink"]


@pytest.mark.parametrize("name", JOBS)
def test_job_sql_is_well_formed(name):
    mod = importlib.import_module(f"flink_jobs.{name}")
    ddl, inserts = mod.ddl(), mod.inserts()
    assert ddl and inserts
    for stmt in ddl:
        assert stmt.lstrip().startswith("CREATE TABLE")
        assert stmt.count("(") == stmt.count(")")
        assert "'connector'" in stmt
    for stmt in inserts:
        assert stmt.lstrip().startswith("INSERT INTO")
        assert stmt.count("(") == stmt.count(")")


@pytest.mark.parametrize("name", JOBS)
def test_inserts_target_declared_tables(name):
    import re

    mod = importlib.import_module(f"flink_jobs.{name}")
    declared = {re.match(r"\s*CREATE TABLE (\w+)", s).group(1) for s in mod.ddl()}
    for stmt in mod.inserts():
        target = re.match(r"\s*INSERT INTO (\w+)", stmt).group(1)
        assert target in declared, f"{name}: INSERT target {target} not declared"
        for table in re.findall(r"(?:FROM|JOIN|TABLE)\s*\(?\s*(?:TABLE\s+)?(\w+)", stmt):
            if table.upper() in ("TABLE", "TUMBLE", "HOP", "SELECT"):
                continue
            assert table in declared or table.startswith("("), f"{name}: unknown table {table}"


def test_analytics_uses_event_time_windows():
    from flink_jobs import airport_analytics as a

    ddl = "\n".join(a.ddl())
    sql = "\n".join(a.inserts())
    assert "WATERMARK FOR event_timestamp" in ddl
    assert "TUMBLE(TABLE flights_enriched" in sql and "HOP(TABLE flights_enriched" in sql
    assert "'5MIN'" in sql and "'1HOUR'" in sql


def test_enrichment_handles_all_configured_airports():
    from config.settings import AIRPORTS
    from flink_jobs import flight_enrichment as fe

    sql = "\n".join(fe.inserts())
    for code in AIRPORTS:
        assert f"WHEN '{code}'" in sql


def test_sink_keys_match_database_constraints():
    from pathlib import Path

    schema = Path(__file__).resolve().parent.parent.joinpath("database", "schema.sql").read_text()
    from flink_jobs import postgres_sink as p

    ddl = "\n".join(p.ddl())
    for key in ("source_event_id", "source_observation_id", "flight_key"):
        assert f"PRIMARY KEY ({key}) NOT ENFORCED" in ddl
        assert key in schema
    assert "UNIQUE (airport_code, window_start)" in schema
