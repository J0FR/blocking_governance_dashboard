"""Impact of blocking drivers: per driver, per city, per block type, and city absorption.

All inputs come from the 28-day driver snapshot, so rates are per *calendar* hour:
    trips_per_hour = finished_orders / (28 * 24)
Using calendar hours (not online hours) avoids overstating the loss of a driver who is
only online a few hours a day: blocking him for 24 h loses what he would do in 24 h of
real time, i.e. his average output per calendar hour.

Block types (from the uploaded CSV):
    block_hours >= 9999  -> permanent: loss is projected over `horizon_days`
    otherwise            -> temporary: loss = rate x block_hours
GMV = lost trips x the driver's own IPT.

Economic loss (net) = lost GMV - CX cost the platform no longer pays for that driver:
    CX cost = compensations paid (USD) + tickets x TICKET_COST_USD
Both come from the same 28-day window, so they are converted to a per-calendar-hour
rate and multiplied by the blocked hours, exactly like trips.

Scale: the base can have 1M+ drivers while a block list is a small subset. Everything
that depends on the whole base (city totals, spare capacity, segment sizes) is computed
ONCE per snapshot in `base_stats`; per request we only touch the blocked rows.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

SNAPSHOT_DAYS = 28
WEEKS = SNAPSHOT_DAYS / 7
HOURS_SNAPSHOT = SNAPSHOT_DAYS * 24
PERMANENT_HOURS = 9999
HORIZON_DAYS = 180
TICKET_COST_USD = 0.69  # cost of answering one CX ticket
GREEN_COVERAGE = 1.2  # >= 120% of lost trips can be absorbed -> green

# (label, upper bound in hours, inclusive) for temporary blocks
DURATION_BUCKETS = [
    ("≤ 24 h", 24),
    ("1–3 days", 72),
    ("3–7 days", 168),
    ("7–30 days", 720),
    ("> 30 days", float("inf")),
]

PROFILE_DIMS = ["block_kind", "country_code", "vehicle_type", "seg_supply_hours",
                "seg_ipt", "seg_incentive", "seg_shor"]
_BASE_DIMS = [d for d in PROFILE_DIMS if d != "block_kind"]

# Only these snapshot columns are used; loading just them halves memory on big bases.
SNAPSHOT_COLUMNS = [
    "driver_id", "country_code", "city_id", "city_name", "vehicle_type", "segment",
    "seg_supply_hours", "seg_ipt", "seg_incentive", "seg_shor",
    "finished_orders", "supply_hours", "ipt", "ipt_usd", "avg_trip_minutes", "available_trips", "available_tsh",
    "occupancy_rate", "tickets", "compensated_usd",
]
_CATEGORICAL = ["country_code", "city_name", "vehicle_type", "segment",
                "seg_supply_hours", "seg_ipt", "seg_incentive", "seg_shor"]

FX_FILE = Path(__file__).parent / "fx_rates.json"


def load_fx() -> dict:
    """Local-currency units per USD by country. Countries not listed are already in USD."""
    try:
        return {k: float(v) for k, v in json.loads(FX_FILE.read_text(encoding="utf-8"))["local_per_usd"].items()}
    except (OSError, ValueError, KeyError):
        return {}


_ID_ALIASES = {"driver_id", "driverid", "id", "driver", "conductor", "id_conductor", "id_driver"}
_HOURS_ALIASES = {"block_hours", "horas_bloqueo", "horas_de_bloqueo", "horas", "hours",
                  "blocked_hours", "block_hrs", "hrs", "horas_bloqueado", "block_time"}


# ---------------------------------------------------------------------------
# Blocklist parsing
# ---------------------------------------------------------------------------
def _norm_col(c: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_")


def parse_blocklist(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Normalise an uploaded CSV. Returns (clean blocks, report).

    clean has columns: driver_id (str), block_hours (float), block_kind.
    Raises ValueError when the needed columns are missing.
    """
    cols = {_norm_col(c): c for c in raw.columns}
    id_col = next((cols[c] for c in cols if c in _ID_ALIASES), None)
    h_col = next((cols[c] for c in cols if c in _HOURS_ALIASES), None)
    if id_col is None or h_col is None:
        raise ValueError(
            "The CSV needs a driver_id column and a block-hours column (block_hours). "
            f"Columns received: {list(raw.columns)}")

    df = pd.DataFrame({
        "driver_id": raw[id_col].astype(str).str.strip().str.replace(r"\.0+$", "", regex=True),
        "block_hours": pd.to_numeric(raw[h_col].astype(str).str.strip().str.replace(",", "", regex=False),
                                     errors="coerce"),
    })
    rows_in = len(df)
    bad = df[(df["driver_id"].isin(["", "nan", "None"])) | df["block_hours"].isna() | (df["block_hours"] <= 0)]
    df = df.drop(bad.index)

    dup = int(df.duplicated("driver_id", keep=False).sum())
    # A driver listed twice keeps the longest block (permanent wins)
    df = df.groupby("driver_id", as_index=False)["block_hours"].max()
    df["block_kind"] = np.where(df["block_hours"] >= PERMANENT_HOURS, "permanent", "temporary")

    report = {
        "rows_in": int(rows_in),
        "rows_invalid": int(len(bad)),
        "invalid_sample": bad["driver_id"].head(10).tolist(),
        "duplicate_rows": dup,
        "count": int(len(df)),
        "temporary": int((df["block_kind"] == "temporary").sum()),
        "permanent": int((df["block_kind"] == "permanent").sum()),
    }
    return df, report


