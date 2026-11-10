"""Block impact + retention: summaries over the output of the two Hive queries.

The dashboard does not run these queries; it receives their result as CSV
(see queries.py for the exact date windows each query must be run with).

Impact query grain   : week x country x city x vehicle x cohort x block type x rule categories
Retention query grain: cohort week x country x city x rule categories x retention week (1..12)

Caveat that applies to every sum below: the query counts DISTINCT drivers at its own grain,
so summing over other dimensions (categories, cities, weeks) counts a driver once per cell,
not once overall. Figures are "driver-weeks / driver-cells", good for comparing groups and
trends but not a de-duplicated head count.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Country groups requested for the dashboard: MX, AR, CO and everything else in SSL.
FOCUS = ["MX", "AR", "CO"]
REST = "Rest of SSL"
TOTAL = "Total SSL"
GROUPS = FOCUS + [REST]
ALL_GROUPS = GROUPS + [TOTAL]

KIND_VALUES = {"temporary": "Temporary Blocked", "permanent": "Permanently Blocked"}

IMPACT_REQUIRED = ["year_calendar_week", "country_code", "block_duration_type", "total_impacted_drivers",
                   "active_impacted_drivers", "total_finished_trips", "total_supply_hours"]
IMPACT_OPTIONAL = ["city_id", "city_name", "vehicle_category", "market_place_cohort", "category_one_name",
                   "category_two_name", "category_three_name", "category_four_name",
                   "total_measures_applied", "total_measure_time_hours"]
IMPACT_NUMERIC = ["total_impacted_drivers", "active_impacted_drivers", "total_finished_trips",
                  "total_supply_hours", "total_measures_applied", "total_measure_time_hours"]
IMPACT_DIMS = {
    "block_duration_type": "Block type",
    "category_one_name": "Rule category 1",
    "category_two_name": "Rule category 2",
    "vehicle_category": "Vehicle",
    "market_place_cohort": "Marketplace cohort",
    "city_name": "City",
    "country_code": "Country",
}

RET_REQUIRED = ["iso_year_calendar_week", "country_code", "retention_order", "eligible_drivers_general",
                "returned_drivers_general", "eligible_drivers_active_14d", "returned_drivers_active_14d"]
RET_OPTIONAL = ["city_id", "city_name", "category_one_name", "category_two_name", "category_three_name",
                "category_four_name", "retention_window_days", "retention_window_weeks",
                "block_duration_type"]  # optional: enables the temporary/permanent filter
RET_NUMERIC = ["retention_order", "eligible_drivers_general", "returned_drivers_general",
               "eligible_drivers_active_14d", "returned_drivers_active_14d"]
RET_BASES = {"general": ("eligible_drivers_general", "returned_drivers_general"),
             "active_14d": ("eligible_drivers_active_14d", "returned_drivers_active_14d")}


# ---------------------------------------------------------------------------
# Date windows each query must be run with
# ---------------------------------------------------------------------------
def _last_sunday_on_or_before(d: date) -> date:
    return d - timedelta(days=(d.weekday() - 6) % 7)


def query_windows(today: date | None = None) -> dict:
    """data_end = today - 2 (last day with complete data).

    Impact   : the 12 most recent COMPLETE weeks (Monday..Sunday): ends on the latest Sunday
               <= data_end and starts 83 days earlier.
    Retention: same 12-week length, but the cohort must end at least 84 days before data_end so
               all 12 retention weeks are mature: ends on the latest Sunday <= data_end - 84.

    Example (today = Tue 2026-11-10): impact 2026-08-17..2026-11-08,
    retention 2026-05-25..2026-08-16 with data_end 2026-11-08.
    """
    today = today or date.today()
    data_end = today - timedelta(days=2)

    imp_end = _last_sunday_on_or_before(data_end)
    imp_start = imp_end - timedelta(days=83)

    ret_end = _last_sunday_on_or_before(data_end - timedelta(days=84))
    ret_start = ret_end - timedelta(days=83)
    # Driver base: the 28 days that END on data_end (period = run_date-28 .. run_date-1, so run_date = data_end+1)
    run_date = data_end + timedelta(days=1)
    return {
        "impact": {"start_date": imp_start.isoformat(), "end_date": imp_end.isoformat()},
        "retention": {"start_date": ret_start.isoformat(), "end_date": ret_end.isoformat(),
                      "data_end_date": data_end.isoformat()},
        "drivers": {"run_date": run_date.isoformat(),
                    "start_date": (run_date - timedelta(days=28)).isoformat(),
                    "end_date": (run_date - timedelta(days=1)).isoformat()},
    }


SQL_DIR = Path(__file__).parent / "sql"
QUERY_FILES = {"impact": "block_impact.sql", "retention": "retention.sql", "drivers": "drivers_query.sql"}
_SQL_VAR = re.compile(r"\$\{(\w+)\}")


def render_query(kind: str, today: date | None = None) -> dict:
    """The query text ready to run as is: every ${variable} is replaced by the real date for the day it is
    copied, so nothing needs to be set or injected on the other side."""
    if kind not in QUERY_FILES:
        raise KeyError(kind)
    dates = query_windows(today)[kind]
    sql = (SQL_DIR / QUERY_FILES[kind]).read_text(encoding="utf-8")
    sql = _SQL_VAR.sub(lambda m: dates.get(m.group(1), m.group(0)), sql)
    left = sorted(set(_SQL_VAR.findall(sql)))
    if left:
        raise ValueError(f"{QUERY_FILES[kind]}: no date for variable(s) {left}")
    return {"kind": kind, "sql": sql, "dates": dates}


# ---------------------------------------------------------------------------
# Reading / validating uploads
# ---------------------------------------------------------------------------
def read_csv_bytes(content: bytes) -> pd.DataFrame:
    text = content.decode("utf-8-sig", errors="replace")
    head = text.split("\n", 1)[0]
    try:
        sep = csv.Sniffer().sniff(head, delimiters=",;\t|").delimiter
    except csv.Error:
        sep = ","
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, na_values=["null", "NULL", "None", ""],
                     keep_default_na=False)
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def _prepare(df: pd.DataFrame, required: list[str], optional: list[str], numeric: list[str], what: str) -> pd.DataFrame:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"This does not look like the {what} query output. Missing columns: {missing}. "
                         f"Columns received: {list(df.columns)[:20]}")
    keep = [c for c in required + optional if c in df.columns]
    d = df[keep].copy()
    for c in numeric:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0.0)
    d["country_code"] = d["country_code"].astype(str).str.strip().str.upper()
    d["group"] = np.where(d["country_code"].isin(FOCUS), d["country_code"], REST)
    for c in keep:
        if c not in numeric and c not in ("group",):
            d[c] = d[c].astype("string")
    return d


def prepare_impact(df: pd.DataFrame) -> pd.DataFrame:
    d = _prepare(df, IMPACT_REQUIRED, IMPACT_OPTIONAL, IMPACT_NUMERIC, "block impact")
    for c in IMPACT_OPTIONAL:
        if c not in d.columns and c in IMPACT_DIMS:
            d[c] = "n/a"
    d["week"] = d["year_calendar_week"].astype(str)
    return d


def prepare_retention(df: pd.DataFrame) -> pd.DataFrame:
    d = _prepare(df, RET_REQUIRED, RET_OPTIONAL, RET_NUMERIC, "retention")
    d["retention_order"] = d["retention_order"].astype(int)
    if "category_one_name" not in d.columns:
        d["category_one_name"] = "n/a"
    d["week"] = d["iso_year_calendar_week"].astype(str)
    return d


# ---------------------------------------------------------------------------
# Impact summaries
# ---------------------------------------------------------------------------
def impact_summary(d: pd.DataFrame, kind: str | None, group: str | None, breakdown: str) -> dict:
    weeks = sorted(d["week"].unique())
    f = d
    if kind in KIND_VALUES:
        f = f[f["block_duration_type"] == KIND_VALUES[kind]]
    n_weeks = max(len(weeks), 1)

    metrics = {"drivers": "total_impacted_drivers", "active": "active_impacted_drivers",
               "trips": "total_finished_trips", "sh": "total_supply_hours"}

    # group x week
    gw = f.groupby(["group", "week"], observed=True)[list(metrics.values())].sum().reset_index()
    tot = f.groupby("week", observed=True)[list(metrics.values())].sum().reset_index().assign(group=TOTAL)
    gw = pd.concat([gw, tot], ignore_index=True)
    gw = gw.rename(columns={v: k for k, v in metrics.items()})
    weekly = (gw.set_index(["group", "week"]).reindex(
        pd.MultiIndex.from_product([ALL_GROUPS, weeks], names=["group", "week"])).fillna(0.0).reset_index())

    # table: weekly average + window total per group
    rows = []
    for g in ALL_GROUPS:
        s = weekly[weekly["group"] == g]
        drivers, active = s["drivers"].sum(), s["active"].sum()
        rows.append({
            "group": g,
            "drivers_avg": drivers / n_weeks, "active_avg": active / n_weeks,
            "trips_avg": s["trips"].sum() / n_weeks, "sh_avg": s["sh"].sum() / n_weeks,
            "trips_total": s["trips"].sum(), "sh_total": s["sh"].sum(),
            "active_share": float(active / drivers) if drivers else None,
            "trips_per_driver": float(s["trips"].sum() / drivers) if drivers else None,
        })

    # breakdown for the selected group
    if breakdown not in IMPACT_DIMS:
        breakdown = "block_duration_type"
    b = f if group in (None, "", TOTAL) else f[f["group"] == group]
    bd = b.groupby(breakdown, observed=True)[list(metrics.values())].sum().reset_index()
    bd = bd.rename(columns={**{v: k for k, v in metrics.items()}, breakdown: "value"})
    for k in metrics:
        bd[k + "_avg"] = bd[k] / n_weeks
    bd["active_share"] = np.where(bd["drivers"] > 0, bd["active"] / bd["drivers"].where(bd["drivers"] > 0), np.nan)
    bd["value"] = bd["value"].astype(object).where(bd["value"].notna(), "No data")
    bd = bd.sort_values("drivers", ascending=False).head(200)

    return {
        "weeks": weeks, "n_weeks": len(weeks),
        "weekly": weekly.replace([np.inf, -np.inf], np.nan).to_dict("records"),
        "table": rows,
        "breakdown_dim": breakdown,
        "breakdown": bd[["value", "drivers_avg", "active_avg", "trips_avg", "sh_avg", "active_share"]]
                        .replace([np.inf, -np.inf], np.nan).to_dict("records"),
        "breakdown_options": [{"key": k, "label": v} for k, v in IMPACT_DIMS.items()],
    }


# ---------------------------------------------------------------------------
# Retention summaries
# ---------------------------------------------------------------------------
def _rate(ret: pd.Series, elig: pd.Series) -> pd.Series:
    return ret / elig.where(elig > 0)


def retention_summary(d: pd.DataFrame, base: str, group: str | None, category: str | None) -> dict:
    elig_c, ret_c = RET_BASES.get(base, RET_BASES["general"])
    f = d if not category else d[d["category_one_name"] == category]

    def agg(frame: pd.DataFrame, by: list[str]) -> pd.DataFrame:
        a = frame.groupby(by + ["retention_order"], observed=True)[[elig_c, ret_c]].sum().reset_index()
        a["rate"] = _rate(a[ret_c], a[elig_c])
        return a.rename(columns={elig_c: "eligible", ret_c: "returned"})

    # curves: one line per group (+ total), across all cohort weeks
    curves = []
    ag = agg(f, ["group"])
    at = agg(f.assign(group=TOTAL), ["group"])
    for g, s in pd.concat([ag, at]).groupby("group"):
        curves.append({"group": g, "points": s.sort_values("retention_order")[
            ["retention_order", "eligible", "returned", "rate"]].to_dict("records")})

    sel = f if group in (None, "", TOTAL) else f[f["group"] == group]

    # cohort heatmap
    h = agg(sel, ["week"])
    heat = []
    for w, s in h.groupby("week"):
        heat.append({"week": w, "eligible": float(s["eligible"].max()),
                     "rates": {int(o): (None if pd.isna(r) else float(r)) for o, r in zip(s["retention_order"], s["rate"])}})
    heat.sort(key=lambda r: r["week"])

    # by rule category: retention at week 1 / 4 / 8 / 12
    cat = agg(sel, ["category_one_name"])
    cats = []
    for c, s in cat.groupby("category_one_name"):
        r = dict(zip(s["retention_order"], s["rate"]))
        cats.append({"category": c, "eligible": float(s["eligible"].max()),
                     **{f"w{k}": (None if pd.isna(r.get(k, np.nan)) else float(r[k])) for k in (1, 4, 8, 12)}})
    cats.sort(key=lambda r: -r["eligible"])

    return {
        "base": base if base in RET_BASES else "general",
        "curves": curves,
        "heatmap": heat,
        "categories": cats[:100],
        "category_options": sorted(d["category_one_name"].dropna().astype(str).unique().tolist()),
        "cohort_weeks": sorted(d["week"].unique().tolist()),
    }


def retention_by_measure(d: pd.DataFrame, country: str | None, measure: str | None) -> dict:
    """Rows = measure (category_four_name), columns = retention window (retention_order 1..12).

    Cell = returned_drivers_general / eligible_drivers_general, where both are summed over every
    cohort week and every selected country/measure BEFORE dividing (never an average of ratios).
    Column labels come from retention_window_weeks / retention_window_days when the file has them."""
    if "category_four_name" not in d.columns:
        raise ValueError("This retention file has no category_four_name column, so it cannot be split by measure.")
    elig_c, ret_c = RET_BASES["general"]
    f = d.assign(measure=d["category_four_name"].astype("string").str.strip().fillna("No measure").astype(object))
    countries = sorted(f["country_code"].unique().tolist())
    measures = sorted(f["measure"].unique().tolist())
    if country:
        f = f[f["country_code"] == country.upper()]
    if measure:
        f = f[f["measure"] == measure]

    # window headers (e.g. "Week 1" / "1-7 Days"), taken from the data, generated if absent
    windows = []
    for o in sorted(d["retention_order"].unique().tolist()):
        sub = d[d["retention_order"] == o]

        def first(col: str, default: str) -> str:
            if col in sub.columns:
                v = sub[col].dropna()
                if len(v):
                    return str(v.iloc[0])
            return default

        windows.append({"order": int(o),
                        "weeks": first("retention_window_weeks", f"Week {int(o)}"),
                        "days": first("retention_window_days", f"{7 * (int(o) - 1) + 1}-{7 * int(o)} Days")})

    def cells(frame: pd.DataFrame, by: str) -> dict:
        a = frame.groupby([by, "retention_order"], observed=True)[[elig_c, ret_c]].sum()
        out: dict = {}
        for (k, o), r in a.iterrows():
            e, t = float(r[elig_c]), float(r[ret_c])
            out.setdefault(k, {})[int(o)] = {"eligible": e, "returned": t, "rate": (t / e) if e > 0 else None}
        return out

    per = cells(f, "measure")
    rows = [{"measure": m, "eligible": max(c["eligible"] for c in v.values()), "cells": v} for m, v in per.items()]
    rows.sort(key=lambda r: -r["eligible"])
    total = cells(f.assign(measure="All"), "measure").get("All", {})
    return {"windows": windows, "rows": rows, "total": total,
            "country_options": countries, "measure_options": measures}


# ---------------------------------------------------------------------------
# Impact by rule: rows = rule, columns = week
# ---------------------------------------------------------------------------
RULE_LEVELS = {
    "category_four_name": "Rule (category 4)",
    "category_three_name": "Category 3",
    "category_two_name": "Category 2",
    "category_one_name": "Category 1",
}
_IMPACT_METRICS = {"drivers": "total_impacted_drivers", "active": "active_impacted_drivers",
                   "trips": "total_finished_trips", "sh": "total_supply_hours"}


def impact_by_rule(d: pd.DataFrame, level: str, max_rows: int = 300) -> dict:
    """Rows = the rule that triggered the block, columns = country group (MX, AR, CO, Rest of SSL, All SSL).

    Each cell carries the four metrics (impacted drivers, active drivers, trips, supply hours) summed over
    the whole window (all weeks), so the metric can be switched in the UI without another request.
    The share of a region (rule / region total) is computed in the UI from `all`.

    The query counts distinct drivers per rule and week, so a driver blocked by two rules, or in two weeks,
    is counted in each: 'All rules' is the sum of the rows (driver-weeks), not a de-duplicated head count."""
    if level not in RULE_LEVELS:
        level = "category_four_name"
    weeks = sorted(d["week"].unique().tolist())
    if level in d.columns:
        rule = d[level].astype("string").str.strip().fillna("No rule")
    else:
        rule = pd.Series("n/a", index=d.index)
    f = d.assign(rule=rule.astype(object))

    cols = list(_IMPACT_METRICS.values())
    zero = {k: 0.0 for k in _IMPACT_METRICS}

    def blank() -> dict:
        return {g: dict(zero) for g in ALL_GROUPS}

    def add(cell: dict, r: pd.Series) -> None:
        for k, v in _IMPACT_METRICS.items():
            cell[k] += float(r[v])

    g = f.groupby(["rule", "group"], observed=True)[cols].sum()
    rows, all_totals = [], blank()
    for rule_name, s in g.groupby(level=0, observed=True):
        totals = blank()
        for (_, grp), r in s.iterrows():
            add(totals[grp], r)
            add(totals[TOTAL], r)
            add(all_totals[grp], r)
            add(all_totals[TOTAL], r)
        rows.append({"rule": rule_name, "totals": totals})
    rows.sort(key=lambda r: -r["totals"][TOTAL]["drivers"])

    return {
        "level": level, "groups": ALL_GROUPS, "n_weeks": len(weeks),
        "first_week": weeks[0] if weeks else None, "last_week": weeks[-1] if weeks else None,
        "rows": rows[:max_rows], "n_rules": len(rows), "truncated": len(rows) > max_rows,
        "all": all_totals,
        "level_options": [{"key": k, "label": v} for k, v in RULE_LEVELS.items()],
    }
