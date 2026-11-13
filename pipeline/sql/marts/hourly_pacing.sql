-- Hourly pacing mart.
-- Grain: one row per advertiser, day and hour (0-23).
-- Shows how each day's spend is spread over the day: does the campaign spend
-- evenly, or run out of budget early? (Task 2, notebook 04: clear hour-of-day pattern.)
-- Every hour gets a row, even with no impressions, so charts have no gaps.

WITH hours AS (
    SELECT a.advertiser_id, d.date AS report_date, h.hour
    FROM dim_campaign a
    CROSS JOIN dim_date d
    CROSS JOIN RANGE(24) AS h(hour)
),

hourly AS (
    SELECT
        advertiser_id,
        impression_date AS report_date,
        hour,
        COUNT(*) AS impressions,
        SUM(clicked) AS clicked_impressions,
        SUM(converted) AS converted_impressions,
        SUM(cost) AS total_cost
    FROM fact_impressions
    GROUP BY advertiser_id, impression_date, hour
),

hourly_bids AS (
    SELECT advertiser_id, bid_date AS report_date, hour, SUM(bids) AS bids
    FROM stg_bid_summary
    GROUP BY advertiser_id, bid_date, hour
)

SELECT
    h.advertiser_id,
    h.report_date,
    CAST(h.hour AS INTEGER) AS hour,
    COALESCE(b.bids, 0) AS bids,
    COALESCE(i.impressions, 0) AS impressions,
    COALESCE(i.clicked_impressions, 0) AS clicked_impressions,
    COALESCE(i.converted_impressions, 0) AS converted_impressions,
    CAST(COALESCE(i.total_cost, 0) AS DECIMAL(18, 3)) AS total_cost
FROM hours h
LEFT JOIN hourly i
    ON h.advertiser_id = i.advertiser_id AND h.report_date = i.report_date AND h.hour = i.hour
LEFT JOIN hourly_bids b
    ON h.advertiser_id = b.advertiser_id AND h.report_date = b.report_date AND h.hour = b.hour
ORDER BY h.advertiser_id, h.report_date, h.hour;