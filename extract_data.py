"""Self-contained Hive / Presto extraction (no dependency on the didi99 package).

Requires: pip install python-dotenv pandas "pyhive[hive_pure_sasl]==0.7.0" "sqlalchemy>=1.4.24,<1.5"
Credentials come from the .env file next to this script.
"""
import os
import warnings

import pandas as pd
import sqlalchemy as sa
from dotenv import load_dotenv
from pyhive import hive

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

USERNAME = os.environ["BIGDATA_USER"]
PASSWORD = os.environ["BIGDATA_PASSWORD"]

# Connection settings come from .env; the rest is copied from didi99/bigdata/config.yaml
HIVE = {
    "host": os.environ["BIGDATA_HOST"],
    "port": int(os.environ["BIGDATA_PORT"]),
    "auth": "CUSTOM",
    "configuration": {
        "mapred.job.name": "didi99_app",
        "mapred.job.queue.name": os.environ["BIGDATA_QUEUE"],
        "hive.auto.convert.join.noconditionaltask": "false",
        "hive.groupby.orderby.position.alias": "true",
        "hive.exec.dynamic.partition.mode": "nonstrict",
        "hive.mapred.mode": "nonstrict",
    },
}

PRESTO = {
    "host": os.environ["BIGDATA_HOST"],
    "port": os.environ["BIGDATA_PORT"],
    "catalog": "hive",
    "configuration": {
        "session_props": {
            "query_max_run_time": "30m",
            "query_max_execution_time": "30m",
        }
    },
}


def query_hive(sql: str) -> pd.DataFrame:
    conn = hive.connect(username=USERNAME, password=PASSWORD, **HIVE)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return pd.read_sql(sql, conn)
    finally:
        conn.close()


def query_presto(sql: str) -> pd.DataFrame:
    # Note: DiDi's Presto URL uses '#' (not ':') between user and password.
    url = f"presto://{USERNAME}#{PASSWORD}@{PRESTO['host']}:{PRESTO['port']}/{PRESTO['catalog']}"
    engine = sa.create_engine(url, connect_args=PRESTO["configuration"])
    with engine.connect() as conn:
        result = conn.execute(sa.text(sql))
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


if __name__ == "__main__":
    print(query_hive("SHOW DATABASES").head())
    print(query_presto("SHOW SCHEMAS").head())