# ---------------------------------------------------------------------------
# Per-driver metrics (whole base) and one-off base statistics
# ---------------------------------------------------------------------------
def with_driver_metrics(df: pd.DataFrame) -> pd.DataFrame:
    d = df[[c for c in SNAPSHOT_COLUMNS if c in df.columns]].copy()
    d["driver_id"] = d["driver_id"].astype(str)
    city = pd.to_numeric(d["city_id"], errors="coerce")
    d["city_key"] = city.fillna(-1).astype("int64")  # -1 = no city (cheap, NA-safe group key)
    d["city_id"] = city.astype("Int64")
    d["city_name"] = d["city_name"].astype(object).where(d["city_name"].notna(), "No city")
    d["tickets"] = pd.to_numeric(d["tickets"], errors="coerce").fillna(0)
    d["compensated_usd"] = pd.to_numeric(d["compensated_usd"], errors="coerce").fillna(0.0)
    d["trips_week"] = d["finished_orders"] / WEEKS
    d["tsh_week"] = d["supply_hours"] / WEEKS
    d["trips_hour"] = d["finished_orders"] / HOURS_SNAPSHOT
    d["tsh_hour"] = d["supply_hours"] / HOURS_SNAPSHOT

    # IPT in USD. The Hive export has it in LOCAL currency (compensations are already USD), so
    # convert with fx_rates.json unless the snapshot already carries an `ipt_usd` column.
    if "ipt_usd" in d.columns:
        ipt = pd.to_numeric(d["ipt_usd"], errors="coerce")
    else:
        fx = load_fx()
        rate = d["country_code"].astype(object).map(fx).fillna(1.0)
        ipt = pd.to_numeric(d["ipt"], errors="coerce") / rate
    ipt = ipt.where(ipt > 0)
    # IPT used for GMV: own IPT; fallback = median of country x vehicle, then global median
    med_cv = ipt.groupby([d["country_code"].astype(object), d["vehicle_type"].astype(object)]).transform("median")
    d["ipt_eff"] = ipt.fillna(med_cv).fillna(ipt.median()).fillna(0.0)

    d["gmv_week"] = d["trips_week"] * d["ipt_eff"]
    # CX cost of the driver (28 days): compensations + ticket handling
    d["cx_cost_28d"] = d["compensated_usd"] + d["tickets"] * TICKET_COST_USD
    d["cx_cost_hour"] = d["cx_cost_28d"] / HOURS_SNAPSHOT
    d["net_week"] = d["gmv_week"] - d["cx_cost_28d"] / WEEKS
    d["busy_hours_week"] = d["trips_week"] * d["avg_trip_minutes"].fillna(0) / 60.0
    for c in _CATEGORICAL:  # smaller in memory, faster group-bys
        if c in d.columns:
            d[c] = d[c].astype("category")
    d.drop(columns=[c for c in ("ipt", "ipt_usd", "cx_cost_28d") if c in d.columns], inplace=True)
    return d


