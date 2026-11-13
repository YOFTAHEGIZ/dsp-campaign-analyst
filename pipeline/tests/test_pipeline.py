"""
Tests for the pipeline SQL: linking clicks and conversions to impressions, facts and dimensions.

    pip install pytest
    pytest pipeline/tests

Each test writes a few hand-made log rows as Parquet in a temporary folder, runs the real
SQL files from pipeline/sql on them, and checks the result.
"""

import os
import sys
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "pipeline"))
import model  # noqa: E402
import ingest  # noqa: E402
import clean  # noqa: E402
import tick  # noqa: E402

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"

EVENT_COLUMNS = [
    "bid_id", "timestamp", "log_type", "ipinyou_id", "user_agent", "ip",
    "region", "city", "ad_exchange", "domain", "url", "anonymous_url_id",
    "ad_slot_id", "ad_slot_width", "ad_slot_height", "ad_slot_visibility",
    "ad_slot_format", "ad_slot_floor_price", "creative_id", "bidding_price",
    "paying_price", "key_page_url", "advertiser_id", "user_tags",
]
BID_COLUMNS = [c for c in EVENT_COLUMNS if c not in ("log_type", "paying_price", "key_page_url")]


def row(bid_id, timestamp, user, columns=EVENT_COLUMNS):
    """One log row as text, like the raw files. Only the fields the tests need are set."""
    values = {c: "0" for c in columns}
    values.update(bid_id=bid_id, timestamp=timestamp, ipinyou_id=user, advertiser_id="1458",
                  paying_price="50", bidding_price="300", ad_slot_floor_price="0",
                  user_agent="Mozilla", domain="null", user_tags="null")
    return {c: values[c] for c in columns}


def write_log(folder, log, day, rows, columns=EVENT_COLUMNS):
    """Save rows like ingest.py does: one Parquet file per hour of the events' timestamps."""
    path = folder / "data" / "interim" / log
    path.mkdir(parents=True, exist_ok=True)
    for hour in sorted({r["timestamp"][:10] for r in rows}):
        hour_rows = [r for r in rows if r["timestamp"][:10] == hour]
        table = pa.table({c: pa.array([r[c] for r in hour_rows], pa.string()) for c in columns})
        table = table.append_column("source_file", pa.array([f"{log}.{day}.txt"] * len(hour_rows), pa.string()))
        pq.write_table(table, path / f"{log}_{day}_{hour}.parquet")
        if log == "bid":
            # ingest.py also writes a bid summary (all advertisers) for every bid file
            summary_dir = folder / "data" / "interim" / "bid_summary"
            summary_dir.mkdir(parents=True, exist_ok=True)
            batch = table.drop_columns(["source_file"]).to_batches()[0]
            pq.write_table(ingest.summarize_bids(batch), summary_dir / f"bid_summary_{day}_{hour}.parquet")


def run_models(folder, up_to=None):
    """Build raw views, staging views, then the whole model (linked, facts, dimensions,
    marts) with the same code the pipeline uses. up_to: only the hours up to this one."""
    os.chdir(folder)
    con = duckdb.connect()
    clean.create_raw_views(con, up_to)
    clean.create_staging_views(con, SQL_DIR / "staging", quiet=True)
    model.build(con, SQL_DIR, quiet=True)
    return con


@pytest.fixture
def con(tmp_path):
    impressions = [
        # A: shown late on 6 June, clicked just after midnight
        row("A", "20130606235800000", "u1"),
        # B: the same bid_id shown to two different users
        row("B", "20130607100000000", "u2"),
        row("B", "20130607110000000", "u3"),
        # C: shown, never clicked, but the user converted later (post-view)
        row("C", "20130607120000000", "u4"),
        # D: the same impression twice in the log (an exact duplicate)
        row("D", "20130607130000000", "u5"),
        row("D", "20130607130000000", "u5"),
    ]
    write_log(tmp_path, "imp", "20130606", impressions[:1])
    write_log(tmp_path, "imp", "20130607", impressions[1:])
    write_log(tmp_path, "clk", "20130607", [
        row("A", "20130607000500000", "u1"),
        row("B", "20130607100500000", "u2"),   # must link to u2's impression, not u3's
        row("Z", "20130607150000000", "u9"),   # no impression with this bid_id
    ])
    write_log(tmp_path, "conv", "20130607", [
        row("A", "20130607010000000", "u1"),   # after a click: post-click
        row("C", "20130607180000000", "u4"),   # no click: post-view
    ])
    write_log(tmp_path, "bid", "20130607", [
        row("A", "20130606235759000", "u1", BID_COLUMNS),   # won: impression A
        row("E", "20130607090000000", "u7", BID_COLUMNS),   # lost: no impression
    ], BID_COLUMNS)
    cwd = os.getcwd()
    yield run_models(tmp_path)
    os.chdir(cwd)


