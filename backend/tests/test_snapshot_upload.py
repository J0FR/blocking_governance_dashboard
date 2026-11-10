import pandas as pd
import pytest

from app import impact, snapshot

HEADER = ("driver_id,country_code,city_id,city_name,vehicle_type,segment,seg_supply_hours,seg_ipt,seg_incentive,"
          "seg_shor,finished_orders,supply_hours,ipt,avg_trip_minutes,available_trips,available_tsh,"
          "occupancy_rate,tickets,compensated_usd")
ROWS = [
    "0012345,MX,1,CDMX,4-Wheels,seg a,Part Time,Low IPT,No Incentive,High,40,80.5,61.2,22.5,3,5.5,0.4,1,0.0",
    "0099999,AR,9,null,No Trips,No Trips,No Trips,No Trips,No Incentive,No SHOR,0,2.1,null,null,0,0,0,0,0",
]


@pytest.fixture()
def snap(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(snapshot, "PARQUET", tmp_path / "drivers.parquet")
    monkeypatch.setattr(snapshot, "META", tmp_path / "meta.json")
    return tmp_path


def write(tmp, header=HEADER, rows=ROWS, sep=","):
    p = tmp / "in.csv"
    p.write_text("\n".join([header] + rows).replace(",", sep), encoding="utf-8")
    return p


def test_ingest_builds_the_snapshot_the_dashboard_reads(snap):
    meta = snapshot.ingest_csv(write(snap), "data.csv")
    assert meta["rows"] == 2 and meta["run_date"] == "data.csv" and meta["engine"] == "csv"
    df = snapshot.load()
    assert list(df["driver_id"]) == ["0012345", "0099999"]            # ids stay text (leading zeros kept)
    assert pd.isna(df.loc[1, "city_name"]) and pd.isna(df.loc[1, "ipt"])   # the text "null" is a real null
    assert snapshot.meta()["rows"] == 2
    # and it flows straight into the impact model
    d = impact.with_driver_metrics(snapshot.load(columns=impact.SNAPSHOT_COLUMNS))
    assert len(d) == 2 and d.loc[0, "trips_week"] == 10


def test_ingest_replaces_the_previous_base_atomically(snap):
    snapshot.ingest_csv(write(snap), "first.csv")
    snapshot.ingest_csv(write(snap, rows=ROWS[:1]), "second.csv")
    assert snapshot.meta()["run_date"] == "second.csv" and len(snapshot.load()) == 1
    assert not list(snap.glob("*.tmp"))


def test_ingest_accepts_semicolon_csv_and_ipt_usd_instead_of_ipt(snap):
    header = HEADER.replace(",ipt,", ",ipt_usd,")
    snapshot.ingest_csv(write(snap, header=header, sep=";"), "x.csv")
    assert "ipt_usd" in snapshot.load().columns


def test_ingest_rejects_a_file_that_is_not_the_driver_query(snap):
    p = snap / "bad.csv"
    p.write_text("driver_id,block_hours\n1,24\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing columns"):
        snapshot.ingest_csv(p, "bad.csv")
    assert not snapshot.PARQUET.exists()                              # nothing was replaced


def test_ingest_rejects_an_empty_file(snap):
    with pytest.raises(ValueError, match="no rows"):
        snapshot.ingest_csv(write(snap, rows=[]), "empty.csv")