def base_stats(d: pd.DataFrame) -> dict:
    """Everything that depends on the whole base but not on who is blocked. Computed once."""
    g = ["country_code", "city_key"]
    city = d.groupby(g, observed=True).agg(
        city_id=("city_id", "first"), city_name=("city_name", "first"),
        drivers=("driver_id", "count"),
        trips_week=("trips_week", "sum"), tsh_week=("tsh_week", "sum"),
        cap_trips_all=("available_trips", "sum"), cap_tsh_all=("available_tsh", "sum"),
    )
    city.index = city.index.set_levels(city.index.levels[0].astype(str), level=0)
    return {
        "total_drivers": int(len(d)),
        "total_trips_week": float(d["trips_week"].sum()),
        "city": city,
        "dim_counts": {dim: d.groupby(dim, observed=True, dropna=False).size() for dim in _BASE_DIMS},
    }


# ---------------------------------------------------------------------------
# Blocked drivers and their losses
# ---------------------------------------------------------------------------
def attach_blocks(d: pd.DataFrame, blocks: pd.DataFrame | None,
                  horizon_days: int = HORIZON_DAYS) -> tuple[pd.DataFrame, dict]:
    """Select the blocked drivers and compute losses over each driver's block duration.

    Returns (blk, match report) where blk has ONLY the blocked rows (+ block/loss columns).
    """
    report = {"matched": 0, "unmatched_count": 0, "unmatched_sample": [], "ambiguous_count": 0}
    if blocks is None or blocks.empty:
        empty = d.iloc[0:0].copy()
        empty["block_kind"] = pd.Series(dtype=object)
        for c in ("block_hours", "block_hours_eff", "lost_trips", "lost_tsh", "lost_gmv",
                  "cx_cost_avoided", "lost_net", "lost_busy_hours"):
            empty[c] = pd.Series(dtype=float)
        return empty, report

    b = blocks.set_index("driver_id")
    blk = d[d["driver_id"].isin(b.index)].copy()
    ids_matched = set(blk["driver_id"])
    report.update(
        matched=int(len(ids_matched)),
        unmatched_count=int(len(set(b.index) - ids_matched)),
        unmatched_sample=sorted(set(b.index) - ids_matched)[:20],
        ambiguous_count=int((blk.groupby("driver_id", observed=True).size() > 1).sum()),
    )

    blk["block_kind"] = blk["driver_id"].map(b["block_kind"])
    blk["block_hours"] = blk["driver_id"].map(b["block_hours"]).astype(float)
    perm = blk["block_kind"] == "permanent"
    # Permanent: whole horizon. Temporary: its own duration, never beyond the horizon.
    cap_h = horizon_days * 24.0
    blk["block_hours_eff"] = np.where(perm, cap_h, np.minimum(blk["block_hours"], cap_h))
    blk["lost_trips"] = blk["trips_hour"] * blk["block_hours_eff"]
    blk["lost_tsh"] = blk["tsh_hour"] * blk["block_hours_eff"]
    blk["lost_gmv"] = blk["lost_trips"] * blk["ipt_eff"]
    blk["cx_cost_avoided"] = blk["cx_cost_hour"] * blk["block_hours_eff"]
    blk["lost_net"] = blk["lost_gmv"] - blk["cx_cost_avoided"]
    blk["lost_busy_hours"] = blk["busy_hours_week"] / (7 * 24) * blk["block_hours_eff"]
    blk["block_kind"] = blk["block_kind"].astype(object)
    return blk, report


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------
def city_table(blk: pd.DataFrame, stats: dict) -> pd.DataFrame:
    """One row per city (every city of the base). Absorption compares the weekly output of the
    blocked drivers *while blocked* with the weekly spare capacity of the drivers who stay active."""
    g = ["country_code", "city_key"]
    b = blk.assign(country_code=blk["country_code"].astype(str))
    lost = b.groupby(g, observed=True).agg(
        blocked_drivers=("driver_id", "count"),
        lost_trips_week=("trips_week", "sum"), lost_tsh_week=("tsh_week", "sum"),
        lost_gmv_week=("gmv_week", "sum"), lost_busy_hours_week=("busy_hours_week", "sum"),
        lost_trips=("lost_trips", "sum"), lost_tsh=("lost_tsh", "sum"), lost_gmv=("lost_gmv", "sum"),
        lost_net=("lost_net", "sum"),
        blk_cap_trips=("available_trips", "sum"), blk_cap_tsh=("available_tsh", "sum"),
    )
    kinds = b.assign(_t=(b["block_kind"] == "temporary").astype(int),
                     _p=(b["block_kind"] == "permanent").astype(int)).groupby(g, observed=True).agg(
        blocked_temporary=("_t", "sum"), blocked_permanent=("_p", "sum"))

    out = stats["city"].join(lost, how="left").join(kinds, how="left").reset_index()
    fill0 = ["blocked_drivers", "blocked_temporary", "blocked_permanent", "lost_trips_week", "lost_tsh_week",
             "lost_gmv_week", "lost_busy_hours_week", "lost_trips", "lost_tsh", "lost_gmv", "lost_net",
             "blk_cap_trips", "blk_cap_tsh"]
    out[fill0] = out[fill0].fillna(0)
    # spare capacity of the drivers who stay active = whole city minus the blocked ones
    out["cap_trips_28d"] = out["cap_trips_all"] - out["blk_cap_trips"]
    out["cap_tsh_28d"] = out["cap_tsh_all"] - out["blk_cap_tsh"]
    out["city_id"] = out["city_id"].astype(object).where(out["city_key"] != -1, None)
    out = out.drop(columns=["city_key", "cap_trips_all", "cap_tsh_all", "blk_cap_trips", "blk_cap_tsh"])

    out["capacity_trips_week"] = out["cap_trips_28d"] / WEEKS
    out["capacity_tsh_week"] = out["cap_tsh_28d"] / WEEKS
    out["market_share_lost"] = np.where(out["trips_week"] > 0, out["lost_trips_week"] / out["trips_week"], 0.0)
    out["coverage"] = np.where(out["lost_trips_week"] > 0,
                               out["capacity_trips_week"] / out["lost_trips_week"], np.nan)
    out["headroom_trips_week"] = out["capacity_trips_week"] - out["lost_trips_week"]
    out["headroom_hours_week"] = out["capacity_tsh_week"] - out["lost_busy_hours_week"]
    out["status"] = np.select(
        [out["lost_trips_week"] <= 0, out["coverage"] < 1.0, out["coverage"] < GREEN_COVERAGE],
        ["none", "red", "yellow"], default="green")
    order = out["status"].map({"red": 0, "yellow": 1, "green": 2, "none": 3})
    out = (out.assign(_o=order, _g=-out["lost_net"]).sort_values(["_o", "_g"])
              .drop(columns=["_o", "_g"]).reset_index(drop=True))
    out["city_name"] = out["city_name"].astype(str)
    return out