def test_duplicate_impression_counted_once(con):
    assert con.sql("SELECT COUNT(*) FROM stg_impressions WHERE bid_id = 'D'").fetchall()[0][0] == 1


def test_click_after_midnight_counts_on_impression_day(con):
    day = con.sql("SELECT impression_date FROM int_clicks_linked WHERE bid_id = 'A'").fetchall()[0][0]
    assert str(day) == "2013-06-06"
    clicks = dict(con.sql("SELECT CAST(report_date AS VARCHAR), clicks FROM daily_campaign").fetchall())
    assert clicks["2013-06-06"] == 1


def test_reused_bid_id_links_to_the_right_user(con):
    user, rule = con.sql("""
        SELECT i.ipinyou_id, c.link_rule
        FROM int_clicks_linked c JOIN stg_impressions i USING (imp_key)
        WHERE c.bid_id = 'B'
    """).fetchall()[0]
    assert user == "u2"
    assert rule == 1


def test_click_without_impression_is_kept(con):
    rule, imp_key = con.sql("SELECT link_rule, imp_key FROM int_clicks_linked WHERE bid_id = 'Z'").fetchall()[0]
    assert rule == 4 and imp_key is None


def test_conversion_types(con):
    types = dict(con.sql("SELECT bid_id, conversion_type FROM int_conversions_linked").fetchall())
    assert types == {"A": "post-click", "C": "post-view"}


def test_totals_match_the_logs(con):
    clicks, conversions = con.sql("SELECT SUM(clicks), SUM(conversions) FROM daily_campaign").fetchall()[0]
    assert clicks == 3 and conversions == 2


# ---- Facts and dimensions -------------------------------------------------

def test_fact_impressions_flags_and_cost(con):
    rows = dict((r[0], r[1:]) for r in con.sql(
        "SELECT bid_id, clicked, click_events, converted, post_click_converted, cost "
        "FROM fact_impressions WHERE bid_id IN ('A', 'C')").fetchall())
    assert rows["A"] == (1, 1, 1, 1, 0.05)       # clicked, then converted after the click
    assert rows["C"] == (0, 0, 1, 0, 0.05)       # not clicked, converted (post-view)


def test_fact_impressions_one_row_per_impression(con):
    total, distinct = con.sql(
        "SELECT COUNT(*), COUNT(DISTINCT imp_key) FROM fact_impressions").fetchall()[0]
    assert total == distinct == 5                 # A, B (two users), C, D (duplicate removed)


def test_device_from_user_agent(con):
    assert con.sql("SELECT DISTINCT device FROM fact_impressions").fetchall() == [("desktop",)]


def test_dimensions(con):
    assert con.sql("SELECT advertiser_id, industry FROM dim_advertiser").fetchall() == [
        (1458, "Chinese vertical e-commerce")]
    campaign = con.sql("SELECT campaign_id, first_date, last_date, has_bid_logs FROM dim_campaign").fetchall()[0]
    assert (campaign[0], str(campaign[1]), str(campaign[2]), campaign[3]) == (1458, "2013-06-06", "2013-06-07", True)
    assert [str(d[0]) for d in con.sql("SELECT date FROM dim_date ORDER BY date").fetchall()] == [
        "2013-06-06", "2013-06-07"]


def test_model_checks_pass(con):
    assert model.check(con) == []


# ---- Daily tables for Neon --------------------------------------------------

def test_bid_summary_counts_bids(con):
    assert con.sql("SELECT SUM(bids), SUM(sum_bidding_price) FROM stg_bid_summary").fetchall() == [(2, 600)]


def test_daily_auction(con):
    bids, wins, paid = con.sql(
        "SELECT SUM(bids), SUM(wins), SUM(sum_paying_price) FROM daily_auction").fetchall()[0]
    assert (bids, wins, paid) == (2, 5, 250)      # 2 bids; 5 impressions at price 50


def test_daily_campaign_cost_and_rates_inputs(con):
    rows = con.sql("""
        SELECT CAST(report_date AS VARCHAR), impressions, clicks, clicked_impressions,
               post_click_conversions, post_view_conversions, CAST(total_cost AS DOUBLE)
        FROM daily_campaign ORDER BY report_date""").fetchall()
    assert rows == [
        ("2013-06-06", 1, 1, 1, 1, 0, 0.05),       # A: shown, clicked after midnight, converted
        ("2013-06-07", 4, 2, 1, 0, 1, 0.20),       # B, B, C, D; click on B + click Z (no impression)
    ]


def test_hourly_pacing_has_every_hour(con):
    rows, impressions = con.sql("SELECT COUNT(*), SUM(impressions) FROM hourly_pacing").fetchall()[0]
    assert rows == 1 * 2 * 24                     # 1 advertiser x 2 days x 24 hours
    assert impressions == 5


# ---- Ingest: hourly files, skip when done, redo when the raw file changes ----

