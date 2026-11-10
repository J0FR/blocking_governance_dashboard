import pandas as pd
import pytest

from app import impact

H = impact.HOURS_SNAPSHOT  # 672 calendar hours in the 28-day snapshot


def make_df():
    base = dict(country_code="MX", city_name="CDMX", city_id=1, avg_trip_minutes=30.0,
                available_tsh=0.0, available_trips=0.0, vehicle_type="4-Wheels",
                seg_supply_hours="Part Time", seg_ipt="Low IPT", seg_incentive="No Incentive",
                seg_shor="High", tickets=0, compensated_usd=0.0)
    rows = [
        dict(base, driver_id=111, finished_orders=672, supply_hours=336.0, ipt_usd=2.0),   # 1 trip/h, 0.5 tsh/h
        dict(base, driver_id=222, finished_orders=80, supply_hours=100.0, ipt_usd=3.0,
             available_trips=100.0, available_tsh=50.0),
        dict(base, driver_id=333, finished_orders=20, supply_hours=40.0, ipt_usd=None,
             available_trips=30.0, available_tsh=15.0, city_id=2, city_name="GDL"),
    ]
    return pd.DataFrame(rows)


def blocks(*pairs):
    return impact.parse_blocklist(pd.DataFrame(pairs, columns=["driver_id", "block_hours"]).astype(str))[0]


def run(df, bl, horizon=impact.HORIZON_DAYS):
    d = impact.with_driver_metrics(df)
    stats = impact.base_stats(d)
    blk, rep = impact.attach_blocks(d, bl, horizon)
    return d, stats, blk, rep


# ---- parsing ------------------------------------------------------------
def test_parse_marks_9999_as_permanent_and_drops_invalid():
    raw = pd.DataFrame({"Driver ID": ["1", "2", "3", "4"], "Horas Bloqueo": ["24", "9999", "0", "abc"]})
    clean, rep = impact.parse_blocklist(raw)
    assert dict(zip(clean.driver_id, clean.block_kind)) == {"1": "temporary", "2": "permanent"}
    assert rep["rows_invalid"] == 2 and rep["temporary"] == 1 and rep["permanent"] == 1


def test_parse_duplicate_keeps_longest_block():
    clean, rep = impact.parse_blocklist(pd.DataFrame({"driver_id": ["5", "5"], "block_hours": ["24", "9999"]}))
    assert len(clean) == 1 and clean.iloc[0].block_kind == "permanent" and rep["duplicate_rows"] == 2


def test_parse_missing_columns_raises():
    with pytest.raises(ValueError):
        impact.parse_blocklist(pd.DataFrame({"foo": [1]}))


# ---- currency -----------------------------------------------------------
def test_local_currency_ipt_is_converted_to_usd(monkeypatch):
    monkeypatch.setattr(impact, "load_fx", lambda: {"MX": 20.0, "CO": 4000.0})
    df = make_df().rename(columns={"ipt_usd": "ipt"})
    df.loc[df.driver_id == 111, "ipt"] = 40.0                       # 40 MXN / 20 = $2
    df.loc[df.driver_id == 222, ["country_code", "ipt"]] = ["CO", 12000.0]   # 12,000 COP / 4000 = $3
    d = impact.with_driver_metrics(df)
    assert d[d.driver_id == "111"].iloc[0].ipt_eff == pytest.approx(2.0)
    assert d[d.driver_id == "222"].iloc[0].ipt_eff == pytest.approx(3.0)


def test_ipt_usd_column_wins_over_fx():
    d = impact.with_driver_metrics(make_df())          # has ipt_usd, MX would otherwise be divided by 18.5
    assert d[d.driver_id == "111"].iloc[0].ipt_eff == pytest.approx(2.0)


# ---- driver losses ------------------------------------------------------
def test_temporary_loss_uses_calendar_hour_rate_and_own_ipt():
    _, _, blk, rep = run(make_df(), blocks(("111", "48")))
    r = blk.iloc[0]
    assert len(blk) == 1
    assert r.lost_trips == pytest.approx(48)      # 1 trip/h x 48 h
    assert r.lost_tsh == pytest.approx(24)        # 0.5 tsh/h x 48 h
    assert r.lost_gmv == pytest.approx(96)        # trips x own IPT (2.0)
    assert rep["matched"] == 1 and rep["unmatched_count"] == 0


def test_permanent_loss_projects_to_horizon():
    _, _, blk, _ = run(make_df(), blocks(("111", "9999")), horizon=180)
    r = blk.iloc[0]
    assert r.lost_trips == pytest.approx(180 * 24)
    assert r.lost_gmv == pytest.approx(180 * 24 * 2.0)


def test_temporary_block_is_capped_at_horizon():
    _, _, blk, _ = run(make_df(), blocks(("111", "5000")), horizon=30)
    assert blk.iloc[0].lost_trips == pytest.approx(30 * 24)