def country_table(cities: pd.DataFrame) -> pd.DataFrame:
    """Roll the city table up to country; coverage/status recomputed on the country totals."""
    sums = ["drivers", "trips_week", "tsh_week", "blocked_drivers", "blocked_temporary", "blocked_permanent",
            "lost_trips_week", "lost_tsh_week", "lost_gmv_week", "lost_busy_hours_week",
            "lost_trips", "lost_tsh", "lost_gmv", "lost_net", "capacity_trips_week", "capacity_tsh_week"]
    out = cities.groupby("country_code", as_index=False)[sums].sum()
    out["cities_affected"] = out["country_code"].map(
        cities[cities["lost_trips_week"] > 0].groupby("country_code").size()).fillna(0).astype(int)
    out["market_share_lost"] = np.where(out["trips_week"] > 0, out["lost_trips_week"] / out["trips_week"], 0.0)
    out["coverage"] = np.where(out["lost_trips_week"] > 0,
                               out["capacity_trips_week"] / out["lost_trips_week"], np.nan)
    out["headroom_trips_week"] = out["capacity_trips_week"] - out["lost_trips_week"]
    out["status"] = np.select(
        [out["lost_trips_week"] <= 0, out["coverage"] < 1.0, out["coverage"] < GREEN_COVERAGE],
        ["none", "red", "yellow"], default="green")
    return out.sort_values("lost_net", ascending=False).reset_index(drop=True)


def _loss_cols(g) -> pd.Series:
    return pd.Series({
        "drivers": len(g),
        "lost_trips": g["lost_trips"].sum(),
        "lost_tsh": g["lost_tsh"].sum(),
        "lost_gmv": g["lost_gmv"].sum(),
        "lost_net": g["lost_net"].sum(),
    })


