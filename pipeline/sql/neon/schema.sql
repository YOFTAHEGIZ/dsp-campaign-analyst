-- Tables in Neon (Postgres) that the dashboard reads.
-- load.py runs this file before every load. Every statement is safe to run again:
-- CREATE ... IF NOT EXISTS does nothing when the table is already there.

-- ---- Dimensions (replaced completely at every load) ----

CREATE TABLE IF NOT EXISTS dim_advertiser (
    advertiser_id INTEGER PRIMARY KEY,
    industry TEXT NOT NULL,
    advertiser_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_campaign (
    campaign_id INTEGER PRIMARY KEY,
    advertiser_id INTEGER NOT NULL,
    campaign_name TEXT NOT NULL,
    season INTEGER,
    first_date DATE,
    last_date DATE,
    days_live INTEGER,
    has_bid_logs BOOLEAN
);

CREATE TABLE IF NOT EXISTS dim_date (
    date DATE PRIMARY KEY,
    weekday TEXT,
    day_of_week INTEGER,
    is_weekend BOOLEAN,
    label TEXT
);

-- ---- Daily campaign KPIs ----
-- The first dashboard created this table with 6 columns; the new columns are added
-- if they are missing, so the existing table keeps working.

CREATE TABLE IF NOT EXISTS daily_campaign (
    advertiser_id INTEGER NOT NULL,
    report_date DATE NOT NULL,
    impressions BIGINT NOT NULL,
    clicks BIGINT NOT NULL,
    conversions BIGINT NOT NULL,
    total_cost NUMERIC(18, 3) NOT NULL,
    PRIMARY KEY (advertiser_id, report_date)
);

-- The first version stored the raw price sum; make sure the column can hold decimals.
-- (Only when needed: a view uses this column, and Postgres refuses to change it then.)
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_name = 'daily_campaign' AND column_name = 'total_cost') <> 'numeric' THEN
        ALTER TABLE daily_campaign ALTER COLUMN total_cost TYPE NUMERIC(18, 3);
    END IF;
END $$;
ALTER TABLE daily_campaign ADD COLUMN IF NOT EXISTS clicked_impressions BIGINT NOT NULL DEFAULT 0;
ALTER TABLE daily_campaign ADD COLUMN IF NOT EXISTS converted_impressions BIGINT NOT NULL DEFAULT 0;
ALTER TABLE daily_campaign ADD COLUMN IF NOT EXISTS post_click_conversions BIGINT NOT NULL DEFAULT 0;
ALTER TABLE daily_campaign ADD COLUMN IF NOT EXISTS post_view_conversions BIGINT NOT NULL DEFAULT 0;

-- ---- Daily auction stats ----

CREATE TABLE IF NOT EXISTS daily_auction (
    advertiser_id INTEGER NOT NULL,
    report_date DATE NOT NULL,
    ad_exchange INTEGER,
    floor_band TEXT NOT NULL,
    bids BIGINT NOT NULL,
    wins BIGINT NOT NULL,
    sum_bid_price BIGINT NOT NULL,
    sum_bid_price_won BIGINT NOT NULL,
    sum_paying_price BIGINT NOT NULL,
    sum_floor_price BIGINT NOT NULL,
    floor_set_price BIGINT NOT NULL,
    paid_above_bid BIGINT NOT NULL,
    paid_below_floor BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS daily_auction_advertiser_date ON daily_auction (advertiser_id, report_date);

-- ---- Hourly pacing ----

CREATE TABLE IF NOT EXISTS hourly_pacing (
    advertiser_id INTEGER NOT NULL,
    report_date DATE NOT NULL,
    hour INTEGER NOT NULL,
    bids BIGINT NOT NULL,
    impressions BIGINT NOT NULL,
    clicked_impressions BIGINT NOT NULL,
    converted_impressions BIGINT NOT NULL,
    total_cost NUMERIC(18, 3) NOT NULL,
    PRIMARY KEY (advertiser_id, report_date, hour)
);

-- ---- When each table was last loaded (the dashboard shows it) ----

CREATE TABLE IF NOT EXISTS load_log (
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    table_name TEXT NOT NULL,
    rows_loaded INTEGER NOT NULL
);

-- ---- Rates, for checking the numbers in the Neon SQL editor ----
-- Always a ratio of sums. NULLIF avoids dividing by zero.

CREATE OR REPLACE VIEW v_campaign_kpis AS
SELECT
    advertiser_id,
    SUM(impressions) AS impressions,
    SUM(clicked_impressions) AS clicked_impressions,
    ROUND(100.0 * SUM(clicked_impressions) / NULLIF(SUM(impressions), 0), 4) AS ctr_pct,
    SUM(total_cost) AS total_cost,
    ROUND(1000.0 * SUM(total_cost) / NULLIF(SUM(impressions), 0), 2) AS cpm,
    ROUND(SUM(total_cost) / NULLIF(SUM(clicked_impressions), 0), 2) AS cpc,
    SUM(conversions) AS conversions,
    ROUND(SUM(total_cost) / NULLIF(SUM(converted_impressions), 0), 2) AS cpa
FROM daily_campaign
GROUP BY advertiser_id;

CREATE OR REPLACE VIEW v_auction_kpis AS
SELECT
    advertiser_id,
    SUM(bids) AS bids,
    SUM(wins) AS wins,
    ROUND(100.0 * SUM(wins) / NULLIF(SUM(bids), 0), 2) AS win_rate_pct,
    ROUND(1.0 * SUM(sum_bid_price) / NULLIF(SUM(bids), 0), 1) AS avg_bid,
    ROUND(1.0 * SUM(sum_paying_price) / NULLIF(SUM(wins), 0), 1) AS avg_paid,
    ROUND(100.0 * SUM(sum_paying_price) / NULLIF(SUM(sum_bid_price_won), 0), 1) AS paid_vs_bid_pct
FROM daily_auction
GROUP BY advertiser_id;

-- ---- How far the data goes (the watermark), shown on the dashboard ----
-- One row. processed_up_to is the end of the last hour loaded (e.g. 2013-06-07 15:00 means
-- everything before 15:00 on 7 June is in). mode is 'batch' (run.py) or 'hourly' (tick.py).

CREATE TABLE IF NOT EXISTS pipeline_status (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    processed_up_to TIMESTAMP,
    mode TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);