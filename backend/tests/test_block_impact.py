from datetime import date, timedelta

import pandas as pd
import pytest

from app import block_impact as bi


def impact_df():
    rows = []
    # 2 weeks; MX has two rules in W1, PE (-> Rest of SSL) one rule
    for week, cc, kind, cat, drv, act, trips, sh in [
        ("202621", "MX", "Temporary Blocked", "Fraud", 10, 6, 100, 400.0),
        ("202621", "MX", "Permanently Blocked", "Safety", 4, 1, 20, 80.0),
        ("202621", "PE", "Temporary Blocked", "Fraud", 5, 5, 50, 200.0),
        ("202622", "MX", "Temporary Blocked", "Fraud", 20, 10, 300, 900.0),
        ("202622", "AR", "Temporary Blocked", "Fraud", 8, 4, 80, 300.0),
        ("202622", "DO", "Permanently Blocked", "Safety", 2, 0, 0, 0.0),
    ]:
        rows.append(dict(year_calendar_week=week, country_code=cc, block_duration_type=kind,
                         category_one_name=cat, total_impacted_drivers=drv, active_impacted_drivers=act,
                         total_finished_trips=trips, total_supply_hours=sh))
    return bi.prepare_impact(pd.DataFrame(rows).astype(str))


def retention_df():
    rows = []
    for week, cc, cat, order, el, rt, ela, rta in [
        ("202601", "MX", "Fraud", 1, 100, 50, 80, 48),
        ("202601", "MX", "Fraud", 2, 100, 30, 80, 24),
        ("202601", "PE", "Fraud", 1, 50, 10, 40, 10),
        ("202601", "PE", "Fraud", 2, 50, 5, 40, 4),
        ("202602", "MX", "Safety", 1, 20, 2, 10, 1),
        ("202602", "MX", "Safety", 2, 20, 1, 10, 1),
    ]:
        rows.append(dict(iso_year_calendar_week=week, country_code=cc, category_one_name=cat, retention_order=order,
                         eligible_drivers_general=el, returned_drivers_general=rt,
                         eligible_drivers_active_14d=ela, returned_drivers_active_14d=rta))
    return bi.prepare_retention(pd.DataFrame(rows).astype(str))


# ---- dates ---------------------------------------------------------------
def test_query_windows_match_the_documented_example():
    w = bi.query_windows(date(2026, 11, 10))
    assert w["impact"] == {"start_date": "2026-08-17", "end_date": "2026-11-08"}
    assert w["retention"] == {"start_date": "2026-05-25", "end_date": "2026-08-16", "data_end_date": "2026-11-08"}


@pytest.mark.parametrize("day", [date(2026, 11, 10), date(2026, 11, 12), date(2026, 11, 15), date(2026, 11, 16)])
def test_windows_are_always_12_complete_weeks(day):
    for name in ("impact", "retention"):
        w = bi.query_windows(day)[name]
        s, e = date.fromisoformat(w["start_date"]), date.fromisoformat(w["end_date"])
        assert s.weekday() == 0 and e.weekday() == 6 and (e - s).days == 83
    w = bi.query_windows(day)
    de = date.fromisoformat(w["retention"]["data_end_date"])
    assert date.fromisoformat(w["retention"]["end_date"]) <= date.fromisoformat(w["impact"]["end_date"])
    assert (de - date.fromisoformat(w["retention"]["end_date"])).days >= 84   # retention weeks are mature
    assert date.fromisoformat(w["impact"]["end_date"]) <= de


# ---- reading / validating -------------------------------------------------
def test_read_csv_handles_null_text_and_semicolons():
    df = bi.read_csv_bytes(b"A;B\n1;null\n2;x\n")
    assert list(df.columns) == ["a", "b"] and df["b"].isna().tolist() == [True, False]


def test_wrong_file_is_rejected_with_the_missing_columns():
    with pytest.raises(ValueError, match="Missing columns"):
        bi.prepare_impact(pd.DataFrame({"driver_id": ["1"]}))
    with pytest.raises(ValueError, match="retention"):
        bi.prepare_retention(pd.DataFrame({"x": ["1"]}))


# ---- impact ----------------------------------------------------------------
def test_country_groups():
    d = impact_df()
    assert dict(zip(d.country_code, d.group)) == {"MX": "MX", "PE": "Rest of SSL", "AR": "AR", "DO": "Rest of SSL"}