def summary(blk: pd.DataFrame, cities: pd.DataFrame, stats: dict, horizon_days: int = HORIZON_DAYS) -> dict:
    tot_trips = stats["total_trips_week"]

    def part(kind: str) -> dict:
        s = blk[blk["block_kind"] == kind]
        return {"drivers": int(len(s)), "lost_trips": float(s["lost_trips"].sum()),
                "lost_tsh": float(s["lost_tsh"].sum()), "lost_gmv": float(s["lost_gmv"].sum()),
                "lost_net": float(s["lost_net"].sum())}

    # How concentrated is the loss? Share of GMV loss from the top 1% / 10% of blocked drivers.
    gmv_sorted = np.sort(blk["lost_gmv"].to_numpy())[::-1]
    total_gmv = float(gmv_sorted.sum())

    def top_share(frac: float) -> float:
        if total_gmv <= 0 or not len(gmv_sorted):
            return 0.0
        k = max(1, int(np.ceil(len(gmv_sorted) * frac)))
        return float(gmv_sorted[:k].sum() / total_gmv)

    return {
        "ticket_cost_usd": TICKET_COST_USD,
        "lost_net": float(blk["lost_net"].sum()),
        "cx_cost_avoided": float(blk["cx_cost_avoided"].sum()),
        "lost_net_week": float(blk["net_week"].sum()),
        "top1_share_gmv": top_share(0.01),
        "top10_share_gmv": top_share(0.10),
        "horizon_days": horizon_days,
        "blocked_drivers": int(len(blk)),
        "total_drivers": stats["total_drivers"],
        "lost_trips": float(blk["lost_trips"].sum()),
        "lost_tsh": float(blk["lost_tsh"].sum()),
        "lost_gmv": float(blk["lost_gmv"].sum()),
        "lost_trips_week": float(blk["trips_week"].sum()),
        "lost_tsh_week": float(blk["tsh_week"].sum()),
        "lost_gmv_week": float(blk["gmv_week"].sum()),
        "market_share_lost": float(blk["trips_week"].sum() / tot_trips) if tot_trips else 0.0,
        "temporary": part("temporary"),
        "permanent": part("permanent"),
        "cities_affected": int((cities["lost_trips_week"] > 0).sum()),
        "cities_red": int((cities["status"] == "red").sum()),
        "cities_yellow": int((cities["status"] == "yellow").sum()),
        "cities_green": int((cities["status"] == "green").sum()),
    }


def duration_table(blk: pd.DataFrame) -> pd.DataFrame:
    """Losses by block duration: temporary buckets + permanent."""
    rows = []
    prev = 0.0
    for label, hi in DURATION_BUCKETS:
        s = blk[(blk["block_kind"] == "temporary") & (blk["block_hours"] > prev) & (blk["block_hours"] <= hi)]
        rows.append({"bucket": label, "kind": "temporary", **_loss_cols(s).to_dict()})
        prev = hi
    rows.append({"bucket": "Permanent", "kind": "permanent",
                 **_loss_cols(blk[blk["block_kind"] == "permanent"]).to_dict()})
    return pd.DataFrame(rows)


def profile(blk: pd.DataFrame, dim: str, stats: dict) -> pd.DataFrame:
    """Who is blocked: count and losses by a dimension, vs the whole driver base."""
    if dim not in PROFILE_DIMS:
        raise ValueError(f"unsupported dimension: {dim}")
    by = blk.groupby(dim, observed=True, dropna=False).agg(
        blocked=("driver_id", "count"),
        lost_trips=("lost_trips", "sum"), lost_tsh=("lost_tsh", "sum"), lost_gmv=("lost_gmv", "sum"),
        lost_net=("lost_net", "sum"),
        tickets=("tickets", "sum"), compensated_usd=("compensated_usd", "sum"),
        avg_ipt=("ipt_eff", "mean"), avg_trips_week=("trips_week", "mean"),
    ).reset_index()
    if dim == "block_kind":
        by["base_drivers"] = stats["total_drivers"]
    else:
        base = stats["dim_counts"][dim].rename("base_drivers").reset_index()
        by[dim] = by[dim].astype(object)
        base[dim] = base[dim].astype(object)
        by = by.merge(base, on=dim, how="left")
    by["share_of_blocked"] = by["blocked"] / max(len(blk), 1)
    by["blocked_rate"] = by["blocked"] / by["base_drivers"].where(by["base_drivers"] > 0)
    by = by.rename(columns={dim: "value"})
    by["value"] = by["value"].astype(object).where(by["value"].notna(), "No data")
    return by.sort_values("lost_net", ascending=False).reset_index(drop=True)
