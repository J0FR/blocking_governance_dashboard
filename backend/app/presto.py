"""Presto connection. Credentials/hosts come from the project's .env file."""
import os
from pathlib import Path

import warnings

import pandas as pd
import sqlalchemy as sa
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def query_presto(sql: str) -> pd.DataFrame:
    user = os.environ["BIGDATA_USER"]
    password = os.environ["BIGDATA_PASSWORD"]
    host = os.environ["PRESTO_HOST"]
    port = os.environ["PRESTO_PORT"]
    # DiDi's Presto URL uses '#' (not ':') between user and password.
    url = f"presto://{user}#{password}@{host}:{port}/hive"
    engine = sa.create_engine(
        url,
        connect_args={
            "session_props": {
                "query_max_run_time": "30m",
                "query_max_execution_time": "30m",
            }
        },
    )
    with engine.connect() as conn:
        result = conn.execute(sa.text(sql))
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


def query_hive(sql: str) -> pd.DataFrame:
    from pyhive import hive

    conn = hive.connect(
        host=os.environ["BIGDATA_HOST"],
        port=int(os.environ["BIGDATA_PORT"]),
        username=os.environ["BIGDATA_USER"],
        password=os.environ["BIGDATA_PASSWORD"],
        auth="CUSTOM",
        configuration={
            "mapred.job.name": "blocking_governance",
            "mapred.job.queue.name": os.environ["BIGDATA_QUEUE"],
            "hive.auto.convert.join.noconditionaltask": "false",
            "hive.exec.dynamic.partition.mode": "nonstrict",
            "hive.mapred.mode": "nonstrict",
        },
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return pd.read_sql(sql, conn)
    finally:
        conn.close()