def test_impact_table_weekly_averages_and_total():
    s = bi.impact_summary(impact_df(), None, None, "block_duration_type")
    t = {r["group"]: r for r in s["table"]}
    assert s["weeks"] == ["202621", "202622"] and s["n_weeks"] == 2
    assert t["MX"]["drivers_avg"] == pytest.approx((10 + 4 + 20) / 2)
    assert t["MX"]["active_avg"] == pytest.approx((6 + 1 + 10) / 2)
    assert t["MX"]["trips_avg"] == pytest.approx((100 + 20 + 300) / 2)
    assert t["MX"]["sh_avg"] == pytest.approx((400 + 80 + 900) / 2)
    assert t["Rest of SSL"]["drivers_avg"] == pytest.approx((5 + 2) / 2)
    assert t["Total SSL"]["drivers_avg"] == pytest.approx(sum(t[g]["drivers_avg"] for g in ("MX", "AR", "CO", "Rest of SSL")))
    assert t["CO"]["drivers_avg"] == 0 and t["CO"]["active_share"] is None


def test_impact_kind_filter_and_breakdown():
    s = bi.impact_summary(impact_df(), "permanent", None, "block_duration_type")
    t = {r["group"]: r for r in s["table"]}
    assert t["MX"]["drivers_avg"] == pytest.approx(4 / 2)
    s = bi.impact_summary(impact_df(), None, "MX", "category_one_name")
    by = {r["value"]: r for r in s["breakdown"]}
    assert by["Fraud"]["drivers_avg"] == pytest.approx(30 / 2) and by["Safety"]["drivers_avg"] == pytest.approx(4 / 2)
    assert by["Fraud"]["active_share"] == pytest.approx(16 / 30)


def test_weekly_series_has_every_group_and_week():
    s = bi.impact_summary(impact_df(), None, None, "block_duration_type")
    assert len(s["weekly"]) == 5 * 2          # (MX, AR, CO, Rest, Total) x 2 weeks
    co = [r for r in s["weekly"] if r["group"] == "CO"]
    assert all(r["drivers"] == 0 for r in co)


# ---- retention -------------------------------------------------------------
def test_retention_curves_and_rates():
    s = bi.retention_summary(retention_df(), "general", None, None)
    curves = {c["group"]: {p["retention_order"]: p for p in c["points"]} for c in s["curves"]}
    assert curves["MX"][1]["rate"] == pytest.approx((50 + 2) / (100 + 20))
    assert curves["Rest of SSL"][2]["rate"] == pytest.approx(5 / 50)
    assert curves["Total SSL"][1]["rate"] == pytest.approx((50 + 10 + 2) / (100 + 50 + 20))


def test_retention_active_base_category_filter_and_heatmap():
    s = bi.retention_summary(retention_df(), "active_14d", "MX", "Fraud")
    assert s["base"] == "active_14d"
    curves = {c["group"]: {p["retention_order"]: p for p in c["points"]} for c in s["curves"]}
    assert curves["MX"][1]["rate"] == pytest.approx(48 / 80)
    assert "Rest of SSL" in curves and curves["Rest of SSL"][1]["rate"] == pytest.approx(10 / 40)
    assert [h["week"] for h in s["heatmap"]] == ["202601"]
    assert s["heatmap"][0]["eligible"] == 80 and s["heatmap"][0]["rates"][2] == pytest.approx(24 / 80)
    assert s["category_options"] == ["Fraud", "Safety"]


def test_retention_category_table():
    s = bi.retention_summary(retention_df(), "general", "MX", None)
    cats = {c["category"]: c for c in s["categories"]}
    assert cats["Fraud"]["w1"] == pytest.approx(0.5) and cats["Safety"]["w1"] == pytest.approx(0.1)
    assert cats["Fraud"]["w12"] is None            # no week-12 rows in the fixture


# ---- impact by rule: rows = rule, columns = country group ------------------------------------
def test_impact_by_rule_columns_are_regions_and_cover_the_whole_window():
    s = bi.impact_by_rule(impact_df(), "category_one_name")
    rows = {r["rule"]: r["totals"] for r in s["rows"]}
    assert s["groups"] == ["MX", "AR", "CO", "Rest of SSL", "Total SSL"] and s["n_weeks"] == 2
    # Fraud: MX 10 (W1) + 20 (W2); PE -> Rest of SSL 5; AR 8 ; summed over both weeks
    assert rows["Fraud"]["MX"] == {"drivers": 30.0, "active": 16.0, "trips": 400.0, "sh": 1300.0}
    assert rows["Fraud"]["Rest of SSL"]["drivers"] == 5.0 and rows["Fraud"]["AR"]["drivers"] == 8.0
    assert rows["Fraud"]["CO"]["drivers"] == 0.0
    assert rows["Fraud"]["Total SSL"]["drivers"] == 43.0
    assert rows["Safety"]["MX"]["drivers"] == 4.0 and rows["Safety"]["Rest of SSL"]["drivers"] == 2.0   # DO -> Rest
    assert s["rows"][0]["rule"] == "Fraud"                                   # sorted by all-SSL drivers


