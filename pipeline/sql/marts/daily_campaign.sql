-- Daily campaign performance mart.
-- One row per advertiser per event date.

WITH all_dates AS (

    -- Collect all dates from the three event datasets
    SELECT advertiser_id, impression_date AS report_date
    FROM stg_impressions

    UNION

    SELECT advertiser_id, click_date AS report_date
    FROM stg_clicks

    UNION

    SELECT advertiser_id, conversion_date AS report_date
    FROM stg_conversions
),

daily_impressions AS (

    SELECT
        advertiser_id,
        impression_date AS report_date,
        COUNT(*) AS impressions,
        SUM(paying_price) AS total_cost
    FROM stg_impressions
    GROUP BY advertiser_id, impression_date
),

daily_clicks AS (

    SELECT
        advertiser_id,
        click_date AS report_date,
        COUNT(*) AS clicks
    FROM stg_clicks
    GROUP BY advertiser_id, click_date
),

daily_conversions AS (

    SELECT
        advertiser_id,
        conversion_date AS report_date,
        COUNT(*) AS conversions
    FROM stg_conversions
    GROUP BY advertiser_id, conversion_date
)

SELECT
    d.advertiser_id,
    d.report_date,

    COALESCE(i.impressions, 0) AS impressions,
    COALESCE(c.clicks, 0) AS clicks,
    COALESCE(v.conversions, 0) AS conversions,
    COALESCE(i.total_cost, 0) AS total_cost

FROM all_dates d

LEFT JOIN daily_impressions i
    ON d.advertiser_id = i.advertiser_id
    AND d.report_date = i.report_date

LEFT JOIN daily_clicks c
    ON d.advertiser_id = c.advertiser_id
    AND d.report_date = c.report_date

LEFT JOIN daily_conversions v
    ON d.advertiser_id = v.advertiser_id
    AND d.report_date = v.report_date;