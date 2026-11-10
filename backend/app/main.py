import csv
import io
import json
import shutil
import threading
from datetime import date

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from . import block_impact as bi
from . import impact, snapshot

app = FastAPI(title="Block Support API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

BLOCKLIST_CSV = snapshot.DATA_DIR / "blocklist.csv"
BLOCKLIST_REPORT = snapshot.DATA_DIR / "blocklist_report.json"

_lock = threading.Lock()
_base_cache: dict = {"mtime": None, "df": None, "stats": None}
_run_cache: dict = {}  # (parquet mtime, blocklist mtime, horizon) -> {d, blocked, match, analysis}
_RUN_CACHE_MAX = 4


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _mtime(p) -> float | None:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return None


def _base_key():
    """Cache key of the base: the snapshot file and the FX table (editing either rebuilds it)."""
    p = _mtime(snapshot.PARQUET)
    return None if p is None else (p, _mtime(impact.FX_FILE))


def _base() -> tuple[pd.DataFrame, dict]:
    """Snapshot with per-driver metrics + whole-base statistics, cached until the parquet changes."""
    mtime = _base_key()
    if mtime is None:
        raise HTTPException(409, "There is no snapshot yet. Run the data refresh first.")
    with _lock:
        if _base_cache["mtime"] != mtime:
            raw = snapshot.load(columns=impact.SNAPSHOT_COLUMNS)
            _base_cache["df"] = impact.with_driver_metrics(raw)
            del raw
            _base_cache["stats"] = impact.base_stats(_base_cache["df"])
            _base_cache["mtime"] = mtime
            _run_cache.clear()
        return _base_cache["df"], _base_cache["stats"]


def _blocks() -> pd.DataFrame | None:
    if not BLOCKLIST_CSV.exists():
        return None
    return pd.read_csv(BLOCKLIST_CSV, dtype={"driver_id": str})


def _run(horizon_days: int) -> dict:
    """Blocked drivers + losses for a horizon. Cached: paging, sorting and searching the
    drivers table must not recompute the whole base (it can have 100k+ drivers)."""
    base, stats = _base()
    key = (_base_cache["mtime"], _mtime(BLOCKLIST_CSV), horizon_days)
    with _lock:
        hit = _run_cache.get(key)
    if hit:
        return hit
    blk, match = impact.attach_blocks(base, _blocks(), horizon_days)
    run = {"blocked": blk, "stats": stats, "match": match, "analysis": None, "horizon": horizon_days}
    with _lock:
        if len(_run_cache) >= _RUN_CACHE_MAX:
            _run_cache.pop(next(iter(_run_cache)))
        _run_cache[key] = run
    return run


def _clean(df: pd.DataFrame) -> list[dict]:
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.astype(object).where(df.notna(), None)
    return df.to_dict("records")


def _saved_report() -> dict | None:
    return json.loads(BLOCKLIST_REPORT.read_text(encoding="utf-8")) if BLOCKLIST_REPORT.exists() else None


def _read_csv(content: bytes) -> pd.DataFrame:
    """Fast CSV read: sniff the delimiter on the header line only (the python engine's
    auto-detection is slow on 100k+ rows)."""
    text = content.decode("utf-8-sig", errors="replace")
    head = text.split("\n", 1)[0]
    try:
        sep = csv.Sniffer().sniff(head, delimiters=",;\t|").delimiter
    except csv.Error:
        sep = ","
    return pd.read_csv(io.StringIO(text), dtype=str, sep=sep)


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------
@app.post("/snapshot/refresh")
def refresh(run_date: date | None = None):
    try:
        return snapshot.refresh(run_date)
    except Exception as e:  # surface Hive errors (connection, permissions) to the UI
        raise HTTPException(502, f"Hive error: {str(e)[:600]}")


@app.post("/snapshot/upload")
def upload_snapshot(file: UploadFile = File(...)):
    """Replace the driver base with the CSV the driver query produced (plain `def`: runs in a worker
    thread and streams the file to disk, so a very large upload does not block the API)."""
    snapshot.DATA_DIR.mkdir(exist_ok=True)
    tmp = snapshot.DATA_DIR / "_upload.csv"
    try:
        with open(tmp, "wb") as out:
            shutil.copyfileobj(file.file, out, 1024 * 1024)
        try:
            meta_ = snapshot.ingest_csv(tmp, file.filename or "upload.csv")
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(400, f"Could not read the CSV: {e}")
    finally:
        tmp.unlink(missing_ok=True)
    # the saved block list was matched against the previous base: match it again with the new one
    blocks = _blocks()
    if blocks is not None:
        try:
            _, match = impact.attach_blocks(_base()[0], blocks, impact.HORIZON_DAYS)
            rep = _saved_report() or {}
            rep.update(match)
            BLOCKLIST_REPORT.write_text(json.dumps(rep), encoding="utf-8")
        except Exception:
            pass
    return meta_


@app.get("/meta")
def meta():
    m = snapshot.meta()
    return {"snapshot": m or None, "driver_window": bi.query_windows()["drivers"], "horizon_days": impact.HORIZON_DAYS,
            "permanent_hours": impact.PERMANENT_HOURS, "ticket_cost_usd": impact.TICKET_COST_USD,
            "fx_local_per_usd": impact.load_fx(), "blocklist": _saved_report()}


# ---------------------------------------------------------------------------
# blocklist
# ---------------------------------------------------------------------------
@app.post("/blocklist")
def upload_blocklist(file: UploadFile = File(...)):
    """CSV with driver_id and block hours (9999 = permanent).

    Plain `def` on purpose: FastAPI runs it in a worker thread, so parsing a big file never
    blocks the event loop (and therefore every other request, e.g. /datasets or /meta)."""
    content = file.file.read()
    try:
        raw = _read_csv(content)
    except Exception as e:
        raise HTTPException(400, f"Could not read the CSV: {e}")
    try:
        blocks, report = impact.parse_blocklist(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if blocks.empty:
        raise HTTPException(400, "The CSV has no valid rows (it needs a driver_id and hours > 0).")

    snapshot.DATA_DIR.mkdir(exist_ok=True)
    blocks.to_csv(BLOCKLIST_CSV, index=False)
    report["filename"] = file.filename
    try:  # match against the snapshot if there is one
        _, match = impact.attach_blocks(_base()[0], blocks, impact.HORIZON_DAYS)
        report.update(match)
    except HTTPException:
        report["snapshot_missing"] = True
    BLOCKLIST_REPORT.write_text(json.dumps(report), encoding="utf-8")
    return report


@app.delete("/blocklist")
def clear_blocklist():
    for p in (BLOCKLIST_CSV, BLOCKLIST_REPORT):
        p.unlink(missing_ok=True)
    return {"ok": True}


# ---------------------------------------------------------------------------
# analysis (everything except the driver rows; small payload whatever the base size)
# ---------------------------------------------------------------------------
@app.get("/analysis")
def analysis(horizon_days: int = Query(impact.HORIZON_DAYS, ge=1, le=730)):
    run = _run(horizon_days)
    if run["analysis"] is None:
        blk, stats = run["blocked"], run["stats"]
        cities = impact.city_table(blk, stats)
        run["analysis"] = {
            "match": run["match"],
            "summary": impact.summary(blk, cities, stats, horizon_days),
            "countries": _clean(impact.country_table(cities)),
            # only cities with at least one blocked driver (country totals above use all cities)
            "cities": _clean(cities[cities["blocked_drivers"] > 0]),
            "durations": _clean(impact.duration_table(blk)),
            "profile": {dim: _clean(impact.profile(blk, dim, stats)) for dim in impact.PROFILE_DIMS},
        }
    return run["analysis"]


_DRIVER_COLS = [
    "driver_id", "country_code", "city_id", "city_name", "vehicle_type", "segment", "block_kind", "block_hours",
    "trips_week", "tsh_week", "gmv_week", "net_week", "ipt_eff", "lost_trips", "lost_tsh", "lost_gmv",
    "cx_cost_avoided", "lost_net", "tickets", "compensated_usd", "occupancy_rate", "available_trips",
]
_SORTABLE = {"driver_id", "city_name", "block_hours", "trips_week", "tsh_week", "gmv_week", "net_week",
             "lost_trips", "lost_tsh", "lost_gmv", "cx_cost_avoided", "lost_net", "tickets"}


def _driver_view(blocked: pd.DataFrame, search: str, country: str | None, city_id: str | None, kind: str | None):
    d = blocked
    if country:
        d = d[d["country_code"] == country]
    if city_id is not None and city_id != "":
        d = d[d["city_id"].isna()] if city_id == "NA" else d[d["city_id"].astype(str) == city_id]
    if kind in ("temporary", "permanent"):
        d = d[d["block_kind"] == kind]
    if search:
        q = search.lower()
        d = d[d["driver_id"].str.lower().str.contains(q, regex=False)
              | d["city_name"].astype(str).str.lower().str.contains(q, regex=False)
              | d["city_id"].astype(str).str.contains(q, regex=False)]
    return d


@app.get("/drivers")
def drivers(horizon_days: int = Query(impact.HORIZON_DAYS, ge=1, le=730), search: str = "",
            country: str | None = None, city_id: str | None = None, kind: str | None = None,
            sort_by: str = "lost_net", sort_dir: str = "desc",
            page: int = Query(0, ge=0), page_size: int = Query(50, ge=1, le=200)):
    if sort_by not in _SORTABLE:
        raise HTTPException(400, f"Cannot sort by {sort_by}")
    d = _driver_view(_run(horizon_days)["blocked"], search, country, city_id, kind)
    total = len(d)
    start = page * page_size
    if start >= total and page > 0:
        start = 0
    # nlargest/nsmallest on the page window avoids a full sort of up to 100k rows
    asc = sort_dir == "asc"
    need = start + page_size
    if sort_by in ("driver_id", "city_name"):
        d = d.sort_values(sort_by, ascending=asc)
    else:
        d = d.nsmallest(need, sort_by) if asc else d.nlargest(need, sort_by)
    return {"total": int(total), "rows": _clean(d.iloc[start:start + page_size][_DRIVER_COLS])}


@app.get("/export/drivers.csv")
def export(horizon_days: int = Query(impact.HORIZON_DAYS, ge=1, le=730), country: str | None = None,
           city_id: str | None = None, kind: str | None = None):
    d = _driver_view(_run(horizon_days)["blocked"], "", country, city_id, kind).sort_values("lost_net", ascending=False)
    return Response(d[_DRIVER_COLS].to_csv(index=False), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=blocked_drivers.csv"})


# ---------------------------------------------------------------------------
# Block impact + retention (output of the two Hive queries, uploaded as CSV)
# ---------------------------------------------------------------------------
_DATASETS = {
    "impact": {"prep": bi.prepare_impact, "weekcol": "week", "label": "block impact"},
    "retention": {"prep": bi.prepare_retention, "weekcol": "week", "label": "retention"},
}
_ds_cache: dict = {}


def _ds_paths(kind: str):
    return snapshot.DATA_DIR / f"{kind}.parquet", snapshot.DATA_DIR / f"{kind}_meta.json"


def _ds_kind(kind: str) -> str:
    if kind not in _DATASETS:
        raise HTTPException(404, f"Unknown dataset '{kind}' (use impact or retention)")
    return kind


def _ds_meta(kind: str) -> dict | None:
    _, m = _ds_paths(kind)
    return json.loads(m.read_text(encoding="utf-8")) if m.exists() else None


def _ds_load(kind: str) -> pd.DataFrame:
    pq, _ = _ds_paths(kind)
    mt = _mtime(pq)
    if mt is None:
        raise HTTPException(409, f"No {_DATASETS[kind]['label']} data uploaded yet.")
    with _lock:
        hit = _ds_cache.get(kind)
        if hit and hit[0] == mt:
            return hit[1]
    df = pd.read_parquet(pq)
    with _lock:
        _ds_cache[kind] = (mt, df)
    return df


@app.get("/datasets")
def datasets():
    return {"impact": _ds_meta("impact"), "retention": _ds_meta("retention"), "windows": bi.query_windows()}


@app.get("/queries/{kind}")
def query_text(kind: str):
    """SQL of the impact / retention query with today's dates applied (for the Copy query button)."""
    if kind not in bi.QUERY_FILES:
        raise HTTPException(404, f"Unknown query '{kind}' (use impact or retention)")
    return bi.render_query(kind)


@app.post("/datasets/{kind}")
def upload_dataset(kind: str, file: UploadFile = File(...)):
    # Plain `def` (worker thread): a large CSV must not block the event loop.
    kind = _ds_kind(kind)
    content = file.file.read()
    try:
        raw = bi.read_csv_bytes(content)
        df = _DATASETS[kind]["prep"](raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Could not read the CSV: {e}")
    if df.empty:
        raise HTTPException(400, "The CSV has no rows.")
    pq, mp = _ds_paths(kind)
    snapshot.DATA_DIR.mkdir(exist_ok=True)
    df.to_parquet(pq, index=False)
    weeks = sorted(df["week"].unique())
    meta_ = {"filename": file.filename, "rows": int(len(df)), "weeks": len(weeks),
             "first_week": weeks[0], "last_week": weeks[-1],
             "countries": sorted(df["country_code"].unique().tolist()),
             "uploaded_at": pd.Timestamp.now().isoformat(timespec="seconds")}
    mp.write_text(json.dumps(meta_), encoding="utf-8")
    return meta_


@app.delete("/datasets/{kind}")
def delete_dataset(kind: str):
    for p in _ds_paths(_ds_kind(kind)):
        p.unlink(missing_ok=True)
    _ds_cache.pop(kind, None)
    return {"ok": True}


@app.get("/block-impact")
def block_impact(kind: str | None = None, group: str | None = None,
                 breakdown: str = "block_duration_type"):
    if kind not in (None, "", "temporary", "permanent"):
        raise HTTPException(400, "kind must be temporary or permanent")
    return _clean_obj(bi.impact_summary(_ds_load("impact"), kind, group, breakdown))


@app.get("/block-impact/by-rule")
def block_impact_by_rule(level: str = "category_four_name"):
    return _clean_obj(bi.impact_by_rule(_ds_load("impact"), level))


@app.get("/retention")
def retention(base: str = "general", group: str | None = None, category: str | None = None):
    return _clean_obj(bi.retention_summary(_ds_load("retention"), base, group, category))


@app.get("/retention/by-measure")
def retention_by_measure(country: str | None = None, measure: str | None = None):
    try:
        return _clean_obj(bi.retention_by_measure(_ds_load("retention"), country, measure))
    except ValueError as e:
        raise HTTPException(400, str(e))


def _clean_obj(o):
    """JSON-safe: NaN/inf -> None, numpy scalars -> python."""
    if isinstance(o, dict):
        return {str(k): _clean_obj(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean_obj(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if (np.isnan(o) or np.isinf(o)) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if o is pd.NA:
        return None
    return o