def test_impact_by_rule_all_row_is_the_sum_of_rules_and_regions_add_up():
    s = bi.impact_by_rule(impact_df(), "category_one_name")
    for metric in ("drivers", "active", "trips", "sh"):
        for g in s["groups"]:
            assert s["all"][g][metric] == pytest.approx(sum(r["totals"][g][metric] for r in s["rows"]))
        assert s["all"]["Total SSL"][metric] == pytest.approx(
            sum(s["all"][g][metric] for g in ("MX", "AR", "CO", "Rest of SSL")))
    assert s["all"]["MX"]["drivers"] == 34.0 and s["all"]["Total SSL"]["drivers"] == 49.0


def test_impact_by_rule_missing_level_column_and_unknown_level():
    s = bi.impact_by_rule(impact_df(), "category_four_name")      # fixture has no category_four_name
    assert [r["rule"] for r in s["rows"]] == ["n/a"] and s["rows"][0]["totals"]["Total SSL"]["drivers"] == 49.0
    assert bi.impact_by_rule(impact_df(), "nonsense")["level"] == "category_four_name"


# ---- retention by measure: rows = measure, columns = retention window, general base -----------
def by_measure_df(with_labels=True):
    rows = []
    for week, cc, m, order, el, rt, ela, rta in [
        # cohort 202601: MX Fake GPS, windows 1 and 2
        ("202601", "MX", "Fake GPS", 1, 100, 50, 10, 9),
        ("202601", "MX", "Fake GPS", 2, 100, 30, 10, 8),
        # cohort 202602: same measure, other week (summed with the one above before dividing)
        ("202602", "MX", "Fake GPS", 1, 300, 60, 10, 9),
        ("202602", "MX", "Fake GPS", 2, 300, 30, 10, 8),
        ("202601", "PE", "Fake GPS", 1, 100, 10, 10, 9),
        ("202601", "MX", "Multi account", 1, 40, 20, 10, 9),
    ]:
        r = dict(iso_year_calendar_week=week, country_code=cc, category_four_name=m, retention_order=order,
                 eligible_drivers_general=el, returned_drivers_general=rt,
                 eligible_drivers_active_14d=ela, returned_drivers_active_14d=rta)
        if with_labels:
            r["retention_window_days"] = f"{7 * (order - 1) + 1}-{7 * order} Days"
            r["retention_window_weeks"] = f"Week {order}"
        rows.append(r)
    return bi.prepare_retention(pd.DataFrame(rows).astype(str))


def cell(s, measure, order):
    return next(r for r in s["rows"] if r["measure"] == measure)["cells"][order]


def test_by_measure_uses_the_general_base_and_sums_before_dividing():
    s = bi.retention_by_measure(by_measure_df(), None, None)
    c = cell(s, "Fake GPS", 1)
    assert c["eligible"] == 500 and c["returned"] == 120                       # 100+300+100 / 50+60+10
    assert c["rate"] == pytest.approx(120 / 500)                                # not the mean of 0.5, 0.2, 0.1
    assert cell(s, "Fake GPS", 2)["rate"] == pytest.approx(60 / 400)
    assert cell(s, "Multi account", 1)["rate"] == pytest.approx(0.5)            # general, not the active_14d columns


def test_by_measure_columns_are_retention_windows_with_their_labels():
    s = bi.retention_by_measure(by_measure_df(), None, None)
    assert s["windows"] == [{"order": 1, "weeks": "Week 1", "days": "1-7 Days"},
                            {"order": 2, "weeks": "Week 2", "days": "8-14 Days"}]
    no_labels = bi.retention_by_measure(by_measure_df(with_labels=False), None, None)["windows"]
    assert no_labels == [{"order": 1, "weeks": "Week 1", "days": "1-7 Days"},
                         {"order": 2, "weeks": "Week 2", "days": "8-14 Days"}]


def test_by_measure_country_and_measure_filters_and_total_row():
    mx = bi.retention_by_measure(by_measure_df(), "MX", None)
    assert cell(mx, "Fake GPS", 1)["eligible"] == 400 and cell(mx, "Fake GPS", 1)["rate"] == pytest.approx(110 / 400)
    assert mx["country_options"] == ["MX", "PE"] and mx["measure_options"] == ["Fake GPS", "Multi account"]
    one = bi.retention_by_measure(by_measure_df(), None, "Multi account")
    assert [r["measure"] for r in one["rows"]] == ["Multi account"]
    assert one["total"][1]["rate"] == pytest.approx(0.5)
    allr = bi.retention_by_measure(by_measure_df(), None, None)
    assert allr["total"][1]["eligible"] == 540 and allr["total"][1]["rate"] == pytest.approx(140 / 540)
    assert [r["measure"] for r in allr["rows"]] == ["Fake GPS", "Multi account"]        # biggest first