def raw_log(rows, columns=EVENT_COLUMNS):
    import bz2
    return bz2.compress(("\n".join("\t".join(r[c] for c in columns) for r in rows) + "\n").encode())


@pytest.fixture
def ingest_dirs(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(ingest, "RAW_DIR", raw)
    monkeypatch.setattr(ingest, "INTERIM_DIR", tmp_path / "interim")
    monkeypatch.setattr(ingest, "ADVERTISER_IDS", [])
    monkeypatch.setattr(ingest, "BID_ADVERTISER_IDS", ["1458"])
    return raw, tmp_path / "interim"


def test_ingest_writes_one_file_per_hour(ingest_dirs):
    raw, interim = ingest_dirs
    # A day file can hold a few events just after midnight: they go to the next day's hour
    (raw / "imp.20130606.txt.bz2").write_bytes(raw_log([
        row("A", "20130606235800000", "u1"), row("B", "20130607000100000", "u2")]))
    ingest.run(["imp"])
    assert sorted(p.name for p in (interim / "imp").glob("*.parquet")) == [
        "imp_20130606_2013060623.parquet", "imp_20130606_2013060700.parquet"]


def test_ingest_skips_done_days_and_redoes_changed_ones(ingest_dirs):
    raw, interim = ingest_dirs
    source = raw / "clk.20130607.txt.bz2"
    source.write_bytes(raw_log([row("A", "20130607100000000", "u1")]))
    ingest.run(["clk"])
    first = (interim / "clk" / "clk_20130607_2013060710.parquet").stat().st_mtime_ns

    ingest.run(["clk"])                                       # nothing changed: skipped
    assert (interim / "clk" / "clk_20130607_2013060710.parquet").stat().st_mtime_ns == first

    source.write_bytes(raw_log([row("A", "20130607100000000", "u1"),   # the raw file grew
                                row("B", "20130607110000000", "u2")]))
    ingest.run(["clk"])
    assert sorted(p.name for p in (interim / "clk").glob("*.parquet")) == [
        "clk_20130607_2013060710.parquet", "clk_20130607_2013060711.parquet"]


def test_ingest_bid_summary_counts_all_advertisers(ingest_dirs):
    raw, interim = ingest_dirs
    other = row("C", "20130607090000000", "u3", BID_COLUMNS) | {"advertiser_id": "3358"}
    (raw / "bid.20130607.txt.bz2").write_bytes(raw_log(
        [row("A", "20130607090000000", "u1", BID_COLUMNS), other], BID_COLUMNS))
    ingest.run(["bid"])
    kept = pq.read_table(interim / "bid" / "bid_20130607_2013060709.parquet")
    summary = pq.read_table(interim / "bid_summary" / "bid_summary_20130607_2013060709.parquet")
    assert kept.column("advertiser_id").to_pylist() == ["1458"]          # full rows: 1458 only
    assert sorted(summary.column("advertiser_id").to_pylist()) == ["1458", "3358"]  # counts: all



# ---- Hourly ticks: replaying hour by hour gives exactly the batch result ----------

def test_available_hours(con):
    assert tick.available_hours() == [
        "2013060623", "2013060700", "2013060701", "2013060709", "2013060710",
        "2013060711", "2013060712", "2013060713", "2013060715", "2013060718"]


def test_hourly_replay_matches_batch(con):
    batch = con.sql("SELECT * FROM daily_campaign ORDER BY ALL").fetchall()
    replay = duckdb.connect()
    watermark = None
    for hour in tick.available_hours():                      # one tick per hour
        tick.process(replay, watermark, hour)
        watermark = hour
    assert replay.sql("SELECT * FROM daily_campaign ORDER BY ALL").fetchall() == batch


def test_first_hour_sees_only_that_hour(con):
    early = duckdb.connect()
    tick.process(early, None, "2013060623")
    assert early.sql("SELECT COUNT(*) FROM fact_impressions").fetchall()[0][0] == 1      # only A
    assert early.sql("SELECT COUNT(*) FROM fact_clicks").fetchall()[0][0] == 0


def test_late_click_reloads_the_impression_day(con):
    # The click on A arrives at 00:05 on 7 June; its impression was shown on 6 June.
    # The tick for 00:00-01:00 must send 6 June to Neon again.
    replay = duckdb.connect()
    tick.process(replay, None, "2013060623")
    days, (impressions, clicks, conversions) = tick.process(replay, "2013060623", "2013060700")
    assert [str(d) for d in days] == ["2013-06-06"]
    assert (impressions, clicks, conversions) == (0, 1, 0)


def test_watermark_is_kept_in_the_warehouse(tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    assert tick.get_watermark(con) is None
    tick.set_watermark(con, "2013060714")
    tick.set_watermark(con, "2013060715")                     # moving it replaces, never adds
    assert tick.get_watermark(con) == "2013060715"
    assert con.sql("SELECT COUNT(*) FROM pipeline_watermark").fetchall()[0][0] == 1