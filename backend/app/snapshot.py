"""Runs the driver query once (Hive) and caches the result as parquet.

drivers.sql is written in Hive dialect (date_sub on strings, percentile_approx, <=>),
so Presto is not supported for this query.
"""
import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .presto import query_hive

DATA_DIR = Path(os.getenv("DATA_DIR") or Path(__file__).resolve().parents[1] / "data")
SQL_FILE = Path(__file__).parent / "sql" / "drivers.sql"
PARQUET = DATA_DIR / "drivers.parquet"
META = DATA_DIR / "meta.json"
ENGINE = "hive"


def _replace_nullif(sql: str) -> str:
    """This Hive has no NULLIF: NULLIF(a, 0) -> (CASE WHEN (a) = 0 THEN NULL ELSE (a) END)."""
    while True:
        i = sql.rfind("NULLIF(")  # last occurrence first, so nesting resolves
        if i < 0:
            return sql
        j = i + len("NULLIF(")
        depth, k = 1, j
        while depth:
            depth += {"(": 1, ")": -1}.get(sql[k], 0)
            k += 1
        a = sql[j:k - 1].rsplit(",", 1)[0].strip()
        sql = sql[:i] + f"(CASE WHEN ({a}) = 0 THEN NULL ELSE ({a}) END)" + sql[k:]


def render_sql(run_date: date) -> str:
    """28 full days: run_date-28 .. run_date-1. Dim tables use today-2 (inside the SQL)."""
    sql = SQL_FILE.read_text(encoding="utf-8")
    sql = sql.replace("${run_date}", run_date.strftime("%Y-%m-%d"))
    sql = sql.strip().rstrip(";")  # HiveServer2 rejects a trailing semicolon
    return _replace_nullif(sql)


def refresh(run_date: date | None = None) -> dict:
    run_date = run_date or date.today() - timedelta(days=1)
    t0 = time.perf_counter()
    print(f"[snapshot] running drivers.sql on hive for run_date={run_date} ...", flush=True)
    df = query_hive(render_sql(run_date))
    print(f"[snapshot] got {len(df)} rows in {time.perf_counter() - t0:.1f}s", flush=True)
    DATA_DIR.mkdir(exist_ok=True)
    df.to_parquet(PARQUET, index=False)
    meta = {
        "run_date": run_date.isoformat(),
        "rows": int(len(df)),
        "engine": ENGINE,
        "seconds": round(time.perf_counter() - t0, 1),
        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
    }
    META.write_text(json.dumps(meta), encoding="utf-8")
    return meta


_NA = ["null", "NULL", "None", ""]
_TEXT_COLS = ["country_code", "city_name", "vehicle_type", "seg_supply_hours", "seg_ipt", "seg_incentive",
              "seg_shor", "segment", "vehicle_category", "two_level_biz_en"]


def ingest_csv(csv_path: Path, filename: str) -> dict:
    """Turn the CSV that the driver query produces into the snapshot the dashboard reads
    (parquet + meta.json). Streams from disk, so a 400 MB / 1.5M-driver file is fine.

    Raises ValueError with a readable message when the file is not the driver query output."""
    import csv as _csv
    import os

    from .impact import SNAPSHOT_COLUMNS

    t0 = time.perf_counter()
    with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
        head = f.readline()
    try:
        sep = _csv.Sniffer().sniff(head, delimiters=",;	|").delimiter
    except _csv.Error:
        sep = ","
    names = [c.strip().lower() for c in pd.read_csv(csv_path, sep=sep, nrows=0, encoding="utf-8-sig").columns]
    required = [c for c in SNAPSHOT_COLUMNS if c not in ("ipt", "ipt_usd")]
    missing = [c for c in required if c not in names]
    if "ipt" not in names and "ipt_usd" not in names:
        missing.append("ipt")
    if missing:
        raise ValueError(
            "This does not look like the driver query output. Missing columns: "
            f"{missing}. Columns received: {names[:20]}")

    df = pd.read_csv(csv_path, sep=sep, encoding="utf-8-sig", dtype={"driver_id": str},
                     na_values=_NA, keep_default_na=False)
    df.columns = [c.strip().lower() for c in df.columns]
    if df.empty:
        raise ValueError("The CSV has no rows.")
    for c in _TEXT_COLS:
        if c in df.columns:
            df[c] = df[c].astype("string")

    DATA_DIR.mkdir(exist_ok=True)
    tmp = PARQUET.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, PARQUET)  # atomic: readers never see a half-written file
    meta = {
        "run_date": filename,
        "rows": int(len(df)),
        "engine": "csv",
        "seconds": round(time.perf_counter() - t0, 1),
        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
    }
    META.write_text(json.dumps(meta), encoding="utf-8")
    return meta


def load(columns: list[str] | None = None) -> pd.DataFrame:
    if not PARQUET.exists():
        raise FileNotFoundError("No snapshot yet. POST /snapshot/refresh first.")
    if columns is not None:  # optional columns (e.g. ipt_usd) may not exist in every snapshot
        import pyarrow.parquet as pq
        have = set(pq.ParquetFile(PARQUET).schema_arrow.names)
        columns = [c for c in columns if c in have]
    return pd.read_parquet(PARQUET, columns=columns)


def meta() -> dict:
    return json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}


if __name__ == "__main__":
    print(refresh())