def test_by_measure_needs_category_four():
    df = by_measure_df().drop(columns=["category_four_name"])
    with pytest.raises(ValueError, match="category_four_name"):
        bi.retention_by_measure(df, None, None)


# ---- the stored queries, rendered with the dates of the day ------------------------------------
ALL_KINDS = ["impact", "retention", "drivers"]


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_rendered_query_has_real_dates_and_no_parameters_left(kind):
    sql = bi.render_query(kind, date(2026, 11, 10))["sql"]
    assert "${" not in sql and "@@" not in sql            # every variable replaced by its date
    assert not any(line.lstrip().upper().startswith("SET ") for line in sql.splitlines())   # nothing to set on the other side


def test_impact_query_dates():
    q = bi.render_query("impact", date(2026, 11, 10))
    assert "BETWEEN '2026-08-17' AND '2026-11-08'" in q["sql"]
    assert "REGEXP_REPLACE('2026-08-17', '-', '')" in q["sql"]
    assert q["dates"] == {"start_date": "2026-08-17", "end_date": "2026-11-08"}


def test_retention_query_dates():
    q = bi.render_query("retention", date(2026, 11, 10))
    assert "TO_DATE('2026-11-08') AS data_end_date" in q["sql"]
    assert "WHERE dt = '2026-11-08'" in q["sql"]
    assert q["dates"] == {"start_date": "2026-05-25", "end_date": "2026-08-16", "data_end_date": "2026-11-08"}


def test_driver_query_dates_cover_the_28_days_that_end_on_the_last_complete_day():
    q = bi.render_query("drivers", date(2026, 11, 10))
    assert q["dates"] == {"run_date": "2026-11-09", "start_date": "2026-10-12", "end_date": "2026-11-08"}
    assert "date_sub('2026-11-09', 28)" in q["sql"] and "date_sub('2026-11-09', 1)" in q["sql"]
    # 28 full days, Monday..Sunday, ending on data_end (today - 2)
    s, e = date.fromisoformat(q["dates"]["start_date"]), date.fromisoformat(q["dates"]["end_date"])
    assert (e - s).days == 27 and s.weekday() == 0 and e.weekday() == 6


@pytest.mark.parametrize("offset", range(0, 14))
def test_driver_period_always_ends_on_the_last_day_with_complete_data(offset):
    today = date(2026, 11, 10) + timedelta(days=offset)
    w = bi.query_windows(today)["drivers"]
    assert date.fromisoformat(w["end_date"]) == today - timedelta(days=2)
    assert (date.fromisoformat(w["end_date"]) - date.fromisoformat(w["start_date"])).days == 27


def test_rendered_dates_follow_the_run_day():
    a = bi.render_query("impact", date(2026, 11, 10))["sql"]
    b = bi.render_query("impact", date(2026, 11, 17))["sql"]                 # a week later: the window moves a week
    assert "'2026-11-08'" in a and "'2026-11-15'" in b and "'2026-11-15'" not in a


def test_unknown_query_kind():
    with pytest.raises(KeyError):
        bi.render_query("nope")


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_stored_sql_is_complete_and_balanced(kind):
    sql = bi.render_query(kind, date(2026, 11, 10))["sql"]
    assert sql.count("(") == sql.count(")")                                  # nothing lost when it was saved
    assert sql.lstrip().startswith("--") and sql.rstrip().endswith(";")
    assert "SELECT" in sql and "ORDER BY" in sql


def test_each_query_outputs_the_columns_the_dashboard_reads():
    from app import impact
    imp = bi.render_query("impact", date(2026, 11, 10))["sql"]
    for col in bi.IMPACT_REQUIRED + ["category_four_name", "category_one_name"]:
        assert col in imp, col
    nl = chr(10)
    ret = bi.render_query("retention", date(2026, 11, 10))["sql"]
    final_select = ret[ret.rindex(nl + "SELECT" + nl):]
    for col in bi.RET_REQUIRED + ["category_four_name", "retention_window_days", "retention_window_weeks",
                                  "block_duration_type"]:
        assert col in final_select, col
    drv = bi.render_query("drivers", date(2026, 11, 10))["sql"]
    drv_final = drv[drv.rindex(nl + "SELECT" + nl):]
    for col in impact.SNAPSHOT_COLUMNS:
        if col != "ipt_usd":                                                  # optional: the query reports ipt in local currency
            assert col in drv_final, col
