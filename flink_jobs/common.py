"""Shared helpers for the PyFlink SQL jobs. Pure string builders + a thin runner (pyflink imported lazily)."""
from __future__ import annotations

import os

from config.settings import get_settings

JSON_OPTS = {
    "format": "json",
    "json.timestamp-format.standard": "ISO-8601",
    "json.ignore-parse-errors": "true",   # unparseable records become NULL rows -> dead-letter filters
}


def _with(options: dict[str, str]) -> str:
    return ",\n  ".join(f"'{k}' = '{v}'" for k, v in options.items())


def kafka_with(topic: str, group_id: str | None = None) -> str:
    """WITH-clause body for a Kafka table. group_id given => source, otherwise sink."""
    opts = {"connector": "kafka", "topic": topic, "properties.bootstrap.servers": get_settings().kafka_bootstrap}
    if group_id:
        opts["properties.group.id"] = group_id
        opts["scan.startup.mode"] = "group-offsets"
        opts["properties.auto.offset.reset"] = "earliest"
    opts.update(JSON_OPTS)
    return _with(opts)


def jdbc_with(table: str, sink: bool = True, lookup: bool = False) -> str:
    cfg = get_settings()
    opts = {
        "connector": "jdbc",
        "url": cfg.jdbc_url,
        "table-name": table,
        "username": cfg.postgres_user,
        "password": cfg.postgres_password,
        "driver": "org.postgresql.Driver",
    }
    if sink:
        opts["sink.buffer-flush.max-rows"] = "200"
        opts["sink.buffer-flush.interval"] = "2s"   # keep dashboards fresh
        opts["sink.max-retries"] = "3"
    if lookup:
        opts["lookup.cache"] = "PARTIAL"
        opts["lookup.partial-cache.max-rows"] = "100"
        opts["lookup.partial-cache.expire-after-write"] = "60s"
    return _with(opts)


def create_table(name: str, columns_sql: str, with_body: str) -> str:
    return f"CREATE TABLE {name} (\n{columns_sql}\n) WITH (\n  {with_body}\n)"


def create_table_env(job_name: str, parallelism: int = 1, checkpoint_ms: int = 30_000):
    from pyflink.datastream import StreamExecutionEnvironment
    from pyflink.table import EnvironmentSettings, StreamTableEnvironment

    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(parallelism)
    env.enable_checkpointing(checkpoint_ms)
    t_env = StreamTableEnvironment.create(env, environment_settings=EnvironmentSettings.in_streaming_mode())
    conf = t_env.get_config()
    conf.set("pipeline.name", job_name)
    conf.set("table.local-time-zone", "UTC")
    conf.set("table.exec.source.idle-timeout", "30 s")   # idle partitions must not stall watermarks
    conf.set("table.exec.state.ttl", "2 h")              # bound de-duplication state
    return t_env


def run_job(job_name: str, ddl: list[str], inserts: list[str]) -> None:
    """Create tables and submit all INSERTs as one Flink job.

    Submitted with `flink run -d` the call returns once the job is accepted. For local debugging
    set FLINK_JOB_WAIT=true to block on the job.
    """
    t_env = create_table_env(job_name)
    for statement in ddl:
        t_env.execute_sql(statement)
    stmt_set = t_env.create_statement_set()
    for statement in inserts:
        stmt_set.add_insert_sql(statement)
    result = stmt_set.execute()
    if os.getenv("FLINK_JOB_WAIT", "").lower() in ("1", "true", "yes"):
        result.wait()