def test_missing_ipt_falls_back_to_median_and_unmatched_reported():
    d, _, blk, rep = run(make_df(), blocks(("333", "24"), ("999", "24")))
    assert d[d.driver_id == "333"].iloc[0].ipt_eff == pytest.approx(2.5)   # median of 2.0 and 3.0
    assert rep["matched"] == 1 and rep["unmatched_count"] == 1 and rep["unmatched_sample"] == ["999"]


def test_net_loss_subtracts_cx_cost_avoided():
    df = make_df()
    # driver 111: 28d compensations $100 + 20 tickets x $0.69 = $113.80 -> $113.80 / 672 h per hour
    df.loc[df.driver_id == 111, ["compensated_usd", "tickets"]] = [100.0, 20]
    _, stats, blk, _ = run(df, blocks(("111", "336")))
    r = blk.iloc[0]
    assert r.cx_cost_avoided == pytest.approx(113.8 * 336 / 672)
    assert r.lost_gmv == pytest.approx(336 * 2.0)
    assert r.lost_net == pytest.approx(r.lost_gmv - r.cx_cost_avoided)
    s = impact.summary(blk, impact.city_table(blk, stats), stats)
    assert s["lost_net"] == pytest.approx(r.lost_net)
    assert s["ticket_cost_usd"] == 0.69


def test_concentration_shares():
    _, stats, blk, _ = run(make_df(), blocks(("111", "9999"), ("222", "24"), ("333", "24")))
    s = impact.summary(blk, impact.city_table(blk, stats), stats)
    assert 0 < s["top1_share_gmv"] <= s["top10_share_gmv"] <= 1.0


# ---- aggregations -------------------------------------------------------
def test_city_absorption_and_status():
    _, stats, blk, _ = run(make_df(), blocks(("111", "9999")))
    c = impact.city_table(blk, stats).set_index("city_name")
    cdmx = c.loc["CDMX"]
    assert cdmx.lost_trips_week == pytest.approx(168)          # 672 / 4 weeks
    assert cdmx.capacity_trips_week == pytest.approx(25)       # driver 222: 100 / 4 (blocked 111 has none)
    assert cdmx.status == "red"
    assert cdmx.headroom_trips_week == pytest.approx(25 - 168)
    assert c.loc["GDL"].status == "none"
    assert cdmx.blocked_permanent == 1 and cdmx.blocked_temporary == 0


def test_blocked_drivers_spare_capacity_is_not_counted_as_absorption():
    df = make_df()
    df.loc[df.driver_id == 222, "finished_orders"] = 40
    _, stats, blk, _ = run(df, blocks(("222", "9999")))     # 222 holds the city's only spare capacity
    c = impact.city_table(blk, stats).set_index("city_name")
    assert c.loc["CDMX"].capacity_trips_week == pytest.approx(0)
    assert c.loc["CDMX"].status == "red"


def test_green_when_capacity_covers_loss():
    df = make_df()
    df.loc[df.driver_id == 111, "finished_orders"] = 40
    _, stats, blk, _ = run(df, blocks(("111", "24")))
    c = impact.city_table(blk, stats).set_index("city_name")
    assert c.loc["CDMX"].lost_trips_week == pytest.approx(10)
    assert c.loc["CDMX"].coverage == pytest.approx(2.5)
    assert c.loc["CDMX"].status == "green"


def test_summary_split_matches_totals_and_country_rollup():
    _, stats, blk, _ = run(make_df(), blocks(("111", "24"), ("333", "9999")), horizon=180)
    cities = impact.city_table(blk, stats)
    s = impact.summary(blk, cities, stats)
    assert s["blocked_drivers"] == 2 and s["total_drivers"] == 3
    assert s["lost_trips"] == pytest.approx(s["temporary"]["lost_trips"] + s["permanent"]["lost_trips"])
    assert s["lost_gmv"] == pytest.approx(cities["lost_gmv"].sum())
    mx = impact.country_table(cities).iloc[0]
    assert mx.country_code == "MX" and mx.lost_gmv == pytest.approx(s["lost_gmv"])


def test_duration_buckets_and_profile():
    _, stats, blk, _ = run(make_df(), blocks(("111", "24"), ("222", "100"), ("333", "9999")))
    t = impact.duration_table(blk).set_index("bucket")
    assert t.loc["≤ 24 h", "drivers"] == 1 and t.loc["3–7 days", "drivers"] == 1 and t.loc["Permanent", "drivers"] == 1
    p = impact.profile(blk, "seg_ipt", stats)
    assert p["blocked"].sum() == 3 and p.iloc[0].base_drivers == 3
    assert impact.profile(blk, "block_kind", stats)["blocked"].sum() == 3


def test_empty_blocklist_gives_zero_impact():
    _, stats, blk, rep = run(make_df(), None)
    cities = impact.city_table(blk, stats)
    assert len(blk) == 0 and (cities["status"] == "none").all()
    assert impact.summary(blk, cities, stats)["lost_net"] == 0
