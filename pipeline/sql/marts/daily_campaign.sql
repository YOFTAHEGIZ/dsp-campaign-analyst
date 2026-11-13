-- Daily campaign performance mart (campaign KPIs).
-- Grain: one row per advertiser per day.
--
-- Only counts and sums are stored. Rates are computed when they are shown, as a ratio
-- of sums: CTR = SUM(clicked_impressions) / SUM(impressions), CPM = SUM(total_cost) /
-- SUM(impressions) * 1000, and so on. Never average daily rates.
--
-- Clicks and conversions count on the day of the impression they came from (report_date).
-- total_cost is in currency units: paying price / 1000 (prices are per 1,000 impressions).

WITH daily_impressions AS (
    SELECT
        advertiser_id,
        impression_date AS report_date,
        COUNT(*) AS impressions,
        SUM(clicked) AS clicked_impressions,
        SUM(converted) AS converted_impressions,
        SUM(cost) AS total_cost
    FROM fact_impressions
    GROUP BY advertiser_id, impression_date
),

daily_clicks AS (
    SELECT advertiser_id, report_date, COUNT(*) AS clicks
    FROM fact_clicks
    GROUP BY advertiser_id, report_date
),

daily_conversions AS (
    SELECT
        advertiser_id,
        report_date,
        COUNT(*) AS conversions,
        COUNT(*) FILTER (WHERE conversion_type = 'post-click') AS post_click_conversions,
        COUNT(*) FILTER (WHERE conversion_type = 'post-view') AS post_view_conversions
    FROM fact_conversions
    GROUP BY advertiser_id, report_date
),

all_dates AS (
    SELECT advertiser_id, report_date FROM daily_impressions
    UNION
    SELECT advertiser_id, report_date FROM daily_clicks
    UNION
    SELECT advertiser_id, report_date FROM daily_conversions
)

SELECT
    d.advertiser_id,
    d.report_date,
    COALESCE(i.impressions, 0) AS impressions,
    COALESCE(c.clicks, 0) AS clicks,                                   -- every click event
    COALESCE(v.conversions, 0) AS conversions,                         -- every conversion event
    CAST(COALESCE(i.total_cost, 0) AS DECIMAL(18, 3)) AS total_cost,
    COALESCE(i.clicked_impressions, 0) AS clicked_impressions,         -- for CTR
    COALESCE(i.converted_impressions, 0) AS converted_impressions,     -- for CPA
    COALESCE(v.post_click_conversions, 0) AS post_click_conversions,   -- for CVR
    COALESCE(v.post_view_conversions, 0) AS post_view_conversions
FROM all_dates d
LEFT JOIN daily_impressions i
    ON d.advertiser_id = i.advertiser_id AND d.report_date = i.report_date
LEFT JOIN daily_clicks c
    ON d.advertiser_id = c.advertiser_id AND d.report_date = c.report_date
LEFT JOIN daily_conversions v
    ON d.advertiser_id = v.advertiser_id AND d.report_date = v.report_date
ORDER BY d.advertiser_id, d.report_date;